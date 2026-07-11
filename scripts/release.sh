#!/usr/bin/env bash
# Release helper (git-flow lite). Run this from `develop` when you want to ship:
# it bumps __version__, fast-forwards `master` to develop, tags, and pushes
# develop + master + tag. The publish.yml workflow then builds + uploads to PyPI
# (Trusted Publishing) on the pushed tag.
#
#   scripts/release.sh <patch|minor|major|X.Y.Z> [--dry-run] [--yes]
#
# Model: develop = working/edge branch, master = released tags only. Runs from
# the Linux dev checkout. Pushing IS intended here — invoking this script is the
# deliberate "release now" action.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="$ROOT/src/claudlet/__init__.py"

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
usage() { echo "usage: scripts/release.sh <patch|minor|major|X.Y.Z> [--dry-run] [--yes]"; exit 2; }

DRY_RUN=0; ASSUME_YES=0; BUMP=""
for a in "$@"; do
  case "$a" in
    --dry-run)            DRY_RUN=1 ;;
    --yes|-y)             ASSUME_YES=1 ;;
    patch|minor|major)    BUMP="$a" ;;
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
if [ "$(git branch --show-current)" != develop ]; then die "not on develop (work + release happen on develop)"; fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "working tree not clean — commit or stash first"
fi
say "fetching origin..."
git fetch --quiet origin
# local develop must not be BEHIND / diverged from origin/develop (we're about to push it)
if git rev-parse -q --verify origin/develop >/dev/null 2>&1; then
  if ! git merge-base --is-ancestor origin/develop develop; then
    die "local develop is behind/diverged from origin/develop — pull/rebase first"
  fi
fi
# master must be an ancestor of develop so it can fast-forward (no master-only commits)
if ! git merge-base --is-ancestor master develop; then
  die "master has commits not in develop — merge master into develop first"
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
  say "[dry-run] would: bump __version__=$NEW on develop, ff master -> develop, tag $TAG,"
  say "[dry-run]        push origin develop + master + $TAG (CI then publishes to PyPI)"
  exit 0
fi

if [ "$ASSUME_YES" != 1 ]; then
  printf 'release %s? bumps develop, fast-forwards master, tags, and PUSHES all three (CI publishes to PyPI). [y/N] ' "$TAG"
  read -r ans
  case "$ans" in [yY]|[yY][eE][sS]) ;; *) echo "aborted."; exit 1 ;; esac
fi

# bump + commit on develop
python3 - "$VERSION_FILE" "$NEW" <<'PY'
import re, sys, pathlib
path, new = sys.argv[1], sys.argv[2]
p = pathlib.Path(path)
p.write_text(re.sub(r'(__version__\s*=\s*")[^"]+(")', r'\g<1>' + new + r'\g<2>', p.read_text()))
PY
git add "$VERSION_FILE"
git commit -q -m "release $TAG"

# fast-forward master to the release commit, tag it there
git checkout -q master
git merge --ff-only develop
git tag -a "$TAG" -m "claudlet $TAG"

say "pushing develop + master + $TAG..."
git push origin develop
git push origin master
git push origin "$TAG"

git checkout -q develop
say "done — CI publishes to PyPI: https://github.com/YeeDochi/Claudlet/actions"
say "verify with:  claudlet-version   (or: pipx upgrade claudlet)"
