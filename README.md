# BusBidder Spain

A modular Python command-line application that filters and ranks competing bus offers from
Madrid to 15 Spanish destinations, using a transparent weighted multi-criteria model, and
then lets you make a simulated booking. Final project for ACIT4420, *Problem-solving with
scripting*, at OsloMet in 2026.

## Requirements

* **Python 3.10 or newer** (developed and tested with Python 3.13)
* **No third-party libraries.** Only the standard library is used (`csv`, `json`, `re`,
  `dataclasses`, `argparse`, `logging`, `unittest`, ...). `requirements.txt` is therefore empty,
  apart from an optional `pytest` line.

## Quick start

Run all commands from the project root, which is the folder that contains this README.

```bash
# 1. Validate the dataset and see which records were rejected, corrected or flagged
python -m busbidder validate

# 2. The example request from the specification
python -m busbidder search --to Malaga --from-date 2026-07-12 --to-date 2026-07-14 --budget 50 --period morning --max-transfers 1 --changeable

# 3. Same trip, four traveller profiles
python -m busbidder compare --to Malaga --from-date 2026-07-12 --to-date 2026-07-14 --budget 50 --max-transfers 1

# 4. Guided interactive session (search, then book)
python -m busbidder
```

On Windows, use `py` instead of `python` if `python` is not on your PATH.

**Entry point:** `python -m busbidder` (this runs `busbidder/__main__.py`, which calls `busbidder/cli.py:main`).

## Commands

| Command | Purpose |
|---|---|
| `python -m busbidder` / `interactive` | Guided session: asks for the trip, shows the ranking and offers to book |
| `validate` | Loads the data and prints rejected, corrected and review records |
| `search <trip options>` | Filters and ranks the offers for one request (`--book` lets you book afterwards, `--top 0` shows all) |
| `compare <trip options>` | Runs every traveller profile (or `--profiles a,b`) on the same trip |
| `sensitivity <trip options>` | Moves each weight ±10 percentage points and checks whether the winner changes |
| `book --offer ID --name "Name" [--seats N]` | Books an offer directly |
| `bookings` | Lists saved bookings |
| `cancel BBS-XXXXXX` | Cancels a booking. A refundable fare is refunded; a changeable-only fare becomes a voucher minus a EUR 5 fee |

**Trip options (hard constraints):** `--to CITY --from-date YYYY-MM-DD [--to-date ...]
[--budget EUR] [--seats N] [--max-transfers N] [--max-duration MIN] [--luggage KG]
[--changeable] [--refundable]`

**Preferences (soft, used only for ranking):** `--period any|morning|afternoon|evening|night`,
`--weights price=40,duration=25,departure=15,flexibility=20` (fractions or percentages; add
`--normalise-weights` to rescale weights that do not add up to the total), or `--profile budget|business|flex_tourist|eco`.

The available criteria are `price`, `duration`, `departure`, `flexibility`, `transfers`, `rating` and `co2`.

Run `python -m busbidder search --help` to see every option.

## Tests

```bash
python -m unittest discover -s tests      # standard library, no installation needed
# or, if pytest is installed:
python -m pytest
```

There are 75 tests covering normal cases, invalid values, missing data and boundary values
(for example budget equal to price, the first and last day of the window, ratings of exactly
1.0 and 5.0, arrival equal to departure, and overbooking). They also include end-to-end CLI tests.

## Reproducing the report results

```bash
python scripts/generate_data.py       # recreates data/*.csv (fixed seed 4420; already included)
python scripts/reproduce_outputs.py   # writes outputs/01-08_*.txt used in the report
```

`reproduce_outputs.py` uses a temporary bookings file, so it never changes your real bookings.

## Files and folders

```
busbidder/            application package
  cli.py              command-line interface, App class wiring the modules together
  models.py           dataclasses: Company, Destination, FareConditions, Offer, TravellerRequest, RankedOffer, Booking
  validation.py       field parsers, regular expressions, reject/correct/review policy
  loader.py           reads CSV files, validates every row, writes rejected/review files
  filters.py          hard constraints (decorator registry)
  scoring.py          criteria (decorator registry), normalisation, Weights
  ranking.py          weighted ranking, deterministic tie-break, sensitivity analysis
  explain.py          data-driven explanation of the top offer
  booking.py          simulated booking, BBS-XXXXXX references, atomic JSON persistence
  profiles.py         traveller profiles + request validation
  display.py          ASCII tables (safe in the Windows console)
  registry.py         Registry class + @logged decorator (metaprogramming)
  exceptions.py       custom exception hierarchy
config.json           paths and scoring settings
data/companies.csv    5 companies
data/destinations.csv 15 destinations
data/offers.csv       1,033 generated offers + 15 deliberately faulty test records
data/profiles.json    budget, business, flex_tourist, eco
data/state/           bookings.json (created at the first booking)
logs/busbidder.log    log of loading, validation, filtering, ranking and booking events
outputs/              rejected/review records + report evidence (01-08_*.txt)
docs/architecture.*   architecture diagram (Mermaid source + PNG)
tests/                unittest test suite
scripts/              data generator and output reproduction
```

## Dataset

All data is fictional. It covers 5 companies × 15 destinations, departures from 10 to 16 July
2026 and 1 to 3 departures per company, destination and day. Each company has its own price
level, speed, departure times, fare flexibility, rating range and CO2 factor
(see `scripts/generate_data.py`). The last 15 rows of `offers.csv` are hand-made test
records:

* **11 rejected:** negative price, unknown destination, 32 July, arrival before departure,
  rating 7.5, -3 seats, missing price, malformed ID, unknown company, a non-numeric price, and non-numeric transfers.
* **1 duplicate ID**, also rejected.
* **2 corrected:** `" málaga "`, `"34,90"`, `"Y"`, `"TRUE"` and the lower-case company code `"ver"`.
* **1 flagged for review:** a 189 EUR Toledo ticket, which is more than three times the median.

## Notes

* No real payment information is ever requested. Payment status is always `SIMULATED_PAID`.
* Delete `data/state/bookings.json` to reset all bookings and seat capacity.
