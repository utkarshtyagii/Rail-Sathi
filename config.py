import os


class Config:
    APP_ENV = os.getenv("RAILSATHI_ENV", "development").lower()
    TEMPLATES_AUTO_RELOAD = APP_ENV != "production"
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///rail_sathi_dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    SOCKETIO_MESSAGE_QUEUE = os.getenv("SOCKETIO_MESSAGE_QUEUE", "").strip() or None
    LOCATION_UPDATE_MIN_INTERVAL_SECONDS = int(os.getenv("LOCATION_UPDATE_MIN_INTERVAL_SECONDS", "3"))
    LOCATION_STALE_AFTER_SECONDS = int(os.getenv("LOCATION_STALE_AFTER_SECONDS", "30"))

