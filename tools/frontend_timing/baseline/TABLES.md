# Baseline tables — 2026-10-02

Generated, do not hand-edit. Regenerate with:

```bash
python3 tools/frontend_timing/baseline_tables.py \
    tools/frontend_timing/baseline/baseline-2026-10-02.json
```

## Provenance

| field | value |
|---|---|
| `generated_at` | `2026-10-02T16:00:58.412916+00:00` |
| `git_sha` | `ac3a4187` |
| `python_version` | `3.12.13` |
| `recorder_version` | `1` |
| `tier` | `None` |
| `torch_spyre_version` | `0.1.0.dev1724+HEAD.gac3a4187.dirty` |
| `torch_version` | `2.13.0+cpu` |

50 points, 150 measured samples.

## Cost by region

| region (self time) | total s | share |
|---|--:|--:|
| `CustomPreSchedulingPasses._maybe_scratchpad_planning` | 1,533.4 | 87.15% |
| `CustomPreSchedulingPasses.span_reduction` | 35.2 | 2.00% |
| `SpyreAsyncCompile.generate_bundle` | 29.3 | 1.66% |
| `torch: Scheduler.fused_nodes` | 19.5 | 1.11% |
| `CustomPreSchedulingPasses._distribute_work` | 17.7 | 1.01% |
| `CustomPostFusionPasses.prepare_spyre_kernels` | 17.0 | 0.97% |
| `torch: PyCodeCache.load_by_key_path` | 16.6 | 0.95% |
| `CustomPreSchedulingPasses.propagate_spyre_tensor_layouts` | 11.3 | 0.64% |
| `torch: _recursive_joint_graph_passes` | 10.3 | 0.58% |
| `CustomPreSchedulingPasses.optimize_restickify_locations` | 9.2 | 0.52% |
| `torch: Scheduler.__init__` | 8.4 | 0.48% |
| `torch: bytecode_tracing` | 7.4 | 0.42% |
| `torch: GraphLowering.run` | 7.4 | 0.42% |
| `torch: Scheduler.codegen` | 5.4 | 0.31% |
| `torch: create_aot_dispatcher_function` | 4.7 | 0.27% |
| *84 further regions* | 36.9 | 2.10% |

## Where the cost sits (inclusive nesting)

| region (inclusive) | total s | share of frontend |
|---|--:|--:|
| `torch: dynamo` | 1,771.8 | 100.7% |
| `torch: entire_frame_compile` | 1,771.7 | 100.7% |
| `torch: compile_attempt_0` | 1,768.1 | 100.5% |
| `torch: backend_compile` | 1,759.6 | 100.0% |
| `torch: create_aot_dispatcher_function` | 1,756.9 | 99.9% |
| `torch: compile_fx.<locals>.fw_compiler_base` | 1,748.8 | 99.4% |
| `torch: inductor_compile` | 1,737.5 | 98.8% |
| `torch: fx_codegen_and_compile` | 1,735.8 | 98.7% |
| `torch: GraphLowering.compile_to_fn` | 1,722.0 | 97.9% |
| `torch: code_gen` | 1,722.0 | 97.9% |
| `torch: GraphLowering.codegen` | 1,674.3 | 95.2% |
| `CustomPreSchedulingPasses.pass_loop` | 1,623.1 | 92.3% |
| `CustomPreSchedulingPasses._maybe_scratchpad_planning` | 1,533.4 | 87.2% |
| `torch: PyCodeCache.load_by_key_path` | 48.1 | 2.7% |
| `GraphLowering.update_scheduler` | 45.1 | 2.6% |
| `torch: Scheduler.__init__` | 45.1 | 2.6% |
| `CustomPreSchedulingPasses.span_reduction` | 35.2 | 2.0% |

## Reproducibility

| metric family | series | median spread | p90 |
|---|--:|--:|--:|
| `counter.*` | 250 | 0.00% | 0.03% |
| `graph_operations` | 50 | 0.00% | 0.00% |
| `peak_rss_kb` | 50 | 2.18% | 5.23% |
| `frontend_ms` | 50 | 3.68% | 9.63% |
| `pass.*_ms (>1ms)` | 1670 | 3.11% | 12.93% |

## Every point

Counters are whole-compile totals rather than per-pass. `ext/op` is
every pass's
read-writes extractions divided by graph operations. `scratch` is scratchpad
planning's share of frontend time. `spread` is (max-min)/median over the
samples. A bracketed label marks an A/B arm.

### control_flow

| point | frontend s | spread | ops | scratch | extract | ext/op | memo hit | RSS MB |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| M=8, K=12, N=6, tile=2 | 1.3 | ±11.3% | 9 | 43% | 443 | 49.2 | 97.85% | 614 |

### dup_constants

| point | frontend s | spread | ops | scratch | extract | ext/op | memo hit | RSS MB |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| dups=4, B=2, M=8, N=32 | 2.2 | ±3.1% | 7 | 50% | 972 | 138.9 | 98.20% | 616 |
| dups=8, B=2, M=8, N=32 | 3.4 | ±9.6% | 15 | 47% | 2,004 | 133.6 | 98.46% | 617 |
| dups=16, B=2, M=8, N=32 | 5.9 | ±1.3% | 31 | 44% | 4,068 | 131.2 | 98.75% | 620 |
| dups=32, B=2, M=8, N=32 | 11.2 | ±1.6% | 63 | 44% | 8,196 | 130.1 | 99.07% | 674 |
| dups=64, B=2, M=8, N=32 | 22.6 | ±0.8% | 127 | 43% | 16,452 | 129.5 | 99.38% | 710 |

### elementwise_chain

| point | frontend s | spread | ops | scratch | extract | ext/op | memo hit | RSS MB |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| ops=64, rows=256, cols=1024 | 10.6 | ±6.3% | 64 | 80% | 8,029 | 125.5 | 99.64% | 1,731 |
| ops=128, rows=256, cols=1024 | 19.5 | ±5.7% | 128 | 78% | 16,125 | 126.0 | 99.71% | 2,265 |
| ops=256, rows=256, cols=1024 | 38.0 | ±11.7% | 256 | 78% | 32,317 | 126.2 | 99.79% | 3,306 |
| ops=512, rows=256, cols=1024 | 80.7 | ±0.7% | 512 | 79% | 64,701 | 126.4 | 99.86% | 6,036 |
| ops=1024, rows=256, cols=1024 | 504.7 | ±2.5% | 1,024 | 93% | 129,469 | 126.4 | 99.92% | 10,849 |

### fanout

| point | frontend s | spread | ops | scratch | extract | ext/op | memo hit | RSS MB |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| consumers=8, rows=256, cols=1024 | 3.0 | ±2.6% | 16 | 68% | 2,430 | 151.9 | 99.52% | 875 |
| consumers=16, rows=256, cols=1024 | 5.5 | ±4.9% | 32 | 74% | 4,998 | 156.2 | 99.56% | 1,239 |
| consumers=32, rows=256, cols=1024 | 10.8 | ±1.6% | 64 | 74% | 10,134 | 158.3 | 99.63% | 1,747 |
| consumers=64, rows=256, cols=1024 | 19.9 | ±7.1% | 128 | 74% | 20,406 | 159.4 | 99.70% | 2,386 |
| consumers=128, rows=256, cols=1024 | 43.4 | ±7.0% | 256 | 76% | 40,950 | 160.0 | 99.78% | 3,882 |

### flash

| point | frontend s | spread | ops | scratch | extract | ext/op | memo hit | RSS MB |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| B=1, H=32, Lq=512, Lk=256, D=128, block_size=128 | 17.4 | ±6.2% | 39 | 87% | 7,702 | 197.5 | 99.71% | 1,840 |
| B=1, H=32, Lq=512, Lk=512, D=128, block_size=128 | 50.2 | ±0.3% | 71 | 91% | 14,414 | 203.0 | 99.73% | 3,227 |
| B=1, H=32, Lq=512, Lk=1024, D=128, block_size=128 | 67.1 | ±0.7% | 135 | 88% | 28,222 | 209.1 | 99.76% | 4,284 |
| B=1, H=32, Lq=512, Lk=2048, D=128, block_size=128 | 109.3 | ±3.3% | 263 | 87% | 57,362 | 218.1 | 99.82% | 6,028 |

### granite_embedding

| point | frontend s | spread | ops | scratch | extract | ext/op | memo hit | RSS MB |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| S=2048, E=4096, vocab=49159 | 1.1 | ±44.9% | 2 | 55% | 195 | 97.5 | 98.71% | 1,262 |
| S=512, E=4096, vocab=49159 | 1.2 | ±16.3% | 2 | 58% | 195 | 97.5 | 98.71% | 1,259 |

### granite_layer

| point | frontend s | spread | ops | scratch | extract | ext/op | memo hit | RSS MB |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| B=1, S=512, layers=1, E=4096, heads=32, kv_heads=8, intermediate=12800 **[SENCORES=1]** | 5.7 | ±5.2% | 38 | 28% | 5,004 | 131.7 | 99.11% | 705 |
| B=1, S=1, layers=1, E=4096, heads=32, kv_heads=8, intermediate=12800 | 6.1 | ±4.1% | 34 | 70% | 3,349 | 98.5 | 99.43% | 987 |
| B=1, S=2048, layers=1, E=4096, heads=32, kv_heads=8, intermediate=12800 | 16.0 | ±6.4% | 37 | 72% | 5,855 | 158.2 | 99.56% | 1,361 |
| B=1, S=1024, layers=1, E=4096, heads=32, kv_heads=8, intermediate=12800 | 17.0 | ±2.3% | 37 | 77% | 5,828 | 157.5 | 99.54% | 1,632 |
| B=1, S=128, layers=1, E=4096, heads=32, kv_heads=8, intermediate=12800 | 31.0 | ±5.8% | 36 | 92% | 7,640 | 212.2 | 99.70% | 2,655 |
| B=1, S=512, layers=1, E=4096, heads=32, kv_heads=8, intermediate=12800 **[SPYRE_LX_PLANNER_RELAYOUT=0]** | 38.0 | ±7.8% | 36 | 94% | 7,158 | 198.8 | 99.71% | 2,213 |
| B=1, S=512, layers=1, E=4096, heads=32, kv_heads=8, intermediate=12800 | 38.3 | ±4.3% | 36 | 94% | 7,278 | 202.2 | 99.71% | 2,217 |
| B=1, S=512, layers=1, E=4096, heads=32, kv_heads=8, intermediate=12800 **[SPYRE_LX_SOLVER_RELAYOUT_GROUPS_PER_EDGE=0]** | 64.2 | ±1.0% | 36 | 96% | 2,631 | 73.1 | 99.58% | 5,301 |
| B=1, S=512, layers=2, E=4096, heads=32, kv_heads=8, intermediate=12800 | 74.4 | ±0.2% | 72 | 94% | 14,775 | 205.2 | 99.74% | 3,924 |
| B=1, S=512, layers=4, E=4096, heads=32, kv_heads=8, intermediate=12800 | 100.9 | ±1.0% | 144 | 92% | 29,770 | 206.7 | 99.78% | 5,014 |
| B=1, S=512, layers=8, E=4096, heads=32, kv_heads=8, intermediate=12800 | 155.6 | ±1.0% | 288 | 90% | 59,754 | 207.5 | 99.83% | 7,206 |

### granite_lm_head

| point | frontend s | spread | ops | scratch | extract | ext/op | memo hit | RSS MB |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| B=1, S=512, E=4096, vocab=49159, chunks=2 | 2.7 | ±4.3% | 10 | 68% | 835 | 83.5 | 99.40% | 878 |
| B=1, S=2048, E=4096, vocab=49159, chunks=4 | 2.9 | ±3.3% | 14 | 65% | 1,077 | 76.9 | 99.37% | 742 |
| B=1, S=128, E=4096, vocab=49159, chunks=4 | 3.0 | ±2.8% | 14 | 68% | 1,225 | 87.5 | 99.39% | 814 |
| B=1, S=1024, E=4096, vocab=49159, chunks=4 | 3.1 | ±4.9% | 14 | 67% | 1,157 | 82.6 | 99.39% | 740 |
| B=1, S=512, E=4096, vocab=49159, chunks=4 | 3.1 | ±3.0% | 14 | 67% | 1,217 | 86.9 | 99.40% | 773 |
| B=1, S=512, E=4096, vocab=49159, chunks=8 | 8.5 | ±3.0% | 22 | 81% | 3,109 | 141.3 | 99.59% | 1,332 |
| B=1, S=512, E=4096, vocab=49159, chunks=16 | 17.3 | ±1.2% | 38 | 87% | 6,045 | 159.1 | 99.64% | 2,201 |

### mlp

| point | frontend s | spread | ops | scratch | extract | ext/op | memo hit | RSS MB |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| seq_len=512, emb_dim=4096, layers=1, intermediate=14336 | 3.1 | ±16.4% | 5 | 78% | 540 | 108.0 | 99.70% | 922 |
| seq_len=512, emb_dim=4096, layers=2, intermediate=14336 | 6.3 | ±7.7% | 10 | 84% | 1,371 | 137.1 | 99.68% | 1,208 |
| seq_len=512, emb_dim=4096, layers=4, intermediate=14336 | 11.7 | ±8.4% | 20 | 88% | 3,033 | 151.7 | 99.68% | 1,924 |
| seq_len=512, emb_dim=4096, layers=8, intermediate=14336 | 24.9 | ±2.3% | 40 | 91% | 6,357 | 158.9 | 99.68% | 3,462 |

### transformer_block

| point | frontend s | spread | ops | scratch | extract | ext/op | memo hit | RSS MB |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| B=1, S=1, E=4096, heads=32, intermediate=14336 | 4.7 | ±5.6% | 31 | 68% | 2,604 | 84.0 | 99.40% | 852 |
| B=1, S=2048, E=4096, heads=32, intermediate=14336 | 14.1 | ±1.6% | 36 | 71% | 5,152 | 143.1 | 99.54% | 1,255 |
| B=1, S=1024, E=4096, heads=32, intermediate=14336 | 16.6 | ±5.5% | 35 | 76% | 5,463 | 156.1 | 99.54% | 1,585 |
| B=1, S=512, E=5120, heads=40, intermediate=16384 | 20.2 | ±5.7% | 34 | 89% | 5,797 | 170.5 | 99.69% | 1,845 |
| B=1, S=512, E=4096, heads=32, intermediate=14336 | 20.2 | ±2.7% | 34 | 89% | 5,487 | 161.4 | 99.65% | 1,719 |
| B=1, S=128, E=4096, heads=32, intermediate=14336 | 20.9 | ±0.9% | 34 | 90% | 6,085 | 179.0 | 99.61% | 2,226 |
