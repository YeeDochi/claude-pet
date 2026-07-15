"""Resolve which `qdbus` executable to invoke for KWin/Konsole D-Bus calls.

Qt6's command-line D-Bus tool is named inconsistently across distros: most
ship it as `qdbus6`, but some use `qdbus-qt6`, a plain `qdbus` (Qt6 or a
symlink), or `qdbus-qt5`. Hardcoding `qdbus6` silently disables every KDE
feature (perch/occlusion feed, click-to-focus, Konsole tab selection) on a
perfectly working KDE that just names the tool differently. Probe the PATH once
and reuse the first name that exists.
"""
import functools
import shutil

# Preference order: the Qt6 name first (what we actually target), then the
# common alternates, then a plain `qdbus`/Qt5 fallback.
CANDIDATES = ("qdbus6", "qdbus-qt6", "qdbus", "qdbus-qt5")


def resolve(candidates, which):
    """First name in `candidates` for which `which(name)` is truthy, else None.

    Pure (no PATH access of its own) so it is unit-testable with a fake `which`;
    `qdbus_bin` wraps it around the real `shutil.which`.
    """
    for name in candidates:
        if which(name):
            return name
    return None


@functools.lru_cache(maxsize=None)
def qdbus_bin():
    """The qdbus executable name to invoke. Resolved once (availability can't
    change mid-session). Falls back to `qdbus6` when none is found so callers
    still build a valid command — it just fails soft (FileNotFoundError, caught
    by the best-effort KDE paths) exactly as the old hardcoded name did.
    """
    return resolve(CANDIDATES, shutil.which) or "qdbus6"
