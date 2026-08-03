#!/usr/bin/env python3
"""Structural checks for the parallel-agent-isolation skill.

A skill fails silently when its packaging is wrong: an unparsed frontmatter
block, a name that no longer matches the directory, or a marketplace entry that
does not point at the skill directory all leave the skill installed and never
loaded. These checks run without an API key so they can gate every PR.

Stdlib only, and the frontmatter is parsed by hand, because a top-level skill
directory has no dependency manifest to hang PyYAML off.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_DIR.parent.parent
SKILL_NAME = SKILL_DIR.name

# Claude Code truncates the combined description and when_to_use text at this
# many characters in the skill listing, so anything past it never reaches the
# model that decides whether to load the skill.
LISTING_CAP = 1536

failures: list[str] = []


def check(condition: bool, message: str) -> bool:
    if not condition:
        failures.append(message)
    return condition


def parse_frontmatter(text: str) -> dict[str, str]:
    """Read a `key: value` frontmatter block, one entry per line."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        failures.append("SKILL.md does not open with a --- frontmatter fence")
        return {}
    try:
        end = lines.index("---", 1)
    except ValueError:
        failures.append("SKILL.md frontmatter is never closed with ---")
        return {}

    fields: dict[str, str] = {}
    for lineno, line in enumerate(lines[1:end], start=2):
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip() or key.startswith((" ", "\t")):
            failures.append(
                f"SKILL.md line {lineno} is not a single-line `key: value` entry: {line!r}"
            )
            continue
        fields[key.strip()] = value.strip()
    return fields


def check_skill_md() -> None:
    path = SKILL_DIR / "SKILL.md"
    if not check(path.is_file(), f"missing {path}"):
        return
    fields = parse_frontmatter(path.read_text())

    check(
        fields.get("name") == SKILL_NAME,
        f"frontmatter name is {fields.get('name')!r}, expected the directory name {SKILL_NAME!r}",
    )
    check(
        bool(fields.get("description")),
        "frontmatter has no description, so nothing tells Claude when to load the skill",
    )

    listing = f"{fields.get('description', '')} {fields.get('when_to_use', '')}".strip()
    check(
        len(listing) <= LISTING_CAP,
        f"description plus when_to_use is {len(listing)} characters and is truncated at {LISTING_CAP}",
    )

    body = path.read_text().split("---", 2)[-1]
    check(
        bool(body.strip()),
        "SKILL.md has frontmatter but no body, so the skill loads and says nothing",
    )


def check_marketplace_entry() -> None:
    path = REPO_ROOT / ".claude-plugin" / "marketplace.json"
    if not check(path.is_file(), f"missing {path}"):
        return
    manifest = json.loads(path.read_text())

    entries = [p for p in manifest.get("plugins", []) if p.get("name") == SKILL_NAME]
    if not check(
        len(entries) == 1,
        f"expected exactly one marketplace entry named {SKILL_NAME!r}, found {len(entries)}",
    ):
        return
    entry = entries[0]

    check(
        entry.get("source") == "./",
        f"entry source is {entry.get('source')!r}, expected './' for a marketplace-root skill",
    )
    check(
        entry.get("strict") is False,
        "entry must set strict to false: there is no plugin.json at the repository root to be the authority",
    )
    check(
        entry.get("skills") == [f"./skills/{SKILL_NAME}"],
        f"entry skills is {entry.get('skills')!r}, expected ['./skills/{SKILL_NAME}']",
    )
    check(
        bool(entry.get("description")),
        "entry has no description, so the plugin listing shows nothing",
    )
    check(
        "version" not in entry,
        "entry pins a version; omit it so the commit SHA is the version and installed copies refresh on every change",
    )


def check_cases() -> None:
    cases_dir = SKILL_DIR / "evals" / "cases"
    cases = sorted(p for p in cases_dir.iterdir() if p.is_dir()) if cases_dir.is_dir() else []
    if not check(len(cases) >= 2, f"expected at least two eval cases in {cases_dir}"):
        return

    expectations = set()
    for case in cases:
        if not check((case / "prompt.md").is_file(), f"{case.name}: missing prompt.md"):
            continue
        spec_path = case / "case.json"
        if not check(spec_path.is_file(), f"{case.name}: missing case.json"):
            continue
        spec = json.loads(spec_path.read_text())
        if check(
            isinstance(spec.get("expect_skill"), bool),
            f"{case.name}: expect_skill must be a boolean",
        ):
            expectations.add(spec["expect_skill"])
        if spec["expect_skill"]:
            check(
                bool(spec.get("rubric")),
                f"{case.name}: a triggering case needs a rubric to grade the answer against",
            )

    check(
        expectations == {True, False},
        "the case set needs both a case the skill must load for and one it must stay out of; a description that "
        "triggers on everything is not a working description",
    )


check_skill_md()
check_marketplace_entry()
check_cases()

for failure in failures:
    print(f"FAIL: {failure}", file=sys.stderr)
if failures:
    sys.exit(1)
print(f"ok: {SKILL_NAME} packaging, marketplace entry, and eval cases")
