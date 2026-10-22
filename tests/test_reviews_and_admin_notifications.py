import unittest
from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import Booking, BookingStatusHistory, PorterReview, ServiceType, Station, SupportRequest, User


class ReviewsAndAdminNotificationsConfig:
    TESTING = True
    SECRET_KEY = "reviews-admin-notifications-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SOCKETIO_MESSAGE_QUEUE = None


class ReviewsAndAdminNotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(ReviewsAndAdminNotificationsConfig)

    def setUp(self):
        with self.app.app_context():
            db.drop_all()
            db.create_all()
            station = Station(name="New Delhi", code="NDLS", region="North")
            db.session.add(station)
            db.session.flush()
            service = ServiceType(station_id=station.id, name="Luggage assistance", base_fare=300)
            self.admin = User(name="Admin", email="admin@example.test", password_hash="test", role="admin")
            self.passenger = User(name="Passenger", email="passenger@example.test", password_hash="test", role="passenger")
            self.porter = User(
                name="Porter", email="porter@example.test", password_hash="test", role="porter",
                porter_status="verified", porter_available=True, preferred_station_id=station.id,
            )
            pending_porter = User(
                name="New Porter", email="newporter@example.test", password_hash="test", role="porter",
                porter_status="pending", preferred_station_id=station.id,
            )
            db.session.add_all([service, self.admin, self.passenger, self.porter, pending_porter])
            db.session.flush()
            booking = Booking(
                public_id="REVIEW123", passenger_id=self.passenger.id, porter_id=self.porter.id,
                station_id=station.id, service_id=service.id,
                service_at=datetime.now() + timedelta(days=1), pickup="Platform 5",
                destination="Coach A2", bags=1, status="completed", estimated_fare=300,
            )
            db.session.add(booking)
            db.session.flush()
            db.session.add(BookingStatusHistory(
                booking_id=booking.id, actor_id=self.passenger.id, status="requested", note="Booking created",
            ))
            db.session.add(SupportRequest(
                name="Passenger", email=self.passenger.email, booking_reference=booking.public_id,
                message="Please help with this journey question.", status="open",
            ))
            db.session.commit()
            self.booking_id = booking.id
            self.admin_id = self.admin.id
            self.passenger_id = self.passenger.id
            self.porter_id = self.porter.id

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

    def test_admin_notifications_show_admin_work_not_booking_updates(self):
        admin = self._client(self.admin_id)
        dashboard = admin.get("/dashboard/")
        self.assertIn(b'passenger-nav-count">2<', dashboard.data)

        response = admin.get("/dashboard/admin/notifications")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Please help with this journey question.", response.data)
        self.assertIn(b"New Porter", response.data)
        self.assertNotIn(b"Recent booking activity", response.data)
        self.assertNotIn(b"Requested", response.data)

    def test_passenger_rating_is_visible_to_the_porter(self):
        response = self._client(self.passenger_id).post(
            f"/bookings/{self.booking_id}/review",
            data={"rating": "4", "comment": "Kind and careful."},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(PorterReview.query.filter_by(booking_id=self.booking_id).count(), 1)

        reviews = self._client(self.porter_id).get("/dashboard/porter/reviews")
        self.assertEqual(reviews.status_code, 200)
        self.assertIn(b"4.0", reviews.data)
        self.assertIn(b"Kind and careful.", reviews.data)

    def test_porter_can_find_and_submit_support_requests(self):
        porter = self._client(self.porter_id)
        dashboard = porter.get("/dashboard/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b'>Support</span>', dashboard.data)
        self.assertIn(b'href="/support"', dashboard.data)

        support_page = porter.get("/support")
        self.assertEqual(support_page.status_code, 200)
        self.assertIn(b"Assignment help", support_page.data)
        self.assertIn(b"Profile and verification", support_page.data)

        response = porter.post("/support", data={
            "name": "Porter",
            "email": "porter@example.com",
            "booking_reference": "REVIEW123",
            "message": "I need help with my assigned job.",
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            ticket = SupportRequest.query.filter_by(email="porter@example.com").one()
            self.assertEqual(ticket.booking_reference, "REVIEW123")
            self.assertEqual(ticket.message, "I need help with my assigned job.")

    def test_resolved_support_ticket_notifies_its_passenger_or_porter(self):
        with self.app.app_context():
            porter_ticket = SupportRequest(
                name="Porter", email="porter@example.test", message="Need help with a job.",
            )
            passenger_ticket = SupportRequest(
                name="Passenger", email="passenger@example.test", message="Need help with a booking.",
            )
            db.session.add_all([porter_ticket, passenger_ticket])
            db.session.commit()
            porter_ticket_id = porter_ticket.id
            passenger_ticket_id = passenger_ticket.id

        admin = self._client(self.admin_id)
        for ticket_id in (porter_ticket_id, passenger_ticket_id):
            response = admin.post(
                f"/admin/support-requests/{ticket_id}/status", data={"status": "closed"},
            )
            self.assertEqual(response.status_code, 302)

        passenger = self._client(self.passenger_id)
        passenger_dashboard = passenger.get("/dashboard/")
        self.assertIn(b'passenger-notice-count', passenger_dashboard.data)
        passenger_updates = passenger.get("/dashboard/notifications")
        self.assertIn(b"Support ticket resolved", passenger_updates.data)
        self.assertIn(f"TKT-{passenger_ticket_id:04d}".encode(), passenger_updates.data)

        porter = self._client(self.porter_id)
        porter_dashboard = porter.get("/dashboard/")
        self.assertIn(b'passenger-notice-count', porter_dashboard.data)
        porter_updates = porter.get("/dashboard/porter/notifications")
        self.assertIn(b"Support ticket resolved", porter_updates.data)
        self.assertIn(f"TKT-{porter_ticket_id:04d}".encode(), porter_updates.data)


if __name__ == "__main__":
    unittest.main()
