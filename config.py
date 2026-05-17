import os
import secrets


class Config:
    ENV = os.getenv("FLASK_ENV") or os.getenv("APP_ENV") or "development"
    IS_PRODUCTION = ENV.lower() in {"production", "prod"}

    SECRET_KEY = os.getenv("SECRET_KEY")
    if not SECRET_KEY:
        if IS_PRODUCTION:
            raise RuntimeError("SECRET_KEY environment variable is required in production.")
        SECRET_KEY = secrets.token_urlsafe(32)

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://root:dyaperi@localhost:3306/fnb_insights",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", str(IS_PRODUCTION)).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
