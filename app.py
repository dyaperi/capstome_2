from datetime import date, datetime, timedelta
from urllib.parse import quote_plus

import pandas as pd
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

from analytics import analyze_sentiment, campaign_roi, forecast_values
from config import Config
from db import db
from models import AnalystNote, CustomerReview, Expense, MarketingCampaign, MenuItem, Sale, User
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
    "QR Feedback Form",
]
ORDER_TYPES = ["Dine-in", "Takeaway", "Delivery"]
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


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        ensure_schema_updates()
        seed_default_data()

    register_routes(app)
    return app


def seed_default_data() -> None:
    if not User.query.filter_by(username="admin").first():
        db.session.add(
            User(
                username="admin",
                full_name="SME Owner",
                role=RoleService.ADMIN_ANALYST,
                password=generate_password_hash("admin123"),
            )
        )
    else:
        admin_user = User.query.filter_by(username="admin").first()
        if admin_user and admin_user.role != RoleService.ADMIN_ANALYST:
            admin_user.role = RoleService.ADMIN_ANALYST

    if not User.query.filter_by(username="client").first():
        db.session.add(
            User(
                username="client",
                full_name="SME Client",
                role=RoleService.CLIENT,
                password=generate_password_hash("client123"),
            )
        )

    if not MenuItem.query.first():
        db.session.add_all(
            [
                MenuItem(item_name="Mee Rebus", category="Main", selling_price=8.0, ingredient_cost=3.0, quantity_sold=50),
                MenuItem(item_name="Nasi Goreng", category="Main", selling_price=9.5, ingredient_cost=3.8, quantity_sold=40),
                MenuItem(item_name="Teh Tarik", category="Beverage", selling_price=3.0, ingredient_cost=1.0, quantity_sold=80),
            ]
        )
    db.session.commit()


def login_required() -> bool:
    return "user_id" in session


def staff_required() -> bool:
    return login_required() and RoleService.is_staff()


def ensure_schema_updates() -> None:
    inspector = inspect(db.engine)
    user_columns = {col["name"] for col in inspector.get_columns("users")}
    if "role" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(30) DEFAULT 'client' NOT NULL"))
        db.session.execute(text("UPDATE users SET role = 'admin_analyst' WHERE username = 'admin'"))
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


def feedback_qr_payload(client_id: int) -> dict:
    feedback_url = url_for("public_feedback", client_id=client_id, _external=True)
    qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=280x280&data={quote_plus(feedback_url)}"
    return {"feedback_url": feedback_url, "qr_image_url": qr_image_url}


def request_value(key: str, default=None):
    payload = request.get_json(silent=True) if request.is_json else None
    if isinstance(payload, dict) and key in payload:
        return payload.get(key, default)
    return request.form.get(key, default)


def compute_dashboard_metrics() -> dict:
    sales = Sale.query.all()
    expenses = Expense.query.all()
    campaigns = MarketingCampaign.query.all()
    reviews = CustomerReview.query.all()

    sales_df = pd.DataFrame(
        [
            {
                "date": s.sale_date,
                "revenue": s.quantity * s.unit_price,
                "cost": s.quantity * s.unit_cost + s.extra_expense,
                "item": s.menu_item.item_name if s.menu_item else "Unknown",
                "qty": s.quantity,
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

    if sales_df.empty:
        return {
            "kpis": {"revenue": 0, "cost": 0, "profit": 0, "roi": 0, "positive_sentiment": 0},
            "revenue_labels": [],
            "revenue_values": [],
            "cash_values": [],
            "forecast_labels": [],
            "forecast_revenue": [],
            "forecast_cash": [],
            "campaign_roi": [],
            "sentiment_counts": {"positive": 0, "neutral": 0, "negative": 0},
            "sentiment_vs_sales_labels": [],
            "sentiment_vs_sales_revenue": [],
            "sentiment_vs_sales_sentiment": [],
            "menu_performance": [],
            "peak_day": None,
            "low_day": None,
        }

    daily = sales_df.groupby("date", as_index=False).agg(revenue=("revenue", "sum"), cost=("cost", "sum"))
    if not expense_df.empty:
        daily_exp = expense_df.groupby("date", as_index=False).agg(op_expense=("amount", "sum"))
        daily = daily.merge(daily_exp, on="date", how="left").fillna({"op_expense": 0})
    else:
        daily["op_expense"] = 0

    daily["profit"] = daily["revenue"] - daily["cost"] - daily["op_expense"]
    daily["cash_flow"] = daily["profit"].cumsum()
    daily = daily.sort_values("date")

    future_days = 14
    forecast_revenue = forecast_values(daily["revenue"], future_days)
    forecast_cash = forecast_values(daily["cash_flow"], future_days)
    forecast_dates = [(daily["date"].max() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, future_days + 1)]

    total_roi = 0.0
    campaign_roi_list = []
    if not campaign_df.empty:
        campaign_group = campaign_df.groupby("campaign", as_index=False).agg(spend=("spend", "sum"), revenue=("revenue", "sum"))
        campaign_group["roi"] = campaign_group.apply(lambda r: campaign_roi(r["spend"], r["revenue"]), axis=1)
        campaign_roi_list = campaign_group.to_dict(orient="records")
        total_spend = campaign_group["spend"].sum()
        total_revenue = campaign_group["revenue"].sum()
        total_roi = campaign_roi(total_spend, total_revenue)

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

    peak_day = daily.loc[daily["revenue"].idxmax(), "date"] if not daily.empty else None
    low_day = daily.loc[daily["revenue"].idxmin(), "date"] if not daily.empty else None

    return {
        "kpis": {
            "revenue": round(float(daily["revenue"].sum()), 2),
            "cost": round(float((daily["cost"] + daily["op_expense"]).sum()), 2),
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
        "menu_performance": menu_perf.to_dict(orient="records"),
        "peak_day": peak_day.strftime("%Y-%m-%d") if peak_day else None,
        "low_day": low_day.strftime("%Y-%m-%d") if low_day else None,
    }


def build_menu_engineering_data(search: str = "", category: str = "All", sort_by: str = "item_name", sort_dir: str = "asc") -> dict:
    query = MenuItem.query
    if search:
        query = query.filter(MenuItem.item_name.ilike(f"%{search}%"))
    if category and category != "All":
        query = query.filter(MenuItem.category == category)

    items = query.order_by(MenuItem.item_name.asc()).all()
    active_items = [i for i in items if i.status == "active"]

    def computed(i: MenuItem) -> dict:
        total_unit_cost = (i.ingredient_cost or 0) + (i.labor_cost or 0) + (i.packaging_cost or 0) + (i.overhead_cost or 0)
        contribution_margin = (i.selling_price or 0) - total_unit_cost
        total_profit = contribution_margin * (i.quantity_sold or 0)
        profit_margin_percent = (contribution_margin / i.selling_price * 100) if i.selling_price else 0
        return {
            "id": i.id,
            "item_name": i.item_name,
            "category": i.category,
            "selling_price": round(i.selling_price or 0, 2),
            "total_unit_cost": round(total_unit_cost, 2),
            "contribution_margin": round(contribution_margin, 2),
            "quantity_sold": int(i.quantity_sold or 0),
            "total_profit": round(total_profit, 2),
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

    categories = ["All"] + sorted(list({i.category for i in MenuItem.query.all() if i.category}))
    return {
        "rows": rows,
        "counts": counts,
        "avg_popularity": round(avg_popularity, 2),
        "avg_profitability": round(avg_profitability, 2),
        "categories": categories,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }


def register_routes(app: Flask) -> None:
    @app.route("/", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password, password):
                session["user_id"] = user.id
                session["full_name"] = user.full_name
                session["role"] = user.role or RoleService.CLIENT
                return redirect(url_for("dashboard"))
            flash("Invalid username or password.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/dashboard")
    def dashboard():
        if not login_required():
            return redirect(url_for("login"))
        metrics = compute_dashboard_metrics()
        qr_payload = None
        if session.get("role") == RoleService.CLIENT:
            qr_payload = feedback_qr_payload(session["user_id"])
        return render_template("dashboard.html", page="dashboard", metrics=metrics, qr_payload=qr_payload)

    @app.route("/client-data", methods=["GET", "POST"])
    def client_data():
        if not staff_required():
            flash("Admin / Analyst access required.", "warning")
            return redirect(url_for("dashboard"))

        clients = User.query.filter_by(role=RoleService.CLIENT).order_by(User.full_name.asc()).all()
        if request.method == "POST":
            client_user_id = request.form.get("client_user_id", type=int)
            note_text = (request.form.get("note_text", "") or "").strip()
            if not client_user_id or not note_text:
                flash("Client and note text are required.", "danger")
            else:
                db.session.add(
                    AnalystNote(
                        client_user_id=client_user_id,
                        analyst_user_id=session["user_id"],
                        note_text=note_text,
                    )
                )
                db.session.commit()
                flash("Client note saved.", "success")
            return redirect(url_for("client_data"))

        notes = AnalystNote.query.order_by(AnalystNote.created_at.desc()).limit(50).all()
        recent_sales = Sale.query.order_by(Sale.sale_date.desc()).limit(30).all()
        recent_expenses = Expense.query.order_by(Expense.expense_date.desc()).limit(30).all()
        recent_marketing = MarketingCampaign.query.order_by(MarketingCampaign.campaign_date.desc()).limit(30).all()
        recent_reviews = CustomerReview.query.order_by(CustomerReview.review_date.desc()).limit(30).all()
        qr_clients = [{"id": c.id, "name": c.full_name, **feedback_qr_payload(c.id)} for c in clients]
        return render_template(
            "client_data.html",
            page="client_data",
            clients=clients,
            notes=notes,
            recent_sales=recent_sales,
            recent_expenses=recent_expenses,
            recent_marketing=recent_marketing,
            recent_reviews=recent_reviews,
            qr_clients=qr_clients,
        )

    @app.route("/menu")
    def menu_redirect():
        return redirect(url_for("menu_engineering"))

    @app.route("/menu-engineering")
    def menu_engineering():
        if not login_required():
            return redirect(url_for("login"))
        data = build_menu_engineering_data(
            request.args.get("search", "").strip(),
            request.args.get("category", "All"),
            request.args.get("sort_by", "item_name"),
            request.args.get("sort_dir", "asc"),
        )
        edit_id = request.args.get("edit", type=int)
        editing = MenuItem.query.get(edit_id) if edit_id else None
        return render_template("menu_engineering.html", page="menu_engineering", data=data, editing=editing)

    @app.route("/menu-engineering/data")
    def menu_engineering_data():
        if not login_required():
            return jsonify({"error": "unauthorized"}), 401
        data = build_menu_engineering_data(
            request.args.get("search", "").strip(),
            request.args.get("category", "All"),
            request.args.get("sort_by", "item_name"),
            request.args.get("sort_dir", "asc"),
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
        if not login_required():
            return redirect(url_for("login"))
        db.session.add(
            MenuItem(
                item_name=request.form.get("item_name"),
                category=request.form.get("category"),
                selling_price=float(request.form.get("selling_price")),
                ingredient_cost=float(request.form.get("ingredient_cost", 0) or 0),
                labor_cost=float(request.form.get("labor_cost", 0) or 0),
                packaging_cost=float(request.form.get("packaging_cost", 0) or 0),
                overhead_cost=float(request.form.get("overhead_cost", 0) or 0),
                quantity_sold=int(request.form.get("quantity_sold", 0) or 0),
                status=request.form.get("status", "active"),
            )
        )
        db.session.commit()
        flash("Menu item added.", "success")
        return redirect(url_for("menu_engineering"))

    @app.route("/menu-engineering/edit/<int:menu_id>", methods=["POST"])
    def menu_engineering_edit(menu_id: int):
        if not login_required():
            return redirect(url_for("login"))
        item = MenuItem.query.get_or_404(menu_id)
        item.item_name = request.form.get("item_name")
        item.category = request.form.get("category")
        item.selling_price = float(request.form.get("selling_price"))
        item.ingredient_cost = float(request.form.get("ingredient_cost", 0) or 0)
        item.labor_cost = float(request.form.get("labor_cost", 0) or 0)
        item.packaging_cost = float(request.form.get("packaging_cost", 0) or 0)
        item.overhead_cost = float(request.form.get("overhead_cost", 0) or 0)
        item.quantity_sold = int(request.form.get("quantity_sold", 0) or 0)
        item.status = request.form.get("status", "active")
        db.session.commit()
        flash("Menu item updated.", "success")
        return redirect(url_for("menu_engineering"))

    @app.route("/menu-engineering/delete/<int:menu_id>", methods=["POST"])
    def menu_engineering_delete(menu_id: int):
        if not login_required():
            return redirect(url_for("login"))
        item = MenuItem.query.get_or_404(menu_id)
        db.session.delete(item)
        db.session.commit()
        flash("Menu item deleted.", "success")
        return redirect(url_for("menu_engineering"))

    @app.route("/sales", methods=["GET", "POST"])
    def sales_entry():
        if not login_required():
            return redirect(url_for("login"))

        edit_id = request.args.get("edit", type=int)
        editing = Sale.query.get(edit_id) if edit_id else None
        items = MenuItem.query.filter_by(status="active").all()

        if request.method == "POST":
            sale_id = request.form.get("sale_id")
            payload = {
                "sale_date": datetime.strptime(request.form.get("sale_date"), "%Y-%m-%d").date(),
                "menu_item_id": int(request.form.get("menu_item_id")),
                "quantity": int(request.form.get("quantity")),
                "unit_price": float(request.form.get("unit_price")),
                "unit_cost": float(request.form.get("unit_cost")),
                "extra_expense": float(request.form.get("extra_expense", 0) or 0),
                "channel": request.form.get("channel", "Walk-in"),
            }
            if sale_id:
                sale = Sale.query.get_or_404(int(sale_id))
                for k, v in payload.items():
                    setattr(sale, k, v)
                flash("Sales record updated.", "success")
            else:
                db.session.add(Sale(**payload))
                flash("Sales record added.", "success")
            db.session.commit()
            return redirect(url_for("sales_entry"))
        recent = Sale.query.order_by(Sale.sale_date.desc()).all()
        return render_template("sales.html", page="sales", items=items, recent=recent, today=date.today(), editing=editing)

    @app.route("/sales/delete/<int:sale_id>", methods=["POST"])
    def sales_delete(sale_id: int):
        if not login_required():
            return redirect(url_for("login"))
        sale = Sale.query.get_or_404(sale_id)
        db.session.delete(sale)
        db.session.commit()
        flash("Sales record deleted.", "success")
        return redirect(url_for("sales_entry"))

    @app.route("/expenses", methods=["GET", "POST"])
    def expense_entry():
        if not login_required():
            return redirect(url_for("login"))
        edit_id = request.args.get("edit", type=int)
        editing = Expense.query.get(edit_id) if edit_id else None
        if request.method == "POST":
            expense_id = request.form.get("expense_id")
            payload = {
                "expense_date": datetime.strptime(request.form.get("expense_date"), "%Y-%m-%d").date(),
                "category": request.form.get("category"),
                "amount": float(request.form.get("amount")),
                "note": request.form.get("note"),
            }
            if expense_id:
                expense = Expense.query.get_or_404(int(expense_id))
                for k, v in payload.items():
                    setattr(expense, k, v)
                flash("Expense record updated.", "success")
            else:
                db.session.add(Expense(**payload))
                flash("Expense record added.", "success")
            db.session.commit()
            return redirect(url_for("expense_entry"))
        recent = Expense.query.order_by(Expense.expense_date.desc()).all()
        return render_template("expenses.html", page="expenses", recent=recent, today=date.today(), editing=editing)

    @app.route("/expenses/delete/<int:expense_id>", methods=["POST"])
    def expense_delete(expense_id: int):
        if not login_required():
            return redirect(url_for("login"))
        expense = Expense.query.get_or_404(expense_id)
        db.session.delete(expense)
        db.session.commit()
        flash("Expense record deleted.", "success")
        return redirect(url_for("expense_entry"))

    @app.route("/marketing", methods=["GET", "POST"])
    def marketing_entry():
        if not login_required():
            return redirect(url_for("login"))
        edit_id = request.args.get("edit", type=int)
        editing = MarketingCampaign.query.get(edit_id) if edit_id else None
        if request.method == "POST":
            campaign_id = request.form.get("campaign_id")
            payload = {
                "campaign_date": datetime.strptime(request.form.get("campaign_date"), "%Y-%m-%d").date(),
                "campaign_name": request.form.get("campaign_name"),
                "platform": request.form.get("platform"),
                "spend": float(request.form.get("spend")),
                "revenue_generated": float(request.form.get("revenue_generated")),
                "note": request.form.get("note"),
            }
            if campaign_id:
                campaign = MarketingCampaign.query.get_or_404(int(campaign_id))
                for k, v in payload.items():
                    setattr(campaign, k, v)
                flash("Marketing campaign updated.", "success")
            else:
                db.session.add(MarketingCampaign(**payload))
                flash("Marketing campaign added.", "success")
            db.session.commit()
            return redirect(url_for("marketing_entry"))
        recent = MarketingCampaign.query.order_by(MarketingCampaign.campaign_date.desc()).all()
        return render_template("marketing.html", page="marketing", recent=recent, today=date.today(), editing=editing)

    @app.route("/marketing/delete/<int:campaign_id>", methods=["POST"])
    def marketing_delete(campaign_id: int):
        if not login_required():
            return redirect(url_for("login"))
        campaign = MarketingCampaign.query.get_or_404(campaign_id)
        db.session.delete(campaign)
        db.session.commit()
        flash("Marketing campaign deleted.", "success")
        return redirect(url_for("marketing_entry"))

    @app.route("/reviews", methods=["GET", "POST"])
    def review_entry():
        if not login_required():
            return redirect(url_for("login"))
        edit_id = request.args.get("edit", type=int)
        editing = CustomerReview.query.get(edit_id) if edit_id else None
        if request.method == "POST":
            review_text = request.form.get("review_text", "")
            rating = int(request.form.get("rating"))
            label, score = analyze_sentiment(review_text, rating)
            review_id = request.form.get("review_id")
            source_value = (request.form.get("source") or "").strip()
            source = source_value if source_value else "Manual Entry"
            issue_tag = request.form.get("issue_tag") or detect_issue_tag(review_text)
            urgency_level = determine_urgency_level(label, rating, issue_tag, review_text)
            payload = {
                "review_date": datetime.strptime(request.form.get("review_date"), "%Y-%m-%d").date(),
                "client_id": request.form.get("client_id", type=int),
                "customer_name": request.form.get("customer_name"),
                "phone_number": request.form.get("phone_number"),
                "menu_item": request.form.get("menu_item"),
                "order_type": request.form.get("order_type"),
                "source": source,
                "rating": rating,
                "review_text": review_text,
                "receipt_number": request.form.get("receipt_number"),
                "issue_tag": issue_tag,
                "urgency_level": urgency_level,
                "submission_channel": request.form.get("submission_channel", "manual"),
                "sentiment_label": label,
                "sentiment_score": score,
            }
            if review_id:
                review = CustomerReview.query.get_or_404(int(review_id))
                for k, v in payload.items():
                    setattr(review, k, v)
                flash("Customer review updated.", "success")
            else:
                db.session.add(CustomerReview(**payload))
                flash("Customer review added and sentiment analyzed.", "success")
            db.session.commit()
            return redirect(url_for("review_entry"))
        selected_source = request.args.get("source", "All")
        query = CustomerReview.query
        if selected_source != "All":
            query = query.filter(CustomerReview.source == selected_source)
        recent = query.order_by(CustomerReview.review_date.desc()).all()
        clients = User.query.filter_by(role=RoleService.CLIENT).order_by(User.full_name.asc()).all()
        qr_preview = None
        if clients:
            default_client = clients[0]
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
        if not login_required():
            return redirect(url_for("login"))
        review = CustomerReview.query.get_or_404(review_id)
        db.session.delete(review)
        db.session.commit()
        flash("Customer review deleted.", "success")
        return redirect(url_for("review_entry"))

    @app.route("/feedback/<int:client_id>", methods=["GET", "POST"])
    def public_feedback(client_id: int):
        client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        if request.method == "POST":
            visit_date_raw = (request.form.get("visit_date") or "").strip()
            menu_item = (request.form.get("menu_item") or "").strip()
            order_type = (request.form.get("order_type") or "").strip()
            review_text = (request.form.get("review_text") or "").strip()
            rating_raw = request.form.get("rating_overall")
            if not visit_date_raw or not menu_item or not order_type or not review_text or not rating_raw:
                flash("Please complete all required fields.", "danger")
                return render_template(
                    "feedback_form.html",
                    client=client,
                    order_types=ORDER_TYPES,
                    issue_tags=ISSUE_TAGS,
                    review_sources=REVIEW_SOURCES,
                )
            try:
                visit_date = datetime.strptime(visit_date_raw, "%Y-%m-%d").date()
                rating = int(rating_raw)
            except ValueError:
                flash("Invalid date or rating format.", "danger")
                return render_template(
                    "feedback_form.html",
                    client=client,
                    order_types=ORDER_TYPES,
                    issue_tags=ISSUE_TAGS,
                    review_sources=REVIEW_SOURCES,
                )
            if order_type not in ORDER_TYPES or rating < 1 or rating > 5:
                flash("Please provide a valid order type and rating.", "danger")
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
                    source="QR Feedback Form",
                    sentiment_label=label,
                    sentiment_score=score,
                    issue_tag=issue_tag,
                    urgency_level=urgency_level,
                    submission_channel="qr",
                )
            )
            db.session.commit()
            return redirect(url_for("feedback_thank_you", client_id=client.id))
        return render_template("feedback_form.html", client=client, order_types=ORDER_TYPES, issue_tags=ISSUE_TAGS)

    @app.route("/feedback/thank-you/<int:client_id>")
    def feedback_thank_you(client_id: int):
        client = User.query.filter_by(id=client_id, role=RoleService.CLIENT).first_or_404()
        return render_template("feedback_thank_you.html", client=client)

    @app.route("/reviews/submit", methods=["POST"])
    def review_submit():
        client_id = request_value("client_id")
        if client_id is not None:
            try:
                client_id = int(client_id)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "client_id must be numeric"}), 400
        review_text = (request_value("review_text", "") or "").strip()
        if not review_text:
            return jsonify({"ok": False, "error": "review_text is required"}), 400
        try:
            rating = int(request_value("rating_overall", request_value("rating", 3)))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "rating must be between 1 and 5"}), 400
        if rating < 1 or rating > 5:
            return jsonify({"ok": False, "error": "rating must be between 1 and 5"}), 400
        visit_date_raw = (request_value("visit_date", request_value("review_date", "")) or "").strip()
        review_date = date.today()
        if visit_date_raw:
            try:
                review_date = datetime.strptime(visit_date_raw, "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"ok": False, "error": "visit_date must be YYYY-MM-DD"}), 400
        label, score = analyze_sentiment(review_text, rating)
        issue_tag = request_value("issue_tag") or detect_issue_tag(review_text)
        source = (request_value("source", "QR Feedback Form") or "QR Feedback Form").strip() or "QR Feedback Form"
        order_type = request_value("order_type")
        if order_type and order_type not in ORDER_TYPES:
            order_type = None
        urgency_level = determine_urgency_level(label, rating, issue_tag, review_text)
        review = CustomerReview(
            client_id=client_id,
            customer_name=request_value("customer_name"),
            phone_number=request_value("phone_number"),
            review_date=review_date,
            menu_item=request_value("menu_item"),
            order_type=order_type,
            rating=rating,
            review_text=review_text,
            receipt_number=request_value("receipt_number"),
            source=source,
            sentiment_label=label,
            sentiment_score=score,
            issue_tag=issue_tag,
            urgency_level=urgency_level,
            submission_channel=request_value("submission_channel", "qr"),
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
        if not login_required():
            return redirect(url_for("login"))
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
        if not login_required():
            return redirect(url_for("login"))
        metrics = compute_dashboard_metrics()
        return render_template("analytics.html", page="analytics", metrics=metrics)

    @app.route("/forecast")
    def forecast_page():
        if not login_required():
            return redirect(url_for("login"))
        metrics = compute_dashboard_metrics()
        return render_template("forecast.html", page="forecast", metrics=metrics)

    @app.route("/roi")
    def roi_page():
        if not login_required():
            return redirect(url_for("login"))
        metrics = compute_dashboard_metrics()
        return render_template("roi.html", page="roi", metrics=metrics)

    @app.route("/sentiment")
    def sentiment_page():
        if not login_required():
            return redirect(url_for("login"))
        metrics = compute_dashboard_metrics()
        selected_source = request.args.get("source", "All")
        base_reviews = CustomerReview.query
        if selected_source != "All":
            base_reviews = base_reviews.filter(CustomerReview.source == selected_source)
        reviews = base_reviews.order_by(CustomerReview.review_date.desc()).all()
        filtered_metrics = dict(metrics)
        if reviews:
            filtered_metrics["sentiment_counts"] = {
                "positive": sum(1 for r in reviews if r.sentiment_label == "positive"),
                "neutral": sum(1 for r in reviews if r.sentiment_label == "neutral"),
                "negative": sum(1 for r in reviews if r.sentiment_label == "negative"),
            }
        else:
            filtered_metrics["sentiment_counts"] = {"positive": 0, "neutral": 0, "negative": 0}
        intelligence = build_sentiment_intelligence(filtered_metrics, reviews=reviews)
        return render_template(
            "sentiment.html",
            page="sentiment",
            metrics=filtered_metrics,
            intelligence=intelligence,
            review_sources=REVIEW_SOURCES,
            selected_source=selected_source,
        )

    @app.route("/reports")
    def reports_page():
        if not login_required():
            return redirect(url_for("login"))
        metrics = compute_dashboard_metrics()
        return render_template("reports.html", page="reports", metrics=metrics)


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
