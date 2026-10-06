#!/bin/bash
# One night of the frontend sweep: graft, build, smoke, sweep, summarize, render.
#
# Run by the mwj-frontend-sweep-nightly CronJob, and by hand for a catch-up run.
# Every exit path writes status.json, because a gap in the dashboard has to be
# explained rather than mysterious: a flat line across a skipped night would
# otherwise read as "nothing changed".
#
# Isolation: this uses ~/nightly/.venv against ~/nightly/torch-spyre and never
# activates ~/.venv, whose editable install points at the dev checkout. See the
# CronJob manifest for why the home is shared.
set -uo pipefail

NIGHTLY="${NIGHTLY_ROOT:-$HOME/nightly}"
REPO="$NIGHTLY/torch-spyre"
VENV="$NIGHTLY/.venv"
GRAFT_BRANCH="${GRAFT_BRANCH:-perf/nightly-integration}"
TIER="${SWEEP_TIER:-nightly}"
SAMPLES="${SWEEP_SAMPLES:-3}"
UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/torch-spyre/torch-spyre.git}"

DAY="$(date +%Y-%m-%d)"
OUT="$NIGHTLY/history/$DAY"
mkdir -p "$OUT"
LOG="$OUT/run.log"
exec > >(tee -a "$LOG") 2>&1

STARTED="$(date -Is)"
echo "=== nightly sweep $DAY started $STARTED ==="

# status.json is the contract with the dashboard. Written on every path.
status() {   # status <state> <detail>
    python3 - "$OUT/status.json" "$1" "$2" "$STARTED" "$GRAFT_BRANCH" "$TIER" <<'PY'
import json, subprocess, sys, datetime
path, state, detail, started, graft, tier = sys.argv[1:7]
def sh(*a):
    try:
        return subprocess.run(a, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""
json.dump({
    "state": state,                 # ok | skipped | failed
    "detail": detail,
    "started": started,
    "finished": datetime.datetime.now().astimezone().isoformat(),
    "graft_branch": graft,
    "tier": tier,
    # The sha of the tree that actually ran. Without it a reader cannot tell a
    # night where nothing changed from a night that measured the wrong tree.
    "main_sha": sh("git", "rev-parse", "--short", "upstream/main"),
    "swept_sha": sh("git", "rev-parse", "--short", "HEAD"),
}, open(path, "w"), indent=1)
PY
    echo "=== status: $1 ($2) ==="
}

cd "$REPO" 2>/dev/null || { mkdir -p "$OUT"; status failed "no checkout at $REPO; run setup_nightly.sh"; exit 1; }

# ---- 1. graft ------------------------------------------------------------
# One conflict surface by design: the integration branch carries every piece of
# instrumentation, and this rebases it onto today's main. async_compile.py has
# conflicted three times in nine days, so the abort path is the common one.
git remote get-url upstream >/dev/null 2>&1 || git remote add upstream "$UPSTREAM_URL"
git fetch upstream main --quiet || { status failed "cannot reach upstream"; exit 1; }
git fetch origin "$GRAFT_BRANCH" --quiet || { status failed "no graft branch $GRAFT_BRANCH"; exit 1; }

git rebase --abort 2>/dev/null
git checkout --quiet -B nightly FETCH_HEAD
if ! git rebase upstream/main >/dev/null 2>&1; then
    conflicted="$(git diff --name-only --diff-filter=U | tr '\n' ' ')"
    git rebase --abort 2>/dev/null
    status skipped "graft conflict in: ${conflicted:-unknown}"
    exit 1
fi
echo "grafted $GRAFT_BRANCH onto main $(git rev-parse --short upstream/main)"

# ---- 2. build ------------------------------------------------------------
source "$VENV/bin/activate" || { status failed "no venv at $VENV"; exit 1; }
# setuptools_scm writes this at build time; anything reading the version dies
# without it, which looks like a code bug and is not.
PYTHONPATH=. python3 -c "
from setuptools_scm import get_version
get_version(root='.', relative_to='pyproject.toml',
            version_file='torch_spyre/_version.py',
            version_scheme='semver-pep440-release-branch',
            local_scheme='_versioning:ci_local_scheme')" >/dev/null 2>&1
if ! uv pip install -e . --no-build-isolation --quiet; then
    status failed "build failed after graft"
    exit 1
fi

# ---- 3. smoke ------------------------------------------------------------
# A trivial compile first: if this fails the night is an ABI or device problem,
# not a measurement, and numbers from it would be worse than no numbers.
# Retries only the transient fault. MMAPNotSupported is a platform-wide
# condition and no retry helps, so it stops the run.
smoke() { cd "$HOME" && python3 -c "
import torch, torch_spyre
x = torch.randn(8, 8, dtype=torch.float16, device='spyre')
w = torch.randn(8, 8, dtype=torch.float16, device='spyre')
torch.compile(lambda a, b: torch.relu(a @ b))(x, w)
print('smoke ok')"; }

ok=0
for attempt in 1 2 3; do
    if out="$(smoke 2>&1)"; then ok=1; break; fi
    echo "$out" | tail -3
    if grep -q "MMAPNotSupported" <<<"$out"; then
        status failed "VFIO MMAPNotSupported: platform fault, not this change"
        exit 1
    fi
    if grep -q "DeviceOpenFail\|Device or resource busy" <<<"$out"; then
        echo "  [device busy, attempt $attempt/3]"; sleep 70; continue
    fi
    status failed "smoke compile failed"
    exit 1
done
cd "$REPO"
[ "$ok" = 1 ] || { status failed "device never came free"; exit 1; }

# ---- 4. sweep ------------------------------------------------------------
if ! python3 -u tools/frontend_timing/run_sweep.py \
        --plan tools/frontend_timing/sweep_plan.json \
        --tier "$TIER" --samples "$SAMPLES" --out "$OUT/records"; then
    status failed "sweep exited non-zero"
    exit 1
fi

# ---- 5. summarize --------------------------------------------------------
python3 tools/frontend_timing/summarize.py "$OUT/records" \
    --json "$OUT/rows.json" --csv "$OUT/rows.csv" > "$OUT/summary.md" || true
python3 tools/frontend_timing/scaling.py "$OUT/rows.json" > "$OUT/scaling.md" 2>/dev/null || true

[ -s "$OUT/rows.json" ] || { status failed "no rows.json; summarizer rejected every record"; exit 1; }

# ---- 6. dashboard --------------------------------------------------------
status ok "$(python3 -c "
import json; print(len(json.load(open('$OUT/rows.json'))['points']), 'points')" 2>/dev/null || echo swept)"
python3 tools/frontend_timing/nightly/dashboard.py "$NIGHTLY/history" \
    --out "$NIGHTLY/dashboard.html" || echo "dashboard render failed (records are still on disk)"

echo "=== nightly sweep $DAY done ==="
