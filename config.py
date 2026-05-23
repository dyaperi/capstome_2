import os
import secrets


def database_uri_from_env() -> str:
    database_url = os.getenv("DATABASE_URL", "mysql+pymysql://root:dyaperi@localhost:3306/fnb_insights")
    if database_url.startswith("mysql://"):
        return database_url.replace("mysql://", "mysql+pymysql://", 1)
    return database_url


class Config:
    ENV = os.getenv("FLASK_ENV") or os.getenv("APP_ENV") or "development"
    IS_PRODUCTION = ENV.lower() in {"production", "prod"}

    SECRET_KEY = os.getenv("SECRET_KEY")
    if not SECRET_KEY:
        if IS_PRODUCTION:
            raise RuntimeError("SECRET_KEY environment variable is required in production.")
        SECRET_KEY = secrets.token_urlsafe(32)

    SQLALCHEMY_DATABASE_URI = database_uri_from_env()
    BASE_URL = (os.getenv("BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "").strip()
    PUBLIC_BASE_URL = BASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", str(IS_PRODUCTION)).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
