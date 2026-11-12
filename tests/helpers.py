"""Shared test fixtures: small hand-made objects so tests never depend on the generated data."""

from datetime import date, time

from busbidder.models import Company, Destination, FareConditions, Offer, TravellerRequest

SOL = Company("SOL", "SolRuta", "Low-cost")
CAM = Company("CAM", "Camino Express", "Fast")
MALAGA = Destination("Malaga", "Andalusia", 530, True)
TOLEDO = Destination("Toledo", "Castile-La Mancha", 75, False)

COMPANIES = {"SOL": SOL, "CAM": CAM}
DESTINATIONS = {"malaga": ("AGP", MALAGA), "toledo": ("TOL", TOLEDO)}


def make_offer(oid="SOL-AGP-20260712-0900", company=SOL, dest=MALAGA, day=date(2026, 7, 12),
               dep=time(9, 0), arr=time(15, 0), offset=0, price=30.0, transfers=0,
               changeable=True, refundable=False, luggage=20, seats=10, rating=4.0, co2=10.0):
    return Offer(oid, company, dest, day, dep, arr, offset, price, transfers,
                 FareConditions(changeable, refundable, luggage), seats, rating, co2)


def make_request(**kw):
    base = dict(destination="Malaga", date_from=date(2026, 7, 12), date_to=date(2026, 7, 14))
    base.update(kw)
    return TravellerRequest(**base)


def csv_row(**overrides):
    row = {"offer_id": "SOL-AGP-20260712-0900", "company_id": "SOL", "destination": "Malaga",
           "travel_date": "2026-07-12", "departure": "09:00", "arrival": "15:00",
           "arrival_day_offset": "0", "price_eur": "30.00", "transfers": "0",
           "luggage_kg": "20", "changeable": "yes", "refundable": "no",
           "seats_available": "10", "rating": "4.0", "co2_kg": "10.0"}
    row.update(overrides)
    return row
