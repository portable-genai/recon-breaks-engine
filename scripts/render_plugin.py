#!/usr/bin/env python3
"""Render this repo's Agent Plugins 1.0.0 directory from what it already declares.

Nothing here is hand-authored. Identity comes from the A2A agent card the repo already
publishes, keywords from what that card says the agent can do, and ``skills/`` from
``.agents/skills``. A manifest typed out by hand would be a second description of the service,
and a second description is one that can be wrong.

Agent Plugins packages TOOLING and carries no data-portability mechanism, so nothing here
touches the evidence trail: the ledger keeps its own export format, and a plugin only ever
REACHES it through the kit's read-only tools.

**Two parts are conditional, because a freshly generated repo has neither yet, and neither
absence is a defect.** Skills arrive when the maintainer's ``sync-skills.sh`` vendors them, and
an MCP server exists only once this repo declares a governed tool catalog and serves it. Both
are DETECTED rather than assumed: a repo that has grown either gets it in the manifest, and one
that has not renders a valid skills-only plugin instead of failing. Detecting beats a flag,
because a flag is a second place to remember.

Run it with ``make plugin``; the output is build output and is not committed.
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys
from importlib import import_module

from hex_service_kit.plugin import (
    Author,
    PluginSpec,
    Server,
    StdioServer,
    keywords_from_skill_ids,
    render,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DEST = REPO_ROOT / "dist" / "plugin"

PACKAGE = "recon_breaks_engine"
PROJECT = "recon-breaks-engine"


def _skills_source() -> pathlib.Path | None:
    """``.agents/skills`` when it has been vendored, otherwise nothing.

    The kit refuses a skills source that is not a directory, and rightly: a path that silently
    contributed no skills would render an empty plugin that looks complete. A repo generated
    five minutes ago genuinely has none, so the absence is reported as None rather than as a
    path that will fail.
    """
    source = REPO_ROOT / ".agents" / "skills"
    return source if source.is_dir() else None


def _servers() -> dict[str, Server]:
    """An MCP server entry only when this repo actually serves its catalog.

    Declaring a server in the manifest that no module answers would be the same defect the
    catalog itself is guarded against, one layer out: a client would install the plugin and
    spawn a process that is not there.
    """
    if importlib.util.find_spec(f"{PACKAGE}.mcp") is None:
        return {}
    return {
        PROJECT: StdioServer(
            command="python",
            args=("-m", f"{PACKAGE}.mcp"),
            cwd="${PLUGIN_ROOT}",
        )
    }


def _capability_ids() -> list[str]:
    """What this agent can do, from the governed tool catalog when there is one.

    The catalog is the stricter source, because every tool in it carries a JSON Schema and is
    bound to a callable at start-up. Falling back to the agent card's skills keeps a repo that
    declares no catalog describable, which is the whole point of a skills-only plugin.
    """
    catalog_path = f"{PACKAGE}.adapters.gcp.mcp_tool_catalog"
    if importlib.util.find_spec(catalog_path) is not None:
        catalog_module = import_module(catalog_path)
        settings = import_module(f"{PACKAGE}.config").Settings.load()
        adapter = catalog_module.McpToolCatalogAdapter(settings)
        return [spec.name for spec in adapter.list_tools()]

    card_module = import_module(f"{PACKAGE}.agent.agent_card")
    return [skill.id for skill in card_module.SKILLS]


def build_spec() -> PluginSpec:
    """Assemble the spec from this repo's own declarations, never from literals."""
    card = import_module(f"{PACKAGE}.agent.agent_card").agent_card_document()

    def _field(name: str) -> str:
        if isinstance(card, dict):
            return str(card.get(name) or "")
        return str(getattr(card, name, "") or "")

    return PluginSpec(
        name=PROJECT,
        version=_field("version") or "0.0.1",
        description=_field("description"),
        license="Apache-2.0",
        repository=f"https://github.com/portable-genai/{PROJECT}",
        # Card skills and catalog tools are CAPABILITIES and reach a client as MCP tools
        # through mcp.json, not as files. They land in the manifest only as keywords.
        keywords=keywords_from_skill_ids(_capability_ids()),
        author=Author(name="portable-genai"),
        servers=_servers(),
        skills_source=_skills_source(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=pathlib.Path, default=DEFAULT_DEST)
    args = parser.parse_args(argv)
    report = render(build_spec(), args.dest)
    print(f"rendered {report.root}: {len(report.skills)} skills, {len(report.servers)} server(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
