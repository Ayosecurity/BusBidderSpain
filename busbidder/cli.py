"""Command-line interface for BusBidder Spain.

Run ``python -m busbidder --help`` from the project root.
Without a sub-command the program starts a guided interactive session.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from datetime import date

from . import display
from .booking import BookingManager
from .config import close_logging, load_config, setup_logging
from .exceptions import BusBidderError
from .explain import explain_top
from .filters import apply_constraints
from .loader import load_marketplace
from .models import TravellerRequest
from .profiles import load_profiles, validate_request
from .ranking import rank_offers, sensitivity
from .scoring import CRITERIA, PERIODS, Weights

log = logging.getLogger(__name__)


class App:
    """Wires the modules together; one instance per program run."""

    def __init__(self, config_path: str | None = None):
        self.cfg = load_config(config_path)
        setup_logging(self.cfg.path("log_file"))
        log.info("=== BusBidder Spain started ===")
        self.market = load_marketplace(self.cfg)
        self.profiles = load_profiles(self.cfg.path("profiles_file"))
        self.bookings = BookingManager(self.cfg.path("bookings_file"))
        self.bookings.apply_to(self.market.offers)
        self.settings = self.cfg.scoring

    def default_weights(self) -> Weights:
        return Weights.create(self.cfg["default_weights"])

    def search(self, request: TravellerRequest, weights: Weights):
        validate_request(request)
        filtered = apply_constraints(self.market.offers, request)
        ranked = rank_offers(filtered.accepted, request, weights, self.settings)
        return filtered, ranked

    def show_search(self, request, weights, top=10, out=print):
        filtered, ranked = self.search(request, weights)
        out(display.request_summary(request, weights))
        for w in weights.dominance_warnings(self.settings.get("dominance_warning", 0.6)):
            out(f"WARNING: {w}")
        out("")
        out(display.filter_summary(filtered))
        if not ranked:
            out("\nNo acceptable offers. Try relaxing a hard constraint "
                "(budget, transfers or fare type) or widening the dates.")
            return ranked
        out("")
        out(display.ranking_table(ranked, weights, top))
        if top and len(ranked) > top:
            out(f"(showing top {top} of {len(ranked)}; use --top 0 to show all)")
        out("\nRECOMMENDATION\n" + explain_top(ranked, weights))
        return ranked


# ------------------------------------------------------------- arguments --
def _date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a date (use YYYY-MM-DD)") from None


def add_request_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("trip (hard constraints)")
    g.add_argument("--to", dest="destination", required=True, help="destination city, e.g. Malaga")
    g.add_argument("--from-date", type=_date, required=True, help="first travel date YYYY-MM-DD")
    g.add_argument("--to-date", type=_date, help="last travel date (default: same as --from-date)")
    g.add_argument("--budget", type=float, help="maximum price per ticket in EUR")
    g.add_argument("--seats", type=int, default=1)
    g.add_argument("--max-transfers", type=int)
    g.add_argument("--max-duration", type=int, help="maximum journey time in minutes")
    g.add_argument("--luggage", type=int, help="minimum luggage allowance in kg")
    g.add_argument("--changeable", action="store_true", help="require a changeable ticket")
    g.add_argument("--refundable", action="store_true", help="require a refundable ticket")
    s = p.add_argument_group("preferences (soft, used for ranking)")
    s.add_argument("--period", default="any", choices=["any", *PERIODS],
                   help="preferred departure period")
    s.add_argument("--weights", help="e.g. price=40,duration=25,departure=15,flexibility=20 "
                                     f"(criteria: {', '.join(CRITERIA.names())})")
    s.add_argument("--normalise-weights", action="store_true",
                   help="rescale weights that do not sum to 1.0/100")
    s.add_argument("--profile", help="use a traveller profile's weights, period and constraints")


def request_from_args(app: App, a) -> tuple[TravellerRequest, Weights]:
    dest = app.market.resolve_destination(a.destination)
    if dest is None:
        raise BusBidderError(f"Unknown destination '{a.destination}'. Choose from: "
                             + ", ".join(sorted(app.market.destination_names())))
    req = TravellerRequest(dest, a.from_date, a.to_date or a.from_date, a.budget, a.seats,
                           a.max_transfers, a.max_duration, a.luggage, a.changeable,
                           a.refundable, a.period)
    if a.profile:
        if a.profile not in app.profiles:
            raise BusBidderError(f"Unknown profile '{a.profile}'. Choose from: "
                                 + ", ".join(app.profiles))
        prof = app.profiles[a.profile]
        req = prof.apply(req)
        weights = prof.weights
    else:
        weights = app.default_weights()
    if a.weights:
        weights = Weights.parse(a.weights, a.normalise_weights)
    return req, weights


# -------------------------------------------------------------- commands --
def cmd_validate(app: App, a) -> None:
    print(display.load_summary(app.market.report))
    print(f"\nDetails written to {app.cfg.path('rejected_file')} and "
          f"{app.cfg.path('review_file')}; log: {app.cfg.path('log_file')}")


def cmd_search(app: App, a) -> None:
    req, weights = request_from_args(app, a)
    ranked = app.show_search(req, weights, a.top or None)
    if a.book and ranked:
        interactive_book(app, ranked, req.seats)


def cmd_compare(app: App, a) -> None:
    base, _ = request_from_args(app, a)
    names = a.profiles.split(",") if a.profiles else list(app.profiles)
    summary = []
    for name in names:
        prof = app.profiles.get(name)
        if prof is None:
            raise BusBidderError(f"Unknown profile '{name}'")
        req = prof.apply(base)
        print("\n" + "#" * 78 + f"\nPROFILE: {name} - {prof.description}\n" + "#" * 78)
        ranked = app.show_search(req, prof.weights, a.top)
        if ranked:
            o = ranked[0].offer
            summary.append([name, o.offer_id, o.company.name, f"{o.departure:%H:%M}",
                            o.duration_text, f"{o.price_eur:.2f}", o.fare.label,
                            f"{ranked[0].total:.1f}", len(ranked)])
        else:
            summary.append([name, "-", "-", "-", "-", "-", "-", "-", 0])
    print("\n" + "=" * 78 + "\nSUMMARY: top offer per profile (same offers, same trip)\n")
    print(display.table(["Profile", "Top offer", "Company", "Dep", "Time", "EUR", "Fare",
                         "Score", "#OK"], summary, "lllllrlrr"))


def cmd_sensitivity(app: App, a) -> None:
    req, weights = request_from_args(app, a)
    filtered, ranked = app.search(req, weights)
    if not ranked:
        print("No acceptable offers.")
        return
    print(f"Baseline winner: {ranked[0].offer.offer_id} ({ranked[0].total:.1f}) "
          f"with weights {weights.describe()}\n")
    rows = [[n, f"{d:+.0%}", top, "CHANGES" if changed else "same"]
            for n, d, top, changed in sensitivity(filtered.accepted, req, weights,
                                                  app.settings, a.delta)]
    print(display.table(["Criterion", "Shift", "New winner", "Result"], rows))


def cmd_book(app: App, a) -> None:
    offer = app.market.find_offer(a.offer)
    if offer is None:
        raise BusBidderError(f"No valid offer with id {a.offer}")
    b = app.bookings.book(offer, a.name, a.seats)
    print(display.booking_confirmation(b))


def cmd_bookings(app: App, a) -> None:
    rows = [[b.reference, b.status, b.traveller_name, b.destination, b.travel_date,
             b.departure, b.company, b.seats, f"{b.total_price:.2f}"]
            for b in app.bookings.bookings.values()]
    print(display.table(["Ref", "Status", "Traveller", "To", "Date", "Dep", "Company",
                         "Seats", "EUR"], rows, "lllllllrr") if rows else "No bookings yet.")


def cmd_cancel(app: App, a) -> None:
    b = app.bookings.get(a.reference)
    b = app.bookings.cancel(b.reference, app.market.find_offer(b.offer_id))
    print(f"{b.reference} cancelled. Simulated refund: EUR {b.refund_eur:.2f}; "
          f"travel voucher: EUR {b.voucher_eur:.2f}.")


# ----------------------------------------------------------- interactive --
def ask(prompt: str, default: str = "") -> str:
    text = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return text or default


def interactive_book(app: App, ranked, seats: int) -> None:
    while True:
        choice = ask("\nBook an offer? Enter its rank number, or press Enter to skip", "")
        if not choice:
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(ranked):
            print(f"Please enter a number between 1 and {len(ranked)}.")
            continue
        offer = ranked[int(choice) - 1].offer
        name = ask("Traveller name")
        try:
            b = app.bookings.book(offer, name, seats)
        except BusBidderError as exc:
            print(f"Booking failed: {exc}")
            continue
        print(display.booking_confirmation(b))
        return


def cmd_interactive(app: App, a) -> None:
    print("Welcome to BusBidder Spain - all journeys depart from Madrid.\n")
    print("Destinations: " + ", ".join(sorted(app.market.destination_names())))
    while True:
        try:
            dest = app.market.resolve_destination(ask("Destination", "Malaga"))
            if not dest:
                print("Unknown destination, please try again.")
                continue
            d1 = date.fromisoformat(ask("First travel date", "2026-07-12"))
            d2 = date.fromisoformat(ask("Last travel date", "2026-07-14"))
            budget = ask("Maximum price per ticket in EUR (blank = none)", "50")
            seats = int(ask("Seats", "1"))
            mt = ask("Maximum transfers (blank = any)", "1")
            ch = ask("Changeable ticket required? (y/n)", "y").lower().startswith("y")
            rf = ask("Refundable ticket required? (y/n)", "n").lower().startswith("y")
            period = ask(f"Preferred departure ({'/'.join(['any', *PERIODS])})", "morning")
            print("Profiles: " + ", ".join(f"{k} ({p.description})"
                                           for k, p in app.profiles.items()))
            prof = ask("Profile name, or 'custom' to type weights, or Enter for default", "")
            req = TravellerRequest(dest, d1, d2, float(budget) if budget else None, seats,
                                   int(mt) if mt else None, None, None, ch, rf, period)
            weights = app.default_weights()
            if prof == "custom":
                weights = Weights.parse(ask("Weights", "price=40,duration=25,departure=15,"
                                                       "flexibility=20"), normalise=True)
            elif prof:
                if prof not in app.profiles:
                    print("Unknown profile; using default weights.")
                else:
                    p = app.profiles[prof]
                    req = p.apply(req)
                    req = replace(req, preferred_period=period)  # user's own choice wins
                    weights = p.weights
            print()
            ranked = app.show_search(req, weights, 10)
            if ranked:
                interactive_book(app, ranked, req.seats)
        except ValueError as exc:
            print(f"Invalid input: {exc}")
        except BusBidderError as exc:
            print(f"Error: {exc}")
        if ask("\nNew search? (y/n)", "n").lower() != "y":
            print("Goodbye.")
            return


# ------------------------------------------------------------------ main --
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="busbidder",
                                description="BusBidder Spain - filter and rank bus offers from Madrid.")
    p.add_argument("--config", help="path to config.json (default: project root)")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("validate", help="load the data and report rejected/corrected records")

    s = sub.add_parser("search", help="filter and rank offers for one traveller request")
    add_request_args(s)
    s.add_argument("--top", type=int, default=10, help="rows to show (0 = all)")
    s.add_argument("--book", action="store_true", help="offer to book after the ranking")

    c = sub.add_parser("compare", help="run several traveller profiles on the same trip")
    add_request_args(c)
    c.add_argument("--profiles", help="comma-separated profile names (default: all)")
    c.add_argument("--top", type=int, default=5)

    se = sub.add_parser("sensitivity", help="check if the winner changes when weights shift")
    add_request_args(se)
    se.add_argument("--delta", type=float, default=0.10)

    b = sub.add_parser("book", help="book an offer directly by id")
    b.add_argument("--offer", required=True)
    b.add_argument("--name", required=True)
    b.add_argument("--seats", type=int, default=1)

    sub.add_parser("bookings", help="list saved bookings")
    ca = sub.add_parser("cancel", help="cancel a booking (simulated refund/voucher)")
    ca.add_argument("reference")
    sub.add_parser("interactive", help="guided session (default)")
    return p


COMMANDS = {"validate": cmd_validate, "search": cmd_search, "compare": cmd_compare,
            "sensitivity": cmd_sensitivity, "book": cmd_book, "bookings": cmd_bookings,
            "cancel": cmd_cancel, "interactive": cmd_interactive, None: cmd_interactive}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        app = App(args.config)
        COMMANDS[args.command](app, args)
    except BusBidderError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        log.info("Command failed: %s", exc)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted.")
        return 130
    finally:
        close_logging()        # release the log file (required on Windows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
