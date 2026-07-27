# Copyright 2025 The Torch-Spyre Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pipeline walkthrough for mul.py.

Runs ``torch.mul`` through torch.compile on a Spyre AIU and prints
intermediate representations at every major stage.

Compilation pipeline stages captured here
------------------------------------------
1. Dynamo FX graph  – the raw graph captured by ``torch._dynamo``
2. Post-grad IR     – after Inductor's decompositions and ``CustomPrePasses``
                      (+ ``CustomPostPasses``)
3. Pre-scheduling   – after layout propagation, restickify, work-division, …
                      (``CustomPreSchedulingPasses``)
4. Generated SuperDSC / debug artefacts dumped to ``torch_compile_debug/``
   when ``TORCH_COMPILE_DEBUG=1``

Environment variables used
--------------------------
TORCH_COMPILE_DEBUG=1       - dump all intermediate artefacts to
                              ``torch_compile_debug/`` (SuperDSC JSON,
                              post-grad graph, schedule, …)
TORCH_LOGS="+dynamo"        - verbose Dynamo tracing
TORCH_LOGS="spyre.inductor:DEBUG"
                            - full Spyre-backend debug logging
                              (lowering, layout, passes, codegen, …)
SENCORES=1                  - run on a single AIU core (recommended for
                              first-pass debugging; isolates multi-core bugs)

Run example (all stages, maximum verbosity)
-------------------------------------------
  TORCH_COMPILE_DEBUG=1 \
  TORCH_LOGS="+dynamo,spyre.inductor:DEBUG" \
  SENCORES=1 \
  python mul_pipeline_debug.py

Run example (passes-only, quieter)
-----------------------------------
  TORCH_LOGS="spyre.inductor.passes:INFO" \
  python mul_pipeline_debug.py
"""

import os
import textwrap

import torch
import torch._dynamo
import torch.fx

# ---------------------------------------------------------------------------
# 0.  Pretty-print helper
# ---------------------------------------------------------------------------

def _banner(title: str) -> None:
    line = "=" * 70
    print(f"\n{line}")
    print(f"  {title}")
    print(f"{line}\n")


# ---------------------------------------------------------------------------
# 1.  Dynamo FX graph capture
#     torch.compile(explain=True) returns a structured explanation that
#     includes the traced FX graph *before* Inductor sees it.
# ---------------------------------------------------------------------------

_banner("STAGE 1 — Dynamo FX graph (torch.compile explain=True)")

DEVICE = torch.device("spyre")
torch.manual_seed(0xAFFE)

x = torch.rand(128, 64, dtype=torch.float16)
y = torch.rand(128, 64, dtype=torch.float16)

x_device = x.to(DEVICE)
y_device = y.to(DEVICE)

fn = lambda a, b: torch.mul(a, b)

# explain=True does a dry-run trace: it does NOT submit work to the device.
explanation = torch._dynamo.explain(fn)(x_device, y_device)
print(explanation)

# The raw FX graphs (one per non-broken sub-graph) are available here:
for i, g in enumerate(explanation.graphs):
    _banner(f"STAGE 1 — Dynamo FX graph #{i}")
    g.print_readable()

# ---------------------------------------------------------------------------
# 2.  Spyre inductor logging for stages 2-6
#     Setting TORCH_LOGS at runtime allows us to capture pass-level details
#     without restarting the process (the logging_config system picks it up on
#     the next import cycle, but we can also drive it programmatically).
# ---------------------------------------------------------------------------

_banner("STAGE 2-6 — Inductor passes  (spyre.inductor:DEBUG)")

# Enable all Spyre inductor loggers at DEBUG so we see every pass banner:
#   •  passes  – BEFORE / AFTER PRE-SCHEDULING listings
#   •  lowering  – per-op lowering decisions
#   •  stickify  – layout assignment per tensor
#   •  codegen   – SuperDSC JSON fragments
import torch_spyre.logging_config as _lc
_lc.set_log_level("spyre.inductor", "DEBUG")

# Also turn on Dynamo + Inductor PyTorch logging so the full schedule and
# Inductor IR are printed to stderr alongside our Spyre-specific messages:
os.environ.setdefault("TORCH_LOGS", "+inductor,+dynamo")

# Now do the real compilation + execution.
# torch.compile is called fresh (reset_code avoids re-using any cached plan).
torch._dynamo.reset()

compiled = torch.compile(fn)

_banner("STAGE 2-6 — Compiling and running torch.mul(x, y) on Spyre")
result_spyre = compiled(x_device, y_device).cpu()

# ---------------------------------------------------------------------------
# 3.  TORCH_COMPILE_DEBUG artefacts
# ---------------------------------------------------------------------------

debug_dir = "torch_compile_debug"
_banner(f"STAGE 4  — TORCH_COMPILE_DEBUG artefacts  (dir: {debug_dir}/)")

if os.path.isdir(debug_dir):
    for root, dirs, files in os.walk(debug_dir):
        for fname in sorted(files):
            full = os.path.join(root, fname)
            rel  = os.path.relpath(full, debug_dir)
            size = os.path.getsize(full)
            print(f"  {rel:<60}  {size:>8} bytes")
    print()
    print(textwrap.dedent("""\
      Key files to inspect:
        output_code.py          – final Inductor-generated Python wrapper
        fx_graph_readable.py    – post-grad FX graph in readable form
        fx_graph_transformed.py – post-grad FX graph after all passes
        *.sdsc.json             – SuperDSC descriptor sent to dxp_standalone
        schedule.txt            – Inductor scheduler output
    """))
else:
    print(
        "  (directory not found — re-run with TORCH_COMPILE_DEBUG=1 to generate artefacts)\n"
        "  Example:\n"
        "    TORCH_COMPILE_DEBUG=1 python mul_pipeline_debug.py\n"
    )

# ---------------------------------------------------------------------------
# 4.  Numeric validation
# ---------------------------------------------------------------------------

_banner("NUMERIC VALIDATION — Compiled Spyre vs. CPU")

cpu_result = torch.mul(x, y)
delta = torch.abs(result_spyre - cpu_result).max()
print(f"CPU result (first 4 elements):    {cpu_result.flatten()[:4]}")
print(f"Spyre result (first 4 elements):  {result_spyre.flatten()[:4]}")
print(f"Max |delta|: {delta:.6f}  ({'PASS ✓' if delta < 0.05 else 'FAIL ✗'})")
