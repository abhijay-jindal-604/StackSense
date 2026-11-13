"""Shared cost-model constants (plan section 7).  Per-candidate bands live in the layer records."""
from __future__ import annotations

from .model import SIZE_CLASSES, size_index

# Upper bounds per size class: (users_12_months, peak_concurrent, data_gb).  xl = anything above l.
SIZE_LIMITS = {
    "xs": (5_000, 100, 5),
    "s": (50_000, 1_000, 100),
    "m": (500_000, 10_000, 1_000),
    "l": (5_000_000, 100_000, 10_000),
}

PEAK_CONCURRENCY_SHARE = 0.05      # C = max(1, ceil(0.05 * users_12_months)) when not given
REQUESTS_PER_CONCURRENT_USER = 0.2  # rps = ceil(0.2 * C) when not given
DATA_GB_PER_USER = 0.002            # 2 MB per user
DATA_GB_PER_USER_MEDIA = 0.05       # when file_media_storage
EGRESS_GB_PER_USER = 0.05           # 50 MB per user per month; x3 for media-heavy
EGRESS_MEDIA_FACTOR = 3
MEDIA_SHARE_OF_DATA = 0.8


def size_class(users_12_months: float, peak_concurrent: float, data_gb: float) -> str:
    """Largest of the three sub-classes (one extreme dimension is enough)."""
    idx = 0
    for dim, value in enumerate((users_12_months, peak_concurrent, data_gb)):
        sub = len(SIZE_CLASSES) - 1
        for i, size in enumerate(SIZE_CLASSES[:-1]):
            if value <= SIZE_LIMITS[size][dim]:
                sub = i
                break
        idx = max(idx, sub)
    return SIZE_CLASSES[idx]


XL_FROM_L_FACTOR = 3  # xl band = l band x 3, flagged "quote needed"


def band_for(cost: dict, size: str):
    """Return ``(min, max, derived)`` for ``size`` or ``None`` when not offered at that size.
    ``xl`` without an explicit band is derived from ``l`` x 3 (derived=True: quote needed)."""
    size_index(size)
    band = cost.get(size)
    if band is not None:
        return band[0], band[1], False
    if size == "xl" and cost.get("l") is not None:
        lo, hi = cost["l"]
        return lo * XL_FROM_L_FACTOR, hi * XL_FROM_L_FACTOR, True
    return None


# Multipliers: availability target -> (compute, database); failover tooling adds a share of total.
AVAILABILITY_MULTIPLIERS = {
    "99": (1.0, 1.0),
    "99.9": (1.0, 1.0),
    "99.95": (1.5, 2.0),
    "99.99": (2.2, 2.5),
}
FAILOVER_TOOLING_SHARE = {"99.99": 0.10}
# traffic pattern on (autoscaling host, fixed host) -> (min multiplier, max multiplier) on compute
TRAFFIC_MULTIPLIERS = {
    "autoscaling": {"spiky": (0.8, 1.4), "seasonal": (0.8, 1.4)},
    "fixed": {"spiky": (1.0, 1.5), "seasonal": (1.0, 1.5)},
}

# Compliance overhead lines, USD/month (min, max) at sizes s / m / l (xs uses s, xl uses l x 3).
COMPLIANCE_OVERHEAD = {
    "pci_dss": {"s": (50, 150), "m": (150, 600), "l": (600, 2000)},
    "hipaa": {"s": (100, 400), "m": (300, 900), "l": (900, 3000)},
    "iso27001": {"s": (20, 80), "m": (50, 300), "l": (300, 1200)},
    "soc2": {"s": (20, 80), "m": (50, 300), "l": (300, 1200)},
    "rbi_localisation": {"s": (0, 0), "m": (0, 0), "l": (0, 0)},
    "gdpr": {"s": (0, 50), "m": (0, 50), "l": (0, 50)},
    "dpdp": {"s": (0, 50), "m": (0, 50), "l": (0, 50)},
}

# Usage-line rates (USD).
OBJECT_STORAGE_RATE_GB_MONTH = {"hyperscaler": (0.023, 0.026), "r2": (0.015, 0.015), "spaces": (0.02, 0.02)}
OBJECT_STORAGE_MINIMUM = {"spaces": 5}
EGRESS_FREE_GB_HYPERSCALER = 100
EGRESS_RATE_GB = (0.09, 0.11)
SMS_PER_USER_MONTH = 2
SMS_RATE_INDIA = (0.0025, 0.004)
SMS_RATE_OTHER = (0.05, 0.08)

# Payment fees are a percentage of transaction value, not infrastructure: excluded with an assumption.
PAYMENT_FEE_NOTE = {"india_domestic_pct": 2.0, "stripe_us": "2.9% + USD 0.30"}

# On-premise / air-gapped: cloud bill 0; amortised hardware + power per node-month.
ONPREM_SERVER_MONTH = (150, 400)   # 4-year amortisation
ONPREM_POWER_COLO_MONTH = (50, 150)
ONPREM_NODES = {"xs": 3, "s": 3, "m": (5, 8), "l": 12}

# Budget verdict and fallback rules.
BUDGET_HEADROOM_FACTOR = 10        # BUDGET_HEADROOM when budget >= 10 x cost.max
BUDGET_FALLBACK_TOP_N = 50         # search the top 50 combinations for one with cost.min <= budget
BUDGET_FALLBACK_ACCEPT_RATIO = 0.85  # accept if combo_score >= 0.85 x best
SIGNIFICANT_FIGURES = 2
CURRENCY_NOTE = "USD list prices, November 2026"
ALWAYS_EXCLUDED = ("payment gateway fees", "staff cost", "audit fees", "domain registration",
                   "app-store fees")


def round_sig(x: float, figures: int = SIGNIFICANT_FIGURES) -> int:
    """Round to ``figures`` significant figures and return an int (deterministic, half away from zero).

    Values whose ``figures``-th significant digit lies below the units place (for example 2.5 at two
    figures) are rounded to the nearest integer, also half away from zero: 2.5 -> 3, -2.5 -> -3."""
    if x == 0:
        return 0
    from decimal import Decimal, ROUND_HALF_UP
    d = Decimal(repr(float(x)))
    exp = max(0, d.adjusted() - figures + 1)
    return int(d.quantize(Decimal(1).scaleb(exp), rounding=ROUND_HALF_UP))
