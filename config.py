import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "capstone-secret-key")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://root:dyaperi@localhost:3306/fnb_insights",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
