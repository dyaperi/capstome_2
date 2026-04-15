from datetime import datetime

from db import db


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="client")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MenuItem(db.Model):
    __tablename__ = "menu_items"
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(150), unique=True, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    selling_price = db.Column(db.Float, nullable=False)
    ingredient_cost = db.Column(db.Float, default=0)
    labor_cost = db.Column(db.Float, default=0)
    packaging_cost = db.Column(db.Float, default=0)
    overhead_cost = db.Column(db.Float, default=0)
    quantity_sold = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Sale(db.Model):
    __tablename__ = "sales"
    id = db.Column(db.Integer, primary_key=True)
    sale_date = db.Column(db.Date, nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey("menu_items.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)
    extra_expense = db.Column(db.Float, default=0)
    channel = db.Column(db.String(50), default="Walk-in")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    menu_item = db.relationship("MenuItem", backref="sales")


class Expense(db.Model):
    __tablename__ = "expenses"
    id = db.Column(db.Integer, primary_key=True)
    expense_date = db.Column(db.Date, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MarketingCampaign(db.Model):
    __tablename__ = "marketing_campaigns"
    id = db.Column(db.Integer, primary_key=True)
    campaign_date = db.Column(db.Date, nullable=False)
    campaign_name = db.Column(db.String(150), nullable=False)
    platform = db.Column(db.String(80), nullable=False)
    spend = db.Column(db.Float, nullable=False)
    revenue_generated = db.Column(db.Float, default=0)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CustomerReview(db.Model):
    __tablename__ = "customer_reviews"
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    customer_name = db.Column(db.String(150))
    phone_number = db.Column(db.String(30))
    review_date = db.Column(db.Date, nullable=False)
    menu_item = db.Column(db.String(150))
    order_type = db.Column(db.String(30))
    source = db.Column(db.String(80), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    review_text = db.Column(db.Text, nullable=False)
    receipt_number = db.Column(db.String(80))
    issue_tag = db.Column(db.String(80), default="General")
    urgency_level = db.Column(db.String(20), default="low")
    submission_channel = db.Column(db.String(30), default="manual")
    sentiment_label = db.Column(db.String(20), nullable=False)
    sentiment_score = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = db.relationship("User", backref="customer_reviews")


class ForecastResult(db.Model):
    __tablename__ = "forecast_results"
    id = db.Column(db.Integer, primary_key=True)
    forecast_date = db.Column(db.Date, nullable=False)
    metric = db.Column(db.String(50), nullable=False)
    value = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AnalystNote(db.Model):
    __tablename__ = "analyst_notes"
    id = db.Column(db.Integer, primary_key=True)
    client_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    analyst_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    note_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    client_user = db.relationship("User", foreign_keys=[client_user_id], backref="client_notes")
    analyst_user = db.relationship("User", foreign_keys=[analyst_user_id], backref="analyst_notes")
