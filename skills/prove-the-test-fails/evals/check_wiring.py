#!/usr/bin/env python3
"""Checks the skill's frontmatter and its marketplace entry.

The marketplace manifest is shared, so another skill's pull request can edit this
skill out of it without touching a file in this directory. Nothing here needs
credentials or a network.
"""

import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_NAME = SKILL_DIR.name
REPO_ROOT = SKILL_DIR.parent.parent
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"

failures: list[str] = []


def require(condition: object, message: str) -> None:
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}")
        failures.append(message)


frontmatter = re.match(r"---\n(.*?)\n---\n", (SKILL_DIR / "SKILL.md").read_text(), re.S)
require(frontmatter, "SKILL.md opens with YAML frontmatter")

if frontmatter:
    fields = dict(re.findall(r"^([a-z-]+):[ ]*(.+)$", frontmatter.group(1), re.M))
    require(fields.get("name") == SKILL_NAME, f"frontmatter name is {SKILL_NAME}")
    require(len(fields.get("description", "")) > 80, "description is long enough to trigger on")

entries = [
    entry
    for entry in json.loads(MARKETPLACE.read_text())["plugins"]
    if f"./skills/{SKILL_NAME}" in entry.get("skills", [])
]
require(len(entries) == 1, "exactly one marketplace entry loads this skill")

if len(entries) == 1:
    entry = entries[0]
    require(entry["source"] == "./", "the entry's source is the marketplace root")
    require(
        entry.get("strict") is False,
        "the entry is strict: false, since the root has no plugin.json",
    )
    require(
        "version" not in entry, "the entry carries no version, so it resolves from the commit SHA"
    )
    require(entry.get("description"), "the entry has a description for the plugin picker")

if failures:
    sys.exit(f"FAIL: {len(failures)} wiring problem(s).")
print("PASS: the skill is packaged and listed correctly.")
