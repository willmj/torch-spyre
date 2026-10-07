#!/bin/bash
# One-off setup for the nightly sweep. Run by hand once; the CronJob never runs it.
#
# Isolation without a second environment. Three facts make that work, and all
# three were established by testing rather than assumed:
#
#   * The dev venv's editable install resolves torch_spyre through a meta-path
#     finder that is *appended* to sys.meta_path, so the standard PathFinder runs
#     first and PYTHONPATH wins. Verified: PYTHONPATH=~/pr-cpu-time makes
#     torch_spyre resolve there instead of to the dev tree.
#   * torch here is 2.13.0+cpu, a local-version wheel with no copy on the PVC and
#     no index to reinstall it from, so a second venv cannot reproduce the
#     environment. Reading the dev venv is the only honest option.
#   * _C.so is symlinked from the built dev tree, which is exactly what
#     ~/ab4859/tsw-base already does, for the same reason.
#
# So the job reads the dev venv and the dev tree's built extension, and writes
# only under ~/nightly. It installs nothing and never touches the dev checkout.
#
# The home is shared because the image's LD_LIBRARY_PATH hardcodes
# /home/mwj/dt-inductor/sentient (6.2 GB) and _C.so links libflex.so from there.
set -euo pipefail

NIGHTLY="${NIGHTLY_ROOT:-$HOME/nightly}"
REPO="$NIGHTLY/torch-spyre"
DEV="${DEV_REPO:-$HOME/dt-inductor/torch-spyre}"
VENV="${DEV_VENV:-$HOME/.venv}"
GRAFT_BRANCH="${GRAFT_BRANCH:-perf/nightly-integration}"
ORIGIN_URL="${ORIGIN_URL:-https://github.com/willmj/torch-spyre.git}"
UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/torch-spyre/torch-spyre.git}"

echo "=== nightly setup into $NIGHTLY ==="
mkdir -p "$NIGHTLY/history"

[ -f "$DEV/torch_spyre/_C.so" ] || {
    echo "no built extension at $DEV/torch_spyre/_C.so."
    echo "The nightly checkout borrows it, so build the dev tree first."
    exit 1
}

if [ ! -d "$REPO/.git" ]; then
    git clone "$ORIGIN_URL" "$REPO"
fi
cd "$REPO"
# The nightly graft rebases, which needs a committer identity; a fresh clone has
# none and there is no global one in this image. Local to this checkout.
git config user.name  "nightly sweep"
git config user.email "nightly@localhost"
git remote get-url upstream >/dev/null 2>&1 || git remote add upstream "$UPSTREAM_URL"
git fetch upstream main --quiet
git fetch origin "$GRAFT_BRANCH" --quiet
git checkout -B nightly "origin/$GRAFT_BRANCH"

ln -sfn "$DEV/torch_spyre/_C.so" "$REPO/torch_spyre/_C.so"
echo "extension: $(readlink "$REPO/torch_spyre/_C.so")"

# A fresh clone has no _version.py -- it is written at build time, and this job
# does not build. The dev venv's setuptools_scm writes it directly.
source "$VENV/bin/activate"
PYTHONPATH=. python3 -c "
from setuptools_scm import get_version
print('version:', get_version(root='.', relative_to='pyproject.toml',
      version_file='torch_spyre/_version.py',
      version_scheme='semver-pep440-release-branch',
      local_scheme='_versioning:ci_local_scheme'))"

# Seed the trend with the committed baseline so night one has two points rather
# than starting blind. Dated from the baseline's own metadata, not today.
BASE="$REPO/tools/frontend_timing/baseline/baseline-2026-10-02.json"
if [ -f "$BASE" ]; then
    python3 - "$BASE" "$NIGHTLY/history" <<'PY'
import json, os, shutil, sys
src, hist = sys.argv[1:3]
day = json.load(open(src))["meta"]["generated_at"][:10]
d = os.path.join(hist, day)
os.makedirs(d, exist_ok=True)
if not os.path.exists(os.path.join(d, "rows.json")):
    shutil.copy(src, os.path.join(d, "rows.json"))
    json.dump({"state": "ok", "detail": "seeded from the committed baseline",
               "tier": "weekly", "swept_sha": "ac3a4187"},
              open(os.path.join(d, "status.json"), "w"), indent=1)
    print(f"seeded history/{day} from the committed baseline")
PY
fi

echo "=== setup done. Prove it end to end before scheduling: ==="
echo "  bash $REPO/tools/frontend_timing/nightly/run_nightly.sh"
