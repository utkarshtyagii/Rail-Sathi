import unittest
from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import Booking, BookingStatusHistory, ServiceType, Station, User


class BookingDispatchTestConfig:
    TESTING = True
    SECRET_KEY = "booking-dispatch-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SOCKETIO_MESSAGE_QUEUE = None


class BookingDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(BookingDispatchTestConfig)

    def setUp(self):
        with self.app.app_context():
            db.drop_all()
            db.create_all()
            station = Station(name="New Delhi", code="NDLS", region="North")
            other_station = Station(name="Mumbai CSMT", code="CSMT", region="West")
            db.session.add_all([station, other_station])
            db.session.flush()
            service = ServiceType(station_id=station.id, name="Luggage assistance", base_fare=300)
            passenger = User(name="Passenger", email="passenger@example.test", password_hash="test", role="passenger")
            porter = User(
                name="Available porter", email="porter@example.test", password_hash="test",
                role="porter", porter_status="verified", porter_available=True,
                preferred_station_id=station.id,
            )
            other_porter = User(
                name="Other porter", email="other@example.test", password_hash="test",
                role="porter", porter_status="verified", porter_available=True,
                preferred_station_id=other_station.id,
            )
            db.session.add_all([service, passenger, porter, other_porter])
            db.session.flush()
            booking = Booking(
                public_id="OPENREQUEST1", passenger_id=passenger.id, station_id=station.id,
                service_id=service.id, service_at=datetime.now() + timedelta(days=1),
                pickup="Entry gate", destination="Platform 5", bags=2,
                status="requested", estimated_fare=335,
            )
            db.session.add(booking)
            db.session.commit()
            self.booking_id = booking.id
            self.porter_id = porter.id
            self.other_porter_id = other_porter.id

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

    def test_station_porter_sees_new_unassigned_booking(self):
        response = self._client(self.porter_id).get("/dashboard/porter/requests")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"OPENREQUEST1", response.data)
        self.assertIn(b"Accept request", response.data)

    def test_first_eligible_porter_can_accept_and_be_assigned(self):
        response = self._client(self.porter_id).post(
            f"/bookings/{self.booking_id}/status",
            data={"status": "accepted"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/dashboard/", response.headers["Location"])
        with self.app.app_context():
            booking = db.session.get(Booking, self.booking_id)
            self.assertEqual(booking.status, "en_route")
            self.assertEqual(booking.porter_id, self.porter_id)
            events = BookingStatusHistory.query.filter_by(booking_id=self.booking_id).order_by(BookingStatusHistory.id).all()
            self.assertEqual([event.status for event in events], ["accepted", "en_route"])
            self.assertTrue(all(event.actor_id == self.porter_id for event in events))
        dashboard = self._client(self.porter_id).get("/dashboard/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Mark arrived", dashboard.data)

    def test_other_station_porter_cannot_see_or_claim_request(self):
        client = self._client(self.other_porter_id)
        response = client.get("/dashboard/porter/requests")
        self.assertNotIn(b"OPENREQUEST1", response.data)
        rejected = client.post(
            f"/bookings/{self.booking_id}/status",
            data={"status": "accepted"},
        )
        self.assertEqual(rejected.status_code, 403)

    def test_offline_porter_does_not_receive_or_claim_open_request(self):
        with self.app.app_context():
            porter = db.session.get(User, self.porter_id)
            porter.porter_available = False
            db.session.commit()
        client = self._client(self.porter_id)
        response = client.get("/dashboard/porter/requests")
        self.assertNotIn(b"OPENREQUEST1", response.data)
        rejected = client.post(
            f"/bookings/{self.booking_id}/status",
            data={"status": "accepted"},
        )
        self.assertEqual(rejected.status_code, 403)


if __name__ == "__main__":
    unittest.main()
