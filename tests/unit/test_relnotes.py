"""Behaviour of the release-notes renderer: commit subjects in -> grouped
bilingual Markdown out. Pure data tests (no git), per the repo's testing rule."""
from claudlet.core import relnotes


def test_parse_conventional_with_scope():
    assert relnotes.parse_subject("feat(install): show README link") == (
        "feat", "install", "show README link", False)


def test_parse_conventional_no_scope():
    assert relnotes.parse_subject("fix: stop crash") == ("fix", "", "stop crash", False)


def test_parse_breaking_marker():
    section, scope, desc, breaking = relnotes.parse_subject("feat(api)!: drop v1")
    assert (section, scope, desc, breaking) == ("feat", "api", "drop v1", True)


def test_build_ci_chore_share_one_section():
    assert relnotes.parse_subject("build: bump")[0] == "chore"
    assert relnotes.parse_subject("ci: cache")[0] == "chore"
    assert relnotes.parse_subject("chore: tidy")[0] == "chore"


def test_non_conventional_goes_to_other():
    assert relnotes.parse_subject("random note") == ("other", "", "random note", False)


def test_release_and_merge_subjects_skipped():
    assert relnotes.parse_subject("release v0.3.1") is None
    assert relnotes.parse_subject("Merge branch 'x'") is None
    assert relnotes.parse_subject("   ") is None


def test_render_orders_sections_and_uses_bilingual_headers():
    md = relnotes.render_notes([
        "docs: tweak readme",
        "feat(x): add thing",
        "fix: squash bug",
    ])
    # section order is Features, Fixes, ... Docs regardless of input order
    assert md.index("Features") < md.index("Fixes") < md.index("Docs")
    assert "## ✨ 새 기능 · Features" in md
    assert "## 🐛 수정 · Fixes" in md
    assert "- **x:** add thing" in md
    assert "- squash bug" in md


def test_render_omits_empty_sections():
    md = relnotes.render_notes(["feat: only a feature"])
    assert "Features" in md
    assert "Fixes" not in md and "Docs" not in md


def test_render_empty_returns_fallback():
    assert relnotes.render_notes(["release v1.0.0", "Merge x"]) == relnotes.render_notes([])
    assert "No notable changes" in relnotes.render_notes([])


def test_breaking_entry_is_flagged():
    md = relnotes.render_notes(["feat!: big change"])
    assert "⚠ BREAKING" in md
