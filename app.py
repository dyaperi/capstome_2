from datetime import date, datetime, timedelta
from io import BytesIO
import re
import secrets
from urllib.parse import quote_plus

import pandas as pd
from flask import Flask, current_app, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import distinct, func, inspect, or_, text
from werkzeug.security import check_password_hash, generate_password_hash

from analytics import analyze_sentiment, campaign_roi, forecast_values
from config import Config
from db import db
from models import AnalystNote, CustomerReview, Expense, ForecastResult, InventoryItem, MarketingCampaign, MenuItem, Sale, StockMovement, User
from services.role_service import RoleService

REVIEW_SOURCES = [
    "Facebook",
    "Grab",
    "Foodpanda",
    "TikTok",
    "Google",
    "WhatsApp",
    "Walk-in",
    "Manual Entry",
    "QR Feedback",
    "QR Feedback Form",
]
ORDER_TYPES = ["Dine-in", "Takeaway", "Delivery"]
SALES_CHANNELS = ["Walk-in", "Delivery", "Takeaway", "Dine-in", "Drive-thru"]
INVENTORY_UNITS = ["kg", "g", "liter", "ml", "pcs", "pack", "box", "bottle", "can"]
STOCK_MOVEMENT_TYPES = ["IN", "OUT", "ADJUSTMENT"]
ISSUE_TAGS = [
    "General",
    "Service Quality",
    "Food Quality",
    "Delivery Delay",
    "Missing/Wrong Order",
    "Pricing",
    "Staff Attitude",
    "Packaging",
]
ISSUE_RECOMMENDATIONS = {
    "Service Quality": "Provide service SOP refresh and monitor service quality by shift.",
    "Food Quality": "Run daily taste checks and tighten ingredient quality controls.",
    "Delivery Delay": "Review dispatch timing and update delivery handoff process.",
    "Missing/Wrong Order": "Introduce order confirmation checkpoints before handoff.",
    "Pricing": "Reassess value bundles and communicate portion/value clearly.",
    "Staff Attitude": "Provide customer-handling refresh training and supervision.",
    "Packaging": "Upgrade packaging standards for delivery durability.",
    "General": "Review recurring comments weekly and assign improvement owners.",
}
CSRF_FIELD_NAME = "csrf_token"


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        ensure_schema_updates()
        seed_default_data()

    register_security_hooks(app)
    register_routes(app)
    return app


def seed_default_data() -> None:
    admin_user = User.query.filter_by(username="admin").first()
    if not admin_user:
        db.session.add(
            User(
                username="admin",
                full_name="SME Consultant",
                role=RoleService.ADMIN_ANALYST,
                status="active",
                password=generate_password_hash("admin123"),
            )
        )
    else:
        if admin_user.role != RoleService.ADMIN_ANALYST:
            admin_user.role = RoleService.ADMIN_ANALYST
        admin_user.full_name = "SME Consultant"
        admin_user.status = "active"
        admin_user.password = generate_password_hash("admin123")

    client_user = User.query.filter_by(username="client").first()
    if not client_user:
        db.session.add(
            User(
                username="client",
                full_name="SME Client",
                role=RoleService.CLIENT,
                status="active",
                password=generate_password_hash("client123"),
            )
        )
    else:
        if client_user.role != RoleService.CLIENT:
            client_user.role = RoleService.CLIENT
        client_user.full_name = "SME Client"
        client_user.status = "active"
        client_user.password = generate_password_hash("client123")

    db.session.flush()
    demo_client = User.query.filter_by(username="client", role=RoleService.CLIENT).first()

    if not MenuItem.query.first():
        db.session.add_all(
            [
                MenuItem(
                    client_id=demo_client.id if demo_client else None,
                    item_name="Mee Rebus",
                    category="Main",
                    selling_price=8.0,
                    ingredient_cost=3.0,
                ),
                MenuItem(
                    client_id=demo_client.id if demo_client else None,
                    item_name="Nasi Goreng",
                    category="Main",
                    selling_price=9.5,
                    ingredient_cost=3.8,
                ),
                MenuItem(
                    client_id=demo_client.id if demo_client else None,
                    item_name="Teh Tarik",
                    category="Beverage",
                    selling_price=3.0,
                    ingredient_cost=1.0,
                ),
            ]
        )

    if demo_client:
        for model in [MenuItem, Sale, Expense, MarketingCampaign, CustomerReview, InventoryItem, ForecastResult]:
            if not model.query.filter(model.client_id == demo_client.id).first():
                for record in model.query.filter(model.client_id.is_(None)).all():
                    record.client_id = demo_client.id
    db.session.commit()


def login_required() -> bool:
    return current_user_id() is not None


def current_user_id():
    return session.get("user_id")


def require_login_redirect():
    if login_required():
        return None
    return redirect(url_for("login"))


def staff_required() -> bool:
    return login_required() and RoleService.is_staff()


def client_required() -> bool:
    return login_required() and RoleService.is_client()


def selected_client_id():
    client_id = session.get("selected_client_id")
    try:
        return int(client_id) if client_id is not None else None
    except (TypeError, ValueError):
        session.pop("selected_client_id", None)
        session.pop("selected_client_name", None)
        return None


def selected_client():
    client_id = selected_client_id()
    if client_id is None:
        return None
    client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first()
    if not client:
        session.pop("selected_client_id", None)
        session.pop("selected_client_name", None)
    return client


def current_client_id():
    if client_required():
        return current_user_id()
    if staff_required():
        return selected_client_id()
    return None


def scoped_query(model):
    query = model.query
    client_id = current_client_id()
    if client_id is not None and hasattr(model, "client_id"):
        query = query.filter(model.client_id == client_id)
    return query


def scoped_stock_movement_query():
    query = StockMovement.query.join(InventoryItem)
    client_id = current_client_id()
    if client_id is not None:
        query = query.filter(InventoryItem.client_id == client_id)
    return query


def require_client_context_redirect():
    login_redirect = require_login_redirect()
    if login_redirect:
        return login_redirect
    if staff_required() and current_client_id() is None:
        flash("Choose a client portfolio before opening workspace data.", "warning")
        return redirect(url_for("clients_page"))
    return None


def get_scoped_or_404(model, record_id: int):
    return scoped_query(model).filter(model.id == record_id).first_or_404()


def owner_payload() -> dict:
    client_id = current_client_id()
    return {"client_id": client_id} if client_id is not None else {}


def client_owner_payload_from_form() -> dict:
    context_client_id = current_client_id()
    if context_client_id is not None:
        return {"client_id": context_client_id}
    client_id = request.form.get("client_id", type=int)
    return {"client_id": client_id} if client_id else {"client_id": None}


def csrf_token() -> str:
    token = session.get(CSRF_FIELD_NAME)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_FIELD_NAME] = token
    return token


def submitted_csrf_token():
    header_token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    if header_token:
        return header_token
    if request.is_json:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            return payload.get(CSRF_FIELD_NAME)
        return None
    return request.form.get(CSRF_FIELD_NAME)


def csrf_error_response():
    if request.is_json or request.path.startswith("/reviews/submit"):
        return jsonify({"ok": False, "error": "Invalid or missing CSRF token."}), 400
    flash("Your session security token expired. Please try again.", "warning")
    return redirect(request.referrer or url_for("login"))


def is_valid_csrf_token(received_token) -> bool:
    expected_token = session.get(CSRF_FIELD_NAME)
    return bool(expected_token and received_token and secrets.compare_digest(expected_token, received_token))


def register_security_hooks(app: Flask) -> None:
    @app.context_processor
    def inject_csrf_token():
        return {
            "csrf_token": csrf_token,
            "csrf_field_name": CSRF_FIELD_NAME,
            "import_specs": import_specs_for_template(),
            "selected_client": selected_client(),
            "selected_client_id": current_client_id(),
            "is_staff_user": staff_required(),
            "is_client_user": client_required(),
        }

    @app.before_request
    def validate_csrf_token():
        if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
            return None
        if request.endpoint == "review_submit":
            return None
        if is_valid_csrf_token(submitted_csrf_token()):
            return None
        return csrf_error_response()

    @app.after_request
    def add_csrf_to_forms(response):
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type.lower() or response.direct_passthrough:
            return response
        html = response.get_data(as_text=True)
        if "<form" not in html.lower():
            return response
        token_field = f'<input type="hidden" name="{CSRF_FIELD_NAME}" value="{csrf_token()}">'
        html = re.sub(
            r"(<form\b[^>]*\bmethod=[\"']?post[\"']?[^>]*>)",
            lambda match: match.group(1) + token_field,
            html,
            flags=re.IGNORECASE,
        )
        response.set_data(html)
        return response


def ensure_schema_updates() -> None:
    inspector = inspect(db.engine)
    dialect_name = db.engine.dialect.name
    user_columns = {col["name"] for col in inspector.get_columns("users")}
    if "role" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(30) DEFAULT 'client' NOT NULL"))
        db.session.execute(text("UPDATE users SET role = 'admin_analyst' WHERE username = 'admin'"))
    if "status" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN status VARCHAR(20) DEFAULT 'active' NOT NULL"))
        db.session.execute(text("UPDATE users SET status = 'active' WHERE status IS NULL OR status = ''"))
    if "last_login_at" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN last_login_at DATETIME NULL"))
    if "phone_number" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN phone_number VARCHAR(30)"))
    if "business_address" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN business_address VARCHAR(255)"))
    if "business_type" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN business_type VARCHAR(100)"))
    if "subscription_type" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN subscription_type VARCHAR(80)"))
    if "preferred_dashboard_period" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN preferred_dashboard_period VARCHAR(30) DEFAULT 'month'"))
    if "updated_at" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"))
    for table_name in ["menu_items", "sales", "expenses", "marketing_campaigns", "inventory_items", "forecast_results"]:
        table_columns = {col["name"]: col for col in inspector.get_columns(table_name)}
        if "client_id" not in table_columns:
            db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN client_id INTEGER NULL"))
        elif not table_columns["client_id"].get("nullable", True) and dialect_name == "mysql":
            db.session.execute(text(f"ALTER TABLE {table_name} MODIFY COLUMN client_id INTEGER NULL"))
    review_columns = {col["name"] for col in inspector.get_columns("customer_reviews")}
    if "client_id" not in review_columns:
        db.session.execute(text("ALTER TABLE customer_reviews ADD COLUMN client_id INTEGER NULL"))
    if "customer_name" not in review_columns:
        db.session.execute(text("ALTER TABLE customer_reviews ADD COLUMN customer_name VARCHAR(150)"))
    if "phone_number" not in review_columns:
        db.session.execute(text("ALTER TABLE customer_reviews ADD COLUMN phone_number VARCHAR(30)"))
    if "menu_item" not in review_columns:
        db.session.execute(text("ALTER TABLE customer_reviews ADD COLUMN menu_item VARCHAR(150)"))
    if "order_type" not in review_columns:
        db.session.execute(text("ALTER TABLE customer_reviews ADD COLUMN order_type VARCHAR(30)"))
    if "receipt_number" not in review_columns:
        db.session.execute(text("ALTER TABLE customer_reviews ADD COLUMN receipt_number VARCHAR(80)"))
    if "issue_tag" not in review_columns:
        db.session.execute(text("ALTER TABLE customer_reviews ADD COLUMN issue_tag VARCHAR(80) DEFAULT 'General'"))
    if "urgency_level" not in review_columns:
        db.session.execute(text("ALTER TABLE customer_reviews ADD COLUMN urgency_level VARCHAR(20) DEFAULT 'low'"))
    if "submission_channel" not in review_columns:
        db.session.execute(
            text("ALTER TABLE customer_reviews ADD COLUMN submission_channel VARCHAR(30) DEFAULT 'manual'")
        )
    if "updated_at" not in review_columns:
        db.session.execute(
            text(
                "ALTER TABLE customer_reviews ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
            )
        )
    db.session.commit()


def build_sentiment_intelligence(metrics: dict, reviews: list[CustomerReview] | None = None) -> dict:
    if reviews is None:
        reviews = CustomerReview.query.order_by(CustomerReview.review_date.desc()).all()
    source_breakdown: list[dict] = []
    issue_breakdown: list[dict] = []
    critical_alerts: list[dict] = []
    recommendations: list[dict] = []

    if reviews:
        review_df = pd.DataFrame(
            [
                {
                    "source": r.source or "Unknown",
                    "label": r.sentiment_label,
                    "issue_tag": r.issue_tag or "General",
                    "score": r.sentiment_score,
                }
                for r in reviews
            ]
        )

        source_group = (
            review_df.groupby(["source", "label"], as_index=False).size().pivot(index="source", columns="label", values="size")
        )
        source_group = source_group.fillna(0)
        for label in ["positive", "neutral", "negative"]:
            if label not in source_group.columns:
                source_group[label] = 0
        source_group = source_group.reset_index().sort_values("negative", ascending=False)
        source_breakdown = [
            {
                "source": row["source"],
                "positive": int(row["positive"]),
                "neutral": int(row["neutral"]),
                "negative": int(row["negative"]),
                "total": int(row["positive"] + row["neutral"] + row["negative"]),
            }
            for _, row in source_group.iterrows()
        ]

        issue_group = (
            review_df[review_df["label"] == "negative"]
            .groupby("issue_tag", as_index=False)
            .size()
            .sort_values("size", ascending=False)
        )
        issue_breakdown = [{"issue_tag": row["issue_tag"], "count": int(row["size"])} for _, row in issue_group.iterrows()]

        critical_rows = [
            r
            for r in reviews
            if r.sentiment_label == "negative" and ((r.sentiment_score is not None and r.sentiment_score <= -0.5) or r.rating <= 2)
        ]
        critical_alerts = [
            {
                "date": c.review_date.strftime("%Y-%m-%d"),
                "source": c.source,
                "rating": c.rating,
                "issue_tag": c.issue_tag or "General",
                "text": c.review_text,
            }
            for c in critical_rows[:10]
        ]

        top_issue_tags = [x["issue_tag"] for x in issue_breakdown[:3]]
        recommendations = [
            {"issue_tag": tag, "recommendation": ISSUE_RECOMMENDATIONS.get(tag, ISSUE_RECOMMENDATIONS["General"])}
            for tag in top_issue_tags
        ]

    if not recommendations:
        recommendations = [{"issue_tag": "General", "recommendation": ISSUE_RECOMMENDATIONS["General"]}]

    trend = (
        reviews_to_trend(reviews)
        if reviews
        else []
    )
    return {
        "distribution": metrics.get("sentiment_counts", {"positive": 0, "neutral": 0, "negative": 0}),
        "source_breakdown": source_breakdown,
        "critical_alerts": critical_alerts,
        "issue_breakdown": issue_breakdown,
        "recommendations": recommendations,
        "sentiment_trend": trend,
    }


def reviews_to_trend(reviews: list[CustomerReview]) -> list[dict]:
    review_df = pd.DataFrame(
        [{"date": r.review_date, "score": r.sentiment_score} for r in reviews if r.review_date is not None]
    )
    if review_df.empty:
        return []
    grouped = review_df.groupby("date", as_index=False).agg(avg_score=("score", "mean")).sort_values("date")
    return [{"date": d.strftime("%Y-%m-%d"), "avg_score": round(float(s), 4)} for d, s in zip(grouped["date"], grouped["avg_score"])]


def detect_issue_tag(review_text: str) -> str:
    text_lower = (review_text or "").lower()
    rules = {
        "Delivery Delay": ["lambat", "late", "delay", "slow delivery", "took too long"],
        "Food Quality": ["tak sedap", "cold food", "stale", "basi", "burnt", "raw", "quality"],
        "Staff Attitude": ["rude", "staff kasar", "kasar", "unfriendly", "biadap"],
        "Missing/Wrong Order": ["missing item", "wrong order", "tak cukup", "incorrect order", "missing"],
        "Packaging": ["packaging", "leaked", "bocor", "spill", "pecah"],
        "Pricing": ["expensive", "mahal", "overpriced", "pricey"],
        "Service Quality": ["bad service", "service teruk", "service slow", "service not good"],
    }
    for tag, keywords in rules.items():
        if any(word in text_lower for word in keywords):
            return tag
    return "General"


def determine_urgency_level(sentiment_label: str, rating: int, issue_tag: str, review_text: str) -> str:
    critical_words = ["refund", "food poisoning", "poisoning", "complaint", "angry", "never again", "terrible", "worst"]
    text_lower = (review_text or "").lower()
    has_critical_word = any(w in text_lower for w in critical_words)
    if sentiment_label == "negative" and (rating <= 2 or has_critical_word or issue_tag in {"Food Quality", "Missing/Wrong Order"}):
        return "high"
    if sentiment_label == "negative" or rating == 3:
        return "medium"
    return "low"


def public_feedback_url(client_id: int) -> str:
    configured_base = (
        current_app.config.get("BASE_URL")
        or current_app.config.get("PUBLIC_BASE_URL")
        or ""
    ).strip()
    base_url = configured_base or request.host_url
    return f"{base_url.rstrip('/')}{url_for('public_feedback', client_id=client_id)}"


def external_qr_image_url(feedback_url: str) -> str:
    return f"https://api.qrserver.com/v1/create-qr-code/?size=320x320&data={quote_plus(feedback_url)}"


def feedback_qr_payload(client_id: int) -> dict:
    feedback_url = public_feedback_url(client_id)
    return {
        "feedback_url": feedback_url,
        "qr_image_url": url_for("feedback_qr_image", client_id=client_id),
        "qr_download_url": url_for("feedback_qr_download", client_id=client_id),
        "qr_page_url": url_for("feedback_qr_page", client_id=client_id),
        "external_qr_image_url": external_qr_image_url(feedback_url),
    }


def qr_png_response(client_id: int, *, as_attachment: bool = False):
    feedback_url = public_feedback_url(client_id)
    try:
        import qrcode
    except ImportError:
        return redirect(external_qr_image_url(feedback_url))

    image = qrcode.make(feedback_url)
    stream = BytesIO()
    image.save(stream, format="PNG")
    stream.seek(0)
    return send_file(
        stream,
        mimetype="image/png",
        as_attachment=as_attachment,
        download_name=f"feedback_qr_client_{client_id}.png",
    )


def request_value(key: str, default=None):
    payload = request.get_json(silent=True) if request.is_json else None
    if isinstance(payload, dict) and key in payload:
        return payload.get(key, default)
    return request.form.get(key, default)


def clean_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def parse_int_field(raw, field_label: str, *, required: bool = False, min_value: int | None = None, max_value: int | None = None):
    text = clean_text(raw)
    if not text:
        if required:
            return None, f"{field_label} is required."
        return None, None
    try:
        value = int(text)
    except (TypeError, ValueError):
        return None, f"{field_label} must be a whole number."
    if min_value is not None and value < min_value:
        return None, f"{field_label} must be at least {min_value}."
    if max_value is not None and value > max_value:
        return None, f"{field_label} must be at most {max_value}."
    return value, None


def parse_float_field(raw, field_label: str, *, required: bool = False, min_value: float | None = None):
    text = clean_text(raw)
    if not text:
        if required:
            return None, f"{field_label} is required."
        return None, None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None, f"{field_label} must be a valid number."
    if min_value is not None and value < min_value:
        return None, f"{field_label} must be at least {min_value}."
    return value, None


def parse_date_field(raw, field_label: str, *, required: bool = False, fmt: str = "%Y-%m-%d"):
    text = clean_text(raw)
    if not text:
        if required:
            return None, f"{field_label} is required."
        return None, None
    try:
        return datetime.strptime(text, fmt).date(), None
    except ValueError:
        return None, f"{field_label} must be in YYYY-MM-DD format."


def extract_route_errors(*results) -> list[str]:
    return [err for _, err in results if err]


RECENT_RECORD_LIMIT = 10
LIST_VIEWS = {"recent", "all", "day", "week", "month", "date", "range"}


def month_bounds(day: date) -> tuple[date, date]:
    start = day.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1) - timedelta(days=1)
    else:
        end = start.replace(month=start.month + 1) - timedelta(days=1)
    return start, end


def build_record_list(query, date_column, *, module_label: str) -> tuple[list, dict]:
    today = date.today()
    view = clean_text(request.args.get("view")) or "recent"
    if view not in LIST_VIEWS:
        flash("Unknown list filter. Showing recent records instead.", "warning")
        view = "recent"

    exact_date_raw = clean_text(request.args.get("date"))
    start_date_raw = clean_text(request.args.get("start_date"))
    end_date_raw = clean_text(request.args.get("end_date"))
    filter_query = query
    active_title = f"Recent {module_label}"
    active_summary = f"Showing the latest {RECENT_RECORD_LIMIT} records. Use Show All or filters to review older records."
    parsed_exact_date = None
    parsed_start_date = None
    parsed_end_date = None

    if view == "all":
        active_title = f"All {module_label}"
        active_summary = "Showing every record available for this account."
    elif view == "day":
        filter_query = filter_query.filter(date_column == today)
        active_title = f"Today's {module_label}"
        active_summary = f"Showing records dated {today.strftime('%Y-%m-%d')}."
    elif view == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        filter_query = filter_query.filter(date_column.between(start, end))
        active_title = f"This week's {module_label}"
        active_summary = f"Showing records from {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}."
    elif view == "month":
        start, end = month_bounds(today)
        filter_query = filter_query.filter(date_column.between(start, end))
        active_title = f"This month's {module_label}"
        active_summary = f"Showing records from {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}."
    elif view == "date":
        parsed_exact_date, date_error = parse_date_field(exact_date_raw or today.strftime("%Y-%m-%d"), "Specific date")
        if date_error:
            flash(date_error, "danger")
            view = "recent"
        else:
            filter_query = filter_query.filter(date_column == parsed_exact_date)
            active_title = f"{module_label.capitalize()} on {parsed_exact_date.strftime('%Y-%m-%d')}"
            active_summary = "Showing records for one selected date."
    elif view == "range":
        parsed_start_date, start_error = parse_date_field(start_date_raw, "Start date")
        parsed_end_date, end_error = parse_date_field(end_date_raw, "End date")
        if start_error or end_error or not parsed_start_date or not parsed_end_date:
            flash("Choose both a valid start date and end date for a custom range.", "danger")
            view = "recent"
        elif parsed_start_date > parsed_end_date:
            flash("Start date must be before or equal to end date.", "danger")
            view = "recent"
        else:
            filter_query = filter_query.filter(date_column.between(parsed_start_date, parsed_end_date))
            active_title = f"{module_label.capitalize()} by date range"
            active_summary = f"Showing records from {parsed_start_date.strftime('%Y-%m-%d')} to {parsed_end_date.strftime('%Y-%m-%d')}."

    if view == "recent":
        records = filter_query.order_by(date_column.desc()).limit(RECENT_RECORD_LIMIT).all()
    else:
        records = filter_query.order_by(date_column.desc()).all()

    return records, {
        "view": view,
        "title": active_title,
        "summary": active_summary,
        "date": (parsed_exact_date or today).strftime("%Y-%m-%d"),
        "start_date": parsed_start_date.strftime("%Y-%m-%d") if parsed_start_date else start_date_raw,
        "end_date": parsed_end_date.strftime("%Y-%m-%d") if parsed_end_date else end_date_raw,
        "count": len(records),
    }


def build_campaign_roi_table(query) -> tuple[list[dict], dict]:
    today = date.today()
    search_term = clean_text(request.args.get("q"))
    view = clean_text(request.args.get("view")) or "all"
    roi_sort = clean_text(request.args.get("roi_sort")) or "default"
    exact_date_raw = clean_text(request.args.get("date"))
    start_date_raw = clean_text(request.args.get("start_date"))
    end_date_raw = clean_text(request.args.get("end_date"))
    valid_views = {"all", "day", "week", "month", "date", "range"}
    valid_roi_sort = {"default", "highest", "lowest"}

    if view not in valid_views:
        flash("Unknown ROI table filter. Showing all campaigns instead.", "warning")
        view = "all"
    if roi_sort not in valid_roi_sort:
        roi_sort = "default"

    filter_query = query
    parsed_exact_date = None
    parsed_start_date = None
    parsed_end_date = None
    active_summary = "Showing all campaign ROI records."

    if search_term:
        filter_query = filter_query.filter(MarketingCampaign.campaign_name.ilike(f"%{search_term}%"))

    if view == "day":
        filter_query = filter_query.filter(MarketingCampaign.campaign_date == today)
        active_summary = f"Showing campaigns dated {today.strftime('%Y-%m-%d')}."
    elif view == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        filter_query = filter_query.filter(MarketingCampaign.campaign_date.between(start, end))
        active_summary = f"Showing campaigns from {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}."
    elif view == "month":
        start, end = month_bounds(today)
        filter_query = filter_query.filter(MarketingCampaign.campaign_date.between(start, end))
        active_summary = f"Showing campaigns from {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}."
    elif view == "date":
        parsed_exact_date, date_error = parse_date_field(exact_date_raw or today.strftime("%Y-%m-%d"), "Specific date")
        if date_error:
            flash(date_error, "danger")
            view = "all"
        else:
            filter_query = filter_query.filter(MarketingCampaign.campaign_date == parsed_exact_date)
            active_summary = f"Showing campaigns for {parsed_exact_date.strftime('%Y-%m-%d')}."
    elif view == "range":
        parsed_start_date, start_error = parse_date_field(start_date_raw, "Start date")
        parsed_end_date, end_error = parse_date_field(end_date_raw, "End date")
        if start_error or end_error or not parsed_start_date or not parsed_end_date:
            flash("Choose both a valid start date and end date for a custom range.", "danger")
            view = "all"
        elif parsed_start_date > parsed_end_date:
            flash("Start date must be before or equal to end date.", "danger")
            view = "all"
        else:
            filter_query = filter_query.filter(MarketingCampaign.campaign_date.between(parsed_start_date, parsed_end_date))
            active_summary = f"Showing campaigns from {parsed_start_date.strftime('%Y-%m-%d')} to {parsed_end_date.strftime('%Y-%m-%d')}."

    records = filter_query.order_by(MarketingCampaign.campaign_date.desc(), MarketingCampaign.id.desc()).all()
    rows: list[dict] = []
    if records:
        campaign_df = pd.DataFrame(
            [
                {
                    "campaign": campaign.campaign_name,
                    "spend": campaign.spend,
                    "revenue": campaign.revenue_generated,
                }
                for campaign in records
            ]
        )
        campaign_group = campaign_df.groupby("campaign", as_index=False).agg(
            spend=("spend", "sum"),
            revenue=("revenue", "sum"),
        )
        campaign_group["roi"] = campaign_group.apply(lambda row: campaign_roi(row["spend"], row["revenue"]), axis=1)
        if roi_sort == "highest":
            campaign_group = campaign_group.sort_values(["roi", "campaign"], ascending=[False, True])
        elif roi_sort == "lowest":
            campaign_group = campaign_group.sort_values(["roi", "campaign"], ascending=[True, True])
        else:
            campaign_group = campaign_group.sort_values("campaign", ascending=True)
        rows = campaign_group.to_dict(orient="records")

    if search_term:
        active_summary += f" Matching campaign name: \"{search_term}\"."
    if roi_sort == "highest":
        active_summary += " Ordered from highest ROI to lowest ROI."
    elif roi_sort == "lowest":
        active_summary += " Ordered from lowest ROI to highest ROI."

    return rows, {
        "q": search_term,
        "view": view,
        "date": (parsed_exact_date or today).strftime("%Y-%m-%d"),
        "start_date": parsed_start_date.strftime("%Y-%m-%d") if parsed_start_date else start_date_raw,
        "end_date": parsed_end_date.strftime("%Y-%m-%d") if parsed_end_date else end_date_raw,
        "roi_sort": roi_sort,
        "summary": active_summary,
        "count": len(rows),
        "record_count": len(records),
        "has_filters": bool(search_term or view != "all" or roi_sort != "default"),
    }


def records_for_export(query, date_column):
    today = date.today()
    view = clean_text(request.args.get("view")) or "recent"
    if view not in LIST_VIEWS:
        view = "recent"
    filter_query = query
    exact_date_raw = clean_text(request.args.get("date"))
    start_date_raw = clean_text(request.args.get("start_date"))
    end_date_raw = clean_text(request.args.get("end_date"))

    if view == "day":
        filter_query = filter_query.filter(date_column == today)
    elif view == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        filter_query = filter_query.filter(date_column.between(start, end))
    elif view == "month":
        start, end = month_bounds(today)
        filter_query = filter_query.filter(date_column.between(start, end))
    elif view == "date":
        parsed_exact_date, date_error = parse_date_field(exact_date_raw or today.strftime("%Y-%m-%d"), "Specific date")
        if not date_error and parsed_exact_date:
            filter_query = filter_query.filter(date_column == parsed_exact_date)
        else:
            view = "recent"
    elif view == "range":
        parsed_start_date, start_error = parse_date_field(start_date_raw, "Start date")
        parsed_end_date, end_error = parse_date_field(end_date_raw, "End date")
        if not start_error and not end_error and parsed_start_date and parsed_end_date and parsed_start_date <= parsed_end_date:
            filter_query = filter_query.filter(date_column.between(parsed_start_date, parsed_end_date))
        else:
            view = "recent"

    if view == "recent":
        return filter_query.order_by(date_column.desc()).limit(RECENT_RECORD_LIMIT).all()
    return filter_query.order_by(date_column.desc()).all()


def export_rows_to_excel(rows: list[dict], *, filename: str, sheet_name: str):
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame([{"Info": "No records found for this export view."}])
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name=sheet_name[:31] or "Sheet1")
    stream.seek(0)
    return send_file(
        stream,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def inventory_stock_label(item: InventoryItem) -> str:
    current_stock = float(item.current_stock or 0)
    minimum_stock = float(item.minimum_stock or 0)
    if current_stock <= 0:
        return "Out of Stock"
    if current_stock <= minimum_stock:
        return "Low Stock"
    return "In Stock"


def inventory_stock_badge_class(item: InventoryItem) -> str:
    label = inventory_stock_label(item)
    if label == "Out of Stock":
        return "text-bg-danger"
    if label == "Low Stock":
        return "text-bg-warning"
    return "text-bg-success"


def inventory_summary(client_id: int | None = None, include_inactive: bool = False) -> dict:
    query = InventoryItem.query
    movement_query = StockMovement.query.join(InventoryItem)
    if client_id is not None:
        query = query.filter(InventoryItem.client_id == client_id)
        movement_query = movement_query.filter(InventoryItem.client_id == client_id)
    if not include_inactive:
        query = query.filter(or_(InventoryItem.status == "active", InventoryItem.status.is_(None)))
        movement_query = movement_query.filter(or_(InventoryItem.status == "active", InventoryItem.status.is_(None)))
    items = query.all()
    low_stock_items = [item for item in items if inventory_stock_label(item) in {"Low Stock", "Out of Stock"}]
    out_of_stock_items = [item for item in items if inventory_stock_label(item) == "Out of Stock"]
    inactive_count_query = InventoryItem.query.filter(InventoryItem.status == "inactive")
    if client_id is not None:
        inactive_count_query = inactive_count_query.filter(InventoryItem.client_id == client_id)
    recent_restock_cutoff = date.today() - timedelta(days=7)
    recent_restocks = (
        movement_query.filter(StockMovement.movement_type == "IN")
        .order_by(StockMovement.movement_date.desc(), StockMovement.created_at.desc())
        .limit(5)
        .all()
    )
    recent_restock_count = (
        movement_query.filter(StockMovement.movement_type == "IN", StockMovement.movement_date >= recent_restock_cutoff)
        .count()
    )
    category_counts = {}
    for item in items:
        category = item.category or "Uncategorized"
        category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "total_items": len(items),
        "low_stock_count": len(low_stock_items),
        "out_of_stock_count": len(out_of_stock_items),
        "inactive_count": inactive_count_query.count(),
        "low_stock_items": low_stock_items,
        "recent_restocks": recent_restocks,
        "recent_restock_count": recent_restock_count,
        "category_counts": category_counts,
    }


def inventory_stock_progress(item: InventoryItem) -> int:
    current_stock = float(item.current_stock or 0)
    minimum_stock = float(item.minimum_stock or 0)
    if current_stock <= 0:
        return 0
    reference_stock = max(minimum_stock * 2, current_stock, 1)
    return max(6, min(int(round((current_stock / reference_stock) * 100)), 100))


def inventory_total_value(item: InventoryItem) -> float:
    return float(item.current_stock or 0) * float(item.cost_per_unit or 0)


def inventory_recent_activity(client_id: int | None = None, limit: int = 5) -> list[StockMovement]:
    query = StockMovement.query.join(InventoryItem)
    if client_id is not None:
        query = query.filter(InventoryItem.client_id == client_id)
    return (
        query.order_by(StockMovement.created_at.desc(), StockMovement.movement_date.desc())
        .limit(limit)
        .all()
    )


def inventory_activity_time_label(movement: StockMovement) -> str:
    if movement.created_at:
        delta = datetime.utcnow() - movement.created_at
        seconds = max(int(delta.total_seconds()), 0)
        if seconds < 3600:
            minutes = max(seconds // 60, 1)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        if seconds < 86400:
            hours = max(seconds // 3600, 1)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if movement.movement_date == date.today():
        return "Today"
    if movement.movement_date == date.today() - timedelta(days=1):
        return "Yesterday"
    return movement.movement_date.strftime("%d %b %Y")


def apply_stock_movement(item: InventoryItem, movement_type: str, quantity: float) -> None:
    current_stock = float(item.current_stock or 0)
    if movement_type == "IN":
        item.current_stock = current_stock + quantity
    elif movement_type == "OUT":
        item.current_stock = max(current_stock - quantity, 0)
    else:
        item.current_stock = max(current_stock + quantity, 0)


IMPORT_SPECS = {
    "menu_items": {
        "label": "Menu items",
        "redirect": "menu_engineering",
        "required": ["item_name", "category", "selling_price"],
        "optional": ["ingredient_cost", "labor_cost", "packaging_cost", "overhead_cost", "status"],
    },
    "sales": {
        "label": "Sales records",
        "redirect": "sales_entry",
        "required": ["sale_date", "menu_item", "quantity"],
        "optional": ["channel", "extra_expense"],
    },
    "expenses": {
        "label": "Expenses",
        "redirect": "expense_entry",
        "required": ["expense_date", "category", "amount"],
        "optional": ["note"],
    },
    "marketing": {
        "label": "Marketing campaigns",
        "redirect": "marketing_entry",
        "required": ["campaign_date", "campaign_name", "platform", "spend", "revenue_generated"],
        "optional": ["note"],
    },
    "reviews": {
        "label": "Customer reviews",
        "redirect": "review_entry",
        "required": ["review_date", "source", "rating", "review_text"],
        "optional": ["customer_name", "phone_number", "menu_item", "order_type", "receipt_number", "issue_tag", "client_username"],
    },
    "inventory_items": {
        "label": "Inventory items",
        "redirect": "inventory_page",
        "error_redirect": "inventory_import",
        "required": ["ingredient_name", "category", "unit", "current_stock", "minimum_stock", "cost_per_unit", "status"],
        "optional": ["supplier_name"],
    },
}


def import_specs_for_template() -> dict:
    return {
        key: {
            **spec,
            "columns": spec["required"] + spec["optional"],
        }
        for key, spec in IMPORT_SPECS.items()
    }


def import_cell(value):
    if pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.date()
    return value


def import_text(row: dict, column: str) -> str:
    value = import_cell(row.get(column, ""))
    if hasattr(value, "date") and not isinstance(value, date):
        value = value.date()
    return str(value).strip() if value is not None else ""


def import_date(row: dict, column: str, label: str):
    value = import_cell(row.get(column, ""))
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    return parse_date_field(value, label, required=True)


def import_int(row: dict, column: str, label: str, *, required: bool = False, min_value: int | None = None, max_value: int | None = None):
    value = import_cell(row.get(column, ""))
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return parse_int_field(value, label, required=required, min_value=min_value, max_value=max_value)


def import_float(row: dict, column: str, label: str, *, required: bool = False, min_value: float | None = None):
    value = import_cell(row.get(column, ""))
    return parse_float_field(value, label, required=required, min_value=min_value)


def read_import_rows(upload, spec: dict):
    filename = (upload.filename or "").lower()
    if not filename.endswith((".xlsx", ".xls")):
        return None, ["Please upload an Excel file ending in .xlsx or .xls."]
    try:
        df = pd.read_excel(upload, dtype=object)
    except ImportError:
        return None, ["Excel import requires the openpyxl package. Install requirements and try again."]
    except Exception as exc:
        return None, [f"Could not read the Excel file: {exc}"]
    df = df.dropna(how="all")
    df.columns = [str(col).strip().lower() for col in df.columns]
    required = set(spec["required"])
    allowed = set(spec["required"] + spec["optional"])
    missing = sorted(required - set(df.columns))
    if missing:
        return None, [f"Missing required columns: {', '.join(missing)}."]
    unknown = sorted(set(df.columns) - allowed)
    if unknown:
        return None, [f"Unexpected columns: {', '.join(unknown)}. Use only: {', '.join(spec['required'] + spec['optional'])}."]
    if df.empty:
        return None, ["The Excel file has no data rows."]
    return df.to_dict(orient="records"), []


def import_redirect_response(spec: dict, *, keep_panel_open: bool = False):
    if keep_panel_open and spec.get("error_redirect"):
        return redirect(url_for(spec["error_redirect"]))
    redirect_query = dict(spec.get("redirect_query") or {})
    if not keep_panel_open:
        redirect_query = {}
    return redirect(url_for(spec["redirect"], **redirect_query))


def validate_menu_import(rows: list[dict]):
    records, errors = [], []
    seen_names = set()
    for index, row in enumerate(rows, start=2):
        item_name = import_text(row, "item_name")
        category = import_text(row, "category")
        selling_price, price_error = import_float(row, "selling_price", "Selling price", required=True, min_value=0)
        ingredient_cost, ingredient_error = import_float(row, "ingredient_cost", "Ingredient cost", min_value=0)
        labor_cost, labor_error = import_float(row, "labor_cost", "Labor cost", min_value=0)
        packaging_cost, packaging_error = import_float(row, "packaging_cost", "Packaging cost", min_value=0)
        overhead_cost, overhead_error = import_float(row, "overhead_cost", "Overhead cost", min_value=0)
        status = import_text(row, "status") or "active"
        row_errors = extract_route_errors((selling_price, price_error), (ingredient_cost, ingredient_error), (labor_cost, labor_error), (packaging_cost, packaging_error), (overhead_cost, overhead_error))
        if not item_name:
            row_errors.append("Item name is required.")
        if not category:
            row_errors.append("Category is required.")
        if status not in {"active", "inactive"}:
            row_errors.append("Status must be active or inactive.")
        name_key = item_name.casefold()
        if name_key in seen_names:
            row_errors.append("Duplicate item name in upload.")
        elif item_name and scoped_query(MenuItem).filter(MenuItem.item_name == item_name).first():
            row_errors.append("Menu item already exists.")
        seen_names.add(name_key)
        if row_errors:
            errors.append(f"Row {index}: {' '.join(row_errors)}")
            continue
        records.append(MenuItem(item_name=item_name, category=category, selling_price=selling_price, ingredient_cost=ingredient_cost or 0, labor_cost=labor_cost or 0, packaging_cost=packaging_cost or 0, overhead_cost=overhead_cost or 0, status=status, **owner_payload()))
    return records, errors


def validate_sales_import(rows: list[dict]):
    records, errors = [], []
    for index, row in enumerate(rows, start=2):
        sale_date, date_error = import_date(row, "sale_date", "Sale date")
        quantity, quantity_error = import_int(row, "quantity", "Quantity", required=True, min_value=1)
        extra_expense, extra_error = import_float(row, "extra_expense", "Extra expense", min_value=0)
        menu_item_name = import_text(row, "menu_item")
        channel = import_text(row, "channel") or "Walk-in"
        row_errors = extract_route_errors((sale_date, date_error), (quantity, quantity_error), (extra_expense, extra_error))
        menu_item = scoped_query(MenuItem).filter(MenuItem.item_name == menu_item_name).first() if menu_item_name else None
        if not menu_item_name:
            row_errors.append("Menu item is required.")
        elif not menu_item:
            row_errors.append("Menu item was not found in Menu Engineering.")
        if channel not in SALES_CHANNELS:
            row_errors.append(f"Channel must be one of: {', '.join(SALES_CHANNELS)}.")
        if row_errors:
            errors.append(f"Row {index}: {' '.join(row_errors)}")
            continue
        unit_cost = (menu_item.ingredient_cost or 0) + (menu_item.labor_cost or 0) + (menu_item.packaging_cost or 0) + (menu_item.overhead_cost or 0)
        records.append(Sale(sale_date=sale_date, menu_item_id=menu_item.id, quantity=quantity, unit_price=menu_item.selling_price or 0, unit_cost=unit_cost, extra_expense=extra_expense or 0, channel=channel, **owner_payload()))
    return records, errors


def validate_expense_import(rows: list[dict]):
    records, errors = [], []
    for index, row in enumerate(rows, start=2):
        expense_date, date_error = import_date(row, "expense_date", "Expense date")
        amount, amount_error = import_float(row, "amount", "Amount", required=True, min_value=0)
        category = import_text(row, "category")
        note = import_text(row, "note")
        row_errors = extract_route_errors((expense_date, date_error), (amount, amount_error))
        if not category:
            row_errors.append("Category is required.")
        if row_errors:
            errors.append(f"Row {index}: {' '.join(row_errors)}")
            continue
        records.append(Expense(expense_date=expense_date, category=category, amount=amount, note=note, **owner_payload()))
    return records, errors


def validate_marketing_import(rows: list[dict]):
    records, errors = [], []
    for index, row in enumerate(rows, start=2):
        campaign_date, date_error = import_date(row, "campaign_date", "Campaign date")
        spend, spend_error = import_float(row, "spend", "Spend", required=True, min_value=0)
        revenue_generated, revenue_error = import_float(row, "revenue_generated", "Revenue", required=True, min_value=0)
        campaign_name = import_text(row, "campaign_name")
        platform = import_text(row, "platform")
        note = import_text(row, "note")
        row_errors = extract_route_errors((campaign_date, date_error), (spend, spend_error), (revenue_generated, revenue_error))
        if not campaign_name:
            row_errors.append("Campaign name is required.")
        if not platform:
            row_errors.append("Platform is required.")
        if row_errors:
            errors.append(f"Row {index}: {' '.join(row_errors)}")
            continue
        records.append(MarketingCampaign(campaign_date=campaign_date, campaign_name=campaign_name, platform=platform, spend=spend, revenue_generated=revenue_generated, note=note, **owner_payload()))
    return records, errors


def validate_review_import(rows: list[dict]):
    records, errors = [], []
    for index, row in enumerate(rows, start=2):
        review_date, date_error = import_date(row, "review_date", "Review date")
        rating, rating_error = import_int(row, "rating", "Rating", required=True, min_value=1, max_value=5)
        source = import_text(row, "source") or "Manual Entry"
        review_text = import_text(row, "review_text")
        order_type = import_text(row, "order_type") or None
        issue_tag = import_text(row, "issue_tag") or detect_issue_tag(review_text)
        client_username = import_text(row, "client_username")
        client_id = current_client_id()
        if staff_required() and client_id is None:
            row_errors = ["Choose a client portfolio before importing reviews."]
        else:
            row_errors = []
        row_errors.extend(extract_route_errors((review_date, date_error), (rating, rating_error)))
        if not review_text:
            row_errors.append("Review text is required.")
        if source not in REVIEW_SOURCES:
            row_errors.append("Invalid review source.")
        if order_type and order_type not in ORDER_TYPES:
            row_errors.append("Invalid order type.")
        if issue_tag not in ISSUE_TAGS:
            row_errors.append("Invalid issue tag.")
        if row_errors:
            errors.append(f"Row {index}: {' '.join(row_errors)}")
            continue
        label, score = analyze_sentiment(review_text, rating)
        records.append(CustomerReview(review_date=review_date, client_id=client_id, customer_name=import_text(row, "customer_name") or None, phone_number=import_text(row, "phone_number") or None, menu_item=import_text(row, "menu_item") or None, order_type=order_type, source=source, rating=rating, review_text=review_text, receipt_number=import_text(row, "receipt_number") or None, issue_tag=issue_tag, urgency_level=determine_urgency_level(label, rating, issue_tag, review_text), submission_channel="manual", sentiment_label=label, sentiment_score=score))
    return records, errors


def validate_inventory_import(rows: list[dict]):
    records, errors = [], []
    seen_keys = set()
    owner = client_owner_payload_from_form()

    if staff_required() and not owner.get("client_id"):
        return [], ["Select a client before importing inventory items."]
    if owner.get("client_id") and not User.query.filter_by(id=owner["client_id"], role=RoleService.CLIENT).first():
        return [], ["Selected client is invalid."]

    for index, row in enumerate(rows, start=2):
        ingredient_name = import_text(row, "ingredient_name")
        category = import_text(row, "category")
        unit = import_text(row, "unit")
        current_stock, current_stock_error = import_float(row, "current_stock", "Current stock", required=True, min_value=0)
        minimum_stock, minimum_stock_error = import_float(row, "minimum_stock", "Minimum stock", required=True, min_value=0)
        cost_per_unit, cost_per_unit_error = import_float(row, "cost_per_unit", "Cost per unit", required=True, min_value=0)
        supplier_name = import_text(row, "supplier_name") or None
        status = (import_text(row, "status") or "active").strip().lower()
        row_errors = extract_route_errors(
            (current_stock, current_stock_error),
            (minimum_stock, minimum_stock_error),
            (cost_per_unit, cost_per_unit_error),
        )
        if not ingredient_name:
            row_errors.append("Ingredient name is required.")
        if not category:
            row_errors.append("Category is required.")
        if unit not in INVENTORY_UNITS:
            row_errors.append(f"Unit must be one of: {', '.join(INVENTORY_UNITS)}.")
        if status not in {"active", "inactive"}:
            row_errors.append("Status must be active or inactive.")

        duplicate_key = (ingredient_name.casefold(), category.casefold())
        if duplicate_key in seen_keys:
            row_errors.append("Duplicate ingredient/category combination in upload.")
        else:
            seen_keys.add(duplicate_key)
        if ingredient_name and category:
            existing_query = InventoryItem.query.filter(
                InventoryItem.ingredient_name == ingredient_name,
                InventoryItem.category == category,
            )
            if owner.get("client_id") is not None:
                existing_query = existing_query.filter(InventoryItem.client_id == owner["client_id"])
            else:
                existing_query = existing_query.filter(InventoryItem.client_id.is_(None))
            if existing_query.first():
                row_errors.append("This ingredient/category already exists for the selected inventory owner.")

        if row_errors:
            errors.append(f"Row {index}: {' '.join(row_errors)}")
            continue

        records.append(
            InventoryItem(
                ingredient_name=ingredient_name,
                category=category,
                unit=unit,
                current_stock=current_stock,
                minimum_stock=minimum_stock,
                cost_per_unit=cost_per_unit,
                supplier_name=supplier_name,
                status=status,
                **owner,
            )
        )
    return records, errors


IMPORT_VALIDATORS = {
    "menu_items": validate_menu_import,
    "sales": validate_sales_import,
    "expenses": validate_expense_import,
    "marketing": validate_marketing_import,
    "reviews": validate_review_import,
    "inventory_items": validate_inventory_import,
}


def compute_dashboard_metrics(client_id: int | None = None) -> dict:
    sales_query = Sale.query
    expenses_query = Expense.query
    campaigns_query = MarketingCampaign.query
    reviews_query = CustomerReview.query
    if client_id is not None:
        sales_query = sales_query.filter(Sale.client_id == client_id)
        expenses_query = expenses_query.filter(Expense.client_id == client_id)
        campaigns_query = campaigns_query.filter(MarketingCampaign.client_id == client_id)
        reviews_query = reviews_query.filter(CustomerReview.client_id == client_id)
    sales = sales_query.all()
    expenses = expenses_query.all()
    campaigns = campaigns_query.all()
    reviews = reviews_query.all()

    sales_df = pd.DataFrame(
        [
            {
                "date": s.sale_date,
                "revenue": s.quantity * s.unit_price,
                "cost": s.quantity * s.unit_cost + s.extra_expense,
                "item": s.menu_item.item_name if s.menu_item else "Unknown",
                "qty": s.quantity,
                "channel": s.channel or "Unspecified",
            }
            for s in sales
        ]
    )
    expense_df = pd.DataFrame([{"date": e.expense_date, "amount": e.amount} for e in expenses])
    campaign_df = pd.DataFrame(
        [
            {
                "campaign": c.campaign_name,
                "spend": c.spend,
                "revenue": c.revenue_generated,
                "date": c.campaign_date,
            }
            for c in campaigns
        ]
    )
    review_df = pd.DataFrame(
        [
            {
                "date": r.review_date,
                "sentiment_label": r.sentiment_label,
                "sentiment_score": r.sentiment_score,
            }
            for r in reviews
        ]
    )

    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    trend_dates = []
    if not sales_df.empty:
        trend_dates.extend(sales_df["date"].dropna().tolist())
    if not expense_df.empty:
        trend_dates.extend(expense_df["date"].dropna().tolist())
    trend_year = max((d.year for d in trend_dates), default=date.today().year)
    monthly_gross_revenue = [0.0] * 12
    monthly_total_expenses = [0.0] * 12

    if not sales_df.empty:
        trend_sales = sales_df[sales_df["date"].apply(lambda d: d.year == trend_year)]
        for _, row in trend_sales.iterrows():
            month_index = row["date"].month - 1
            monthly_gross_revenue[month_index] += float(row["revenue"] or 0)
            monthly_total_expenses[month_index] += float(row["cost"] or 0)

    if not expense_df.empty:
        trend_expenses = expense_df[expense_df["date"].apply(lambda d: d.year == trend_year)]
        for _, row in trend_expenses.iterrows():
            month_index = row["date"].month - 1
            monthly_total_expenses[month_index] += float(row["amount"] or 0)

    monthly_net_income = [
        gross - expenses_total
        for gross, expenses_total in zip(monthly_gross_revenue, monthly_total_expenses)
    ]
    monthly_revenue_trend = {
        "year": trend_year,
        "labels": month_labels,
        "gross_revenue": [round(value, 2) for value in monthly_gross_revenue],
        "net_income": [round(value, 2) for value in monthly_net_income],
        "total_expenses": [round(value, 2) for value in monthly_total_expenses],
    }

    roi_dates = trend_dates[:]
    if not campaign_df.empty:
        roi_dates.extend(campaign_df["date"].dropna().tolist())
    roi_year = max((d.year for d in roi_dates), default=date.today().year)
    monthly_sales = [0.0] * 12
    monthly_campaign_spend = [0.0] * 12
    monthly_campaign_revenue = [0.0] * 12

    if not sales_df.empty:
        roi_sales = sales_df[sales_df["date"].apply(lambda d: d.year == roi_year)]
        for _, row in roi_sales.iterrows():
            monthly_sales[row["date"].month - 1] += float(row["revenue"] or 0)

    if not campaign_df.empty:
        roi_campaigns = campaign_df[campaign_df["date"].apply(lambda d: d.year == roi_year)]
        for _, row in roi_campaigns.iterrows():
            month_index = row["date"].month - 1
            monthly_campaign_spend[month_index] += float(row["spend"] or 0)
            monthly_campaign_revenue[month_index] += float(row["revenue"] or 0)

    monthly_roi = [
        campaign_roi(spend, revenue)
        for spend, revenue in zip(monthly_campaign_spend, monthly_campaign_revenue)
    ]
    highest_sales_index = max(range(12), key=lambda index: monthly_sales[index]) if any(monthly_sales) else None
    roi_month_indexes = [index for index, spend in enumerate(monthly_campaign_spend) if spend > 0]
    lowest_roi_index = min(roi_month_indexes, key=lambda index: monthly_roi[index]) if roi_month_indexes else None
    monthly_sales_roi_graph = {
        "year": roi_year,
        "labels": month_labels,
        "sales": [round(value, 2) for value in monthly_sales],
        "roi": [round(value, 2) for value in monthly_roi],
        "highest_sales_month": month_labels[highest_sales_index] if highest_sales_index is not None else None,
        "highest_sales_value": round(monthly_sales[highest_sales_index], 2) if highest_sales_index is not None else 0,
        "lowest_roi_month": month_labels[lowest_roi_index] if lowest_roi_index is not None else None,
        "lowest_roi_value": round(monthly_roi[lowest_roi_index], 2) if lowest_roi_index is not None else 0,
        "active_marketing_months": len(roi_month_indexes),
    }

    total_roi = 0.0
    campaign_roi_list = []
    if not campaign_df.empty:
        campaign_group = campaign_df.groupby("campaign", as_index=False).agg(spend=("spend", "sum"), revenue=("revenue", "sum"))
        campaign_group["roi"] = campaign_group.apply(lambda r: campaign_roi(r["spend"], r["revenue"]), axis=1)
        campaign_roi_list = campaign_group.to_dict(orient="records")
        total_spend = campaign_group["spend"].sum()
        total_revenue = campaign_group["revenue"].sum()
        total_roi = campaign_roi(total_spend, total_revenue)

    if sales_df.empty:
        return {
            "kpis": {"revenue": 0, "cost": 0, "profit": 0, "roi": round(float(total_roi), 2), "positive_sentiment": 0},
            "revenue_labels": [],
            "revenue_values": [],
            "cash_values": [],
            "forecast_labels": [],
            "forecast_revenue": [],
            "forecast_cash": [],
            "campaign_roi": campaign_roi_list,
            "sentiment_counts": {"positive": 0, "neutral": 0, "negative": 0},
            "sentiment_vs_sales_labels": [],
            "sentiment_vs_sales_revenue": [],
            "sentiment_vs_sales_sentiment": [],
            "revenue_by_channel": [],
            "revenue_by_channel_total": 0,
            "menu_performance": [],
            "peak_day": None,
            "low_day": None,
            "monthly_revenue_trend": monthly_revenue_trend,
            "monthly_sales_roi_graph": monthly_sales_roi_graph,
        }

    daily_sales = sales_df.groupby("date", as_index=False).agg(revenue=("revenue", "sum"), cost=("cost", "sum"))
    daily_exp = (
        expense_df.groupby("date", as_index=False).agg(op_expense=("amount", "sum"))
        if not expense_df.empty
        else pd.DataFrame(columns=["date", "op_expense"])
    )
    daily_campaigns = (
        campaign_df.groupby("date", as_index=False).agg(marketing_spend=("spend", "sum"))
        if not campaign_df.empty
        else pd.DataFrame(columns=["date", "marketing_spend"])
    )

    all_financial_dates = sorted(
        {
            *daily_sales["date"].dropna().tolist(),
            *daily_exp["date"].dropna().tolist(),
            *daily_campaigns["date"].dropna().tolist(),
        }
    )
    daily = pd.DataFrame({"date": all_financial_dates})
    daily = daily.merge(daily_sales, on="date", how="left")
    daily = daily.merge(daily_exp, on="date", how="left")
    daily = daily.merge(daily_campaigns, on="date", how="left")
    daily = daily.fillna({"revenue": 0, "cost": 0, "op_expense": 0, "marketing_spend": 0}).sort_values("date")

    daily["total_expenses"] = daily["cost"] + daily["op_expense"] + daily["marketing_spend"]
    daily["profit"] = daily["revenue"] - daily["total_expenses"]
    daily["cash_flow"] = daily["profit"].cumsum()

    future_days = 14
    forecast_revenue = forecast_values(daily["revenue"], future_days)
    forecast_expenses = forecast_values(daily["total_expenses"], future_days)
    forecast_cash = [round(revenue - expenses, 2) for revenue, expenses in zip(forecast_revenue, forecast_expenses)]
    forecast_dates = [(daily["date"].max() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, future_days + 1)]

    sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0}
    compare_labels, compare_sales, compare_sentiment = [], [], []
    positive_ratio = 0.0
    if not review_df.empty:
        counts = review_df["sentiment_label"].value_counts().to_dict()
        sentiment_counts.update(counts)
        positive_ratio = (review_df["sentiment_label"] == "positive").mean() * 100

        sentiment_daily = review_df.groupby("date", as_index=False).agg(sentiment_score=("sentiment_score", "mean"))
        joined = daily[["date", "revenue"]].merge(sentiment_daily, on="date", how="left").ffill()
        joined = joined.dropna()
        compare_labels = [d.strftime("%Y-%m-%d") for d in joined["date"]]
        compare_sales = joined["revenue"].round(2).tolist()
        compare_sentiment = joined["sentiment_score"].round(3).tolist()

    menu_perf = (
        sales_df.groupby("item", as_index=False)
        .agg(quantity=("qty", "sum"), revenue=("revenue", "sum"), cost=("cost", "sum"))
        .assign(profit=lambda d: d["revenue"] - d["cost"])
    )
    channel_revenue = (
        sales_df.groupby("channel", as_index=False)
        .agg(revenue=("revenue", "sum"))
        .sort_values("revenue", ascending=False)
    )
    channel_revenue["revenue"] = channel_revenue["revenue"].round(2)

    peak_day = daily.loc[daily["revenue"].idxmax(), "date"] if not daily.empty else None
    low_day = daily.loc[daily["revenue"].idxmin(), "date"] if not daily.empty else None

    total_revenue = round(float(daily["revenue"].sum()), 2)
    return {
        "kpis": {
            "revenue": total_revenue,
            "cost": round(float(daily["total_expenses"].sum()), 2),
            "profit": round(float(daily["profit"].sum()), 2),
            "roi": round(float(total_roi), 2),
            "positive_sentiment": round(float(positive_ratio), 2),
        },
        "revenue_labels": [d.strftime("%Y-%m-%d") for d in daily["date"]],
        "revenue_values": daily["revenue"].round(2).tolist(),
        "cash_values": daily["cash_flow"].round(2).tolist(),
        "forecast_labels": forecast_dates,
        "forecast_revenue": [round(x, 2) for x in forecast_revenue],
        "forecast_cash": [round(x, 2) for x in forecast_cash],
        "campaign_roi": campaign_roi_list,
        "sentiment_counts": sentiment_counts,
        "sentiment_vs_sales_labels": compare_labels,
        "sentiment_vs_sales_revenue": compare_sales,
        "sentiment_vs_sales_sentiment": compare_sentiment,
        "revenue_by_channel": channel_revenue.to_dict(orient="records"),
        "revenue_by_channel_total": total_revenue,
        "menu_performance": menu_perf.to_dict(orient="records"),
        "peak_day": peak_day.strftime("%Y-%m-%d") if peak_day else None,
        "low_day": low_day.strftime("%Y-%m-%d") if low_day else None,
        "monthly_revenue_trend": monthly_revenue_trend,
        "monthly_sales_roi_graph": monthly_sales_roi_graph,
    }


def generate_revenue_forecast_if_needed(client_id: int) -> dict:
    if client_id is None:
        print("[forecast debug] selected client_id: None", flush=True)
        return {
            "generated": False,
            "message": "Choose a client portfolio before viewing revenue forecasts.",
            "avg_daily_revenue": 0,
            "rows_created": 0,
        }

    total_revenue, active_sale_days = (
        db.session.query(
            func.coalesce(func.sum(Sale.quantity * Sale.unit_price), 0),
            func.count(distinct(Sale.sale_date)),
        )
        .filter(Sale.client_id == client_id)
        .one()
    )

    total_revenue = float(total_revenue or 0)
    active_sale_days = int(active_sale_days or 0)

    ForecastResult.query.filter(
        ForecastResult.client_id == client_id,
        ForecastResult.metric == "revenue",
    ).delete(synchronize_session=False)

    if active_sale_days <= 0:
        db.session.commit()
        print(f"[forecast debug] selected client_id: {client_id}", flush=True)
        print("[forecast debug] no sales rows found for revenue forecast generation", flush=True)
        print("[forecast debug] revenue forecast rows generated: 0", flush=True)
        return {
            "generated": False,
            "message": "No sales data yet. Add sales records to generate the next 14 days of revenue forecasts.",
            "avg_daily_revenue": 0,
            "rows_created": 0,
        }

    avg_daily_revenue = round(total_revenue / active_sale_days, 2)
    today = date.today()
    forecast_rows = [
        ForecastResult(
            client_id=client_id,
            forecast_date=today + timedelta(days=day_offset),
            metric="revenue",
            value=avg_daily_revenue,
        )
        for day_offset in range(1, 15)
    ]
    db.session.add_all(forecast_rows)
    db.session.commit()

    print(f"[forecast debug] selected client_id: {client_id}", flush=True)
    print(f"[forecast debug] total sales revenue used: {round(total_revenue, 2)}", flush=True)
    print(f"[forecast debug] active sale days used: {active_sale_days}", flush=True)
    print(f"[forecast debug] avg daily revenue generated: {avg_daily_revenue}", flush=True)
    print(f"[forecast debug] revenue forecast rows generated: {len(forecast_rows)}", flush=True)

    return {
        "generated": True,
        "message": "",
        "avg_daily_revenue": avg_daily_revenue,
        "rows_created": len(forecast_rows),
    }


def build_forecast_revenue_chart_data(client_id: int) -> dict:
    revenue_rows = (
        ForecastResult.query.filter(
            ForecastResult.client_id == client_id,
            ForecastResult.metric == "revenue",
        )
        .order_by(ForecastResult.forecast_date.asc())
        .all()
    )
    labels = [row.forecast_date.strftime("%Y-%m-%d") for row in revenue_rows]
    values = [round(float(row.value or 0), 2) for row in revenue_rows]

    print(f"[forecast debug] selected client_id: {client_id}", flush=True)
    print(f"[forecast debug] revenue forecast rows found: {len(revenue_rows)}", flush=True)
    print(f"[forecast debug] revenue forecast values sent to chart: {values}", flush=True)

    return {
        "forecast_labels": labels,
        "forecast_revenue_labels": labels,
        "forecast_revenue": values,
    }


def parse_inventory_form_submission():
    item_id_raw = clean_text(request.form.get("inventory_item_id"))
    item_id_res = parse_int_field(item_id_raw, "Inventory item ID")
    ingredient_name = clean_text(request.form.get("ingredient_name"))
    category = clean_text(request.form.get("category"))
    unit = clean_text(request.form.get("unit"))
    current_stock_res = parse_float_field(request.form.get("current_stock"), "Current stock", required=True, min_value=0)
    minimum_stock_res = parse_float_field(request.form.get("minimum_stock"), "Minimum stock", required=True, min_value=0)
    cost_per_unit_res = parse_float_field(request.form.get("cost_per_unit"), "Cost per unit", min_value=0)
    supplier_name = clean_text(request.form.get("supplier_name")) or None
    status = clean_text(request.form.get("status")) or "active"
    owner = client_owner_payload_from_form()
    errors = extract_route_errors(item_id_res, current_stock_res, minimum_stock_res, cost_per_unit_res)
    if not ingredient_name:
        errors.append("Ingredient name is required.")
    if not category:
        errors.append("Category is required.")
    if unit not in INVENTORY_UNITS:
        errors.append("Choose a valid stock unit.")
    if status not in {"active", "inactive"}:
        errors.append("Status must be active or inactive.")
    if staff_required() and not owner.get("client_id"):
        errors.append("Select a client for this inventory item.")
    if owner.get("client_id") and not User.query.filter_by(id=owner["client_id"], role=RoleService.CLIENT).first():
        errors.append("Selected client is invalid.")
    payload = {
        "ingredient_name": ingredient_name,
        "category": category,
        "unit": unit,
        "current_stock": current_stock_res[0],
        "minimum_stock": minimum_stock_res[0],
        "cost_per_unit": cost_per_unit_res[0] or 0,
        "supplier_name": supplier_name,
        "status": status,
        **owner,
    }
    return item_id_raw, item_id_res, payload, errors


def build_inventory_page_context() -> dict:
    status_filter = clean_text(request.args.get("status")) or "all"
    if status_filter not in {"all", "in_stock", "low_stock", "out_of_stock"}:
        status_filter = "all"
    search_term = clean_text(request.args.get("q"))
    category_filter = clean_text(request.args.get("category"))
    page_number = max(request.args.get("page", type=int) or 1, 1)
    per_page = 4
    items_query = scoped_query(InventoryItem).filter(or_(InventoryItem.status == "active", InventoryItem.status.is_(None)))
    inactive_items_query = scoped_query(InventoryItem).filter(InventoryItem.status == "inactive")
    if search_term:
        items_query = items_query.filter(
            or_(
                InventoryItem.ingredient_name.ilike(f"%{search_term}%"),
                InventoryItem.category.ilike(f"%{search_term}%"),
            )
        )
        inactive_items_query = inactive_items_query.filter(
            or_(
                InventoryItem.ingredient_name.ilike(f"%{search_term}%"),
                InventoryItem.category.ilike(f"%{search_term}%"),
            )
        )
    if category_filter:
        items_query = items_query.filter(InventoryItem.category == category_filter)
        inactive_items_query = inactive_items_query.filter(InventoryItem.category == category_filter)
    if status_filter == "in_stock":
        items_query = items_query.filter(InventoryItem.current_stock > InventoryItem.minimum_stock)
    elif status_filter == "low_stock":
        items_query = items_query.filter(InventoryItem.current_stock > 0, InventoryItem.current_stock <= InventoryItem.minimum_stock)
    elif status_filter == "out_of_stock":
        items_query = items_query.filter(InventoryItem.current_stock <= 0)

    filtered_items = items_query.order_by(InventoryItem.ingredient_name.asc()).all()
    filtered_total = len(filtered_items)
    total_pages = ((filtered_total - 1) // per_page) + 1 if filtered_total else 1
    page_number = min(page_number, total_pages)
    start_idx = (page_number - 1) * per_page
    end_idx = start_idx + per_page
    items = filtered_items[start_idx:end_idx]
    inactive_items = inactive_items_query.order_by(InventoryItem.ingredient_name.asc()).all()
    category_rows = (
        scoped_query(InventoryItem)
        .with_entities(InventoryItem.category)
        .distinct()
        .order_by(InventoryItem.category.asc())
        .all()
    )
    category_options = [row[0] for row in category_rows if row[0]]
    summary = inventory_summary(current_client_id())
    recent_activity = inventory_recent_activity(current_client_id())
    category_distribution = [
        {"label": label, "value": value}
        for label, value in sorted(summary["category_counts"].items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "items": items,
        "inactive_items": inactive_items,
        "inventory_summary": summary,
        "recent_activity": recent_activity,
        "category_distribution": category_distribution,
        "category_options": category_options,
        "inventory_filters": {
            "status": status_filter,
            "q": search_term,
            "category": category_filter,
            "has_filters": bool(search_term or category_filter or status_filter != "all"),
            "filtered_count": filtered_total,
        },
        "inventory_pagination": {
            "page": page_number,
            "per_page": per_page,
            "total": filtered_total,
            "total_pages": total_pages,
            "showing_from": start_idx + 1 if filtered_total else 0,
            "showing_to": min(end_idx, filtered_total),
        },
    }


def build_menu_engineering_data(
    search: str = "",
    category: str = "All",
    sort_by: str = "item_name",
    sort_dir: str = "asc",
    client_id: int | None = None,
) -> dict:
    query = MenuItem.query
    category_query = MenuItem.query
    if client_id is not None:
        query = query.filter(MenuItem.client_id == client_id)
        category_query = category_query.filter(MenuItem.client_id == client_id)
    if search:
        query = query.filter(MenuItem.item_name.ilike(f"%{search}%"))
    if category and category != "All":
        query = query.filter(MenuItem.category == category)

    items = query.order_by(MenuItem.item_name.asc()).all()
    active_items = [i for i in items if i.status == "active"]
    item_ids = [i.id for i in items]
    sales_rows = []
    if item_ids:
        sales_query = Sale.query.filter(Sale.menu_item_id.in_(item_ids))
        if client_id is not None:
            sales_query = sales_query.filter(Sale.client_id == client_id)
        sales_rows = sales_query.all()

    sales_by_item = {item_id: {"quantity_sold": 0, "total_profit": 0.0} for item_id in item_ids}
    for sale in sales_rows:
        item_sales = sales_by_item.setdefault(sale.menu_item_id, {"quantity_sold": 0, "total_profit": 0.0})
        item_sales["quantity_sold"] += sale.quantity or 0
        item_sales["total_profit"] += ((sale.unit_price or 0) - (sale.unit_cost or 0)) * (sale.quantity or 0) - (sale.extra_expense or 0)

    def computed(i: MenuItem) -> dict:
        total_unit_cost = (i.ingredient_cost or 0) + (i.labor_cost or 0) + (i.packaging_cost or 0) + (i.overhead_cost or 0)
        contribution_margin = (i.selling_price or 0) - total_unit_cost
        sales_totals = sales_by_item.get(i.id, {"quantity_sold": 0, "total_profit": 0.0})
        profit_margin_percent = (contribution_margin / i.selling_price * 100) if i.selling_price else 0
        return {
            "id": i.id,
            "item_name": i.item_name,
            "category": i.category,
            "selling_price": round(i.selling_price or 0, 2),
            "total_unit_cost": round(total_unit_cost, 2),
            "contribution_margin": round(contribution_margin, 2),
            "quantity_sold": int(sales_totals["quantity_sold"]),
            "total_profit": round(sales_totals["total_profit"], 2),
            "profit_margin_percent": round(profit_margin_percent, 2),
            "status": i.status,
        }

    rows = [computed(i) for i in items]
    active_rows = [r for r in rows if r["status"] == "active"] or rows
    avg_popularity = sum(r["quantity_sold"] for r in active_rows) / max(len(active_rows), 1)
    avg_profitability = sum(r["contribution_margin"] for r in active_rows) / max(len(active_rows), 1)

    counts = {"Star": 0, "Plowhorse": 0, "Puzzle": 0, "Dog": 0}
    recommendations = {
        "Star": "Maintain quality and visibility. Consider as signature item.",
        "Plowhorse": "Increase price slightly or reduce portion cost carefully.",
        "Puzzle": "Improve promotion, naming, and photo. Test price optimization.",
        "Dog": "Consider removing, replacing, or redesigning this item.",
    }

    for r in rows:
        high_profit = r["contribution_margin"] >= avg_profitability
        high_pop = r["quantity_sold"] >= avg_popularity
        if high_profit and high_pop:
            cls = "Star"
        elif not high_profit and high_pop:
            cls = "Plowhorse"
        elif high_profit and not high_pop:
            cls = "Puzzle"
        else:
            cls = "Dog"
        r["classification"] = cls
        r["recommendation"] = recommendations[cls]
        counts[cls] += 1

    sortable_fields = {"quantity_sold", "contribution_margin", "total_profit", "classification", "item_name"}
    if sort_by in sortable_fields:
        rows.sort(key=lambda x: x[sort_by], reverse=(sort_dir == "desc"))

    categories = ["All"] + sorted(list({i.category for i in category_query.all() if i.category}))
    return {
        "rows": rows,
        "counts": counts,
        "avg_popularity": round(avg_popularity, 2),
        "avg_profitability": round(avg_profitability, 2),
        "categories": categories,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }


def client_status_label(client: User) -> str:
    return (client.status or "active").strip().lower()


def client_portfolio_summary(client: User) -> dict:
    metrics = compute_dashboard_metrics(client.id)
    last_activity_candidates = [
        Sale.query.filter_by(client_id=client.id).order_by(Sale.created_at.desc()).first(),
        Expense.query.filter_by(client_id=client.id).order_by(Expense.created_at.desc()).first(),
        MarketingCampaign.query.filter_by(client_id=client.id).order_by(MarketingCampaign.created_at.desc()).first(),
        CustomerReview.query.filter_by(client_id=client.id).order_by(CustomerReview.created_at.desc()).first(),
        InventoryItem.query.filter_by(client_id=client.id).order_by(InventoryItem.updated_at.desc()).first(),
        AnalystNote.query.filter_by(client_user_id=client.id).order_by(AnalystNote.created_at.desc()).first(),
    ]
    last_activity = max(
        [record.created_at for record in last_activity_candidates if record and record.created_at],
        default=None,
    )
    return {
        "client": client,
        "status": client_status_label(client),
        "metrics": metrics["kpis"],
        "sales_count": Sale.query.filter_by(client_id=client.id).count(),
        "reviews_count": CustomerReview.query.filter_by(client_id=client.id).count(),
        "inventory_count": InventoryItem.query.filter_by(client_id=client.id).count(),
        "notes_count": AnalystNote.query.filter_by(client_user_id=client.id).count(),
        "last_activity": last_activity,
        "created_at": client.created_at,
        "last_login_at": client.last_login_at,
    }


def register_routes(app: Flask) -> None:
    @app.route("/", methods=["GET", "POST"])
    def login():
        selected_portal = "consultant"
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            selected_portal = request.form.get("login_role_view", "consultant").strip().lower()
            allowed_portals = {"consultant", "client"}
            if selected_portal not in allowed_portals:
                flash("Please choose a valid login portal.", "danger")
                return render_template("login.html", selected_portal="consultant")

            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password, password):
                user_role = user.role or RoleService.CLIENT
                if (user.status or "active").lower() != "active":
                    flash("This account is inactive. Please contact your consultant.", "warning")
                    return render_template("login.html", selected_portal=selected_portal)
                if selected_portal == "consultant" and user_role != RoleService.ADMIN_ANALYST:
                    flash("Client accounts must log in through Client View.", "danger")
                    return render_template("login.html", selected_portal=selected_portal)
                if selected_portal == "client" and user_role != RoleService.CLIENT:
                    flash("Consultant accounts must log in through Consultant.", "danger")
                    return render_template("login.html", selected_portal=selected_portal)

                session["user_id"] = user.id
                session["full_name"] = user.full_name
                session["role"] = user_role
                session.pop("selected_client_id", None)
                session.pop("selected_client_name", None)
                user.last_login_at = datetime.utcnow()
                db.session.commit()
                if user_role == RoleService.ADMIN_ANALYST:
                    return redirect(url_for("clients_page"))
                return redirect(url_for("dashboard"))
            flash("Invalid username or password.", "danger")
        return render_template("login.html", selected_portal=selected_portal)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        login_redirect = require_login_redirect()
        if login_redirect:
            return login_redirect

        user = db.session.get(User, session["user_id"])
        if not user:
            session.clear()
            flash("Please log in again.", "warning")
            return redirect(url_for("login"))
        is_client_account = (user.role or RoleService.CLIENT) == RoleService.CLIENT
        dashboard_periods = {
            "week": "Last 7 days",
            "month": "This month",
            "quarter": "This quarter",
            "year": "This year",
        }

        if request.method == "POST":
            form_name = clean_text(request.form.get("form_name"))
            if form_name == "account":
                full_name = clean_text(request.form.get("full_name"))
                username = clean_text(request.form.get("username"))
                phone_number = clean_text(request.form.get("phone_number")) or None
                preferred_period = clean_text(request.form.get("preferred_dashboard_period")) or "month"
                errors = []
                if not full_name:
                    errors.append("Name is required.")
                if not username:
                    errors.append("Username or email is required.")
                if preferred_period not in dashboard_periods:
                    errors.append("Choose a valid dashboard period.")
                existing_user = User.query.filter(User.username == username, User.id != user.id).first() if username else None
                if existing_user:
                    errors.append("That username or email is already in use.")
                if errors:
                    flash(" ".join(errors), "danger")
                    return redirect(url_for("settings_page"))

                user.full_name = full_name
                user.username = username
                user.phone_number = phone_number
                user.preferred_dashboard_period = preferred_period
                if is_client_account:
                    user.business_address = clean_text(request.form.get("business_address")) or None
                    user.business_type = clean_text(request.form.get("business_type")) or None
                db.session.commit()
                session["full_name"] = user.full_name
                flash("Account settings saved.", "success")
                return redirect(url_for("settings_page"))

            if form_name == "password":
                current_password = request.form.get("current_password", "")
                new_password = request.form.get("new_password", "")
                confirm_password = request.form.get("confirm_password", "")
                errors = []
                if not check_password_hash(user.password, current_password):
                    errors.append("Current password is incorrect.")
                if len(new_password) < 8:
                    errors.append("New password must be at least 8 characters.")
                if new_password != confirm_password:
                    errors.append("New password and confirmation do not match.")
                if errors:
                    flash(" ".join(errors), "danger")
                    return redirect(url_for("settings_page"))

                user.password = generate_password_hash(new_password)
                db.session.commit()
                flash("Password changed successfully.", "success")
                return redirect(url_for("settings_page"))

            flash("Choose a valid settings form.", "danger")
            return redirect(url_for("settings_page"))

        return render_template(
            "settings.html",
            page="settings",
            user=user,
            is_client_account=is_client_account,
            dashboard_periods=dashboard_periods,
        )

    @app.route("/clients", methods=["GET", "POST"])
    def clients_page():
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            full_name = clean_text(request.form.get("full_name"))
            username = clean_text(request.form.get("username"))
            password = request.form.get("password") or "client123"
            status = clean_text(request.form.get("status")) or "active"
            errors = []
            if not full_name:
                errors.append("Business name is required.")
            if not username:
                errors.append("Client email/username is required.")
            if username and User.query.filter_by(username=username).first():
                errors.append("That client email/username is already in use.")
            if status not in {"active", "inactive"}:
                errors.append("Status must be active or inactive.")
            if errors:
                flash(" ".join(errors), "danger")
                return redirect(url_for("clients_page"))

            client = User(
                username=username,
                full_name=full_name,
                role=RoleService.CLIENT,
                status=status,
                password=generate_password_hash(password),
            )
            db.session.add(client)
            db.session.commit()
            flash(f"Client portfolio created for {client.full_name}.", "success")
            return redirect(url_for("clients_page", q=username))

        search = clean_text(request.args.get("q"))
        status_filter = clean_text(request.args.get("status")) or "all"
        clients_query = User.query.filter_by(role=RoleService.CLIENT)
        if search:
            clients_query = clients_query.filter(or_(User.full_name.ilike(f"%{search}%"), User.username.ilike(f"%{search}%")))
        if status_filter in {"active", "inactive"}:
            clients_query = clients_query.filter(User.status == status_filter)
        elif status_filter != "all":
            status_filter = "all"
        clients = clients_query.order_by(User.full_name.asc()).all()
        summaries = [client_portfolio_summary(client) for client in clients]
        selected = selected_client()
        selected_notes = []
        if selected:
            selected_notes = (
                AnalystNote.query.filter_by(client_user_id=selected.id)
                .order_by(AnalystNote.created_at.desc())
                .limit(8)
                .all()
            )
        return render_template(
            "clients.html",
            page="clients",
            summaries=summaries,
            search=search,
            status_filter=status_filter,
            selected_portfolio=selected,
            selected_notes=selected_notes,
        )

    @app.route("/clients/<int:client_id>")
    def open_client_portfolio(client_id: int):
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        session["selected_client_id"] = client.id
        session["selected_client_name"] = client.full_name
        flash(f"Opened portfolio: {client.full_name}.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/clients/switch")
    def switch_client():
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        session.pop("selected_client_id", None)
        session.pop("selected_client_name", None)
        return redirect(url_for("clients_page"))

    @app.route("/clients/<int:client_id>/edit", methods=["POST"])
    def edit_client(client_id: int):
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        full_name = clean_text(request.form.get("full_name"))
        username = clean_text(request.form.get("username"))
        status = clean_text(request.form.get("status")) or "active"
        password = request.form.get("password")
        errors = []
        if not full_name:
            errors.append("Business name is required.")
        if not username:
            errors.append("Client email/username is required.")
        existing_user = User.query.filter(User.username == username, User.id != client.id).first() if username else None
        if existing_user:
            errors.append("That client email/username is already in use.")
        if status not in {"active", "inactive"}:
            errors.append("Status must be active or inactive.")
        if errors:
            flash(" ".join(errors), "danger")
            return redirect(url_for("clients_page", q=client.username))

        client.full_name = full_name
        client.username = username
        client.status = status
        if password:
            client.password = generate_password_hash(password)
        db.session.commit()
        if selected_client_id() == client.id:
            session["selected_client_name"] = client.full_name
        flash("Client profile updated.", "success")
        return redirect(url_for("clients_page", q=client.username))

    @app.route("/clients/<int:client_id>/status", methods=["POST"])
    def client_status(client_id: int):
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        status = clean_text(request.form.get("status"))
        if status not in {"active", "inactive"}:
            flash("Choose a valid client status.", "danger")
            return redirect(url_for("clients_page"))
        client.status = status
        db.session.commit()
        flash(f"{client.full_name} is now {status}.", "success")
        return redirect(url_for("clients_page"))

    @app.route("/clients/<int:client_id>/reset-password", methods=["POST"])
    def reset_client_password(client_id: int):
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        new_password = clean_text(request.form.get("password")) or "client123"
        client.password = generate_password_hash(new_password)
        db.session.commit()
        flash(f"Password reset for {client.full_name}. Temporary password: {new_password}", "success")
        return redirect(url_for("clients_page", q=client.username))

    @app.route("/clients/<int:client_id>/notes", methods=["POST"])
    def client_note_add(client_id: int):
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        note_text = clean_text(request.form.get("note_text"))
        if not note_text:
            flash("Note text is required.", "danger")
            return redirect(url_for("clients_page", q=client.username))
        db.session.add(
            AnalystNote(
                client_user_id=client.id,
                analyst_user_id=session["user_id"],
                note_text=note_text,
            )
        )
        db.session.commit()
        flash("Client note saved.", "success")
        return redirect(url_for("clients_page", q=client.username))

    @app.route("/dashboard")
    def dashboard():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        client_id = current_client_id()
        metrics = compute_dashboard_metrics(client_id)
        inv_summary = inventory_summary(client_id)
        qr_payload = None
        analyst_notes = []
        if session.get("role") == RoleService.CLIENT:
            qr_payload = feedback_qr_payload(session["user_id"])
            analyst_notes = AnalystNote.query.filter_by(client_user_id=session["user_id"]).order_by(AnalystNote.created_at.desc()).limit(5).all()
        elif client_id is not None:
            analyst_notes = AnalystNote.query.filter_by(client_user_id=client_id).order_by(AnalystNote.created_at.desc()).limit(5).all()
        return render_template(
            "dashboard.html",
            page="dashboard",
            metrics=metrics,
            inventory_summary=inv_summary,
            qr_payload=qr_payload,
            analyst_notes=analyst_notes,
        )

    @app.route("/client-data", methods=["GET", "POST"])
    def client_data():
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        return redirect(url_for("clients_page"))

    @app.route("/menu")
    def menu_redirect():
        return redirect(url_for("menu_engineering"))

    @app.route("/menu-engineering")
    def menu_engineering():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        data = build_menu_engineering_data(
            request.args.get("search", "").strip(),
            request.args.get("category", "All"),
            request.args.get("sort_by", "item_name"),
            request.args.get("sort_dir", "asc"),
            current_client_id(),
        )
        edit_id = request.args.get("edit", type=int)
        editing = get_scoped_or_404(MenuItem, edit_id) if edit_id else None
        return render_template("menu_engineering.html", page="menu_engineering", data=data, editing=editing)

    @app.route("/menu-engineering/data")
    def menu_engineering_data():
        if not login_required():
            return jsonify({"error": "unauthorized"}), 401
        if staff_required() and current_client_id() is None:
            return jsonify({"error": "client portfolio required"}), 400
        data = build_menu_engineering_data(
            request.args.get("search", "").strip(),
            request.args.get("category", "All"),
            request.args.get("sort_by", "item_name"),
            request.args.get("sort_dir", "asc"),
            current_client_id(),
        )
        return jsonify(data)

    @app.route("/menu-engineering/filter")
    def menu_engineering_filter():
        return redirect(
            url_for(
                "menu_engineering",
                search=request.args.get("search", ""),
                category=request.args.get("category", "All"),
                sort_by=request.args.get("sort_by", "item_name"),
                sort_dir=request.args.get("sort_dir", "asc"),
            )
        )

    @app.route("/menu-engineering/add", methods=["POST"])
    def menu_engineering_add():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        item_name = clean_text(request.form.get("item_name"))
        category = clean_text(request.form.get("category"))
        status = clean_text(request.form.get("status")) or "active"
        valid_statuses = {"active", "inactive"}
        selling_price_res = parse_float_field(request.form.get("selling_price"), "Selling price", required=True, min_value=0)
        ingredient_cost_res = parse_float_field(request.form.get("ingredient_cost", 0), "Ingredient cost", min_value=0)
        labor_cost_res = parse_float_field(request.form.get("labor_cost", 0), "Labor cost", min_value=0)
        packaging_cost_res = parse_float_field(request.form.get("packaging_cost", 0), "Packaging cost", min_value=0)
        overhead_cost_res = parse_float_field(request.form.get("overhead_cost", 0), "Overhead cost", min_value=0)
        errors = []
        if not item_name:
            errors.append("Item name is required.")
        if not category:
            errors.append("Category is required.")
        if status not in valid_statuses:
            errors.append("Status must be active or inactive.")
        errors.extend(extract_route_errors(selling_price_res, ingredient_cost_res, labor_cost_res, packaging_cost_res, overhead_cost_res))
        if errors:
            flash(" ".join(errors), "danger")
            return redirect(url_for("menu_engineering"))
        db.session.add(
            MenuItem(
                item_name=item_name,
                category=category,
                selling_price=selling_price_res[0],
                ingredient_cost=ingredient_cost_res[0] or 0,
                labor_cost=labor_cost_res[0] or 0,
                packaging_cost=packaging_cost_res[0] or 0,
                overhead_cost=overhead_cost_res[0] or 0,
                status=status,
                **owner_payload(),
            )
        )
        db.session.commit()
        flash("Menu item added.", "success")
        return redirect(url_for("menu_engineering"))

    @app.route("/menu-engineering/edit/<int:menu_id>", methods=["POST"])
    def menu_engineering_edit(menu_id: int):
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        item = get_scoped_or_404(MenuItem, menu_id)
        item_name = clean_text(request.form.get("item_name"))
        category = clean_text(request.form.get("category"))
        status = clean_text(request.form.get("status")) or "active"
        valid_statuses = {"active", "inactive"}
        selling_price_res = parse_float_field(request.form.get("selling_price"), "Selling price", required=True, min_value=0)
        ingredient_cost_res = parse_float_field(request.form.get("ingredient_cost", 0), "Ingredient cost", min_value=0)
        labor_cost_res = parse_float_field(request.form.get("labor_cost", 0), "Labor cost", min_value=0)
        packaging_cost_res = parse_float_field(request.form.get("packaging_cost", 0), "Packaging cost", min_value=0)
        overhead_cost_res = parse_float_field(request.form.get("overhead_cost", 0), "Overhead cost", min_value=0)
        errors = []
        if not item_name:
            errors.append("Item name is required.")
        if not category:
            errors.append("Category is required.")
        if status not in valid_statuses:
            errors.append("Status must be active or inactive.")
        errors.extend(extract_route_errors(selling_price_res, ingredient_cost_res, labor_cost_res, packaging_cost_res, overhead_cost_res))
        if errors:
            flash(" ".join(errors), "danger")
            return redirect(url_for("menu_engineering", edit=menu_id))
        item.item_name = item_name
        item.category = category
        item.selling_price = selling_price_res[0]
        item.ingredient_cost = ingredient_cost_res[0] or 0
        item.labor_cost = labor_cost_res[0] or 0
        item.packaging_cost = packaging_cost_res[0] or 0
        item.overhead_cost = overhead_cost_res[0] or 0
        item.status = status
        db.session.commit()
        flash("Menu item updated.", "success")
        return redirect(url_for("menu_engineering"))

    @app.route("/menu-engineering/delete/<int:menu_id>", methods=["POST"])
    def menu_engineering_delete(menu_id: int):
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        item = get_scoped_or_404(MenuItem, menu_id)
        db.session.delete(item)
        db.session.commit()
        flash("Menu item deleted.", "success")
        return redirect(url_for("menu_engineering"))

    @app.route("/inventory")
    def inventory_page():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        page_context = build_inventory_page_context()
        return render_template(
            "inventory.html",
            page="inventory",
            stock_label=inventory_stock_label,
            stock_badge_class=inventory_stock_badge_class,
            stock_progress=inventory_stock_progress,
            total_value=inventory_total_value,
            activity_time_label=inventory_activity_time_label,
            **page_context,
        )

    @app.route("/inventory/add", methods=["GET", "POST"])
    def inventory_add():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        if request.method == "POST":
            item_id_raw, _, payload, errors = parse_inventory_form_submission()
            if errors:
                flash(" ".join(errors), "danger")
                return redirect(url_for("inventory_add"))
            if item_id_raw:
                flash("New inventory items cannot include an existing item ID.", "danger")
                return redirect(url_for("inventory_add"))
            db.session.add(InventoryItem(**payload))
            db.session.commit()
            flash("Inventory item added.", "success")
            return redirect(url_for("inventory_page"))
        return render_template(
            "inventory_add.html",
            page="inventory",
            editing=None,
            inventory_units=INVENTORY_UNITS,
        )

    @app.route("/inventory/<int:item_id>/edit", methods=["GET", "POST"])
    def inventory_edit(item_id: int):
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        item = get_scoped_or_404(InventoryItem, item_id)
        if request.method == "POST":
            item_id_raw, item_id_res, payload, errors = parse_inventory_form_submission()
            if item_id_raw and item_id_res[0] != item.id:
                errors.append("Inventory item ID does not match the item being edited.")
            if errors:
                flash(" ".join(errors), "danger")
                return redirect(url_for("inventory_edit", item_id=item.id))
            for key, value in payload.items():
                setattr(item, key, value)
            db.session.commit()
            flash("Inventory item updated.", "success")
            return redirect(url_for("inventory_page"))
        return render_template(
            "inventory_add.html",
            page="inventory",
            editing=item,
            inventory_units=INVENTORY_UNITS,
        )

    @app.route("/inventory/import")
    def inventory_import():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        return render_template(
            "inventory_import.html",
            page="inventory",
            import_specs=import_specs_for_template(),
        )

    @app.route("/inventory/delete/<int:item_id>", methods=["POST"])
    def inventory_delete(item_id: int):
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        item = get_scoped_or_404(InventoryItem, item_id)
        db.session.delete(item)
        db.session.commit()
        flash("Inventory item deleted.", "success")
        return redirect(url_for("inventory_page"))

    @app.route("/inventory/<int:item_id>/status", methods=["POST"])
    def inventory_status(item_id: int):
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        item = get_scoped_or_404(InventoryItem, item_id)
        status = clean_text(request.form.get("status"))
        if status not in {"active", "inactive"}:
            flash("Choose a valid inventory status.", "danger")
            return redirect(url_for("inventory_page"))
        item.status = status
        db.session.commit()
        flash(f"{item.ingredient_name} {'activated' if status == 'active' else 'deactivated'}.", "success")
        return redirect(url_for("inventory_page"))

    @app.route("/inventory/<int:item_id>")
    def inventory_detail(item_id: int):
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        item = get_scoped_or_404(InventoryItem, item_id)
        movements = StockMovement.query.filter_by(inventory_item_id=item.id).order_by(StockMovement.movement_date.desc(), StockMovement.created_at.desc()).all()
        return render_template(
            "inventory_detail.html",
            page="inventory",
            item=item,
            movements=movements,
            stock_label=inventory_stock_label,
            stock_badge_class=inventory_stock_badge_class,
            stock_progress=inventory_stock_progress,
            total_value=inventory_total_value,
            activity_time_label=inventory_activity_time_label,
        )

    @app.route("/inventory/<int:item_id>/movement", methods=["GET", "POST"])
    def inventory_movement(item_id: int):
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        item = get_scoped_or_404(InventoryItem, item_id)
        if item.status == "inactive":
            flash("Activate this inventory item before recording stock movement.", "warning")
            return redirect(url_for("inventory_detail", item_id=item.id))
        if request.method == "POST":
            movement_type = clean_text(request.form.get("movement_type"))
            quantity_res = parse_float_field(request.form.get("quantity"), "Quantity", required=True)
            movement_date_res = parse_date_field(request.form.get("movement_date"), "Movement date", required=True)
            note = clean_text(request.form.get("note"))
            errors = extract_route_errors(quantity_res, movement_date_res)
            if movement_type not in STOCK_MOVEMENT_TYPES:
                errors.append("Choose a valid movement type.")
            quantity = quantity_res[0] if quantity_res[0] is not None else 0
            if movement_type in {"IN", "OUT"} and quantity <= 0:
                errors.append("IN and OUT quantities must be greater than 0.")
            if movement_type == "ADJUSTMENT" and quantity == 0:
                errors.append("Adjustment quantity cannot be 0.")
            if errors:
                flash(" ".join(errors), "danger")
                return redirect(url_for("inventory_movement", item_id=item.id))

            movement = StockMovement(
                inventory_item_id=item.id,
                movement_type=movement_type,
                quantity=quantity,
                movement_date=movement_date_res[0],
                note=note,
            )
            apply_stock_movement(item, movement_type, quantity)
            if movement_type == "IN":
                item.last_restock_date = movement_date_res[0]
            db.session.add(movement)
            db.session.commit()
            flash("Stock movement recorded.", "success")
            return redirect(url_for("inventory_detail", item_id=item.id))

        return render_template(
            "inventory_movement.html",
            page="inventory",
            item=item,
            movement_types=STOCK_MOVEMENT_TYPES,
            today=date.today(),
            stock_label=inventory_stock_label,
            stock_badge_class=inventory_stock_badge_class,
            stock_progress=inventory_stock_progress,
            total_value=inventory_total_value,
        )

    @app.route("/imports/<module_key>", methods=["POST"])
    def import_excel(module_key: str):
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        inventory_import = module_key == "inventory_items"
        if not staff_required():
            if not inventory_import:
                flash("Excel import is handled by the analyst team. Please use manual entry.", "warning")
                return redirect(url_for("dashboard"))
        spec = IMPORT_SPECS.get(module_key)
        validator = IMPORT_VALIDATORS.get(module_key)
        if not spec or not validator:
            flash("This import type is not supported.", "danger")
            return redirect(url_for("dashboard"))
        upload = request.files.get("excel_file")
        if not upload or not upload.filename:
            flash("Please choose an Excel file to import.", "danger")
            return import_redirect_response(spec, keep_panel_open=True)
        rows, read_errors = read_import_rows(upload, spec)
        if read_errors:
            flash(" ".join(read_errors), "danger")
            return import_redirect_response(spec, keep_panel_open=True)
        records, row_errors = validator(rows)
        if row_errors:
            preview = " ".join(row_errors[:8])
            remaining = len(row_errors) - 8
            if remaining > 0:
                preview += f" Plus {remaining} more row error(s)."
            flash(f"No rows were imported. {preview}", "danger")
            return import_redirect_response(spec, keep_panel_open=True)
        if not records:
            flash("No valid rows were found to import.", "warning")
            return import_redirect_response(spec, keep_panel_open=True)
        db.session.add_all(records)
        db.session.commit()
        flash(f"Imported {len(records)} {spec['label'].lower()} from Excel.", "success")
        return import_redirect_response(spec)

    @app.route("/exports/sales.xlsx")
    def export_sales_excel():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        records = records_for_export(scoped_query(Sale), Sale.sale_date)
        rows = [
            {
                "Sale Date": sale.sale_date.strftime("%Y-%m-%d") if sale.sale_date else "",
                "Menu Item": sale.menu_item.item_name if sale.menu_item else "",
                "Quantity": sale.quantity,
                "Unit Price (RM)": round(sale.unit_price or 0, 2),
                "Unit Cost (RM)": round(sale.unit_cost or 0, 2),
                "Extra Expense (RM)": round(sale.extra_expense or 0, 2),
                "Channel": sale.channel or "",
                "Client": sale.client.full_name if sale.client else "",
                "Created At": sale.created_at.strftime("%Y-%m-%d %H:%M:%S") if sale.created_at else "",
            }
            for sale in records
        ]
        return export_rows_to_excel(rows, filename=f"sales_export_{date.today().isoformat()}.xlsx", sheet_name="Sales")

    @app.route("/exports/expenses.xlsx")
    def export_expenses_excel():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        records = records_for_export(scoped_query(Expense), Expense.expense_date)
        rows = [
            {
                "Expense Date": expense.expense_date.strftime("%Y-%m-%d") if expense.expense_date else "",
                "Category": expense.category or "",
                "Amount (RM)": round(expense.amount or 0, 2),
                "Note": expense.note or "",
                "Client": expense.client.full_name if expense.client else "",
                "Created At": expense.created_at.strftime("%Y-%m-%d %H:%M:%S") if expense.created_at else "",
            }
            for expense in records
        ]
        return export_rows_to_excel(rows, filename=f"expenses_export_{date.today().isoformat()}.xlsx", sheet_name="Expenses")

    @app.route("/exports/marketing.xlsx")
    def export_marketing_excel():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        records = records_for_export(scoped_query(MarketingCampaign), MarketingCampaign.campaign_date)
        rows = [
            {
                "Campaign Date": campaign.campaign_date.strftime("%Y-%m-%d") if campaign.campaign_date else "",
                "Campaign Name": campaign.campaign_name or "",
                "Platform": campaign.platform or "",
                "Spend (RM)": round(campaign.spend or 0, 2),
                "Revenue Generated (RM)": round(campaign.revenue_generated or 0, 2),
                "ROI (%)": round(((campaign.revenue_generated or 0) - (campaign.spend or 0)) / (campaign.spend or 1) * 100, 2) if campaign.spend else 0,
                "Note": campaign.note or "",
                "Client": campaign.client.full_name if campaign.client else "",
                "Created At": campaign.created_at.strftime("%Y-%m-%d %H:%M:%S") if campaign.created_at else "",
            }
            for campaign in records
        ]
        return export_rows_to_excel(rows, filename=f"marketing_export_{date.today().isoformat()}.xlsx", sheet_name="Marketing")

    @app.route("/exports/menu-items.xlsx")
    def export_menu_items_excel():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        search = clean_text(request.args.get("search"))
        category = clean_text(request.args.get("category")) or "All"
        sort_by = clean_text(request.args.get("sort_by")) or "item_name"
        sort_dir = clean_text(request.args.get("sort_dir")) or "asc"
        data = build_menu_engineering_data(search, category, sort_by, sort_dir, current_client_id())
        rows = [
            {
                "Item Name": row["item_name"],
                "Category": row["category"],
                "Selling Price (RM)": row["selling_price"],
                "Total Unit Cost (RM)": row["total_unit_cost"],
                "Contribution Margin (RM)": row["contribution_margin"],
                "Quantity Sold": row["quantity_sold"],
                "Total Profit (RM)": row["total_profit"],
                "Profit Margin (%)": row["profit_margin_percent"],
                "Classification": row["classification"],
                "Status": row["status"] or "active",
                "Recommendation": row["recommendation"],
            }
            for row in data["rows"]
        ]
        return export_rows_to_excel(rows, filename=f"menu_items_export_{date.today().isoformat()}.xlsx", sheet_name="Menu Items")

    @app.route("/exports/reviews.xlsx")
    def export_reviews_excel():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        selected_source = clean_text(request.args.get("source")) or "All"
        query = scoped_query(CustomerReview)
        if selected_source != "All":
            query = query.filter(CustomerReview.source == selected_source)
        records = query.order_by(CustomerReview.review_date.desc()).all()
        rows = [
            {
                "Review Date": review.review_date.strftime("%Y-%m-%d") if review.review_date else "",
                "Client": review.client.full_name if review.client else "",
                "Source": review.source or "",
                "Order Type": review.order_type or "",
                "Rating": review.rating,
                "Sentiment Label": review.sentiment_label or "",
                "Sentiment Score": round(review.sentiment_score or 0, 4),
                "Issue Tag": review.issue_tag or "",
                "Urgency Level": review.urgency_level or "",
                "Customer Name": review.customer_name or "",
                "Phone Number": review.phone_number or "",
                "Menu Item": review.menu_item or "",
                "Receipt Number": review.receipt_number or "",
                "Submission Channel": review.submission_channel or "",
                "Review Text": review.review_text or "",
                "Created At": review.created_at.strftime("%Y-%m-%d %H:%M:%S") if review.created_at else "",
            }
            for review in records
        ]
        return export_rows_to_excel(rows, filename=f"reviews_export_{date.today().isoformat()}.xlsx", sheet_name="Reviews")

    @app.route("/exports/inventory-items.xlsx")
    def export_inventory_items_excel():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        search_term = clean_text(request.args.get("q"))
        category_filter = clean_text(request.args.get("category"))
        export_mode = clean_text(request.args.get("mode")) or "active"
        if export_mode not in {"active", "inactive"}:
            export_mode = "active"
        status_filter = clean_text(request.args.get("status")) or "all"
        query = scoped_query(InventoryItem)
        if export_mode == "active":
            query = query.filter(or_(InventoryItem.status == "active", InventoryItem.status.is_(None)))
            if status_filter == "in_stock":
                query = query.filter(InventoryItem.current_stock > InventoryItem.minimum_stock)
            elif status_filter == "low_stock":
                query = query.filter(InventoryItem.current_stock > 0, InventoryItem.current_stock <= InventoryItem.minimum_stock)
            elif status_filter == "out_of_stock":
                query = query.filter(InventoryItem.current_stock <= 0)
        elif export_mode == "inactive":
            query = query.filter(InventoryItem.status == "inactive")
        if search_term:
            query = query.filter(
                or_(
                    InventoryItem.ingredient_name.ilike(f"%{search_term}%"),
                    InventoryItem.category.ilike(f"%{search_term}%"),
                )
            )
        if category_filter:
            query = query.filter(InventoryItem.category == category_filter)
        records = query.order_by(InventoryItem.ingredient_name.asc()).all()
        rows = [
            {
                "Ingredient Name": item.ingredient_name or "",
                "Category": item.category or "",
                "Unit": item.unit or "",
                "Current Stock": round(item.current_stock or 0, 2),
                "Minimum Stock": round(item.minimum_stock or 0, 2),
                "Stock Health": inventory_stock_label(item),
                "Status": item.status or "active",
                "Cost Per Unit (RM)": round(item.cost_per_unit or 0, 2),
                "Total Value (RM)": round(inventory_total_value(item), 2),
                "Supplier Name": item.supplier_name or "",
                "Last Restock Date": item.last_restock_date.strftime("%Y-%m-%d") if item.last_restock_date else "",
                "Client": item.client.full_name if item.client else "",
                "Updated At": item.updated_at.strftime("%Y-%m-%d %H:%M:%S") if item.updated_at else "",
            }
            for item in records
        ]
        file_prefix = "inactive_inventory" if export_mode == "inactive" else "inventory_items"
        return export_rows_to_excel(rows, filename=f"{file_prefix}_export_{date.today().isoformat()}.xlsx", sheet_name="Inventory")

    @app.route("/exports/stock-movements.xlsx")
    def export_stock_movements_excel():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        item_id = request.args.get("item_id", type=int)
        query = scoped_stock_movement_query()
        if item_id:
            item = get_scoped_or_404(InventoryItem, item_id)
            query = query.filter(StockMovement.inventory_item_id == item.id)
        records = query.order_by(StockMovement.movement_date.desc(), StockMovement.created_at.desc()).all()
        rows = [
            {
                "Movement Date": movement.movement_date.strftime("%Y-%m-%d") if movement.movement_date else "",
                "Ingredient Name": movement.inventory_item.ingredient_name if movement.inventory_item else "",
                "Category": movement.inventory_item.category if movement.inventory_item else "",
                "Movement Type": movement.movement_type or "",
                "Quantity": round(movement.quantity or 0, 2),
                "Unit": movement.inventory_item.unit if movement.inventory_item else "",
                "Note": movement.note or "",
                "Client": movement.inventory_item.client.full_name if movement.inventory_item and movement.inventory_item.client else "",
                "Created At": movement.created_at.strftime("%Y-%m-%d %H:%M:%S") if movement.created_at else "",
            }
            for movement in records
        ]
        return export_rows_to_excel(rows, filename=f"stock_movements_export_{date.today().isoformat()}.xlsx", sheet_name="Stock Movements")

    @app.route("/sales", methods=["GET", "POST"])
    def sales_entry():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect

        edit_id = request.args.get("edit", type=int)
        editing = get_scoped_or_404(Sale, edit_id) if edit_id else None
        items_query = scoped_query(MenuItem).filter_by(status="active")
        if editing and editing.menu_item and editing.menu_item.status != "active":
            items = items_query.union(scoped_query(MenuItem).filter(MenuItem.id == editing.menu_item_id)).order_by(MenuItem.item_name.asc()).all()
        else:
            items = items_query.order_by(MenuItem.item_name.asc()).all()
        item_snapshots = [
            {
                "id": item.id,
                "unit_price": round(item.selling_price or 0, 2),
                "unit_cost": round((item.ingredient_cost or 0) + (item.labor_cost or 0) + (item.packaging_cost or 0) + (item.overhead_cost or 0), 2),
            }
            for item in items
        ]

        if request.method == "POST":
            sale_id_raw = clean_text(request.form.get("sale_id"))
            sale_id_res = parse_int_field(sale_id_raw, "Sale ID")
            sale_date_res = parse_date_field(request.form.get("sale_date"), "Sale date", required=True)
            menu_item_id_res = parse_int_field(request.form.get("menu_item_id"), "Menu item", required=True, min_value=1)
            quantity_res = parse_int_field(request.form.get("quantity"), "Quantity", required=True, min_value=1)
            extra_expense_res = parse_float_field(request.form.get("extra_expense", 0), "Extra expense", min_value=0)
            channel = clean_text(request.form.get("channel")) or "Walk-in"
            errors = extract_route_errors(
                sale_id_res,
                sale_date_res,
                menu_item_id_res,
                quantity_res,
                extra_expense_res,
            )
            if channel not in SALES_CHANNELS:
                errors.append(f"Channel must be one of: {', '.join(SALES_CHANNELS)}.")
            menu_item = scoped_query(MenuItem).filter(MenuItem.id == menu_item_id_res[0]).first() if menu_item_id_res[0] is not None else None
            if menu_item_id_res[0] is not None and not menu_item:
                errors.append("Selected menu item does not exist.")
            if errors:
                flash(" ".join(errors), "danger")
                return redirect(url_for("sales_entry"))
            unit_cost = (menu_item.ingredient_cost or 0) + (menu_item.labor_cost or 0) + (menu_item.packaging_cost or 0) + (menu_item.overhead_cost or 0)
            payload = {
                "sale_date": sale_date_res[0],
                "menu_item_id": menu_item_id_res[0],
                "quantity": quantity_res[0],
                "unit_price": menu_item.selling_price or 0,
                "unit_cost": unit_cost,
                "extra_expense": extra_expense_res[0] or 0,
                "channel": channel,
                **owner_payload(),
            }
            if sale_id_raw:
                sale = get_scoped_or_404(Sale, sale_id_res[0])
                for k, v in payload.items():
                    setattr(sale, k, v)
                flash("Sales record updated.", "success")
            else:
                db.session.add(Sale(**payload))
                flash("Sales record added.", "success")
            db.session.commit()
            return redirect(url_for("sales_entry"))
        recent, list_filter = build_record_list(scoped_query(Sale), Sale.sale_date, module_label="sales")
        return render_template("sales.html", page="sales", items=items, item_snapshots=item_snapshots, recent=recent, list_filter=list_filter, today=date.today(), editing=editing, sales_channels=SALES_CHANNELS)

    @app.route("/sales/delete/<int:sale_id>", methods=["POST"])
    def sales_delete(sale_id: int):
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        sale = get_scoped_or_404(Sale, sale_id)
        db.session.delete(sale)
        db.session.commit()
        flash("Sales record deleted.", "success")
        return redirect(url_for("sales_entry"))

    @app.route("/expenses", methods=["GET", "POST"])
    def expense_entry():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        edit_id = request.args.get("edit", type=int)
        editing = get_scoped_or_404(Expense, edit_id) if edit_id else None
        if request.method == "POST":
            expense_id_raw = clean_text(request.form.get("expense_id"))
            expense_id_res = parse_int_field(expense_id_raw, "Expense ID")
            expense_date_res = parse_date_field(request.form.get("expense_date"), "Expense date", required=True)
            category = clean_text(request.form.get("category"))
            amount_res = parse_float_field(request.form.get("amount"), "Amount", required=True, min_value=0)
            note = clean_text(request.form.get("note"))
            errors = extract_route_errors(expense_id_res, expense_date_res, amount_res)
            if not category:
                errors.append("Category is required.")
            if errors:
                flash(" ".join(errors), "danger")
                return redirect(url_for("expense_entry"))
            payload = {
                "expense_date": expense_date_res[0],
                "category": category,
                "amount": amount_res[0],
                "note": note,
                **owner_payload(),
            }
            if expense_id_raw:
                expense = get_scoped_or_404(Expense, expense_id_res[0])
                for k, v in payload.items():
                    setattr(expense, k, v)
                flash("Expense record updated.", "success")
            else:
                db.session.add(Expense(**payload))
                flash("Expense record added.", "success")
            db.session.commit()
            return redirect(url_for("expense_entry"))
        recent, list_filter = build_record_list(scoped_query(Expense), Expense.expense_date, module_label="expenses")
        return render_template("expenses.html", page="expenses", recent=recent, list_filter=list_filter, today=date.today(), editing=editing)

    @app.route("/expenses/delete/<int:expense_id>", methods=["POST"])
    def expense_delete(expense_id: int):
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        expense = get_scoped_or_404(Expense, expense_id)
        db.session.delete(expense)
        db.session.commit()
        flash("Expense record deleted.", "success")
        return redirect(url_for("expense_entry"))

    @app.route("/marketing", methods=["GET", "POST"])
    def marketing_entry():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        edit_id = request.args.get("edit", type=int)
        editing = get_scoped_or_404(MarketingCampaign, edit_id) if edit_id else None
        if request.method == "POST":
            campaign_id_raw = clean_text(request.form.get("campaign_id"))
            campaign_id_res = parse_int_field(campaign_id_raw, "Campaign ID")
            campaign_date_res = parse_date_field(request.form.get("campaign_date"), "Campaign date", required=True)
            campaign_name = clean_text(request.form.get("campaign_name"))
            platform = clean_text(request.form.get("platform"))
            spend_res = parse_float_field(request.form.get("spend"), "Spend", required=True, min_value=0)
            revenue_res = parse_float_field(request.form.get("revenue_generated"), "Revenue", required=True, min_value=0)
            note = clean_text(request.form.get("note"))
            errors = extract_route_errors(campaign_id_res, campaign_date_res, spend_res, revenue_res)
            if not campaign_name:
                errors.append("Campaign name is required.")
            if not platform:
                errors.append("Platform is required.")
            if errors:
                flash(" ".join(errors), "danger")
                return redirect(url_for("marketing_entry"))
            payload = {
                "campaign_date": campaign_date_res[0],
                "campaign_name": campaign_name,
                "platform": platform,
                "spend": spend_res[0],
                "revenue_generated": revenue_res[0],
                "note": note,
                **owner_payload(),
            }
            if campaign_id_raw:
                campaign = get_scoped_or_404(MarketingCampaign, campaign_id_res[0])
                for k, v in payload.items():
                    setattr(campaign, k, v)
                flash("Marketing campaign updated.", "success")
            else:
                db.session.add(MarketingCampaign(**payload))
                flash("Marketing campaign added.", "success")
            db.session.commit()
            return redirect(url_for("marketing_entry"))
        recent, list_filter = build_record_list(scoped_query(MarketingCampaign), MarketingCampaign.campaign_date, module_label="campaigns")
        return render_template("marketing.html", page="marketing", recent=recent, list_filter=list_filter, today=date.today(), editing=editing)

    @app.route("/marketing/delete/<int:campaign_id>", methods=["POST"])
    def marketing_delete(campaign_id: int):
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        campaign = get_scoped_or_404(MarketingCampaign, campaign_id)
        db.session.delete(campaign)
        db.session.commit()
        flash("Marketing campaign deleted.", "success")
        return redirect(url_for("marketing_entry"))

    @app.route("/reviews", methods=["GET", "POST"])
    def review_entry():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        edit_id = request.args.get("edit", type=int)
        editing = get_scoped_or_404(CustomerReview, edit_id) if edit_id else None
        if request.method == "POST":
            review_id_raw = clean_text(request.form.get("review_id"))
            review_id_res = parse_int_field(review_id_raw, "Review ID")
            review_text = clean_text(request.form.get("review_text", ""))
            review_date_res = parse_date_field(request.form.get("review_date"), "Review date", required=True)
            rating_res = parse_int_field(request.form.get("rating"), "Rating", required=True, min_value=1, max_value=5)
            client_id_raw = clean_text(request.form.get("client_id"))
            client_id_res = parse_int_field(client_id_raw, "Client", min_value=1)
            customer_name = clean_text(request.form.get("customer_name")) or None
            phone_number = clean_text(request.form.get("phone_number")) or None
            menu_item = clean_text(request.form.get("menu_item")) or None
            order_type_raw = clean_text(request.form.get("order_type"))
            order_type = order_type_raw or None
            source_value = clean_text(request.form.get("source"))
            source = source_value if source_value else "Manual Entry"
            issue_tag_raw = clean_text(request.form.get("issue_tag"))
            issue_tag = issue_tag_raw if issue_tag_raw else detect_issue_tag(review_text)
            submission_channel = clean_text(request.form.get("submission_channel")) or "manual"
            valid_submission_channels = {"manual", "qr", "QR"}
            errors = extract_route_errors(review_id_res, review_date_res, rating_res, client_id_res)
            if not review_text:
                errors.append("Review text is required.")
            if source not in REVIEW_SOURCES:
                errors.append("Invalid review source selected.")
            if issue_tag not in ISSUE_TAGS:
                errors.append("Invalid issue tag selected.")
            if order_type and order_type not in ORDER_TYPES:
                errors.append("Invalid order type selected.")
            if submission_channel not in valid_submission_channels:
                errors.append("Invalid submission channel selected.")
            context_client_id = current_client_id()
            if context_client_id is not None:
                client_id_res = (context_client_id, None)
            if client_id_res[0] is not None and not User.query.filter_by(id=client_id_res[0], role=RoleService.CLIENT).first():
                errors.append("Selected client is invalid.")
            if errors:
                flash(" ".join(errors), "danger")
                return redirect(url_for("review_entry"))
            rating = rating_res[0]
            label, score = analyze_sentiment(review_text, rating)
            urgency_level = determine_urgency_level(label, rating, issue_tag, review_text)
            payload = {
                "review_date": review_date_res[0],
                "client_id": client_id_res[0],
                "customer_name": customer_name,
                "phone_number": phone_number,
                "menu_item": menu_item,
                "order_type": order_type,
                "source": source,
                "rating": rating,
                "review_text": review_text,
                "receipt_number": clean_text(request.form.get("receipt_number")) or None,
                "issue_tag": issue_tag,
                "urgency_level": urgency_level,
                "submission_channel": submission_channel,
                "sentiment_label": label,
                "sentiment_score": score,
            }
            if review_id_raw:
                review = get_scoped_or_404(CustomerReview, review_id_res[0])
                for k, v in payload.items():
                    setattr(review, k, v)
                flash("Customer review updated.", "success")
            else:
                db.session.add(CustomerReview(**payload))
                flash("Customer review added and sentiment analyzed.", "success")
            db.session.commit()
            return redirect(url_for("review_entry"))
        selected_source = request.args.get("source", "All")
        query = scoped_query(CustomerReview)
        if selected_source != "All":
            query = query.filter(CustomerReview.source == selected_source)
        recent = query.order_by(CustomerReview.review_date.desc()).all()
        context_client_id = current_client_id()
        if staff_required() and context_client_id is not None:
            clients = User.query.filter_by(id=context_client_id, role=RoleService.CLIENT).all()
        elif staff_required():
            clients = User.query.filter_by(role=RoleService.CLIENT).order_by(User.full_name.asc()).all()
        else:
            clients = User.query.filter_by(id=current_user_id(), role=RoleService.CLIENT).all()
        qr_preview = None
        if clients:
            default_client = User.query.get(context_client_id) if context_client_id else clients[0]
            qr_preview = {
                "client_id": default_client.id,
                "client_name": default_client.full_name,
                **feedback_qr_payload(default_client.id),
            }
        return render_template(
            "reviews.html",
            page="reviews",
            recent=recent,
            today=date.today(),
            editing=editing,
            review_sources=REVIEW_SOURCES,
            issue_tags=ISSUE_TAGS,
            order_types=ORDER_TYPES,
            clients=clients,
            selected_source=selected_source,
            qr_preview=qr_preview,
        )

    @app.route("/reviews/delete/<int:review_id>", methods=["POST"])
    def reviews_delete(review_id: int):
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        review = get_scoped_or_404(CustomerReview, review_id)
        db.session.delete(review)
        db.session.commit()
        flash("Customer review deleted.", "success")
        return redirect(url_for("review_entry"))

    @app.route("/feedback/<int:client_id>", methods=["GET", "POST"])
    def public_feedback(client_id: int):
        client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        if request.method == "POST":
            visit_date_res = parse_date_field(request.form.get("visit_date"), "Visit date", required=True)
            menu_item = clean_text(request.form.get("menu_item"))
            order_type = clean_text(request.form.get("order_type"))
            review_text = clean_text(request.form.get("review_text"))
            rating_res = parse_int_field(request.form.get("rating_overall"), "Rating", required=True, min_value=1, max_value=5)
            errors = extract_route_errors(visit_date_res, rating_res)
            visit_date = visit_date_res[0]
            rating = rating_res[0]
            if not menu_item:
                errors.append("Menu item is required.")
            if not review_text:
                errors.append("Review text is required.")
            elif len(review_text) > 1000:
                errors.append("Review text must be 1000 characters or fewer.")
            if visit_date and visit_date > date.today():
                errors.append("Visit date cannot be in the future.")
            if not order_type:
                errors.append("Order type is required.")
            elif order_type not in ORDER_TYPES:
                errors.append("Please provide a valid order type.")
            if errors:
                flash(" ".join(errors), "danger")
                return render_template(
                    "feedback_form.html",
                    client=client,
                    order_types=ORDER_TYPES,
                    issue_tags=ISSUE_TAGS,
                    review_sources=REVIEW_SOURCES,
                )
            if visit_date is None or rating is None:
                flash("Please complete all required fields.", "danger")
                return render_template(
                    "feedback_form.html",
                    client=client,
                    order_types=ORDER_TYPES,
                    issue_tags=ISSUE_TAGS,
                    review_sources=REVIEW_SOURCES,
                )
            label, score = analyze_sentiment(review_text, rating)
            issue_tag = detect_issue_tag(review_text)
            urgency_level = determine_urgency_level(label, rating, issue_tag, review_text)
            db.session.add(
                CustomerReview(
                    client_id=client.id,
                    customer_name=(request.form.get("customer_name") or "").strip() or None,
                    phone_number=(request.form.get("phone_number") or "").strip() or None,
                    review_date=visit_date,
                    menu_item=menu_item,
                    order_type=order_type,
                    rating=rating,
                    review_text=review_text,
                    receipt_number=(request.form.get("receipt_number") or "").strip() or None,
                    source="QR Feedback",
                    sentiment_label=label,
                    sentiment_score=score,
                    issue_tag=issue_tag,
                    urgency_level=urgency_level,
                    submission_channel="QR",
                )
            )
            db.session.commit()
            return redirect(url_for("feedback_thank_you", client_id=client.id))
        return render_template("feedback_form.html", client=client, order_types=ORDER_TYPES, issue_tags=ISSUE_TAGS)

    @app.route("/feedback/thank-you/<int:client_id>")
    def feedback_thank_you(client_id: int):
        client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        return render_template("feedback_thank_you.html", client=client)

    @app.route("/clients/<int:client_id>/feedback-qr")
    def feedback_qr_page(client_id: int):
        login_redirect = require_login_redirect()
        if login_redirect:
            return login_redirect
        if not (staff_required() or session.get("user_id") == client_id):
            flash("Unauthorized access to feedback QR.", "danger")
            return redirect(url_for("dashboard"))
        client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        return render_template(
            "feedback_qr.html",
            page="clients" if staff_required() else "reviews",
            client=client,
            qr_payload=feedback_qr_payload(client.id),
        )

    @app.route("/clients/<int:client_id>/feedback-qr.png")
    def feedback_qr_image(client_id: int):
        login_redirect = require_login_redirect()
        if login_redirect:
            return login_redirect
        if not (staff_required() or session.get("user_id") == client_id):
            flash("Unauthorized access to feedback QR.", "danger")
            return redirect(url_for("dashboard"))
        User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        return qr_png_response(client_id)

    @app.route("/clients/<int:client_id>/feedback-qr/download")
    def feedback_qr_download(client_id: int):
        login_redirect = require_login_redirect()
        if login_redirect:
            return login_redirect
        if not (staff_required() or session.get("user_id") == client_id):
            flash("Unauthorized access to feedback QR.", "danger")
            return redirect(url_for("dashboard"))
        User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        return qr_png_response(client_id, as_attachment=True)

    @app.route("/reviews/submit", methods=["POST"])
    def review_submit():
        if not request.is_json:
            return jsonify({"ok": False, "error": "Content-Type must be application/json."}), 415

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "Request body must be a valid JSON object."}), 400

        csrf_value = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token") or payload.get(CSRF_FIELD_NAME)
        if not is_valid_csrf_token(csrf_value):
            return jsonify({"ok": False, "error": "Invalid or missing CSRF token."}), 400

        def json_value(key: str, default=None):
            return payload.get(key, default)

        client_id_raw = clean_text(json_value("client_id"))
        client_id_res = parse_int_field(client_id_raw, "client_id", min_value=1)
        if client_id_res[1]:
            return jsonify({"ok": False, "error": "client_id must be numeric"}), 400
        client_id = client_id_res[0] or current_client_id()
        if client_id is None:
            return jsonify({"ok": False, "error": "client_id is required"}), 400
        if not User.query.filter_by(id=client_id, role=RoleService.CLIENT).first():
            return jsonify({"ok": False, "error": "client_id is invalid"}), 400
        review_text = clean_text(json_value("review_text", ""))
        if not review_text:
            return jsonify({"ok": False, "error": "review_text is required"}), 400
        rating_res = parse_int_field(
            json_value("rating_overall", json_value("rating", 3)),
            "rating",
            required=True,
            min_value=1,
            max_value=5,
        )
        if rating_res[1]:
            return jsonify({"ok": False, "error": "rating must be between 1 and 5"}), 400
        rating = rating_res[0]
        visit_date_raw = clean_text(json_value("visit_date", json_value("review_date", "")))
        review_date = date.today()
        if visit_date_raw:
            visit_date_res = parse_date_field(visit_date_raw, "visit_date", required=True)
            if visit_date_res[1]:
                return jsonify({"ok": False, "error": "visit_date must be YYYY-MM-DD"}), 400
            review_date = visit_date_res[0]
        label, score = analyze_sentiment(review_text, rating)
        issue_tag_raw = clean_text(json_value("issue_tag"))
        issue_tag = issue_tag_raw or detect_issue_tag(review_text)
        if issue_tag not in ISSUE_TAGS:
            return jsonify({"ok": False, "error": "issue_tag is invalid"}), 400
        source = clean_text(json_value("source", "QR Feedback Form")) or "QR Feedback Form"
        if source not in REVIEW_SOURCES:
            return jsonify({"ok": False, "error": "source is invalid"}), 400
        order_type_raw = clean_text(json_value("order_type"))
        order_type = order_type_raw or None
        if order_type and order_type not in ORDER_TYPES:
            return jsonify({"ok": False, "error": "order_type is invalid"}), 400
        submission_channel = clean_text(json_value("submission_channel", "qr")) or "qr"
        if submission_channel not in {"manual", "qr", "QR"}:
            return jsonify({"ok": False, "error": "submission_channel is invalid"}), 400
        urgency_level = determine_urgency_level(label, rating, issue_tag, review_text)
        review = CustomerReview(
            client_id=client_id,
            customer_name=clean_text(json_value("customer_name")) or None,
            phone_number=clean_text(json_value("phone_number")) or None,
            review_date=review_date,
            menu_item=clean_text(json_value("menu_item")) or None,
            order_type=order_type,
            rating=rating,
            review_text=review_text,
            receipt_number=clean_text(json_value("receipt_number")) or None,
            source=source,
            sentiment_label=label,
            sentiment_score=score,
            issue_tag=issue_tag,
            urgency_level=urgency_level,
            submission_channel=submission_channel,
        )
        db.session.add(review)
        db.session.commit()
        return jsonify(
            {
                "ok": True,
                "review_id": review.id,
                "sentiment_label": label,
                "sentiment_score": round(float(score), 4),
                "issue_tag": issue_tag,
                "urgency_level": urgency_level,
            }
        )

    @app.route("/client/<int:client_id>/qr-code")
    def client_qr_code(client_id: int):
        login_redirect = require_login_redirect()
        if login_redirect:
            return login_redirect
        if not (staff_required() or session.get("user_id") == client_id):
            flash("Unauthorized access to QR code.", "danger")
            return redirect(url_for("dashboard"))
        client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        return jsonify({"client_id": client.id, "client_name": client.full_name, **feedback_qr_payload(client.id)})

    @app.route("/admin/client/<int:client_id>/qr-code")
    def admin_client_qr_code(client_id: int):
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        return jsonify({"client_id": client.id, "client_name": client.full_name, **feedback_qr_payload(client.id)})

    @app.route("/analytics")
    def analytics_page():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        metrics = compute_dashboard_metrics(current_client_id())
        return render_template("analytics.html", page="analytics", metrics=metrics)

    @app.route("/forecast")
    def forecast_page():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        client_id = current_client_id()
        forecast_generation = generate_revenue_forecast_if_needed(client_id)
        if not forecast_generation["generated"]:
            flash(forecast_generation["message"], "info")
        metrics = compute_dashboard_metrics(client_id)
        metrics.update(build_forecast_revenue_chart_data(client_id))
        return render_template("forecast.html", page="forecast", metrics=metrics)

    @app.route("/roi")
    def roi_page():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        metrics = compute_dashboard_metrics(current_client_id())
        roi_rows, roi_table_filter = build_campaign_roi_table(scoped_query(MarketingCampaign))
        return render_template(
            "roi.html",
            page="roi",
            metrics=metrics,
            roi_rows=roi_rows,
            roi_table_filter=roi_table_filter,
        )

    @app.route("/sentiment")
    def sentiment_page():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        metrics = compute_dashboard_metrics(current_client_id())
        selected_source = request.args.get("source", "All")
        selected_period = clean_text(request.args.get("period")) or "month"
        if selected_period not in {"day", "week", "month"}:
            selected_period = "month"
        today = date.today()
        if selected_period == "day":
            period_start = today
            period_end = today
            period_label = "Today"
        elif selected_period == "week":
            period_start = today - timedelta(days=today.weekday())
            period_end = period_start + timedelta(days=6)
            period_label = "This Week"
        else:
            period_start, period_end = month_bounds(today)
            period_label = "This Month"
        base_reviews = scoped_query(CustomerReview)
        if selected_source != "All":
            base_reviews = base_reviews.filter(CustomerReview.source == selected_source)
        base_reviews = base_reviews.filter(CustomerReview.review_date.between(period_start, period_end))
        reviews = base_reviews.order_by(CustomerReview.review_date.desc()).all()
        filtered_metrics = dict(metrics)
        sentiment_counts = {
            "positive": sum(1 for r in reviews if r.sentiment_label == "positive"),
            "neutral": sum(1 for r in reviews if r.sentiment_label == "neutral"),
            "negative": sum(1 for r in reviews if r.sentiment_label == "negative"),
        }
        sentiment_total = sum(sentiment_counts.values())
        sentiment_percentages = {
            key: round((value / sentiment_total) * 100) if sentiment_total else 0
            for key, value in sentiment_counts.items()
        }
        filtered_metrics["sentiment_counts"] = sentiment_counts
        filtered_metrics["sentiment_total"] = sentiment_total
        filtered_metrics["sentiment_percentages"] = sentiment_percentages
        intelligence = build_sentiment_intelligence(filtered_metrics, reviews=reviews)
        return render_template(
            "sentiment.html",
            page="sentiment",
            metrics=filtered_metrics,
            intelligence=intelligence,
            review_sources=REVIEW_SOURCES,
            selected_source=selected_source,
            selected_period=selected_period,
            period_label=period_label,
            period_start=period_start,
            period_end=period_end,
        )

    @app.route("/reports")
    def reports_page():
        context_redirect = require_client_context_redirect()
        if context_redirect:
            return context_redirect
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))
        metrics = compute_dashboard_metrics(current_client_id())
        return render_template("reports.html", page="reports", metrics=metrics)


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
