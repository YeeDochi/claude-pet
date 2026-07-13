#!/usr/bin/env python3
"""Turn a range of conventional-commit subjects into a grouped Markdown
changelog — the English auto-draft that seeds each release's notes.

Pure and data-driven (no git, no IO), so it unit-tests off a plain list of
subject strings. `scripts/release_notes.py` is the thin wrapper that feeds it
`git log --pretty=%s <prev>..<cur>`.

Final release notes are bilingual and hand-finished by whoever cuts the release
(usually in a Claude Code session); this module produces the always-available
fallback/skeleton so a release is never left with empty notes. Section headers
are already bilingual ("한글 · English") so even the raw auto-draft reads in both.
"""
import re

# Ordered: sections render in this order. Each conventional-commit `type` maps
# to a section key; several types can share one section (chore/build/ci).
# key -> (emoji, korean, english)
SECTIONS = [
    ("feat",     ("✨", "새 기능", "Features")),
    ("fix",      ("🐛", "수정", "Fixes")),
    ("perf",     ("⚡", "성능", "Performance")),
    ("refactor", ("♻️", "리팩터", "Refactor")),
    ("docs",     ("📝", "문서", "Docs")),
    ("test",     ("✅", "테스트", "Tests")),
    ("chore",    ("🔧", "기타", "Chore / Build / CI")),
    ("other",    ("📦", "그 외", "Other")),
]
_SECTION_KEYS = {k for k, _ in SECTIONS}

# type token (as written in commits) -> section key above.
TYPE_TO_SECTION = {
    "feat": "feat",
    "fix": "fix",
    "perf": "perf",
    "refactor": "refactor",
    "docs": "docs",
    "test": "test",
    "tests": "test",
    "chore": "chore",
    "build": "chore",
    "ci": "chore",
    "style": "chore",
}

# `type(scope)!: desc` / `type: desc` — scope and the `!` breaking-marker optional.
_CONV = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<desc>.+)$")

# subjects that are noise in a changelog: the release commit itself, merges.
_SKIP = re.compile(r"^(release\s+v?\d|merge\b)", re.IGNORECASE)


def parse_subject(subject):
    """One commit subject -> (section_key, scope, desc, breaking). A subject that
    isn't conventional-commit shaped falls into the 'other' section with its full
    text as desc. Returns None for subjects that should be skipped entirely."""
    s = (subject or "").strip()
    if not s or _SKIP.match(s):
        return None
    m = _CONV.match(s)
    if not m:
        return ("other", "", s, False)
    section = TYPE_TO_SECTION.get(m.group("type"), "other")
    return (section, (m.group("scope") or "").strip(),
            m.group("desc").strip(), bool(m.group("bang")))


def group(subjects):
    """Subjects -> {section_key: [(scope, desc, breaking), ...]} preserving input
    order within each section. Skipped/empty subjects are dropped."""
    out = {}
    for subj in subjects:
        parsed = parse_subject(subj)
        if parsed is None:
            continue
        section, scope, desc, breaking = parsed
        out.setdefault(section, []).append((scope, desc, breaking))
    return out


def _format_entry(scope, desc, breaking):
    prefix = "**⚠ BREAKING** " if breaking else ""
    if scope:
        return "- %s**%s:** %s" % (prefix, scope, desc)
    return "- %s%s" % (prefix, desc)


def render_notes(subjects, empty="_기타 변경 없음 · No notable changes._"):
    """Grouped bilingual-headed Markdown changelog for `subjects`. Only sections
    that have entries are emitted, in SECTIONS order. `empty` is returned when
    nothing survives filtering (so callers always get a non-empty body)."""
    grouped = group(subjects)
    blocks = []
    for key, (emoji, ko, en) in SECTIONS:
        entries = grouped.get(key)
        if not entries:
            continue
        header = "## %s %s · %s" % (emoji, ko, en)
        lines = [_format_entry(sc, de, br) for sc, de, br in entries]
        blocks.append(header + "\n" + "\n".join(lines))
    return "\n\n".join(blocks) if blocks else empty
