"""Generate the simulated BusBidder Spain dataset (reproducible: fixed seed).

Run from the project root:
    python scripts/generate_data.py

Writes data/companies.csv, data/destinations.csv and data/offers.csv.
The last rows of offers.csv are *deliberately faulty* test records used to
demonstrate validation (see README, section "Dataset").
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 4420
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

COMPANIES = [
    # id, name, profile
    ("SOL", "SolRuta", "Low-cost daytime services"),
    ("CAM", "Camino Express", "Fast direct connections between major cities"),
    ("COS", "CostaLink", "Strong coverage of coastal destinations"),
    ("VER", "VerdeBus", "Environment-focused services and modern vehicles"),
    ("NOC", "NocheVia", "Overnight and late-evening services"),
]

DESTINATIONS = [
    # code, name, region, road distance from Madrid (approx. km), coastal
    ("BCN", "Barcelona", "Catalonia", 620, True),
    ("VLC", "Valencia", "Valencian Community", 360, True),
    ("SVQ", "Seville", "Andalusia", 530, False),
    ("AGP", "Malaga", "Andalusia", 530, True),
    ("GRX", "Granada", "Andalusia", 420, False),
    ("ODB", "Cordoba", "Andalusia", 400, False),
    ("BIO", "Bilbao", "Basque Country", 400, True),
    ("EAS", "San Sebastian", "Basque Country", 450, True),
    ("ZAZ", "Zaragoza", "Aragon", 320, False),
    ("ALC", "Alicante", "Valencian Community", 420, True),
    ("MJV", "Murcia", "Region of Murcia", 400, False),
    ("SLM", "Salamanca", "Castile and Leon", 215, False),
    ("TOL", "Toledo", "Castile-La Mancha", 75, False),
    ("SCQ", "Santiago de Compostela", "Galicia", 600, False),
    ("CAD", "Cadiz", "Andalusia", 650, True),
]
MAJOR = {"Barcelona", "Valencia", "Seville", "Malaga", "Bilbao", "Zaragoza"}

# Company behaviour: EUR per km, speed factor (1.0 = average), departure times,
# P(changeable), P(refundable), luggage kg, rating range, CO2 factor
PROFILES = {
    "SOL": dict(rate=0.050, speed=1.15, times=["07:00", "08:30", "11:15", "13:45", "16:30"],
                p_change=0.30, p_refund=0.05, luggage=20, rating=(3.3, 4.0), co2=1.0),
    "CAM": dict(rate=0.095, speed=0.88, times=["07:30", "09:00", "12:00", "15:00", "18:30"],
                p_change=0.85, p_refund=0.45, luggage=25, rating=(4.2, 4.8), co2=1.0),
    "COS": dict(rate=0.070, speed=1.00, times=["06:45", "09:30", "13:15", "17:00", "20:00"],
                p_change=0.60, p_refund=0.20, luggage=30, rating=(3.8, 4.4), co2=1.0),
    "VER": dict(rate=0.080, speed=1.02, times=["08:00", "10:30", "14:00", "17:30"],
                p_change=0.70, p_refund=0.50, luggage=23, rating=(4.0, 4.6), co2=0.45),
    "NOC": dict(rate=0.055, speed=1.20, times=["21:00", "22:15", "23:30"],
                p_change=0.50, p_refund=0.15, luggage=25, rating=(3.4, 4.1), co2=0.95),
}

START = date(2026, 7, 10)
DAYS = 7

HEADER = ["offer_id", "company_id", "destination", "travel_date", "departure", "arrival",
          "arrival_day_offset", "price_eur", "transfers", "luggage_kg", "changeable",
          "refundable", "seats_available", "rating", "co2_kg"]


def transfers_for(cid: str, dest: tuple, rnd: random.Random) -> int:
    _, name, _, km, coastal = dest
    if cid == "CAM":
        return 0 if name in MAJOR else (1 if rnd.random() < 0.3 else 0)
    if cid == "COS":
        return 0 if coastal else rnd.choice([1, 1, 2])
    if cid == "SOL":
        return 1 if km > 450 and rnd.random() < 0.6 else 0
    if cid == "VER":
        return 1 if rnd.random() < 0.25 else 0
    return 1 if km > 500 and rnd.random() < 0.4 else 0   # NOC


def make_offer(cid: str, dest: tuple, day: date, dep: str, rnd: random.Random) -> list:
    p = PROFILES[cid]
    code, name, _, km, _ = dest
    transfers = transfers_for(cid, dest, rnd)
    minutes = (km / 78 * 60 + 15) * p["speed"] * rnd.uniform(0.95, 1.08) + 40 * transfers
    minutes = int(round(minutes / 5) * 5)
    h, m = map(int, dep.split(":"))
    end = h * 60 + m + minutes
    offset, end = divmod(end, 24 * 60)
    arrival = f"{end // 60:02d}:{end % 60:02d}"

    changeable = rnd.random() < p["p_change"]
    refundable = rnd.random() < p["p_refund"]
    price = 4 + km * p["rate"]
    price *= 1.15 if day.weekday() >= 4 else 1.0           # Fri-Sun demand
    price *= 1.10 if 7 <= h <= 9 and cid != "NOC" else 1.0  # morning peak
    price *= 1.08 if changeable else 1.0
    price *= 1.15 if refundable else 1.0
    price *= 0.92 if transfers else 1.0
    price *= rnd.uniform(0.88, 1.12)
    price = max(3.0, round(price * 2) / 2 - 0.01)

    seats = 0 if rnd.random() < 0.04 else rnd.randint(1, 49)
    rating = "" if rnd.random() < 0.02 else f"{rnd.uniform(*p['rating']):.1f}"
    co2 = km * 0.028 * p["co2"] * (1.05 if transfers else 1.0)
    co2_txt = "" if (cid == "SOL" and rnd.random() < 0.3) else f"{co2:.1f}"

    oid = f"{cid}-{code}-{day:%Y%m%d}-{dep.replace(':', '')}"
    return [oid, cid, name, day.isoformat(), dep, arrival, offset, f"{price:.2f}", transfers,
            p["luggage"], "yes" if changeable else "no", "yes" if refundable else "no",
            seats, rating, co2_txt]


FAULTY_ROWS = [
    # --- impossible / inconsistent -> REJECTED -----------------------------
    ["SOL-AGP-20260712-0915", "SOL", "Malaga", "2026-07-12", "09:15", "16:40", 0, "-12.50", 0, 20, "no", "no", 20, "3.8", "14.8"],
    ["CAM-XXX-20260712-1000", "CAM", "Atlantis", "2026-07-12", "10:00", "15:00", 0, "35.00", 0, 25, "yes", "no", 12, "4.5", "10.0"],
    ["COS-AGP-20260732-0800", "COS", "Malaga", "2026-07-32", "08:00", "14:00", 0, "29.00", 0, 30, "yes", "no", 10, "4.0", "14.8"],
    ["VER-AGP-20260713-1500", "VER", "Malaga", "2026-07-13", "15:00", "11:30", 0, "39.00", 0, 23, "yes", "yes", 8, "4.3", "6.7"],
    ["CAM-AGP-20260713-1100", "CAM", "Malaga", "2026-07-13", "11:00", "16:00", 0, "45.00", 0, 25, "yes", "no", 9, "7.5", "14.8"],
    ["SOL-AGP-20260714-1015", "SOL", "Malaga", "2026-07-14", "10:15", "17:45", 0, "21.00", 1, 20, "no", "no", -3, "3.6", "15.5"],
    ["NOC-AGP-20260714-2200", "NOC", "Malaga", "2026-07-14", "22:00", "05:30", 1, "", 0, 25, "yes", "no", 14, "3.9", "14.1"],
    ["badid-123", "COS", "Valencia", "2026-07-12", "09:00", "13:30", 0, "26.00", 0, 30, "no", "no", 11, "4.1", "10.1"],
    ["XYZ-AGP-20260712-0900", "XYZ", "Malaga", "2026-07-12", "09:00", "15:00", 0, "25.00", 0, 20, "no", "no", 5, "4.0", "14.8"],
    ["COS-VLC-20260712-0945", "COS", "Valencia", "2026-07-12", "09:45", "14:00", 0, "two", 0, 30, "no", "no", 11, "4.1", "10.1"],
    ["VER-SVQ-20260712-1400", "VER", "Seville", "2026-07-12", "14:00", "20:30", 0, "41.00", "two", 23, "yes", "no", 11, "4.4", "6.7"],
    # --- formatting problems that can be safely CORRECTED ------------------
    ["COS-AGP-20260713-0905", "COS", " málaga ", "2026-07-13", "09:05", "16:30", 0, "47,90", 0, 30, "Y", "n", 17, "4.2", "14.8"],
    ["VER-AGP-20260712-0710", "ver", "MALAGA", "2026-07-12", "07:10", "13:35", 0, "44.49", 0, 23, "TRUE", "false", 6, "4.4", "6.7"],
    # --- plausible but suspicious -> kept, flagged for REVIEW --------------
    ["CAM-TOL-20260712-0815", "CAM", "Toledo", "2026-07-12", "08:15", "09:20", 0, "189.00", 0, 25, "yes", "yes", 30, "4.6", "2.1"],
]


def main() -> None:
    rnd = random.Random(SEED)
    DATA.mkdir(exist_ok=True)
    with open(DATA / "companies.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["company_id", "name", "profile"])
        w.writerows(COMPANIES)
    with open(DATA / "destinations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "region", "distance_km", "coastal"])
        w.writerows([(c, n, r, km, "yes" if co else "no") for c, n, r, km, co in DESTINATIONS])

    rows = []
    for cid, *_ in COMPANIES:
        times = PROFILES[cid]["times"]
        for dest in DESTINATIONS:
            for d in range(DAYS):
                day = START + timedelta(days=d)
                k = rnd.randint(1, min(3, len(times)))
                for dep in sorted(rnd.sample(times, k)):
                    rows.append(make_offer(cid, dest, day, dep, rnd))
    # A duplicate of an existing id -> must be rejected as DUPLICATE_ID
    dup = list(rows[10])
    dup[7] = "1.00"
    with open(DATA / "offers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
        w.writerows(FAULTY_ROWS)
        w.writerow(dup)
    print(f"Wrote {len(rows)} generated offers + {len(FAULTY_ROWS) + 1} test records to {DATA}")


if __name__ == "__main__":
    main()
