from datetime import date, datetime, timezone
from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, text
from werkzeug.security import check_password_hash, generate_password_hash
from .extensions import db, login_manager


ACTIVE_BOOKING_STATUSES = ("assigned", "accepted", "en_route", "arrived", "in_progress")


def now_utc():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __table_args__ = (
        Index(
            "uq_user_one_main_admin",
            "is_main_admin",
            unique=True,
            sqlite_where=text("is_main_admin = 1"),
            postgresql_where=text("is_main_admin = true"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="passenger")
    is_main_admin = db.Column(db.Boolean, nullable=False, default=False, server_default=text("false"))
    active = db.Column(db.Boolean, nullable=False, default=True)
    phone = db.Column(db.String(30))
    date_of_birth = db.Column(db.Date)
    last_notification_read_at = db.Column(db.DateTime(timezone=True))
    preferred_station_id = db.Column(db.Integer, db.ForeignKey("station.id"))
    porter_status = db.Column(
        db.String(20),
        nullable=False,
        default="not_applicable",
        server_default="not_applicable",
    )
    porter_available = db.Column(db.Boolean, nullable=False, default=False, server_default=text("false"))
    porter_review_note = db.Column(db.String(300))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)
    bookings = db.relationship("Booking", back_populates="passenger", foreign_keys="Booking.passenger_id")
    porter_bookings = db.relationship("Booking", back_populates="porter", foreign_keys="Booking.porter_id")
    preferred_station = db.relationship("Station", foreign_keys=[preferred_station_id])

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Station(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(10), unique=True, nullable=False, index=True)
    region = db.Column(db.String(80), nullable=False)
    supported = db.Column(db.Boolean, default=True, nullable=False)
    services = db.relationship("ServiceType", back_populates="station")


class ServiceType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey("station.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=False, default="")
    base_fare = db.Column(db.Numeric(10, 2), nullable=False, default=250)
    active = db.Column(db.Boolean, nullable=False, default=True)
    station = db.relationship("Station", back_populates="services")


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(16), unique=True, nullable=False, index=True)
    passenger_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    porter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    station_id = db.Column(db.Integer, db.ForeignKey("station.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("service_type.id"), nullable=False)
    service_at = db.Column(db.DateTime(timezone=True), nullable=False)
    passenger_phone = db.Column(db.String(30))
    train_number = db.Column(db.String(20))
    platform = db.Column(db.String(20))
    coach = db.Column(db.String(20))
    berth = db.Column(db.String(20))
    pickup = db.Column(db.String(180), nullable=False)
    pickup_latitude = db.Column(db.Float)
    pickup_longitude = db.Column(db.Float)
    destination = db.Column(db.String(180), nullable=False)
    destination_latitude = db.Column(db.Float)
    destination_longitude = db.Column(db.Float)
    bags = db.Column(db.Integer, nullable=False, default=1)
    instructions = db.Column(db.String(500))
    status = db.Column(db.String(30), nullable=False, default="requested", index=True)
    estimated_fare = db.Column(db.Numeric(10, 2), nullable=False)
    handoff_otp_nonce = db.Column(db.String(64))
    handoff_otp_expires_at = db.Column(db.DateTime(timezone=True))
    handoff_otp_attempts = db.Column(db.Integer, nullable=False, default=0, server_default=text("0"))
    handoff_otp_verified_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)
    passenger = db.relationship("User", back_populates="bookings", foreign_keys=[passenger_id])
    porter = db.relationship("User", back_populates="porter_bookings", foreign_keys=[porter_id])
    station = db.relationship("Station")
    service = db.relationship("ServiceType")
    history = db.relationship("BookingStatusHistory", back_populates="booking", order_by="BookingStatusHistory.created_at")
    payments = db.relationship("PaymentAttempt", back_populates="booking", order_by="PaymentAttempt.created_at.desc()")


class BookingLiveLocation(db.Model):
    """The latest consented location fix for one participant in one booking."""

    __tablename__ = "booking_live_location"
    __table_args__ = (
        db.UniqueConstraint("booking_id", "user_id", name="uq_booking_live_location_participant"),
    )

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    accuracy_m = db.Column(db.Float)
    is_sharing = db.Column(db.Boolean, nullable=False, default=False, server_default=text("false"))
    sharing_opted_out = db.Column(db.Boolean, nullable=False, default=False, server_default=text("false"))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)


class BookingStatusHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)
    booking = db.relationship("Booking", back_populates="history")


class PorterReview(db.Model):
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_porter_review_rating_range"),
    )

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id", ondelete="CASCADE"), nullable=False, unique=True)
    passenger_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    porter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)
    booking = db.relationship("Booking", backref=db.backref("porter_review", uselist=False))
    passenger = db.relationship("User", foreign_keys=[passenger_id])
    porter = db.relationship("User", foreign_keys=[porter_id])


class SupportRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    booking_reference = db.Column(db.String(16))
    message = db.Column(db.String(1500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)
    closed_at = db.Column(db.DateTime(timezone=True), index=True)


class PaymentAttempt(db.Model):
    __table_args__ = (
        Index(
            "uq_payment_attempt_one_active_booking",
            "booking_id",
            unique=True,
            sqlite_where=text("status IN ('creating', 'created', 'authorized', 'processing')"),
            postgresql_where=text("status IN ('creating', 'created', 'authorized', 'processing')"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False, index=True)
    amount_paise = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="INR")
    status = db.Column(db.String(20), nullable=False, default="creating", index=True)
    provider_order_id = db.Column(db.String(80), unique=True)
    provider_payment_id = db.Column(db.String(80), unique=True)
    receipt = db.Column(db.String(40), unique=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)
    booking = db.relationship("Booking", back_populates="payments")

