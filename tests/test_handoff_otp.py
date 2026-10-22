import re
import unittest
from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import Booking, ServiceType, Station, User


class HandoffOtpTestConfig:
    TESTING = True
    SECRET_KEY = "handoff-otp-test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SOCKETIO_MESSAGE_QUEUE = None


class HandoffOtpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(HandoffOtpTestConfig)

    def setUp(self):
        with self.app.app_context():
            db.drop_all()
            db.create_all()
            station = Station(name="New Delhi", code="NDLS", region="North")
            db.session.add(station)
            db.session.flush()
            service = ServiceType(station_id=station.id, name="Luggage assistance", base_fare=300)
            passenger = User(name="Passenger", email="passenger@example.test", password_hash="test", role="passenger")
            porter = User(
                name="Porter", email="porter@example.test", password_hash="test", role="porter",
                porter_status="verified", porter_available=True, preferred_station_id=station.id,
            )
            db.session.add_all([service, passenger, porter])
            db.session.flush()
            booking = Booking(
                public_id="HANDOFF123", passenger_id=passenger.id, porter_id=porter.id,
                station_id=station.id, service_id=service.id,
                service_at=datetime.now() + timedelta(days=1), pickup="Platform 5",
                destination="Coach A2", bags=1, status="en_route", estimated_fare=300,
            )
            db.session.add(booking)
            db.session.commit()
            self.booking_id = booking.id
            self.passenger_id = passenger.id
            self.porter_id = porter.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _client(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        return client

    def _arrive(self):
        return self._client(self.porter_id).post(
            f"/bookings/{self.booking_id}/status", data={"status": "arrived"}
        )

    def _passenger_code(self):
        response = self._client(self.passenger_id).get("/dashboard/bookings?status=active")
        self.assertEqual(response.status_code, 200)
        match = re.search(rb'class="passenger-handoff-code-value">([0-9]{6})<', response.data)
        self.assertIsNotNone(match, "The passenger should see the current handoff code")
        return match.group(1).decode("ascii")

    def test_starting_assistance_requires_passenger_code(self):
        self.assertEqual(self._arrive().status_code, 302)
        code = self._passenger_code()

        porter_client = self._client(self.porter_id)
        porter_page = porter_client.get("/dashboard/porter/active-job")
        self.assertIn(b"Passenger OTP", porter_page.data)
        self.assertIn(b"Mark in progress", porter_page.data)
        self.assertNotIn(code.encode("ascii"), porter_page.data)
        self.assertLess(porter_page.data.index(b"Mark in progress"), porter_page.data.index(b"data-tracking-map"))
        self.assertLess(porter_page.data.index(b"data-start-sharing"), porter_page.data.index(b"data-tracking-map"))

        missing = porter_client.post(
            f"/bookings/{self.booking_id}/status", data={"status": "in_progress"}
        )
        self.assertEqual(missing.status_code, 302)
        with self.app.app_context():
            booking = db.session.get(Booking, self.booking_id)
            self.assertEqual(booking.status, "arrived")
            self.assertEqual(booking.handoff_otp_attempts, 0)

        wrong_code = f"{(int(code) + 1) % 1_000_000:06d}"
        wrong = porter_client.post(
            f"/bookings/{self.booking_id}/status",
            data={"status": "in_progress", "handoff_otp": wrong_code},
        )
        self.assertEqual(wrong.status_code, 302)
        with self.app.app_context():
            booking = db.session.get(Booking, self.booking_id)
            self.assertEqual(booking.status, "arrived")
            self.assertEqual(booking.handoff_otp_attempts, 1)

        accepted = porter_client.post(
            f"/bookings/{self.booking_id}/status",
            data={"status": "in_progress", "handoff_otp": code},
        )
        self.assertEqual(accepted.status_code, 302)
        with self.app.app_context():
            booking = db.session.get(Booking, self.booking_id)
            self.assertEqual(booking.status, "in_progress")
            self.assertIsNone(booking.handoff_otp_verified_at)
        completion_code = self._passenger_code()
        porter_page = porter_client.get("/dashboard/porter/active-job")
        self.assertIn(b"Passenger OTP", porter_page.data)
        self.assertIn(b"Complete job", porter_page.data)

        missing_completion_code = porter_client.post(
            f"/bookings/{self.booking_id}/status", data={"status": "completed"}
        )
        self.assertEqual(missing_completion_code.status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(Booking, self.booking_id).status, "in_progress")

        completed = porter_client.post(
            f"/bookings/{self.booking_id}/status",
            data={"status": "completed", "handoff_otp": completion_code},
        )
        self.assertEqual(completed.status_code, 302)
        with self.app.app_context():
            booking = db.session.get(Booking, self.booking_id)
            self.assertEqual(booking.status, "completed")
            self.assertIsNotNone(booking.handoff_otp_verified_at)

    def test_only_the_passenger_can_view_or_regenerate_the_code(self):
        self._arrive()
        passenger_page = self._client(self.passenger_id).get("/dashboard/bookings?status=active")
        code_match = re.search(rb'class="passenger-handoff-code-value">([0-9]{6})<', passenger_page.data)
        self.assertIsNotNone(code_match)
        code = code_match.group(1)

        porter_page = self._client(self.porter_id).get("/dashboard/porter/active-job")
        self.assertNotIn(code, porter_page.data)

        regenerated = self._client(self.passenger_id).post(
            f"/bookings/{self.booking_id}/handoff-otp/regenerate"
        )
        self.assertEqual(regenerated.status_code, 302)
        new_code = self._passenger_code()
        self.assertRegex(new_code, r"^[0-9]{6}$")

    def test_completed_booking_accepts_one_passenger_review(self):
        with self.app.app_context():
            booking = db.session.get(Booking, self.booking_id)
            booking.status = "completed"
            db.session.commit()

        passenger = self._client(self.passenger_id)
        page = passenger.get("/dashboard/bookings?status=completed")
        self.assertIn(b"How was your porter?", page.data)

        response = passenger.post(
            f"/bookings/{self.booking_id}/review",
            data={"rating": "5", "comment": "Careful and helpful."},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            from app.models import PorterReview
            review = PorterReview.query.filter_by(booking_id=self.booking_id).one()
            self.assertEqual(review.rating, 5)
            self.assertEqual(review.comment, "Careful and helpful.")

        page = passenger.get("/dashboard/bookings?status=completed")
        self.assertIn(b"Thank you for sharing feedback", page.data)
        self.assertNotIn(b"How was your porter?", page.data)

    def test_porter_cannot_submit_a_passenger_review(self):
        with self.app.app_context():
            booking = db.session.get(Booking, self.booking_id)
            booking.status = "completed"
            db.session.commit()

        response = self._client(self.porter_id).post(
            f"/bookings/{self.booking_id}/review", data={"rating": "5"}
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
