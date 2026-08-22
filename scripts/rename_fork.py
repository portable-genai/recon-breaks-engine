"""Rebrand this base repo for your institution in one pass.

Rewrites the python package name, the console-script name, the ``RECONBREAKS`` env-var prefix,
the Terraform resource-id stem and the distribution / git id across the tree, so a fork does not
have to hunt them down by hand. It is a mechanical text plus directory rename, deliberately
conservative: it prints a plan, writes nothing unless you pass ``--yes``, and by default leaves
Markdown prose alone (pass ``--include-docs`` to sweep it too).

    # See what would change (no writes):
    python scripts/rename_fork.py --package acme_recon --cli acme-recon \
        --env-prefix ACME --resource acme-recon --dry-run

    # Apply it:
    python scripts/rename_fork.py --package acme_recon --cli acme-recon \
        --env-prefix ACME --resource acme-recon --yes

Every rule is applied in ONE simultaneous pass over each file, so no rule can rewrite another
rule's output. That matters here: in this template the console-script name IS the package name
(see ``[project.scripts]`` in ``pyproject.toml``), so a sequential search and replace would
rename the command twice. The CLI rules therefore match only the places a command NAME appears
(the ``[project.scripts]`` key, and a documented shell invocation followed by a subcommand or a
flag), and the package rule takes every other occurrence.

After running: recreate the venv and ``pip install -e ".[dev]"`` (the distribution name changed),
then run ``make gate``. See docs/ADOPTING.md for the checklist of human decisions (region, IdP,
policy numbers, fixtures, eval golden set) that this script deliberately does NOT make for you.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------------------- #
# What this repo is called today. These five strings are the whole per-repo surface: a sibling
# catalog repo's copy of this script differs from this one in this block and nowhere else.
# --------------------------------------------------------------------------------------- #
_OLD_PACKAGE = "recon_breaks_engine"
_OLD_CLI = "recon_breaks_engine"
_OLD_ENV_STEM = "RECONBREAKS"
_OLD_RESOURCE = "f1-svc"
_OLD_DIST = "recon-breaks-engine"

# Directories never touched.
_SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    ".next",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "out",
}
# File suffixes considered text (everything else is skipped).
_TEXT_SUFFIXES = {
    ".py",
    ".toml",
    ".yaml",
    ".yml",
    ".md",
    ".json",
    ".cfg",
    ".ini",
    ".txt",
    ".tf",
    ".hcl",
    ".mjs",
    ".ts",
    ".tsx",
    ".lock",
    ".env",
    ".example",
    "",
}
# Docs prose is only swept with --include-docs (keep code deterministic by default).
_DOC_SUFFIXES = {".md"}


def _iter_files(include_docs: bool):
    for path in sorted(_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(_ROOT).parts):
            continue
        if path.suffix not in _TEXT_SUFFIXES:
            continue
        if not include_docs and path.suffix in _DOC_SUFFIXES:
            continue
        yield path


def _rules(args: argparse.Namespace) -> list[tuple[str, str, str]]:
    """``(label, pattern, replacement)``, most specific first.

    Order is load-bearing: the alternation is tried left to right at each position, so the git
    id (which contains no other token here) and the CLI's two narrow shapes must precede the
    bare package token that would otherwise swallow them.
    """
    env_stem = args.env_prefix.rstrip("_").upper()
    package = re.escape(_OLD_PACKAGE)
    return [
        # The distribution / git id: pyproject name, the GitHub URLs, CI, the image tag.
        ("dist", re.escape(_OLD_DIST), args.dist),
        # This script's own _OLD_CLI constant. The general rules cannot get it right, because
        # the CLI and the package are the same token upstream and the package rule would win,
        # leaving a fork's copy unable to rename itself a second time.
        ("cli", rf'(?<=^_OLD_CLI = "){package}(?="$)', args.cli),
        # The console-script NAME, in the only two shapes it appears in:
        #   1. the [project.scripts] key, which is followed by " = " and never by a subcommand
        #      (the alternation is compiled MULTILINE, so ^ here is the start of a line)
        ("cli", rf"^{package}(?= *= *\")", args.cli),
        #   2. a documented shell invocation: the command, then a subcommand or a flag. The two
        #      lookbehinds keep `from <pkg> import ...` and `import <pkg> ...` out of it, which
        #      is a python module path and not a command however much it looks like one.
        (
            "cli",
            rf"(?<!from )(?<!import )(?<![\w.\-/]){package}"
            rf"(?=[ \t]+(?:--?[a-z]|[a-z][\w-]*))(?![ \t]+(?:import|as)\b)",
            args.cli,
        ),
        # The python package: import paths, the src/ tree, the adapter binding map, wheel config.
        ("package", package, args.package),
        # The env-var prefix. Matched WITHOUT the trailing underscore so both RECONBREAKS_PROFILE
        # and the bare stem (render.tf.json, AGENTS.md) are covered, and never mid-identifier.
        (
            "env",
            rf"(?<![A-Za-z0-9_]){re.escape(_OLD_ENV_STEM)}(?![A-Za-z0-9])",
            env_stem,
        ),
        # The Terraform name_prefix stem every deployed resource id is derived from (naming.tf).
        ("resource", re.escape(_OLD_RESOURCE), args.resource),
    ]


def _compile(rules: list[tuple[str, str, str]]) -> tuple[re.Pattern[str], dict[str, str]]:
    """One alternation over every rule, so a single pass cannot cascade."""
    replacements = {f"r{index}": rule[2] for index, rule in enumerate(rules)}
    pattern = "|".join(f"(?P<r{index}>{rule[1]})" for index, rule in enumerate(rules))
    return re.compile(pattern, re.MULTILINE), replacements


def _rewrite(text: str, pattern: re.Pattern[str], replacements: dict[str, str]) -> tuple[str, int]:
    hits = 0

    def _substitute(match: re.Match[str]) -> str:
        nonlocal hits
        hits += 1
        return replacements[str(match.lastgroup)]

    return pattern.sub(_substitute, text), hits


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebrand this base repo for a fork.")
    parser.add_argument("--package", required=True, help="new python package (snake_case)")
    parser.add_argument("--cli", required=True, help="new console-script name, e.g. acme-recon")
    parser.add_argument("--env-prefix", required=True, help="new env-var prefix stem, e.g. ACME")
    parser.add_argument(
        "--resource", required=True, help="new Terraform name_prefix stem, e.g. acme-recon"
    )
    parser.add_argument(
        "--dist", default="", help="new distribution / git id (default: the package, hyphenated)"
    )
    parser.add_argument("--include-docs", action="store_true", help="also rewrite Markdown prose")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    parser.add_argument("--yes", action="store_true", help="apply without the confirmation prompt")
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z_][a-z0-9_]*", args.package):
        parser.error("--package must be a valid snake_case python identifier")
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", args.cli):
        parser.error("--cli must be lowercase letters, digits, hyphens or underscores")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", args.env_prefix.rstrip("_")):
        parser.error("--env-prefix must be an alphanumeric stem, e.g. ACME")
    # The Terraform variable validates this too, at plan time; failing here is cheaper.
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,18}", args.resource):
        parser.error("--resource must match ^[a-z][a-z0-9-]{2,18}$ (Terraform name_prefix)")
    if not args.dist:
        args.dist = args.package.replace("_", "-")

    # Write only when explicitly applying; --dry-run always wins over --yes.
    apply = args.yes and not args.dry_run

    rules = _rules(args)
    print("Planned replacements (whole tree):")
    for label, pattern, replacement in rules:
        print(f"  {label:9} {pattern!r:60} -> {replacement!r}")
    print()

    pattern, replacements = _compile(rules)
    touched: list[tuple[Path, int]] = []
    for path in _iter_files(args.include_docs):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rewritten, hits = _rewrite(text, pattern, replacements)
        if not hits:
            continue
        touched.append((path, hits))
        if apply:
            path.write_text(rewritten, encoding="utf-8")

    total = sum(hits for _, hits in touched)
    print(f"{'Edited' if apply else 'Would edit'} {len(touched)} file(s), {total} replacement(s).")

    # Rename the package directory LAST, after its contents have been rewritten.
    old_dir = _ROOT / "src" / _OLD_PACKAGE
    new_dir = _ROOT / "src" / args.package
    if old_dir.exists() and old_dir != new_dir:
        print(f"{'Renaming' if apply else 'Would rename'} {old_dir} -> {new_dir}")
        if apply:
            old_dir.rename(new_dir)

    if not apply:
        print("\nNothing was written. Re-run with --yes to apply.")
        if not args.include_docs:
            print("Markdown prose was skipped; add --include-docs to sweep it as well.")
        return 0
    print('\nDone. Next: recreate the venv, `pip install -e ".[dev]"`, then `make gate`.')
    print("Then work through docs/ADOPTING.md: region, IdP, policy numbers, fixtures, eval set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
