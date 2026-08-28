"""The Agent Plugins directory is rendered from this repo's declarations, never hand-authored.

A manifest typed out by hand is a second description of the service, and a second description is
one that can be wrong. So the only thing worth guarding is that the rendered directory still
says what the repo says, and that it does so from the moment the repo is generated.

**A freshly generated repo has no vendored skills and no MCP server, and neither absence is a
defect.** Skills arrive when the maintainer's ``sync-skills.sh`` runs; a server exists only once
this repo declares a governed tool catalog and serves it. ``render_plugin`` detects both rather
than assuming them, and the guards below cover the empty case explicitly, because that is the
state every new repo starts in and therefore the one most likely to go unexercised.
"""

from __future__ import annotations

import json
import pathlib
import sys

import jsonschema
import pytest
from hex_service_kit.plugin import load_schema

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _render(tmp_path: pathlib.Path) -> pathlib.Path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import render_plugin

    render_plugin.main(["--dest", str(tmp_path / "plugin")])
    return tmp_path / "plugin"


@pytest.fixture
def rendered(tmp_path: pathlib.Path) -> pathlib.Path:
    return _render(tmp_path)


def test_the_manifest_validates_against_the_vendored_specification_schema(
    rendered: pathlib.Path,
) -> None:
    """``jsonschema`` is a hard dev dependency so this can never quietly skip into green."""
    manifest = json.loads((rendered / "plugin.json").read_text())

    jsonschema.validate(manifest, load_schema("plugin"))


def test_the_manifest_advertises_exactly_what_this_repo_declares(rendered: pathlib.Path) -> None:
    """Keywords come from the declarations, so they cannot drift into a separate description."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import render_plugin

    manifest = json.loads((rendered / "plugin.json").read_text())
    declared = {name.replace("_", "-") for name in render_plugin._capability_ids()}

    assert declared, "a repo that declares no capability at all would render an empty plugin"
    assert set(manifest["keywords"]) == declared


def test_no_server_is_advertised_until_one_exists(rendered: pathlib.Path) -> None:
    """Advertising a server no module answers is the declared-and-unperformable defect, one
    layer out: a client would install the plugin and spawn a process that is not there.

    This repo grows an MCP server when it has a catalog worth serving. Until then ``mcp.json``
    must be absent rather than present and empty.
    """
    import importlib.util

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import render_plugin

    serves = importlib.util.find_spec(f"{render_plugin.PACKAGE}.mcp") is not None

    assert (rendered / "mcp.json").exists() is serves


def test_skills_are_copied_when_vendored_and_absent_otherwise(rendered: pathlib.Path) -> None:
    """The other half of the same rule, for the directory ``sync-skills.sh`` fills in.

    A skills source that is not a directory makes the kit refuse, which is right: a path that
    silently contributed nothing would render an empty plugin that looks complete. A repo
    generated five minutes ago genuinely has none, so ``render_plugin`` reports the absence
    rather than passing a path that will fail.
    """
    vendored = REPO_ROOT / ".agents" / "skills"
    expected = (
        {child.name for child in vendored.iterdir() if (child / "SKILL.md").is_file()}
        if vendored.is_dir()
        else set()
    )

    copied = (
        {child.name for child in (rendered / "skills").iterdir()}
        if (rendered / "skills").is_dir()
        else set()
    )

    assert copied == expected
