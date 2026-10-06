#!/bin/bash
# One-off setup for the nightly sweep. Run by hand on the dev pod, not by the
# CronJob: it clones, creates a venv and does one full build, which is ~20 min.
#
# Why a second venv rather than reusing ~/.venv: that one's editable install maps
# torch_spyre to the absolute path ~/dt-inductor/torch-spyre, so anything using it
# imports the dev checkout -- whatever is there and dirty at 2am. This PVC already
# carries two venvs, so a third is the established shape.
#
# The home stays shared because the image's LD_LIBRARY_PATH hardcodes
# /home/mwj/dt-inductor/sentient (6.2 GB) and the built _C.so links libflex.so
# from it. A private home would mean duplicating that runtime.
set -euo pipefail

NIGHTLY="${NIGHTLY_ROOT:-$HOME/nightly}"
REPO="$NIGHTLY/torch-spyre"
VENV="$NIGHTLY/.venv"
GRAFT_BRANCH="${GRAFT_BRANCH:-perf/nightly-integration}"
ORIGIN_URL="${ORIGIN_URL:-https://github.com/willmj/torch-spyre.git}"
UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/torch-spyre/torch-spyre.git}"

echo "=== nightly setup into $NIGHTLY ==="
mkdir -p "$NIGHTLY/history"

if [ ! -d "$REPO/.git" ]; then
    git clone "$ORIGIN_URL" "$REPO"
fi
cd "$REPO"
git remote get-url upstream >/dev/null 2>&1 || git remote add upstream "$UPSTREAM_URL"
git fetch upstream main --quiet
git fetch origin "$GRAFT_BRANCH" --quiet
git checkout -B nightly "origin/$GRAFT_BRANCH"

if [ ! -d "$VENV" ]; then
    # Match the dev venv's interpreter; uv because this PVC has no pip in its venvs.
    uv venv "$VENV" --python python3.12
fi
source "$VENV/bin/activate"
uv pip install "setuptools_scm>=10"
PYTHONPATH=. python3 -c "
from setuptools_scm import get_version
get_version(root='.', relative_to='pyproject.toml',
            version_file='torch_spyre/_version.py',
            version_scheme='semver-pep440-release-branch',
            local_scheme='_versioning:ci_local_scheme')"

echo "=== first build (slow; later nights are incremental) ==="
uv pip install -e . --no-build-isolation

# Seed the trend with the committed baseline, so night one has two points rather
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

echo "=== setup done. Smoke it before scheduling: ==="
echo "  bash $REPO/tools/frontend_timing/nightly/run_nightly.sh"
