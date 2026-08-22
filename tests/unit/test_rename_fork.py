"""The command name and the package name are the same token, and must stay separable.

``[project.scripts]`` in this repo declares ``<package> = "<package>.cli.main:main"``: the
console-script NAME and the python package NAME are spelled identically. Any rename that matched
either of them bare would consume every occurrence and leave the other doing nothing, so an
adopter running ``rename_fork.py`` with ``--cli`` different from ``--package`` would silently get
one of the two flags ignored, and would find out only after the fork was already published.

``_rules`` keeps them separable by anchoring the CLI on the shapes a command NAME actually appears
in (the ``[project.scripts]`` key, and a documented shell invocation) and letting the bare package
rule take every other occurrence, with the whole set applied as ONE simultaneous alternation so no
rule can rewrite another rule's output. That correctness lives entirely in the rule ORDER and in
the anchors; nothing about the constants shows it, and a later refactor to a plain sequential
search-and-replace would reintroduce the collapse while every other test stayed green.

The last test here is the one that stops the rest being decorative: it runs the same input through
the same pass with the CLI anchors removed and proves the collapse is real, so these assertions are
known to be capable of failing rather than merely believed to be.
"""

from __future__ import annotations

import importlib.util
from argparse import Namespace
from types import ModuleType

from tests import REPO_ROOT

_SCRIPT = REPO_ROOT / "scripts" / "rename_fork.py"


def _load_script() -> ModuleType:
    """Load the script by path: it is a standalone file, not an importable installed module."""
    spec = importlib.util.spec_from_file_location("rename_fork", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MODULE = _load_script()


def _args() -> Namespace:
    """A fork that deliberately names its command and its package DIFFERENTLY.

    If the two were spelled alike here (as they are upstream) every assertion below would pass
    whichever token won, which is exactly the bug this file exists to catch.
    """
    return Namespace(
        package="acme_migration",
        cli="acme-migrate",
        env_prefix="ACME",
        resource="acme-migrate",
        dist="acme-migration",
    )


def _apply(text: str, rules: list[tuple[str, str, str]]) -> str:
    pattern, replacements = _MODULE._compile(rules)
    rewritten, _ = _MODULE._rewrite(text, pattern, replacements)
    return rewritten


def test_the_console_script_key_and_its_module_path_are_renamed_independently() -> None:
    """One line, two different answers: the key takes --cli, the import path takes --package."""
    declaration = (
        f'[project.scripts]\n{_MODULE._OLD_CLI} = "{_MODULE._OLD_PACKAGE}.cli.main:main"\n'
    )

    rewritten = _apply(declaration, _MODULE._rules(_args()))

    assert rewritten == ('[project.scripts]\nacme-migrate = "acme_migration.cli.main:main"\n')


def test_import_paths_take_the_package_name_and_never_the_command_name() -> None:
    """A module path is not a command, however much the token looks like one."""
    source = (
        f"import {_MODULE._OLD_PACKAGE}\n"
        f"from {_MODULE._OLD_PACKAGE}.domain import model\n"
        f"python -m {_MODULE._OLD_PACKAGE}.api.app\n"
    )

    rewritten = _apply(source, _MODULE._rules(_args()))

    assert rewritten == (
        "import acme_migration\n"
        "from acme_migration.domain import model\n"
        "python -m acme_migration.api.app\n"
    )


def test_a_documented_shell_invocation_becomes_the_command() -> None:
    docs = f"{_MODULE._OLD_CLI} plan --profile local\n"

    rewritten = _apply(docs, _MODULE._rules(_args()))

    assert rewritten == "acme-migrate plan --profile local\n"


def test_the_scripts_own_constants_are_each_rewritten_to_their_own_value() -> None:
    """A fork must be able to rename itself a SECOND time.

    Both constants hold the same string upstream, so if either rule took both lines the fork's
    copy of this script would carry one name for two different things.
    """
    constants = f'_OLD_PACKAGE = "{_MODULE._OLD_PACKAGE}"\n_OLD_CLI = "{_MODULE._OLD_CLI}"\n'

    rewritten = _apply(constants, _MODULE._rules(_args()))

    assert rewritten == '_OLD_PACKAGE = "acme_migration"\n_OLD_CLI = "acme-migrate"\n'


def test_without_the_cli_anchors_the_command_name_collapses_into_the_package() -> None:
    """The anchors are load-bearing, and this is what their absence costs.

    Same input, same single pass, only the CLI rules removed: the bare package rule then takes the
    ``[project.scripts]`` key as well, the console script is renamed to the package name, and
    ``--cli`` has silently done nothing. Exercised rather than assumed, so the assertions above
    are known to be able to go red.
    """
    declaration = f'{_MODULE._OLD_CLI} = "{_MODULE._OLD_PACKAGE}.cli.main:main"'
    anchored = _MODULE._rules(_args())
    unanchored = [rule for rule in anchored if rule[0] != "cli"]

    collapsed = _apply(declaration, unanchored)
    correct = _apply(declaration, anchored)

    assert collapsed == 'acme_migration = "acme_migration.cli.main:main"'
    assert correct == 'acme-migrate = "acme_migration.cli.main:main"'
    assert collapsed != correct
