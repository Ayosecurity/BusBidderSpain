"""Generate a short, data-driven explanation for the top-ranked offer."""

from __future__ import annotations

from statistics import mean

from .models import RankedOffer
from .scoring import CRITERIA, Weights

STRONG, WEAK = 70.0, 40.0
NEAR_TIE = 1.0          # points; below this the order is too fragile to call


def _describe(name: str, r: RankedOffer, ranked: list[RankedOffer]) -> str:
    o = r.offer
    if name == "price":
        cheapest = min(x.offer.price_eur for x in ranked)
        if o.price_eur == cheapest:
            return f"the lowest price (EUR {o.price_eur:.2f})"
        return f"price EUR {o.price_eur:.2f} (cheapest acceptable: EUR {cheapest:.2f})"
    if name == "duration":
        fastest = min(x.offer.duration_min for x in ranked)
        if o.duration_min == fastest:
            return f"the shortest journey ({o.duration_text})"
        return f"journey time {o.duration_text} (fastest acceptable: " \
               f"{min(ranked, key=lambda x: x.offer.duration_min).offer.duration_text})"
    if name == "departure":
        return f"departure at {o.departure:%H:%M}"
    if name == "flexibility":
        return f"a {o.fare.label} fare"
    if name == "transfers":
        return "a direct route" if o.transfers == 0 else f"{o.transfers} transfer(s)"
    if name == "rating":
        return "no customer rating available" if o.rating is None \
            else f"customer rating {o.rating:.1f}/5"
    if name == "co2":
        return "no CO2 estimate available" if o.co2_kg is None \
            else f"estimated {o.co2_kg:.1f} kg CO2 per passenger"
    return CRITERIA[name]["label"]


def explain_top(ranked: list[RankedOffer], weights: Weights) -> str:
    if not ranked:
        return "No offer satisfies all mandatory constraints."
    top = ranked[0]
    o = top.offer
    avg = {n: mean(r.criterion_scores[n] for r in ranked) for n in weights}

    strengths = [n for n in weights
                 if top.criterion_scores[n] >= STRONG and top.criterion_scores[n] >= avg[n]]
    weaknesses = [n for n in weights
                  if top.criterion_scores[n] <= WEAK or top.criterion_scores[n] < avg[n] - 10]
    strengths.sort(key=lambda n: -top.contributions[n])

    lines = [f"{o.company.name} {o.departure:%H:%M} on {o.travel_date:%d %b} ranks first "
             f"with {top.total:.1f}/100."]
    if strengths:
        lines.append("Advantages: " + "; ".join(_describe(n, top, ranked) for n in strengths) + ".")
    if weaknesses:
        lines.append("Disadvantages: " + "; ".join(_describe(n, top, ranked) for n in weaknesses) + ".")
    else:
        weakest = min(weights, key=lambda n: top.criterion_scores[n])
        lines.append(f"No major disadvantage; weakest point: {_describe(weakest, top, ranked)} "
                     f"({top.criterion_scores[weakest]:.0f}/100 on "
                     f"{CRITERIA[weakest]['label'].lower()}).")
    if top.missing:
        lines.append("Note: missing data for " + ", ".join(top.missing)
                     + " was given a neutral score of 50.")

    if len(ranked) > 1:
        second = ranked[1]
        gap = top.total - second.total
        diffs = sorted(((top.contributions[n] - second.contributions[n], n) for n in weights),
                       reverse=True)
        decisive = [CRITERIA[n]["label"].lower() for d, n in diffs if d > 0.5][:2]
        if gap <= 0.05:
            lines.append(f"It is effectively tied with {second.offer.company.name} "
                         f"{second.offer.departure:%H:%M}; the tie-break is the lower price.")
        elif gap < NEAR_TIE:
            lines.append(f"It is practically tied with {second.offer.company.name} "
                         f"{second.offer.departure:%H:%M} (gap {gap:.1f} points): a small change "
                         f"in the weights could reverse the order, so compare both.")
        else:
            reason = f", mainly thanks to {' and '.join(decisive)}" if decisive else ""
            lines.append(f"It leads {second.offer.company.name} "
                         f"{second.offer.departure:%H:%M} by {gap:.1f} points{reason}.")

    lines.append("This is the best match only under the chosen constraints and weights "
                 f"({weights.describe()}), not an objectively best ticket.")
    return "\n".join(lines)
