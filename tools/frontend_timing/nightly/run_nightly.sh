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
DEV="${DEV_REPO:-$HOME/dt-inductor/torch-spyre}"
VENV="${DEV_VENV:-$HOME/.venv}"
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

# ---- 1. graft (merge main in) --------------------------------------------
# One conflict surface by design: the integration branch carries every piece of
# instrumentation, and this rebases it onto today's main. async_compile.py has
# conflicted three times in nine days, so the abort path is the common one.
git remote get-url upstream >/dev/null 2>&1 || git remote add upstream "$UPSTREAM_URL"
git fetch upstream main --quiet || { status failed "cannot reach upstream"; exit 1; }
git fetch origin "$GRAFT_BRANCH" --quiet || { status failed "no graft branch $GRAFT_BRANCH"; exit 1; }

git rebase --abort 2>/dev/null
# This checkout is machine-managed and holds nothing worth keeping: the borrowed
# _C.so symlink and the generated _version.py are both re-made below. Resetting
# makes the job idempotent, and a rebase refuses outright on a dirty tree.
git reset --hard --quiet
git checkout --quiet -B nightly FETCH_HEAD
# A rebase needs a committer identity, and a fresh clone has none. Local to this
# checkout so it cannot leak into the dev tree.
git config user.name  "$(git config --get user.name  || echo 'nightly sweep')"
git config user.email "$(git config --get user.email || echo 'nightly@localhost')"

# Merge main in, rather than rebase onto it. The integration branch is itself
# assembled from merges of the four PR branches, so a rebase replays all of that
# history commit by commit and re-fights conflicts already resolved on the
# branch -- eighteen conflict surfaces instead of one. A merge resolves against
# the merge base and keeps those resolutions.
if ! merge_err="$(git merge --no-edit upstream/main 2>&1)"; then
    conflicted="$(git diff --name-only --diff-filter=U | tr '\n' ' ')"
    git merge --abort 2>/dev/null
    if [ -n "$conflicted" ]; then
        status skipped "graft conflict in: $conflicted"
    else
        # Not a conflict. Reporting one would send someone to resolve a merge
        # that never happened, so say what git actually said.
        status failed "graft failed, no conflict: $(tail -3 <<<"$merge_err" | tr '\n' ' ')"
    fi
    exit 1
fi
echo "grafted $GRAFT_BRANCH onto main $(git rev-parse --short upstream/main)"

# ---- 2. point at the grafted tree ----------------------------------------
# No build. The dev venv is read for torch (2.13.0+cpu is a local-version wheel
# with no copy on the PVC, so a private venv cannot reproduce it) and PYTHONPATH
# makes torch_spyre resolve here instead: the editable install's finder is
# appended to sys.meta_path, so the standard PathFinder runs first. The built
# extension is borrowed from the dev tree, the way ~/ab4859/tsw-base does.
source "$VENV/bin/activate" || { status failed "no venv at $VENV"; exit 1; }
export PYTHONPATH="$REPO"

# _C.so links libflex, libspyre_comms and friends from the custom runtime under
# $HOME, and the image puts those on LD_LIBRARY_PATH through a login profile. A
# non-login invocation loses them and the import dies with
# "libspyre_comms.so.1: cannot open shared object file", which reads like a
# broken build. Re-add them ahead of the image's own /opt/ibm/spyre copies.
S="${SENTIENT_ROOT:-$HOME/dt-inductor/sentient}"
if [ -d "$S" ]; then
    for lib in spyre_comms libaiupti runtime deeptools; do
        case ":$LD_LIBRARY_PATH:" in
            *":$S/$lib/lib:"*) ;;
            *) export LD_LIBRARY_PATH="$S/$lib/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;;
        esac
    done
fi

ln -sfn "$DEV/torch_spyre/_C.so" "$REPO/torch_spyre/_C.so" 2>/dev/null
[ -e "$REPO/torch_spyre/_C.so" ] || { status failed "no built extension to borrow from $DEV"; exit 1; }

# A fresh clone has no _version.py; it is written at build time and nothing here
# builds. Anything reading the version dies without it, which looks like a code
# bug and is not.
if [ ! -f torch_spyre/_version.py ]; then
    PYTHONPATH=. python3 -c "
from setuptools_scm import get_version
get_version(root='.', relative_to='pyproject.toml',
            version_file='torch_spyre/_version.py',
            version_scheme='semver-pep440-release-branch',
            local_scheme='_versioning:ci_local_scheme')" >/dev/null 2>&1
fi
[ -f torch_spyre/_version.py ] || { status failed "could not write _version.py"; exit 1; }

# ---- 3. smoke ------------------------------------------------------------
# A trivial compile first. If this fails the night is an ABI or device problem,
# not a measurement, and numbers from it would be worse than none. Each failure
# gets its own status, because they need different responses: a borrowed
# extension older than the Python calling it needs the dev tree rebuilt, a
# platform VFIO fault needs nobody to do anything, and a busy device needs a
# retry.
smoke() { cd "$HOME" && python3 -c "
import torch, torch_spyre
x = torch.randn(8, 8, dtype=torch.float16, device='spyre')
w = torch.randn(8, 8, dtype=torch.float16, device='spyre')
torch.compile(lambda a, b: torch.relu(a @ b))(x, w)
import os
print('smoke ok via', os.path.dirname(torch_spyre.__file__))"; }

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
    # The borrowed extension predates the Python calling it, which happens
    # whenever main changes C++ and the dev tree has not been rebuilt. Named
    # explicitly because it reads like a code bug and is not.
    if grep -qE "incompatible function arguments|undefined symbol" <<<"$out"; then
        status skipped "borrowed _C.so is older than this tree; rebuild the dev checkout"
        exit 1
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
