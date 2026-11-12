"""Rank filtered offers with the weighted scoring model, deterministically."""

from __future__ import annotations

import logging
from typing import Any

from .models import Offer, RankedOffer, TravellerRequest
from .registry import logged
from .scoring import CRITERIA, Weights, normalise_relative

log = logging.getLogger(__name__)


def score_offers(offers: list[Offer], request: TravellerRequest, weights: Weights,
                 settings: dict[str, Any] | None = None) -> list[RankedOffer]:
    settings = settings or {}
    missing_score = settings.get("missing_value_score", 50.0)
    robust = settings.get("normalisation", "minmax") == "robust"
    per_criterion: dict[str, list[float]] = {}
    missing: dict[int, list[str]] = {i: [] for i in range(len(offers))}

    for name in weights:
        meta = CRITERIA[name]
        raw = [meta["func"](o, request) for o in offers]
        for i, v in enumerate(raw):
            if v is None:
                missing[i].append(name)
        if meta["kind"] == "relative":
            per_criterion[name] = normalise_relative(
                raw, meta.get("higher_is_better", True),
                min_spread=settings.get("min_spread", {}).get(name, 0.0),
                robust=robust, iqr_factor=settings.get("iqr_factor", 1.5),
                robust_min_n=settings.get("robust_min_n", 5), missing_score=missing_score)
        else:
            per_criterion[name] = [missing_score if v is None else round(v, 2) for v in raw]

    ranked = []
    for i, offer in enumerate(offers):
        scores = {n: per_criterion[n][i] for n in weights}
        contrib = {n: weights[n] * scores[n] for n in weights}
        ranked.append(RankedOffer(offer, scores, contrib, round(sum(contrib.values()), 2),
                                  missing[i]))
    return ranked


def _sort_key(r: RankedOffer):
    # Ties are broken by cheaper price, then shorter journey, then earlier departure,
    # then offer id - so the same input always gives exactly the same order.
    o = r.offer
    return (-r.total, o.price_eur, o.duration_min, o.departure_dt, o.offer_id)


@logged
def rank_offers(offers: list[Offer], request: TravellerRequest, weights: Weights,
                settings: dict[str, Any] | None = None) -> list[RankedOffer]:
    settings = settings or {}
    tol = settings.get("tie_tolerance", 0.05)
    ranked = sorted(score_offers(offers, request, weights, settings), key=_sort_key)
    for pos, r in enumerate(ranked, start=1):
        r.rank = pos
        if pos > 1 and abs(ranked[pos - 2].total - r.total) <= tol:
            r.tied_with_previous = True
    if ranked:
        log.info("Ranked %d offers with weights {%s}; top=%s (%.2f)", len(ranked),
                 weights.describe(), ranked[0].offer.offer_id, ranked[0].total)
    return ranked


def shift_weight(weights: Weights, name: str, delta: float) -> Weights:
    """Move ``delta`` of weight to/from ``name``; others are rescaled proportionally."""
    new_w = min(max(weights[name] + delta, 0.0), 1.0)
    rest = {k: v for k, v in weights.items() if k != name}
    rest_total = sum(rest.values())
    if rest_total == 0:
        return weights
    scale = (1.0 - new_w) / rest_total
    raw = {k: v * scale for k, v in rest.items()}
    raw[name] = new_w
    return Weights.create(raw, normalise=True)


def sensitivity(offers: list[Offer], request: TravellerRequest, weights: Weights,
                settings: dict[str, Any] | None = None, delta: float = 0.10):
    """Does the winner change if one weight moves +/- ``delta``? (robustness check)"""
    base = rank_offers(offers, request, weights, settings)
    if not base:
        return []
    winner = base[0].offer.offer_id
    rows = []
    for name in weights:
        for d in (-delta, delta):
            w2 = shift_weight(weights, name, d)
            top = rank_offers(offers, request, w2, settings)[0].offer.offer_id
            rows.append((name, d, top, top != winner))
    return rows
