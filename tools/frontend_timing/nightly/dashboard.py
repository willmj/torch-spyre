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

"""Render the nightly sweep history as one self-contained page.

    python3 dashboard.py ~/nightly/history --out ~/nightly/dashboard.html

Reads every ``history/<date>/rows.json`` (schema ``frontend-timing-rows/1``, what
``summarize.py --json`` writes) plus its ``status.json``, and emits a page with two
halves: the latest night in detail, and every metric against date.

Three things it is careful about, each learned the hard way:

* **Regions are ranked by self time, never inclusive.** Every ancestor of the hot
  pass encloses it, so an inclusive ranking puts a dozen regions at ~100% and says
  nothing.
* **Counters and times are on separate charts.** Different units, and a dual axis
  is the one chart mistake worth refusing outright.
* **A skipped night is drawn as a gap, with its reason.** A flat line across a
  graft conflict would otherwise read as "nothing changed" when it means "we did
  not measure".
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from typing import Any

SCHEMA = "frontend-timing-rows/1"
HOT_PASS = "pass.CustomPreSchedulingPasses._maybe_scratchpad_planning_self_ms"
#: Counters worth a trend line, as per-operation rates.
COUNTERS = (
    "counter.read_writes.extractions",
    "counter.read_writes.misses",
    "counter.device_coordinates",
)


def short_labels(points: list[dict[str, Any]]) -> dict[str, str]:
    """``granite_layer-B1_E4096_S512_..._layers8`` -> ``granite_layer S512 L8``.

    Only the parameters that vary inside a workload family carry information; the
    rest are the family's fixed shape and just push the table's other columns off
    screen. Keyed by full name so the long form stays available in a tooltip.
    """
    families: dict[str, list[dict[str, Any]]] = {}
    for p in points:
        families.setdefault(p["workload"], []).append(p)
    out = {}
    for workload, group in families.items():
        keys = sorted({k for p in group for k in p["params"]})
        varying = [k for k in keys if len({str(p["params"].get(k)) for p in group}) > 1]
        for p in group:
            bits = [f"{k}{p['params'][k]}" for k in varying if k in p["params"]]
            label = " ".join([workload] + bits)
            if p["arm"]:
                label += f" [{p['arm']}]"
            out[p["name"]] = label
    return out


def _pct(part: float | None, whole: float | None) -> float:
    return round(100 * (part or 0) / (whole or 1), 1)


def _rate(total: float | None, per: float | None) -> float:
    return round((total or 0) / (per or 1), 1)


def med(point: dict[str, Any], key: str) -> float | None:
    vals = point["measurements"].get(key)
    return statistics.median(vals) if vals else None


def read_history(root: str) -> list[dict[str, Any]]:
    """One entry per dated directory, in date order, skipped nights included."""
    nights = []
    for day in sorted(os.listdir(root)):
        d = os.path.join(root, day)
        if not os.path.isdir(d):
            continue
        status = {}
        if os.path.exists(os.path.join(d, "status.json")):
            try:
                status = json.load(open(os.path.join(d, "status.json")))
            except Exception:
                status = {"state": "failed", "detail": "status.json unreadable"}
        rows = None
        rows_path = os.path.join(d, "rows.json")
        if os.path.exists(rows_path):
            try:
                doc = json.load(open(rows_path))
                if doc.get("schema") == SCHEMA:
                    rows = doc
                else:
                    status.setdefault("detail", f"unknown schema {doc.get('schema')!r}")
            except Exception as exc:
                status.setdefault("detail", f"rows.json unreadable: {exc}")
        nights.append({"day": day, "status": status, "rows": rows})
    return nights


def summarize_night(rows: dict[str, Any]) -> dict[str, Any]:
    """Per-night aggregates: totals, the hot pass's share, counter rates."""
    points = rows["points"]
    frontend = sum(med(p, "frontend_ms") or 0 for p in points)
    hot = sum(med(p, HOT_PASS) or 0 for p in points)
    ops = sum(med(p, "graph_operations") or 0 for p in points)
    out = {
        "points": len(points),
        "frontend_s": round(frontend / 1000, 2),
        "hot_share": round(100 * hot / frontend, 2) if frontend else None,
        "ops": ops,
        "git_sha": rows["meta"].get("git_sha"),
        "torch": rows["meta"].get("torch_version"),
    }
    for key in COUNTERS:
        total = sum(med(p, key) or 0 for p in points)
        out[key] = round(total / ops, 2) if ops else None
    return out


def regions(rows: dict[str, Any], top: int = 12) -> list[dict[str, Any]]:
    """Cost per region by self time, summing each point's median."""
    totals: dict[str, float] = {}
    for p in rows["points"]:
        for key in p["measurements"]:
            if key.endswith("_self_ms"):
                totals[key] = totals.get(key, 0.0) + (med(p, key) or 0.0)
    grand = sum(med(p, "frontend_ms") or 0 for p in rows["points"])
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    dominant = None
    if ranked and grand and 100 * ranked[0][1] / grand > 50:
        dominant = ranked[0]
        ranked = ranked[1:]
    ranked = ranked[:top]
    name = lambda k: (  # noqa: E731
        k.replace("_self_ms", "")
        .replace("pass.CustomPreSchedulingPasses.", "preSched · ")
        .replace("pass.CustomPostFusionPasses.", "postFusion · ")
        .replace("stage.torch.", "torch · ")
        .replace("stage.", "")
    )
    rows = [
        {"name": name(k), "s": round(v / 1000, 2), "pct": round(100 * v / grand, 2)}
        for k, v in ranked
        if v > 0
    ]
    excluded = None
    if dominant:
        excluded = {
            "name": name(dominant[0]),
            "s": round(dominant[1] / 1000, 2),
            "pct": round(100 * dominant[1] / grand, 2),
        }
    return {"rows": rows, "excluded": excluded}


def anchor_points(nights: list[dict[str, Any]], n: int = 3) -> list[str]:
    """The costliest points present on the latest night, as trend series.

    Three because the categorical palette validates three slots for every chart
    form; a fourth would put yellow beside orange and fail the all-pairs gate.
    """
    latest = next((x for x in reversed(nights) if x["rows"]), None)
    if not latest:
        return []
    ranked = sorted(
        latest["rows"]["points"],
        key=lambda p: -(med(p, "frontend_ms") or 0),
    )
    return [p["name"] for p in ranked[:n]]


def build_series(
    nights: list[dict[str, Any]],
    anchors: list[str],
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Per-date values for each trend chart. None where a night was skipped."""
    days = [x["day"] for x in nights]
    labels = labels or {}
    key = {a: labels.get(a, a) for a in anchors}
    per_point: dict[str, list[float | None]] = {key[a]: [] for a in anchors}
    hot_share: list[float | None] = []
    counters: dict[str, list[float | None]] = {c: [] for c in COUNTERS}
    notes = []
    for night in nights:
        rows, status = night["rows"], night["status"]
        notes.append(
            {
                "day": night["day"],
                "state": status.get("state", "unknown"),
                "detail": status.get("detail", ""),
                "sha": (rows or {}).get("meta", {}).get("git_sha")
                or status.get("swept_sha"),
            }
        )
        if not rows:
            hot_share.append(None)
            for a in anchors:
                per_point[key[a]].append(None)
            for c in COUNTERS:
                counters[c].append(None)
            continue
        agg = summarize_night(rows)
        hot_share.append(agg["hot_share"])
        for c in COUNTERS:
            counters[c].append(agg[c])
        by_name = {p["name"]: p for p in rows["points"]}
        for a in anchors:
            p = by_name.get(a)
            ms = med(p, "frontend_ms") if p else None
            per_point[key[a]].append(round(ms / 1000, 2) if ms else None)
    return {
        "days": days,
        "notes": notes,
        "frontend_s": per_point,
        "hot_share": hot_share,
        "counters": counters,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("history")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    nights = read_history(args.history)
    if not nights:
        raise SystemExit(f"no dated directories under {args.history}")
    latest = next((x for x in reversed(nights) if x["rows"]), None)
    anchors = anchor_points(nights)

    labels_all = short_labels(latest["rows"]["points"]) if latest else {}
    data = {
        "generated": __import__("datetime").datetime.now().astimezone().isoformat(),
        "trend": build_series(nights, anchors, labels_all),
        "anchors": anchors,
        "latest": None,
    }
    if latest:
        labels = labels_all
        data["latest"] = {
            "day": latest["day"],
            "agg": summarize_night(latest["rows"]),
            "regions": regions(latest["rows"]),
            "points": [
                {
                    "name": p["name"],
                    "short": labels.get(p["name"], p["name"]),
                    "arm": p["arm"],
                    "ops": med(p, "graph_operations"),
                    "frontend_s": round((med(p, "frontend_ms") or 0) / 1000, 2),
                    "hot_pct": _pct(med(p, HOT_PASS), med(p, "frontend_ms")),
                    "ext_per_op": _rate(
                        med(p, "counter.read_writes.extractions"),
                        med(p, "graph_operations"),
                    ),
                }
                for p in sorted(
                    latest["rows"]["points"],
                    key=lambda p: -(med(p, "frontend_ms") or 0),
                )
            ],
        }

    template = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "dashboard_template.html"
    )
    html = (
        open(template)
        .read()
        .replace("__DATA__", json.dumps(data, separators=(",", ":")))
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write(html)
    skipped = sum(1 for n in nights if not n["rows"])
    print(f"{args.out}: {len(nights)} nights ({skipped} without records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
