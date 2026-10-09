# Nightly frontend sweep

A sweep every night at 02:00, and one page that shows today's compile cost beside
every previous night's. Wires the sweep suite to a schedule (#4117 Task 6) so the
numbers stop being a one-off and the committed baseline stops rotting.

## What runs

```
CronJob mwj-frontend-sweep-nightly        torch-spyre-docs/pods/cronjob-frontend-sweep.yaml
  └─ run_nightly.sh      graft → build → smoke → sweep → summarize → render
       writes  ~/nightly/history/<YYYY-MM-DD>/{records,rows.json,status.json,run.log}
       renders ~/nightly/dashboard.html
```

Six steps, and the order matters: each one refuses to continue rather than hand the
next a tree it should not measure.

1. **Graft.** `$GRAFT_BRANCH` rebased onto today's `upstream/main`. None of the
   instrumentation is in main yet, so there is nothing to sweep without this.
2. **Build.** `uv pip install -e . --no-build-isolation`, incremental.
3. **Smoke.** One trivial compile. If this fails the night is an ABI or device
   problem and its numbers would be worse than no numbers.
4. **Sweep.** `run_sweep.py --tier $SWEEP_TIER --samples $SWEEP_SAMPLES`.
5. **Summarize.** `summarize.py --json` plus `scaling.py`.
6. **Render.** `dashboard.py` over the whole history.

## Setup, once

```bash
bash tools/frontend_timing/nightly/setup_nightly.sh   # ~20 min: clone, venv, first build
bash tools/frontend_timing/nightly/run_nightly.sh     # ~1.5 h: prove it end to end
kubectl apply -f ../torch-spyre-docs/pods/cronjob-frontend-sweep.yaml
```

`setup_nightly.sh` also seeds `history/2026-10-02` from the committed baseline, so
the trend half has two points on the first night rather than starting blind.

## Why a second venv and a shared home

The dev venv's editable install maps `torch_spyre` to the absolute path
`~/dt-inductor/torch-spyre`, so anything using `~/.venv` imports the dev checkout --
whatever is there and dirty at 02:00. The job therefore has its own
`~/nightly/.venv` against its own `~/nightly/torch-spyre`, and never activates
`~/.venv` or touches the dev tree.

The home stays shared because the image's `LD_LIBRARY_PATH` hardcodes
`/home/mwj/dt-inductor/sentient` (6.2 GB) and the built `_C.so` links `libflex.so`
from there. A private home would mean duplicating that runtime.

## Reading a night that produced nothing

Every run writes `status.json` whichever way it ends, and the dashboard draws a gap
rather than a line through it. A line through a skipped night would read as
"nothing changed" when it means "nothing was measured".

| `state` | What happened |
|---|---|
| `ok` | swept; `rows.json` is there |
| `skipped` | `graft conflict in: <files>` -- the expected failure. `async_compile.py` conflicted three times in nine days |
| `failed` | build, smoke, sweep or summarizer failed; `detail` says which, `run.log` has the rest |

`VFIO::DeviceOpenFail` and "Device or resource busy" are retried three times, 70 s
apart, because they are transient. `MMAPNotSupported` is not retried: it is a
platform-wide condition and no retry helps.

## Re-running a night by hand

```bash
kubectl create job --from=cronjob/mwj-frontend-sweep-nightly sweep-manual-1
kubectl logs -f job/sweep-manual-1
```

Or on a dev pod, writing into a scratch history so the real one is untouched:

```bash
NIGHTLY_ROOT=~/nightly-test bash tools/frontend_timing/nightly/run_nightly.sh
```

Re-render alone, which needs no device:

```bash
python3 tools/frontend_timing/nightly/dashboard.py ~/nightly/history \
    --out ~/nightly/dashboard.html
```

## The graft is the fragile part, deliberately

One branch, one rebase, one conflict surface. It exists only because #4268, #4740,
PR 3 and PR A are unmerged; every piece that lands deletes a cherry-pick, and when
the last one lands step 1 collapses to `git checkout main`. Keeping it as a single
integration branch rather than four cherry-picks is what keeps the failure legible.

## What the dashboard will and will not tell you

It leads with the counters because they are the trustworthy half: across a 50-point
sweep they varied **0.00%** between samples against **3.68%** for times. A step in
`extractions/op` is a real change in what the compiler does; a 5% wobble in seconds
is usually the pod.

The first two nights put numbers on how much that matters. A point's own three
samples spread **11% at the median and 63% at the worst**, which is larger than
most night-over-night moves, while every counter spread 0.00% over the same
samples. So the time chart plots the **fastest** sample, not the median, and draws
the full sample range as a band behind it. Contamination of a compile is one-sided
-- a neighbour on the node, a device retry or a cold page cache can only make a
sample slower -- so the minimum is the order statistic that estimates the tree and
not the machine. It is a real improvement and not a cure: switching from median to
min cut the worst apparent night-over-night move from **110% to 42%**, and on the
headline Granite point turned an apparent **+17.8% regression into -2.3%**, but 11
of 26 points still moved more than 15%. Read a time move only when it clears the
band, and confirm it against a counter before believing it.

Two things make a time comparison meaningless regardless of estimator, and both
are now recorded in `status.json` so they can be ruled out. A different **node**:
each night is a fresh pod the scheduler may place anywhere. And the pod requests
no CPU, so it is BestEffort and shares a 144-core node with whatever else is
running -- a quiet night and a busy one are not the same measurement. Adding a
`requests.cpu` would tighten this at the cost of possibly not scheduling at all.

Regions are ranked by **self** time. An inclusive ranking puts every ancestor of the
hot pass near 100% and says nothing, and the one region above half the total is
excluded from the chart and reported in a tile instead -- otherwise every other bar
is a flat line against it.

It is not shareable by link. The repo's perf tier pushes benchmark numbers to
ClickHouse inline rather than uploading artifacts, explicitly so compile numbers do
not become world-readable; this keeps everything on the PVC for the same reason.
