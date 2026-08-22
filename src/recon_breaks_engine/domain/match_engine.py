"""The deterministic multi-pass matcher: canonical entries in, matches and typed breaks out.

This is the product. It is a frozen dataclass over pure stdlib and the injected
:class:`ReconPolicy`, with one method per pass family, and it owns every consequential decision:
which entries reconcile, what residual a pass leaves, and what kind of break the residue is. A
model has no entry point here, by construction.

Two properties are load-bearing and each has a unit test:

* **Pass precedence.** The passes run in a fixed order (exact, tolerance, many-to-one, fx-fee),
  and an entry a pass consumes is never offered to a later pass. A looser pass can therefore
  never claim a pair a stricter one would have matched, and the pass name on a :class:`Match`
  faithfully records which rule reconciled it.
* **Byte-identical replay.** Every pool is sorted by a total key before it is walked, the
  many-to-one subset search is bounded and takes the lexicographically first exact subset, and
  ``as_of`` is supplied by the caller. Two runs over the same entries produce identical output.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import combinations

from .kernel import Citation
from .models import Break, BreakType, CanonicalEntry, FeedSide, Match
from .policy import ReconPolicy

#: A hard ceiling on how many candidates the many-to-one pass will search over for one target,
#: independent of the policy's subset-size cap. Subset search is combinatorial, so an unbounded
#: candidate pool is a denial-of-service on a pathological feed; past this many candidates the
#: pass declines rather than hangs, and the entries fall through to break classification.
_MANY_TO_ONE_MAX_CANDIDATES = 12


def _sort_key(entry: CanonicalEntry) -> tuple[object, ...]:
    return (entry.value_date.toordinal(), entry.currency, entry.amount_minor, entry.entry_id)


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    """What one reconciliation produced: the reconciled groups and the residue, typed."""

    matches: tuple[Match, ...]
    breaks: tuple[Break, ...]


@dataclass(frozen=True, slots=True)
class MatchEngine:
    """Reconcile two feeds by running the passes in strict order, then typing the residue."""

    policy: ReconPolicy

    def reconcile(self, entries: Iterable[CanonicalEntry], *, as_of: date) -> MatchOutcome:
        pool_a = sorted((e for e in entries if e.side == FeedSide.A), key=_sort_key)
        pool_b = sorted((e for e in _iter_b(entries)), key=_sort_key)
        # Recurrence signal computed over the ORIGINAL input, before anything is consumed, so a
        # break's repeat_count reflects the whole run rather than what happened to be left.
        repeat = _reference_counts([*pool_a, *pool_b])

        consumed: set[str] = set()
        matches: list[Match] = []
        for pass_fn in (self._exact, self._tolerance, self._many_to_one, self._fx_fee):
            matches.extend(pass_fn(pool_a, pool_b, consumed))

        residue_a = [e for e in pool_a if e.entry_id not in consumed]
        residue_b = [e for e in pool_b if e.entry_id not in consumed]
        breaks = self._classify(residue_a, residue_b, as_of=as_of, repeat=repeat)
        return MatchOutcome(matches=tuple(matches), breaks=tuple(breaks))

    # -- passes --------------------------------------------------------------------------------

    def _exact(
        self, pool_a: Sequence[CanonicalEntry], pool_b: Sequence[CanonicalEntry], consumed: set[str]
    ) -> list[Match]:
        """Pair entries agreeing on currency, amount and reference, dated within the window."""
        matches: list[Match] = []
        window = self.policy.aging.timing_window_days
        by_key_b = _index(pool_b, lambda e: (e.currency, e.amount_minor, e.reference_key), consumed)
        for a in pool_a:
            if a.entry_id in consumed:
                continue
            bucket = by_key_b.get((a.currency, a.amount_minor, a.reference_key), [])

            def within_window(b: CanonicalEntry, a: CanonicalEntry = a) -> bool:
                return _days(a.value_date, b.value_date) <= window

            b = _take_first(bucket, consumed, within_window)
            if b is not None:
                consumed.update({a.entry_id, b.entry_id})
                matches.append(_pair_match("exact", a, b, residual=0))
        return matches

    def _tolerance(
        self, pool_a: Sequence[CanonicalEntry], pool_b: Sequence[CanonicalEntry], consumed: set[str]
    ) -> list[Match]:
        """Pair entries agreeing on reference and currency whose amounts are within tolerance."""
        matches: list[Match] = []
        window = self.policy.aging.timing_window_days
        by_ref_b = _index(pool_b, lambda e: (e.currency, e.reference_key), consumed)
        for a in pool_a:
            if a.entry_id in consumed:
                continue
            bucket = by_ref_b.get((a.currency, a.reference_key), [])

            def acceptable(b: CanonicalEntry, a: CanonicalEntry = a) -> bool:
                larger = max(abs(a.amount_minor), abs(b.amount_minor))
                diff = a.amount_minor - b.amount_minor
                return _days(a.value_date, b.value_date) <= window and self.policy.tolerance.within(
                    a.currency, larger, diff
                )

            b = _take_first(bucket, consumed, acceptable)
            if b is not None:
                consumed.update({a.entry_id, b.entry_id})
                matches.append(
                    _pair_match("tolerance", a, b, residual=a.amount_minor - b.amount_minor)
                )
        return matches

    def _many_to_one(
        self, pool_a: Sequence[CanonicalEntry], pool_b: Sequence[CanonicalEntry], consumed: set[str]
    ) -> list[Match]:
        """Match one entry against a bounded subset of same-counterparty entries that sums to it."""
        matches: list[Match] = []
        matches.extend(self._subset_side(pool_b, pool_a, consumed, one_side=FeedSide.B))
        matches.extend(self._subset_side(pool_a, pool_b, consumed, one_side=FeedSide.A))
        return matches

    def _subset_side(
        self,
        ones: Sequence[CanonicalEntry],
        manys: Sequence[CanonicalEntry],
        consumed: set[str],
        *,
        one_side: FeedSide,
    ) -> list[Match]:
        matches: list[Match] = []
        window = self.policy.aging.timing_window_days
        cap = self.policy.aging.many_to_one_candidate_cap
        for one in ones:
            if one.entry_id in consumed:
                continue
            candidates = [
                m
                for m in manys
                if m.entry_id not in consumed
                and m.currency == one.currency
                and m.counterparty_key == one.counterparty_key
                and _days(one.value_date, m.value_date) <= window
            ]
            if not 2 <= len(candidates) <= _MANY_TO_ONE_MAX_CANDIDATES:
                continue
            subset = _first_exact_subset(candidates, one.amount_minor, max_size=cap)
            if subset is None:
                continue
            ids = {m.entry_id for m in subset}
            consumed.update({one.entry_id, *ids})
            if one_side == FeedSide.B:
                matches.append(_group_match("many_to_one", subset, [one]))
            else:
                matches.append(_group_match("many_to_one", [one], subset))
        return matches

    def _fx_fee(
        self, pool_a: Sequence[CanonicalEntry], pool_b: Sequence[CanonicalEntry], consumed: set[str]
    ) -> list[Match]:
        """Match cross-currency pairs within the FX window, and fee-explained same-ccy pairs."""
        matches: list[Match] = []
        window = self.policy.aging.timing_window_days
        by_ref_b = _index(pool_b, lambda e: (e.reference_key,), consumed)
        for a in pool_a:
            if a.entry_id in consumed:
                continue
            for b in list(by_ref_b.get((a.reference_key,), [])):
                if b.entry_id in consumed:
                    continue
                if _days(a.value_date, b.value_date) > window:
                    continue
                residual = self._fx_fee_residual(a, b)
                if residual is None:
                    continue
                consumed.update({a.entry_id, b.entry_id})
                name = "fx" if a.currency != b.currency else "fee"
                matches.append(_pair_match(name, a, b, residual=residual))
                break
        return matches

    def _fx_fee_residual(self, a: CanonicalEntry, b: CanonicalEntry) -> int | None:
        """The base-currency residual if (a, b) reconcile by FX or by fee, else ``None``."""
        if a.currency == b.currency:
            diff = abs(a.amount_minor - b.amount_minor)
            if 0 < diff <= self.policy.fees.max_fee_minor(a.currency):
                return a.amount_minor - b.amount_minor
            return None
        converted = _convert(self.policy, b, a.currency)
        if converted is None:
            return None
        larger = max(abs(a.amount_minor), abs(converted))
        window = (larger * self.policy.fx.window_bps) // 10_000
        diff = a.amount_minor - converted
        return diff if abs(diff) <= window else None

    # -- residue classification ----------------------------------------------------------------

    def _classify(
        self,
        residue_a: Sequence[CanonicalEntry],
        residue_b: Sequence[CanonicalEntry],
        *,
        as_of: date,
        repeat: dict[str, int],
    ) -> list[Break]:
        breaks: list[Break] = []
        done: set[str] = set()

        # DUPLICATE first (same side), so a repeated entry is named as a duplicate rather than as
        # a spurious missing pair with its own twin.
        for side_pool in (residue_a, residue_b):
            for group in _duplicate_groups(side_pool, done):
                breaks.append(self._break("duplicate", BreakType.DUPLICATE, group, as_of, repeat))

        # Then the cross-side residue relationships, in a fixed precedence.
        remaining_a = [e for e in residue_a if e.entry_id not in done]
        remaining_b = [e for e in residue_b if e.entry_id not in done]
        for a in remaining_a:
            if a.entry_id in done:
                continue
            partner, kind = self._cross_partner(a, remaining_b, done)
            if partner is not None and kind is not None:
                done.update({a.entry_id, partner.entry_id})
                breaks.append(self._break("x", kind, [a, partner], as_of, repeat))

        # Whatever is still unpaired is genuinely MISSING on the other side.
        for e in [*remaining_a, *remaining_b]:
            if e.entry_id in done:
                continue
            done.add(e.entry_id)
            breaks.append(self._break("missing", BreakType.MISSING, [e], as_of, repeat))

        breaks.sort(key=lambda brk: brk.break_id)
        return breaks

    def _cross_partner(
        self, a: CanonicalEntry, pool_b: Sequence[CanonicalEntry], done: set[str]
    ) -> tuple[CanonicalEntry | None, BreakType | None]:
        """Find a residue counterpart for ``a`` and the break type its mismatch implies."""
        window = self.policy.aging.timing_window_days
        timing: CanonicalEntry | None = None
        fx: CanonicalEntry | None = None
        fee: CanonicalEntry | None = None
        for b in pool_b:
            if b.entry_id in done or b.reference_key != a.reference_key:
                continue
            if (
                b.currency == a.currency
                and b.amount_minor == a.amount_minor
                and _days(a.value_date, b.value_date) > window
            ):
                timing = timing or b
            elif b.currency != a.currency:
                fx = fx or b
            elif b.currency == a.currency and b.amount_minor != a.amount_minor:
                fee = fee or b
        if timing is not None:
            return timing, BreakType.TIMING
        if fx is not None:
            return fx, BreakType.FX
        if fee is not None:
            return fee, BreakType.FEE
        return None, None

    def _break(
        self,
        tag: str,
        break_type: BreakType,
        entries: Sequence[CanonicalEntry],
        as_of: date,
        repeat: dict[str, int],
    ) -> Break:
        primary = entries[0]
        entry_ids = tuple(sorted(e.entry_id for e in entries))
        amount = (
            sum(e.amount_minor for e in entries)
            if break_type == BreakType.DUPLICATE
            else primary.amount_minor
        )
        age = max((as_of - min(e.value_date for e in entries)).days, 0)
        rep = (
            len(entries)
            if break_type == BreakType.DUPLICATE
            else repeat.get(primary.reference_key, 1)
        )
        citations = tuple(_dedupe_citations(e.citation for e in entries))
        break_id = f"BRK-{break_type.value}-{'_'.join(entry_ids)}"
        return Break(
            break_id=break_id,
            break_type=break_type,
            side=primary.side,
            entry_ids=entry_ids,
            amount_minor=amount,
            currency=primary.currency,
            value_date=primary.value_date,
            reference_key=primary.reference_key,
            counterparty_key=primary.counterparty_key,
            account=primary.account,
            age_days=age,
            repeat_count=rep,
            citations=citations,
        )


# -- module-level helpers (pure) ---------------------------------------------------------------


def _iter_b(entries: Iterable[CanonicalEntry]) -> Iterable[CanonicalEntry]:
    return (e for e in entries if e.side == FeedSide.B)


def _days(left: date, right: date) -> int:
    return abs((left - right).days)


def _reference_counts(entries: Sequence[CanonicalEntry]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.reference_key] = counts.get(e.reference_key, 0) + 1
    return counts


def _index(
    pool: Sequence[CanonicalEntry],
    key_fn: Callable[[CanonicalEntry], tuple[object, ...]],
    consumed: set[str],
) -> dict[tuple[object, ...], list[CanonicalEntry]]:
    out: dict[tuple[object, ...], list[CanonicalEntry]] = {}
    for e in pool:
        if e.entry_id in consumed:
            continue
        out.setdefault(key_fn(e), []).append(e)
    return out


def _take_first(
    bucket: Sequence[CanonicalEntry],
    consumed: set[str],
    predicate: Callable[[CanonicalEntry], bool],
) -> CanonicalEntry | None:
    for candidate in bucket:
        if candidate.entry_id not in consumed and predicate(candidate):
            return candidate
    return None


def _first_exact_subset(
    candidates: Sequence[CanonicalEntry], target: int, *, max_size: int
) -> tuple[CanonicalEntry, ...] | None:
    ordered = sorted(candidates, key=lambda e: e.entry_id)
    for size in range(2, min(max_size, len(ordered)) + 1):
        for combo in combinations(ordered, size):
            if sum(e.amount_minor for e in combo) == target:
                return combo
    return None


def _convert(policy: ReconPolicy, entry: CanonicalEntry, into: str) -> int | None:
    """Convert ``entry.amount_minor`` into ``into``'s minor units at the policy rate, or None.

    Minor-unit exponents are ignored deliberately: the fixtures reconcile currencies that share a
    2-decimal exponent, and mixing a zero-decimal currency into an FX pair is out of scope for the
    shipped rate table. A pair the table cannot convert simply does not FX-match and falls to a
    break, which is the fail-closed answer.
    """
    rate = policy.fx.rate_scaled(into, entry.currency)
    if rate is None:
        return None
    return (entry.amount_minor * rate) // 10_000_000


def _duplicate_groups(pool: Sequence[CanonicalEntry], done: set[str]) -> list[list[CanonicalEntry]]:
    buckets: dict[tuple[str, int, str, str], list[CanonicalEntry]] = {}
    for e in pool:
        if e.entry_id in done:
            continue
        buckets.setdefault(
            (e.currency, e.amount_minor, e.reference_key, e.counterparty_key), []
        ).append(e)
    groups: list[list[CanonicalEntry]] = []
    for key in sorted(buckets):
        members = buckets[key]
        if len(members) >= 2:
            done.update(e.entry_id for e in members)
            groups.append(sorted(members, key=lambda e: e.entry_id))
    return groups


def _dedupe_citations(citations: Iterable[Citation]) -> list[Citation]:
    seen: set[str] = set()
    out: list[Citation] = []
    for citation in citations:
        if citation.source_id in seen:
            continue
        seen.add(citation.source_id)
        out.append(citation)
    return out


def _pair_match(name: str, a: CanonicalEntry, b: CanonicalEntry, *, residual: int) -> Match:
    return Match(
        pass_name=name,
        currency=a.currency,
        a_entry_ids=(a.entry_id,),
        b_entry_ids=(b.entry_id,),
        a_total_minor=a.amount_minor,
        b_total_minor=b.amount_minor,
        residual_minor=residual,
        citations=tuple(_dedupe_citations((a.citation, b.citation))),
    )


def _group_match(
    name: str, a_side: Sequence[CanonicalEntry], b_side: Sequence[CanonicalEntry]
) -> Match:
    a_total = sum(e.amount_minor for e in a_side)
    b_total = sum(e.amount_minor for e in b_side)
    return Match(
        pass_name=name,
        currency=(a_side or b_side)[0].currency,
        a_entry_ids=tuple(sorted(e.entry_id for e in a_side)),
        b_entry_ids=tuple(sorted(e.entry_id for e in b_side)),
        a_total_minor=a_total,
        b_total_minor=b_total,
        residual_minor=a_total - b_total,
        citations=tuple(_dedupe_citations(e.citation for e in [*a_side, *b_side])),
    )
