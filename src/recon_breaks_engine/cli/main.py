"""Minimal stdlib CLI: reconcile two feeds, or verify the audit chain (argparse, no extra deps).

The reconcile command prints the per-pass arithmetic and the ranked break worklist, so an
operator sees exactly which rule matched what and why a break sits where it does. Rule R8 routing
and case opening happen inside the service, identically to the API path.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from hex_service_kit.logging import configure_logging

from ..config import build_container
from ..domain.resolution_service import ResolutionService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recon_breaks_engine")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("reconcile", help="Reconcile two feed sets.")
    rec.add_argument("feed_a")
    rec.add_argument("feed_b")
    rec.add_argument("--as-of", default="", help="ISO date to reconcile against (default today).")
    rec.add_argument("--actor", default="cli-user@bank.example")
    rec.add_argument(
        "--tenant", default="", help="Tenant partition asserted to human-review-console."
    )

    args = parser.parse_args(argv)
    container = build_container()
    # Idempotent: a process that is both an API app and a CLI configures once.
    configure_logging(container.settings.profile, service="recon-breaks-engine")

    if args.command == "reconcile":
        service = ResolutionService(
            feeds=container.feeds,
            generation=container.generation,
            review_router=container.review_router,
            audit=container.audit,
            case_engine=container.case_engine,
            tracer=container.tracer,
        )
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
        run = service.run(
            feed_a=args.feed_a,
            feed_b=args.feed_b,
            as_of=as_of,
            actor=args.actor,
            tenant=args.tenant,
        )
        print(f"reconciled {args.feed_a} vs {args.feed_b} as at {run.as_of.isoformat()}")
        print(f"  matches: {len(run.matches)}")
        for m in run.matches:
            print(
                f"    {m.pass_name:11} A={list(m.a_entry_ids)} B={list(m.b_entry_ids)} "
                f"residual={m.residual_minor} {m.currency}"
            )
        print(f"  breaks: {len(run.ranked_breaks)} (ranked worklist)")
        for rb in run.ranked_breaks:
            brk = rb.record
            print(
                f"    #{rb.rank} {brk.break_type.value:9} {list(brk.entry_ids)} "
                f"amount={brk.amount_minor} {brk.currency} age={brk.age_days}d score={rb.score}"
            )
        print(f"  requires_human_review: {run.requires_human_review}")
        return 0

    return 2  # pragma: no cover - argparse requires a subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
