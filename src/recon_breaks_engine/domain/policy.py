"""Bank-owned reconciliation policy: every threshold, tolerance and weight in one frozen place.

The matcher, the break ranker and the aging clock read their numbers from here rather than
from module constants scattered through the engines, so a deployment tunes behaviour by
constructing a different :class:`ReconPolicy` and never by editing code. The shipped
:meth:`ReconPolicy.default` is a demonstrable, obviously-synthetic baseline; a real adopter
overrides it. Amounts are integer MINOR units (cents, or whole yen for a zero-decimal currency)
so every comparison is exact and no float rounding enters a consequential decision.

Currencies here are ISO 4217 alpha codes. ``_MINOR_EXPONENT`` records how many minor units make
one major unit, defaulting to 2, with the zero-decimal exceptions the demo uses. It lives in
policy because the exponent is a property of money, not of the parser.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

#: Minor-unit exponents for the currencies the fixtures use. 2 unless listed. A currency absent
#: here is treated as 2-decimal, which is correct for every currency the demo touches.
_MINOR_EXPONENT: Mapping[str, int] = MappingProxyType({"JPY": 0, "KRW": 0})


def minor_exponent(currency: str) -> int:
    """How many minor units make one major unit of ``currency`` (2 unless a known exception)."""
    return _MINOR_EXPONENT.get(currency.upper(), 2)


@dataclass(frozen=True, slots=True)
class TolerancePolicy:
    """How far two amounts may differ and still be one reconciled pair.

    A pair passes tolerance when the absolute difference is within EITHER the per-currency basis
    points of the larger leg OR the per-currency absolute cap. The bps allowance covers a large
    ticket that may legitimately drift by a large absolute amount; the absolute cap covers a
    small ticket whose bps allowance rounds down to almost nothing. Taking the larger of the two
    is what lets a single policy serve both without forcing either.
    """

    per_currency_bps: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    default_bps: int = 5
    per_currency_abs_cap_minor: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )
    default_abs_cap_minor: int = 50

    def bps(self, currency: str) -> int:
        return self.per_currency_bps.get(currency.upper(), self.default_bps)

    def abs_cap_minor(self, currency: str) -> int:
        return self.per_currency_abs_cap_minor.get(currency.upper(), self.default_abs_cap_minor)

    def allowance_minor(self, currency: str, larger_minor: int) -> int:
        """The largest difference this policy forgives for a pair whose larger leg is given."""
        bps_allow = (abs(larger_minor) * self.bps(currency)) // 10_000
        return max(bps_allow, self.abs_cap_minor(currency))

    def within(self, currency: str, larger_minor: int, diff_minor: int) -> bool:
        """Is ``diff_minor`` within tolerance for this currency and larger leg?"""
        return abs(diff_minor) <= self.allowance_minor(currency, larger_minor)


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    """The maximum explainable fee (a known deduction) that turns a difference into a match.

    A same-currency pair that agrees on reference and counterparty but differs by no more than
    the fee cap is a fee-explained match, not a break: the smaller leg is net of a processing
    fee. A difference larger than the cap is a real FEE break for a human to explain.
    """

    per_currency_max_fee_minor: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )
    default_max_fee_minor: int = 500

    def max_fee_minor(self, currency: str) -> int:
        return self.per_currency_max_fee_minor.get(currency.upper(), self.default_max_fee_minor)


@dataclass(frozen=True, slots=True)
class FxRateWindow:
    """A deterministic FX rate per ordered currency pair, plus the bps window it may drift in.

    Cross-currency pairs that agree on reference reconcile when the counter-leg, converted at the
    policy rate, lands within ``window_bps`` of the base leg. The rate is fixed policy data, not a
    live feed: a reconciliation must replay byte for byte, and a moving rate would defeat that.
    Rates are expressed in ten-millionths (1e-7) to keep the conversion integer-only.
    """

    #: (base, quote) -> rate scaled by 1e7. amount_in_base = amount_in_quote * rate / 1e7.
    rates_scaled: Mapping[tuple[str, str], int] = field(
        default_factory=lambda: MappingProxyType({})
    )
    window_bps: int = 25

    def rate_scaled(self, base: str, quote: str) -> int | None:
        return self.rates_scaled.get((base.upper(), quote.upper()))


@dataclass(frozen=True, slots=True)
class RankingPolicy:
    """Integer weights that turn a break into a rank score (higher is more urgent).

    Integer arithmetic throughout: a float score would make the ranking sensitive to summation
    order and platform rounding, and a break worklist that reorders itself on replay is not a
    worklist. Amount contributes by log-scaled band rather than linearly, so one very large break
    cannot swamp every aging signal.
    """

    age_weight: int = 10
    amount_band_weight: int = 40
    repeat_weight: int = 15
    #: Per-account criticality bonus, keyed by account id. Absent accounts score 0.
    account_criticality: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    default_account_criticality: int = 0

    def criticality(self, account: str) -> int:
        return self.account_criticality.get(account, self.default_account_criticality)


@dataclass(frozen=True, slots=True)
class AgingPolicy:
    """When a break is old enough or large enough to open an escalation case on
    human-review-console.

    A break breaches when its age in days reaches ``escalate_age_days`` OR its amount reaches
    ``escalate_amount_minor``. Both are deployment policy; the engine only compares.
    """

    escalate_age_days: int = 3
    escalate_amount_minor: int = 1_000_000
    #: Timing window: a counterpart found on the other side but dated more than this many days
    #: apart is a TIMING break, not a clean match.
    timing_window_days: int = 1
    #: The largest subset the many-to-one pass will consider summing, to bound the search.
    many_to_one_candidate_cap: int = 6


@dataclass(frozen=True, slots=True)
class ReconPolicy:
    """The whole tunable surface of the engine, injected into every deterministic component."""

    tolerance: TolerancePolicy = field(default_factory=TolerancePolicy)
    fees: FeeSchedule = field(default_factory=FeeSchedule)
    fx: FxRateWindow = field(default_factory=FxRateWindow)
    ranking: RankingPolicy = field(default_factory=RankingPolicy)
    aging: AgingPolicy = field(default_factory=AgingPolicy)

    @classmethod
    def default(cls) -> ReconPolicy:
        """The shipped baseline: obviously-synthetic numbers a real adopter overrides."""
        return cls(
            tolerance=TolerancePolicy(
                per_currency_bps=MappingProxyType({"USD": 5, "EUR": 5, "SGD": 5, "JPY": 3}),
                default_bps=5,
                per_currency_abs_cap_minor=MappingProxyType(
                    {"USD": 50, "EUR": 50, "SGD": 50, "JPY": 3}
                ),
                default_abs_cap_minor=50,
            ),
            fees=FeeSchedule(
                per_currency_max_fee_minor=MappingProxyType({"USD": 500, "SGD": 500, "JPY": 5}),
                default_max_fee_minor=500,
            ),
            fx=FxRateWindow(
                rates_scaled=MappingProxyType(
                    {
                        ("USD", "SGD"): 7_400_000,  # 1 SGD = 0.74 USD
                        ("USD", "EUR"): 10_800_000,  # 1 EUR = 1.08 USD
                    }
                ),
                window_bps=25,
            ),
            ranking=RankingPolicy(
                age_weight=10,
                amount_band_weight=40,
                repeat_weight=15,
                account_criticality=MappingProxyType({"NOSTRO-USD-001": 50, "NOSTRO-EUR-001": 30}),
                default_account_criticality=0,
            ),
            aging=AgingPolicy(
                escalate_age_days=3,
                escalate_amount_minor=1_000_000,
                timing_window_days=1,
                many_to_one_candidate_cap=6,
            ),
        )
