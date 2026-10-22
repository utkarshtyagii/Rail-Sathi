import os
from decimal import Decimal
from datetime import timezone
from flask import Flask, render_template, request
from flask_login import current_user
from sqlalchemy import func
from werkzeug.exceptions import HTTPException
import click
from zoneinfo import ZoneInfo
from config import Config
from .extensions import csrf, db, login_manager, migrate, socketio


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    if app.config.get("APP_ENV") == "production":
        secret_key = app.config.get("SECRET_KEY", "")
        if secret_key in {"", "dev-only-change-me", "replace-with-a-long-random-value"} or len(secret_key) < 32:
            raise RuntimeError("Production requires a SECRET_KEY with at least 32 characters.")
        if not app.config.get("SESSION_COOKIE_SECURE"):
            raise RuntimeError("Set COOKIE_SECURE=true when serving the production site over HTTPS.")
    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    csrf.init_app(app)
    socketio.init_app(app, message_queue=app.config.get("SOCKETIO_MESSAGE_QUEUE"))

    from . import models  # noqa: F401
    from .handoff import passenger_handoff_code
    from . import tracking  # noqa: F401  Register authenticated Socket.IO handlers.
    from .models import Booking, BookingStatusHistory, SupportRequest, User
    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .public import bp as public_bp
    from .bookings import bp as bookings_bp
    from .dashboards import bp as dashboards_bp
    from .payments import bp as payments_bp

    app.jinja_env.globals["passenger_handoff_code"] = passenger_handoff_code

    @app.context_processor
    def passenger_notification_context():
        if not current_user.is_authenticated or current_user.role not in {"passenger", "porter", "admin"}:
            return {"passenger_unread_notification_count": 0, "porter_unread_notification_count": 0, "admin_unread_notification_count": 0}

        unread_query = (
            db.select(func.count(BookingStatusHistory.id))
            .join(Booking, Booking.id == BookingStatusHistory.booking_id)
        )
        if current_user.role == "admin":
            support_query = db.select(func.count(SupportRequest.id)).where(SupportRequest.status == "open")
            porter_query = db.select(func.count(User.id)).where(
                User.role == "porter",
                User.porter_status == "pending",
            )
            if current_user.last_notification_read_at:
                support_query = support_query.where(SupportRequest.created_at > current_user.last_notification_read_at)
                porter_query = porter_query.where(User.created_at > current_user.last_notification_read_at)
            unread_count = (db.session.scalar(support_query) or 0) + (db.session.scalar(porter_query) or 0)
            return {"passenger_unread_notification_count": 0, "porter_unread_notification_count": 0, "admin_unread_notification_count": unread_count}
        if current_user.role == "passenger":
            unread_query = unread_query.where(Booking.passenger_id == current_user.id)
        else:
            unread_query = unread_query.where(
                Booking.porter_id == current_user.id,
                BookingStatusHistory.status.in_(("assigned", "accepted", "declined", "en_route", "arrived", "in_progress", "completed", "cancelled")),
            )
        if current_user.last_notification_read_at:
            unread_query = unread_query.where(
                BookingStatusHistory.created_at > current_user.last_notification_read_at
            )
        unread_count = db.session.scalar(unread_query) or 0
        support_query = db.select(func.count(SupportRequest.id)).where(
            SupportRequest.email == current_user.email,
            SupportRequest.status == "closed",
            SupportRequest.closed_at.is_not(None),
        )
        if current_user.last_notification_read_at:
            support_query = support_query.where(
                SupportRequest.closed_at > current_user.last_notification_read_at
            )
        unread_count += db.session.scalar(support_query) or 0
        return {
            "passenger_unread_notification_count": unread_count if current_user.role == "passenger" else 0,
            "porter_unread_notification_count": unread_count if current_user.role == "porter" else 0,
            "admin_unread_notification_count": 0,
        }

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(bookings_bp, url_prefix="/bookings")
    app.register_blueprint(dashboards_bp, url_prefix="/dashboard")
    app.register_blueprint(admin_bp)
    app.register_blueprint(payments_bp)

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.path.startswith(("/auth", "/dashboard", "/bookings", "/payments", "/support")):
            response.headers.setdefault("Cache-Control", "no-store")
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        descriptions = {
            400: "That request could not be understood. Please go back and try again.",
            403: "You don’t have access to that page or action.",
            404: "We couldn’t find the page you were looking for.",
            409: "That record has changed and can’t be updated in its current state.",
        }
        return (
            render_template(
                "errors/error.html",
                code=error.code,
                title=error.name,
                description=descriptions.get(error.code, "We couldn’t complete that request."),
            ),
            error.code,
        )

    @app.errorhandler(500)
    def handle_server_error(_error):
        db.session.rollback()
        return (
            render_template(
                "errors/error.html",
                code=500,
                title="Something went wrong",
                description="We couldn’t complete this request. Please try again in a moment.",
            ),
            500,
        )

    @app.template_filter("inr")
    def inr(value):
        amount = Decimal(value)
        if amount == amount.quantize(Decimal("1")):
            return f"₹{amount:,.0f}"
        return f"₹{amount:,.2f}"

    india_timezone = ZoneInfo("Asia/Kolkata")

    @app.template_filter("india_local")
    def india_local(value):
        if value.tzinfo is None:
            return value.replace(tzinfo=india_timezone)
        return value.astimezone(india_timezone)

    @app.template_filter("india_utc")
    def india_utc(value):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(india_timezone)

    @app.cli.command("seed")
    def seed():
        from .seed import seed_development_data
        seed_development_data()
        print("Development stations and services seeded.")

    @app.cli.command("create-main-admin")
    @click.argument("email")
    def create_main_admin(email):
        """Promote an existing account to the single main administrator."""
        from .models import User
        from sqlalchemy import func

        user = db.session.scalar(db.select(User).where(func.lower(User.email) == email.strip().lower()))
        if not user:
            raise click.ClickException("No account found for that email. Register it first.")
        existing_main_admin = User.query.filter_by(is_main_admin=True).first()
        if existing_main_admin and existing_main_admin.id != user.id:
            raise click.ClickException(f"A main administrator already exists: {existing_main_admin.email}.")
        user.role = "admin"
        user.active = True
        user.is_main_admin = True
        db.session.commit()
        click.echo(f"Main administrator access enabled for {user.email}.")

    return app

