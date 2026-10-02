# Frontend timing baseline

A committed sweep result, so a later sweep can be compared against a number
somebody actually measured rather than against a recollection.

| | |
|---|---|
| File | `baseline-2026-10-02.json` (schema `frontend-timing-rows/1`) |
| Produced by | `summarize.py --json`, from 150 records |
| Points | 50 (tier `weekly`), 3 cold samples each plus a discarded warmup |
| Metrics | up to 106 per point, every sample value kept |
| Device time | 2.8 h |
| torch | 2.13.0 |

## What is in it

Per point: the workload, its parameters, the A/B arm if any, and a `measurements`
map holding **every sample value** rather than a summary, so a reader can take a
median, look at the spread, or drop an outlier without re-running anything.

The metric families:

- `frontend_ms`, `backend_ms`, `total_ms`, `compile_wall_ms` — the compile, with
  frontend as the documented subtraction.
- `graph_operations`, `graph_nodes` — the input description, not a cost.
- `pass.<Pipeline>.<pass>_ms` — every pass in all six pipelines.
- `stage.torch.<phase>_ms` — upstream's own `dynamo_timed` phases: lowering, codegen,
  scheduler construction, AOT, Dynamo, and its individual FX passes.
- `stage.<Owner>.<what>_ms` — torch-spyre stages outside the pass lists.
- `counter.read_writes.{requests,misses,extractions}`, `counter.device_coordinates`,
  `counter.host_coordinates` — deterministic counts of analysis calls.
- `peak_rss_kb`, `kernels_skipped`.

## Why the counters are the part to assert on

Measured across this sweep, over 250 counter series and 885 timing series:

| metric family | median spread across 3 samples | p90 |
|---|--:|--:|
| `counter.*` | **0.00%** | 0.03% |
| `graph_operations` | 0.00% | 0.00% |
| `peak_rss_kb` | 2.18% | 5.23% |
| `frontend_ms` | 3.68% | 9.63% |
| `pass.*_ms` | 3.11% | 12.79% |

84.8% of counter series were byte-identical across all three samples. So a
regression test can assert a counter and cannot sensibly assert a millisecond:
the counters are two orders of magnitude more reproducible, and they are the
reason this baseline is worth committing rather than just plotting.

## Comparing a later sweep against this

```bash
python3 tools/frontend_timing/run_sweep.py \
    --plan tools/frontend_timing/sweep_plan.json --tier weekly --samples 3 --out /tmp/new
python3 tools/frontend_timing/summarize.py /tmp/new --json /tmp/new-rows.json
python3 tools/frontend_timing/scaling.py /tmp/new-rows.json   # exponents, with R2
```

Compare `counter.*` first. A counter that moved is a change in what the compiler
does and is worth explaining; a time that moved by less than ~10% is probably the
pod. If a counter moved and no time did, something got slower in a way this sweep
is too small to see yet.

## Provenance caveat, read before trusting the sha

`meta.git_sha` says `ac3a4187`. **That is not the tree that produced these records.**
The sweep ran on a pod whose checkout was at `ac3a4187` with the combined
instrumentation applied as a patch on top, so the recorded sha names the checkout and
not the content. The only honest signal in the file is the `.dirty` suffix on
`meta.torch_spyre_version`.

The tree was the five-commit stack: the compile bucket timer and frontend-only mode
(#4268), the mirrored upstream phases, the frontend work counters, and the sweep
suite — plus two instrument fixes made while taking this baseline (pinning
`TORCHINDUCTOR_COMPILE_THREADS=1`, and matching the backend event by exact name
rather than by trailing segment, which had been driving every frontend figure
negative).

This is a real weakness of the artifact and the reason the next baseline should be
taken from a pushed commit, so `git_sha` resolves for someone who was not there.

## Conditions

Frontend-only (`TORCH_SPYRE_FRONTEND_ONLY=1`), so `backend_ms` is 0 by construction
and `frontend_ms` is the whole compile. Caches disabled, one compile thread, one
process per sample, serial. One warmup out of 50 failed with a transient
`senlib PfMSIMonitor` device fault; its three measured samples then succeeded, and
warmups are discarded regardless.
