from email_validator import EmailNotValidError, validate_email
from datetime import date
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import login_user, logout_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from .extensions import db
from .models import Station, User


bp = Blueprint("auth", __name__)


def redirect_after_auth(role):
    """Honor safe local paths, but send signed-in users to their dashboard before booking."""
    destination = request.args.get("next") or session.pop("auth_next", "")
    is_local_path = (
        destination.startswith("/")
        and not destination.startswith("//")
        and "\\" not in destination
        and not any(ord(character) < 32 for character in destination)
    )
    if is_local_path:
        if destination.startswith("/bookings/"):
            return redirect(url_for("dashboards.index"))
        return redirect(destination)
    return redirect(url_for("dashboards.index"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    stations = Station.query.filter_by(supported=True).order_by(Station.name).all()
    form_data = {"name": "", "email": "", "phone": "", "date_of_birth": "", "preferred_station": ""}
    selected_role = "passenger"

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        submitted_email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "passenger")
        phone = request.form.get("phone", "").strip()
        date_of_birth_raw = request.form.get("date_of_birth", "").strip()
        preferred_station_id = request.form.get("preferred_station", type=int)
        selected_role = role if role in {"passenger", "porter"} else "passenger"
        form_data.update(
            name=name,
            email=submitted_email,
            phone=phone,
            date_of_birth=date_of_birth_raw,
            preferred_station=str(preferred_station_id or ""),
        )
        preferred_station = db.session.get(Station, preferred_station_id) if preferred_station_id else None

        try:
            email = validate_email(submitted_email, check_deliverability=False).normalized
        except EmailNotValidError:
            email = ""

        phone_digits = "".join(character for character in phone if character.isdigit())
        try:
            date_of_birth = date.fromisoformat(date_of_birth_raw)
        except ValueError:
            date_of_birth = None
        valid_account = (
            role in {"passenger", "porter"}
            and 1 <= len(name) <= 120
            and email
            and len(email) <= 255
            and 1 <= len(password) <= 128
        )
        valid_porter_application = (
            role != "porter"
            or (
                preferred_station
                and preferred_station.supported
            )
        )
        valid_phone = (
            len(phone) <= 30
            and all(character.isdigit() or character in "+().- " for character in phone)
            and 8 <= len(phone_digits) <= 15
        )
        valid_passenger_details = role != "passenger" or (date_of_birth is not None and date_of_birth <= date.today())

        if not valid_account:
            flash("Enter a valid name and email, and choose a password of up to 128 characters.", "error")
        elif not valid_phone:
            flash("Enter a valid phone number with 8 to 15 digits.", "error")
        elif not valid_passenger_details:
            flash("Enter a valid date of birth that is not in the future.", "error")
        elif not valid_porter_application:
            flash("Porter applicants must enter a valid phone number and choose a supported station.", "error")
        elif db.session.scalar(db.select(User).where(func.lower(User.email) == email.lower())):
            flash("An account already uses that email.", "error")
        else:
            user = User(
                name=name,
                email=email,
                role=role,
                phone=phone[:30],
                date_of_birth=date_of_birth if role == "passenger" else None,
                preferred_station_id=preferred_station.id if role == "porter" else None,
                porter_status="pending" if role == "porter" else "not_applicable",
            )
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("An account already uses that email. Try signing in instead.", "error")
            else:
                session.pop("auth_account_id", None)
                session.pop("auth_role", None)
                login_user(user)
                return redirect_after_auth(user.role)

    return render_template(
        "auth.html",
        mode="register",
        stations=stations,
        form_data=form_data,
        selected_role=selected_role,
        today=date.today().isoformat(),
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET" and request.args.get("next"):
        session["auth_next"] = request.args.get("next", "")
    if request.method == "GET" and request.args.get("restart") == "1":
        session.pop("auth_account_id", None)
        session.pop("auth_role", None)

    if request.method == "POST":
        step = request.form.get("step", "identify")
        if step == "password":
            user = db.session.get(User, session.get("auth_account_id"))
            password = request.form.get("password", "")
            if user and user.active and user.role == session.get("auth_role") and user.check_password(password):
                session.pop("auth_account_id", None)
                session.pop("auth_role", None)
                login_user(user)
                return redirect_after_auth(user.role)
            if user and not user.active:
                flash("This account is inactive. Contact Rail Sathi support for help.", "error")
            else:
                flash("Password is incorrect. Try again or use a different email or phone.", "error")
            return render_template(
                "auth.html",
                mode="login",
                login_step="password",
                selected_role=session.get("auth_role", "passenger"),
                identifier_display=(user.email if user else "Your account"),
                form_data={"identifier": user.email if user else ""},
            )

        if step != "identify":
            abort(400)
        session.pop("auth_account_id", None)
        session.pop("auth_role", None)
        role = request.form.get("role", "passenger")
        role = role if role in {"passenger", "porter", "admin"} else "passenger"
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        accounts = []
        valid_identifier = False
        if "@" in identifier:
            try:
                normalized_email = validate_email(identifier, check_deliverability=False).normalized
            except EmailNotValidError:
                normalized_email = ""
            if normalized_email:
                valid_identifier = True
                account = db.session.scalar(db.select(User).where(func.lower(User.email) == normalized_email.lower()))
                accounts = [account] if account else []
        else:
            phone_digits = "".join(character for character in identifier if character.isdigit())
            valid_identifier = (
                8 <= len(phone_digits) <= 15
                and len(identifier) <= 30
                and all(character.isdigit() or character in "+().- " for character in identifier)
            )
            if valid_identifier:
                normalized_phone = User.phone
                for character in ("+", " ", "-", "(", ")", "."):
                    normalized_phone = func.replace(normalized_phone, character, "")
                accounts = db.session.scalars(
                    db.select(User).where(User.phone.isnot(None), normalized_phone == phone_digits)
                ).all()

        if not valid_identifier:
            flash("Enter a valid email address or phone number to continue.", "error")
            return render_template("auth.html", mode="login", login_step="identify", selected_role=role, form_data={"identifier": identifier})
        if len(accounts) > 1:
            flash("More than one account uses that phone number. Continue with your email address.", "error")
            return render_template("auth.html", mode="login", login_step="identify", selected_role=role, form_data={"identifier": identifier})
        elif accounts:
            user = accounts[0]
            if user.role != role:
                flash(f"That login belongs to a {user.role} account. Select that account type to continue.", "error")
            elif not user.active:
                flash("This account is inactive. Contact Rail Sathi support for help.", "error")
            else:
                if not password:
                    flash("Enter your password to continue.", "error")
                elif user.check_password(password):
                    session.pop("auth_account_id", None)
                    session.pop("auth_role", None)
                    login_user(user)
                    return redirect_after_auth(user.role)
                else:
                    flash("Password is incorrect. Check it and try again.", "error")
            return render_template("auth.html", mode="login", login_step="identify", selected_role=role, form_data={"identifier": identifier})
        elif role == "admin":
            flash("No administrator account matches that email or phone. Ask the main admin to create your account.", "error")
            return render_template("auth.html", mode="login", login_step="identify", selected_role=role, form_data={"identifier": identifier})
        elif not identifier:
            flash("Enter the email address or phone number for your account.", "error")
        else:
            session.pop("auth_account_id", None)
            session.pop("auth_role", None)
            form_data = {
                "name": "",
                "email": identifier if "@" in identifier else "",
                "phone": "" if "@" in identifier else identifier,
                "date_of_birth": "",
                "preferred_station": "",
            }
            return render_template(
                "auth.html",
                mode="register",
                stations=Station.query.filter_by(supported=True).order_by(Station.name).all(),
                form_data=form_data,
                selected_role=role,
                today=date.today().isoformat(),
                signup_prompt=True,
            )

    login_step = "password" if session.get("auth_account_id") else "identify"
    user = db.session.get(User, session.get("auth_account_id")) if login_step == "password" else None
    return render_template(
        "auth.html",
        mode="login",
        login_step=login_step,
        selected_role=session.get("auth_role", "passenger"),
        identifier_display=user.email if user else "",
        form_data={"identifier": user.email if user else ""},
    )


@bp.post("/logout")
def logout():
    logout_user()
    session.pop("auth_account_id", None)
    session.pop("auth_role", None)
    session.pop("auth_next", None)
    return redirect(url_for("public.home"))
