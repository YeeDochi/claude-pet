#!/usr/bin/env bash
# Release helper — bump __version__, commit, tag, push. The publish.yml workflow
# then builds + uploads to PyPI (Trusted Publishing) on the pushed tag.
#
#   scripts/release.sh <patch|minor|major|X.Y.Z> [--dry-run] [--yes]
#
# Runs from the repo's Linux dev checkout (releases happen here). Aborts unless
# on a clean master in sync with origin, tests pass, and the tag is new.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="$ROOT/src/claudlet/__init__.py"

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
usage() { echo "usage: scripts/release.sh <patch|minor|major|X.Y.Z> [--dry-run] [--yes]"; exit 2; }

DRY_RUN=0; ASSUME_YES=0; BUMP=""
for a in "$@"; do
  case "$a" in
    --dry-run)          DRY_RUN=1 ;;
    --yes|-y)           ASSUME_YES=1 ;;
    patch|minor|major)  BUMP="$a" ;;
    [0-9]*.[0-9]*.[0-9]*) BUMP="$a" ;;
    *) echo "unknown arg: $a" >&2; usage ;;
  esac
done
[ -n "$BUMP" ] || usage

cd "$ROOT"

CUR="$(python3 -c "import re,pathlib;print(re.search(r'__version__\s*=\s*\"([^\"]+)\"',pathlib.Path('$VERSION_FILE').read_text()).group(1))")"
[ -n "$CUR" ] || die "could not read __version__ from $VERSION_FILE"

if [ "$BUMP" = patch ] || [ "$BUMP" = minor ] || [ "$BUMP" = major ]; then
  IFS=. read -r MA MI PA <<<"$CUR"
  case "$BUMP" in
    major) MA=$((MA + 1)); MI=0; PA=0 ;;
    minor) MI=$((MI + 1)); PA=0 ;;
    patch) PA=$((PA + 1)) ;;
  esac
  NEW="$MA.$MI.$PA"
else
  NEW="$BUMP"
fi
TAG="v$NEW"
say "current $CUR  ->  new $NEW  (tag $TAG)"

# ---- preflight (if-blocks so `set -e` doesn't abort on the check itself) ----
if [ "$(git branch --show-current)" != master ]; then die "not on master"; fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "working tree not clean — commit or stash first"
fi
say "fetching origin..."
git fetch --quiet origin
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/master)" ]; then
  die "local master not in sync with origin/master — push/pull first"
fi
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1; then
  die "tag $TAG already exists locally"
fi
if git ls-remote --exit-code --tags origin "$TAG" >/dev/null 2>&1; then
  die "tag $TAG already exists on origin"
fi

say "running tests..."
if ! python3 -m pytest -q; then die "tests failed — aborting release"; fi

if [ "$DRY_RUN" = 1 ]; then
  say "[dry-run] would set __version__=$NEW, commit 'release $TAG', tag $TAG, push origin master + $TAG"
  exit 0
fi

if [ "$ASSUME_YES" != 1 ]; then
  printf 'release %s? this commits, tags, and PUSHES (CI then publishes to PyPI). [y/N] ' "$TAG"
  read -r ans
  case "$ans" in [yY]|[yY][eE][sS]) ;; *) echo "aborted."; exit 1 ;; esac
fi

python3 - "$VERSION_FILE" "$NEW" <<'PY'
import re, sys, pathlib
path, new = sys.argv[1], sys.argv[2]
p = pathlib.Path(path)
p.write_text(re.sub(r'(__version__\s*=\s*")[^"]+(")', r'\g<1>' + new + r'\g<2>', p.read_text()))
PY

git add "$VERSION_FILE"
git commit -q -m "release $TAG"
git tag -a "$TAG" -m "claudlet $TAG"
say "pushing master + $TAG..."
git push origin master
git push origin "$TAG"
say "done — CI publishes to PyPI: https://github.com/YeeDochi/Claudlet/actions"
say "verify with:  claudlet-version   (or: pipx upgrade claudlet)"
