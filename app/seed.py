from .extensions import db
from .models import Station, ServiceType

STATIONS = [
    ("New Delhi", "NDLS", "North"), ("Mumbai CSMT", "CSMT", "West"),
    ("Lucknow", "LKO", "North"), ("Jaipur", "JP", "North"),
    ("Bengaluru City", "SBC", "South"), ("Chennai Central", "MAS", "South"),
    ("Howrah", "HWH", "East"), ("Hyderabad Deccan", "HYB", "South"),
]
SERVICES = ["Platform Transfer", "Entry to Platform", "Train to Exit", "Platform to Platform", "Full Station Assistance", "Special Assistance", "Luggage Support"]


def seed_development_data():
    for name, code, region in STATIONS:
        station = Station.query.filter_by(code=code).first()
        if not station:
            station = Station(name=name, code=code, region=region)
            db.session.add(station)
            db.session.flush()
        if not station.services:
            for i, label in enumerate(SERVICES):
                db.session.add(ServiceType(station_id=station.id, name=label, description="Verified porter assistance", base_fare=250 + (i * 50)))
    db.session.commit()
