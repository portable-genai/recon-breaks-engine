"""The core imports only the standard library, its own package and the workspace kits.

``domain/`` and ``ports/`` are the code a client owns outright after an extraction: the policy,
the decisions and the port contracts. A cloud or model SDK import there is lock-in wearing a
green gate. The rule is an allowlist rather than an SDK blocklist, because a blocklist rots the
day a vendor renames a distribution.

Twin of the core-purity section of the fleet-wide portfolio gate,
which repeats this scan across every repository in the workspace. This copy travels with the
repository when it is extracted and handed over, which is exactly when the workspace scan can
no longer see it.

The dynamic blocked-import probe (``tests/contract/_sdk_free_probe.py``) proves the SDK-free
profiles construct with the SDK unimportable; this static scan additionally catches a lazy
import inside a function body on a call path that profile construction never exercises.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"

#: The workspace kits a core may import: stdlib-pure, versioned, owned in this catalog.
ALLOWED_KITS = frozenset(
    {
        "agent_eval_kit",
        "consent_preference_kit",
        "hex_service_kit",
        "review_kit",
        "obligation_register",
        "pii_kit",
        "speech_lexicon_kit",
    }
)

#: The trees that make up the core in this repository.
CORE_LAYERS = ("domain", "ports")

#: Written exemptions: (path relative to the package, import root) -> why it is still here.
#: Debt with a name on it, not an allowance. Delete the row when the import moves out of the
#: core; an import not listed here fails the scan.
EXEMPT_IMPORTS: dict[tuple[str, str], str] = {}

_STDLIB = frozenset(sys.stdlib_module_names)


def _core_trees() -> list[tuple[str, Path]]:
    trees: list[tuple[str, Path]] = []
    for package in sorted(p for p in SRC.iterdir() if (p / "__init__.py").is_file()):
        for layer in CORE_LAYERS:
            if (package / layer).is_dir():
                trees.append((package.name, package / layer))
    return trees


def _violations(
    trees: list[tuple[str, Path]],
    allowed_kits: frozenset[str],
    exemptions: Mapping[tuple[str, str], str] = EXEMPT_IMPORTS,
) -> tuple[int, list[str]]:
    """(files scanned, violation lines). Factored so the control test can aim it at a bad tree."""
    scanned = 0
    found: list[str] = []
    for own_pkg, tree in trees:
        for source in sorted(tree.rglob("*.py")):
            scanned += 1
            within_package = source.relative_to(tree.parent).as_posix()
            syntax = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(syntax):
                if isinstance(node, ast.Import):
                    imported = [(alias.name, node.lineno) for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    imported = [(node.module or "", node.lineno)]
                else:
                    continue
                for dotted, lineno in imported:
                    top = dotted.split(".")[0]
                    if not top or top in _STDLIB or top == own_pkg or top in allowed_kits:
                        continue
                    if (within_package, top) in exemptions:
                        continue
                    location = (
                        source.relative_to(REPO_ROOT)
                        if source.is_relative_to(REPO_ROOT)
                        else source
                    )
                    found.append(f"{location}:{lineno}: imports {top}")
    return scanned, found


def test_the_core_imports_only_what_it_owns() -> None:
    trees = _core_trees()
    assert trees, "no core trees found under src/; a scan of nothing proves nothing"
    scanned, found = _violations(trees, ALLOWED_KITS)
    assert scanned > 0, "core trees exist but hold no python modules; the scan saw nothing"
    assert not found, "the core imports code it does not own:\n" + "\n".join(found)


def test_every_written_exemption_names_a_file_that_still_exists() -> None:
    """The exemption map is debt with an owner, not a blanket escape.

    A row that no longer matches a file in the core is deleted rather than left to quietly
    cover the next violation that lands at the same path.
    """
    packages = [p for p in SRC.iterdir() if (p / "__init__.py").is_file()]
    for (within_package, top), reason in sorted(EXEMPT_IMPORTS.items()):
        assert reason.strip(), f"the exemption for {within_package}:{top} states no reason"
        assert within_package.split("/")[0] in CORE_LAYERS, (
            f"the exemption for {within_package} is outside the core; the scan never reads it"
        )
        assert any((package / within_package).is_file() for package in packages), (
            f"stale exemption: {within_package} no longer exists, so delete the row"
        )


def test_the_scan_can_see_a_violation(tmp_path: Path) -> None:
    """The positive control: a scanner that cannot go red is decoration, not a gate."""
    bad = tmp_path / "domain"
    bad.mkdir()
    (bad / "impure.py").write_text("import boto3\n", encoding="utf-8")
    scanned, found = _violations([("synthetic_pkg", bad)], ALLOWED_KITS, {})
    assert scanned == 1
    assert found and "imports boto3" in found[0]


def test_a_written_exemption_silences_only_its_own_import(tmp_path: Path) -> None:
    """The exemption is keyed by file and import root, so it cannot cover the next one."""
    tree = tmp_path / "domain"
    tree.mkdir()
    (tree / "packs.py").write_text("import yaml\nimport boto3\n", encoding="utf-8")
    exempt = {("domain/packs.py", "yaml"): "the reason this row exists"}
    _, found = _violations([("synthetic_pkg", tree)], ALLOWED_KITS, exempt)
    assert len(found) == 1
    assert "imports boto3" in found[0]


def test_the_scan_treats_relative_and_own_imports_as_owned(tmp_path: Path) -> None:
    """``from . import x`` and imports of the owning package must not false-positive."""
    tree = tmp_path / "domain"
    tree.mkdir()
    (tree / "clean.py").write_text(
        "from . import sibling\nimport json\nfrom synthetic_pkg.ports import thing\n",
        encoding="utf-8",
    )
    scanned, found = _violations([("synthetic_pkg", tree)], ALLOWED_KITS, {})
    assert scanned == 1
    assert not found
