#!/usr/bin/env python3
# Copyright 2026 The Torch-Spyre Authors.
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

"""Render a committed baseline as markdown tables.

    python3 tools/frontend_timing/baseline_tables.py baseline/baseline-2026-10-02.json

``summarize.py`` prints a table of the run it just read; this reads a *baseline file*
instead, so the tables in a document can be regenerated from the committed artifact
by someone who never had the records. It groups by workload family, carries the
counters next to the times they explain, and reports sample spread so a reader can
see which figures are solid.

What it cannot show: per-pass counter values. The baseline keeps per-pass times but
only whole-compile counters, because a counter per pass would multiply the metric
name set by the pass count. Joining those needs the raw records.
"""

from __future__ import annotations

import argparse
import json
import statistics
from typing import Any

SCRATCH = "pass.CustomPreSchedulingPasses._maybe_scratchpad_planning_ms"
COUNTERS = {
    "counter.read_writes.extractions": "extract",
    "counter.read_writes.requests": "request",
    "counter.read_writes.misses": "miss",
    "counter.device_coordinates": "dev coord",
    "counter.host_coordinates": "host coord",
}


def med(point: dict[str, Any], key: str) -> float | None:
    vals = point["measurements"].get(key)
    return statistics.median(vals) if vals else None


def spread(point: dict[str, Any], key: str) -> float:
    vals = point["measurements"].get(key) or []
    if len(vals) < 2:
        return 0.0
    m = statistics.median(vals)
    return (max(vals) - min(vals)) / m * 100 if m else 0.0


def axis_label(point: dict[str, Any]) -> str:
    """The parameters that distinguish points inside one family."""
    params = point["params"]
    return ", ".join(f"{k}={v}" for k, v in params.items())


def table(headers: list[str], rows: list[list[str]], align: str) -> str:
    sep = {"l": "---", "r": "--:", "c": ":-:"}
    out = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(sep[a] for a in align) + "|",
    ]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def per_point(points: list[dict[str, Any]]) -> str:
    """One table per family: cost, graph size, scratchpad share, counters."""
    out = []
    families: dict[str, list[dict[str, Any]]] = {}
    for p in points:
        families.setdefault(p["workload"], []).append(p)
    for family in sorted(families):
        fam = sorted(families[family], key=lambda p: med(p, "frontend_ms") or 0)
        rows = []
        for p in fam:
            fe, ops, sc = (
                med(p, "frontend_ms"),
                med(p, "graph_operations"),
                med(p, SCRATCH),
            )
            ext = med(p, "counter.read_writes.extractions") or 0
            req = med(p, "counter.read_writes.requests") or 0
            miss = med(p, "counter.read_writes.misses") or 0
            rss = med(p, "peak_rss_kb") or 0
            label = axis_label(p) + (f" **[{p['arm']}]**" if p["arm"] else "")
            rows.append(
                [
                    label,
                    f"{fe / 1000:,.1f}" if fe else "-",
                    f"±{spread(p, 'frontend_ms'):.1f}%",
                    f"{ops:,.0f}" if ops else "-",
                    f"{100 * sc / fe:.0f}%" if sc and fe else "-",
                    f"{ext:,.0f}",
                    f"{ext / ops:.1f}" if ops else "-",
                    f"{100 * (1 - miss / req):.2f}%" if req else "-",
                    f"{rss / 1024:,.0f}",
                ]
            )
        out.append(f"### {family}\n")
        out.append(
            table(
                [
                    "point",
                    "frontend s",
                    "spread",
                    "ops",
                    "scratch",
                    "extract",
                    "ext/op",
                    "memo hit",
                    "RSS MB",
                ],
                rows,
                "lrrrrrrrr",
            )
        )
        out.append("")
    return "\n".join(out)


def _region_name(key: str) -> str:
    return (
        key.replace("_self_ms", "")
        .replace("_ms", "")
        .replace("pass.", "")
        .replace("stage.torch.", "torch: ")
        .replace("stage.", "")
        .replace("pipeline.", "pipeline: ")
    )


def per_region(points: list[dict[str, Any]], top: int) -> str:
    """Cost per region, ranked by SELF time.

    Ranking by inclusive time is meaningless here: every ancestor of the hot pass
    encloses it, so a dozen regions all read ~100% and the table says nothing.
    """
    totals: dict[str, float] = {}
    for p in points:
        for key in p["measurements"]:
            if key.endswith("_self_ms"):
                totals[key] = totals.get(key, 0.0) + (med(p, key) or 0.0)
    if not totals:
        return (
            "*(baseline predates `_self_ms`; regenerate with a current summarize.py)*"
        )
    grand = sum(med(p, "frontend_ms") or 0 for p in points)
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    rows = [
        [f"`{_region_name(k)}`", f"{ms / 1000:,.1f}", f"{100 * ms / grand:.2f}%"]
        for k, ms in ranked[:top]
        if ms > 0
    ]
    rest = sum(ms for _, ms in ranked[len(rows) :])
    rows.append(
        [
            f"*{len(ranked) - len(rows)} further regions*",
            f"{rest / 1000:,.1f}",
            f"{100 * rest / grand:.2f}%",
        ]
    )
    return table(["region (self time)", "total s", "share"], rows, "lrr")


def nesting(points: list[dict[str, Any]], floor_pct: float = 2.0) -> str:
    """The inclusive chain, which is where the cost sits rather than how much.

    Read downward: each row encloses the next, so the first row whose share drops is
    where the time actually goes.
    """
    totals: dict[str, float] = {}
    for p in points:
        for key in p["measurements"]:
            if (
                key.endswith("_ms")
                and not key.endswith("_self_ms")
                and (key.startswith(("pass.", "stage.", "pipeline.")))
            ):
                totals[key] = totals.get(key, 0.0) + (med(p, key) or 0.0)
    grand = sum(med(p, "frontend_ms") or 0 for p in points)
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    rows = [
        [f"`{_region_name(k)}`", f"{ms / 1000:,.1f}", f"{100 * ms / grand:.1f}%"]
        for k, ms in ranked
        if 100 * ms / grand >= floor_pct
    ]
    return table(["region (inclusive)", "total s", "share of frontend"], rows, "lrr")


def determinism(points: list[dict[str, Any]]) -> str:
    """Why the counters are the part worth asserting on."""
    groups: dict[str, list[float]] = {}
    for p in points:
        if p["samples"] < 2:
            continue
        for key in p["measurements"]:
            if key.startswith("counter."):
                name = "counter.*"
            elif key == "frontend_ms":
                name = "frontend_ms"
            elif key == "graph_operations":
                name = "graph_operations"
            elif key == "peak_rss_kb":
                name = "peak_rss_kb"
            elif (
                key.startswith("pass.")
                and key.endswith("_ms")
                and (med(p, key) or 0) > 1
            ):
                name = "pass.*_ms (>1ms)"
            else:
                continue
            groups.setdefault(name, []).append(spread(p, key))
    rows = []
    for name in (
        "counter.*",
        "graph_operations",
        "peak_rss_kb",
        "frontend_ms",
        "pass.*_ms (>1ms)",
    ):
        vals = sorted(groups.get(name, []))
        if not vals:
            continue
        p90 = vals[max(int(0.9 * len(vals)) - 1, 0)]
        rows.append(
            [
                f"`{name}`",
                f"{len(vals)}",
                f"{statistics.median(vals):.2f}%",
                f"{p90:.2f}%",
            ]
        )
    return table(["metric family", "series", "median spread", "p90"], rows, "lrrr")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("--top", type=int, default=15, help="regions in the cost table")
    args = ap.parse_args()
    doc = json.load(open(args.baseline))
    if doc.get("schema") != "frontend-timing-rows/1":
        raise SystemExit(f"unknown schema {doc.get('schema')!r}")
    points = doc["points"]
    meta = doc["meta"]

    print(f"<!-- generated by baseline_tables.py from {args.baseline} -->\n")
    print("## Provenance\n")
    print(
        table(
            ["field", "value"],
            [[f"`{k}`", f"`{v}`"] for k, v in sorted(meta.items())],
            "ll",
        )
    )
    print(
        f"\n{len(points)} points, "
        f"{sum(p['samples'] for p in points)} measured samples.\n"
    )
    print("## Cost by region\n")
    print(per_region(points, args.top))
    print("\n## Where the cost sits (inclusive nesting)\n")
    print(nesting(points))
    print("\n## Reproducibility\n")
    print(determinism(points))
    print("\n## Every point\n")
    print(
        "Counters are whole-compile totals rather than per-pass. `ext/op` is\n"
        "every pass's\n"
        "read-writes extractions divided by graph operations. `scratch` is scratchpad\n"
        "planning's share of frontend time. `spread` is (max-min)/median over the\n"
        "samples. A bracketed label marks an A/B arm.\n"
    )
    print(per_point(points))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
