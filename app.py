from datetime import date, datetime, timedelta

import pandas as pd
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from analytics import analyze_sentiment, campaign_roi, forecast_values
from config import Config
from db import db
from models import CustomerReview, Expense, MarketingCampaign, MenuItem, Sale, User


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        seed_default_data()

    register_routes(app)
    return app


def seed_default_data() -> None:
    if not User.query.filter_by(username="admin").first():
        db.session.add(
            User(username="admin", full_name="SME Owner", password=generate_password_hash("admin123"))
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
        return render_template("dashboard.html", page="dashboard", metrics=metrics)

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
            payload = {
                "review_date": datetime.strptime(request.form.get("review_date"), "%Y-%m-%d").date(),
                "source": request.form.get("source"),
                "rating": rating,
                "review_text": review_text,
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
        recent = CustomerReview.query.order_by(CustomerReview.review_date.desc()).all()
        return render_template("reviews.html", page="reviews", recent=recent, today=date.today(), editing=editing)

    @app.route("/reviews/delete/<int:review_id>", methods=["POST"])
    def reviews_delete(review_id: int):
        if not login_required():
            return redirect(url_for("login"))
        review = CustomerReview.query.get_or_404(review_id)
        db.session.delete(review)
        db.session.commit()
        flash("Customer review deleted.", "success")
        return redirect(url_for("review_entry"))

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
        return render_template("sentiment.html", page="sentiment", metrics=metrics)

    @app.route("/reports")
    def reports_page():
        if not login_required():
            return redirect(url_for("login"))
        metrics = compute_dashboard_metrics()
        return render_template("reports.html", page="reports", metrics=metrics)


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
