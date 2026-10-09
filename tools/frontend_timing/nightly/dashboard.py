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
* **Time is plotted as the fastest sample, inside a band of all of them.** On the
  first two nights the same point's own three samples spread 11% at the median
  and 63% at the worst, which is larger than every night-over-night move we saw.
  A bare line through that invites reading noise as a regression, so the band
  shows what the night could not distinguish. The counters spread 0.00% over the
  same samples, which is why they, not the times, are the thing to watch.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from typing import Any

SCHEMA = "frontend-timing-rows/1"
#: The pass that dominates frontend compile, tracked **inclusive** of its children
#: -- the one place self time is the wrong measure. The question this series asks
#: is "how much of a compile is scratchpad planning", which its subtree answers
#: and its self time does not: adding a timer inside the pass moves time from its
#: self into a child and shrinks the self share without anything getting faster.
#: That happened between the first two nights, where substage timers took the self
#: share from 87% to 4% while the subtree went from 87% to 90% and total frontend
#: time rose. Ranking regions against each other still uses self time -- see
#: ``regions`` -- because there every ancestor would otherwise read ~100%.
HOT_PASS = "pass.CustomPreSchedulingPasses._maybe_scratchpad_planning_ms"
#: Substages of the hot pass, as shares of frontend time. These are what its self
#: time became, so they are shown together with it: a drop in one that reappears
#: in another is a reattribution, not a saving.
HOT_SUBSTAGES = (
    "stage.Scratchpad.prepare_buffers_self_ms",
    "stage.Scratchpad.solve_self_ms",
    "stage.Scratchpad.cpsat_solve_self_ms",
)
#: Per-night figures that are not times: cost with graph size divided out, the
#: worst single compile's peak RSS, and extraction's share of the total.
EFFICIENCY = ("ms_per_op", "peak_rss_mb", "extract_share")
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


def best(point: dict[str, Any], key: str) -> float | None:
    """Fastest sample, which is the estimator the time trend uses.

    Contamination of a compile time is one-sided: another tenant on the node, a
    device retry or a page-cache miss only ever makes a sample slower, never
    faster. So the minimum is the one order statistic that estimates the tree's
    own cost rather than the node's mood, and across the first two nights it cut
    the worst night-over-night move from 110% to 42% with no change to any
    counter. It is still not enough to read a 13% move as drift -- see
    ``spread``, which is why the chart carries a band.
    """
    vals = point["measurements"].get(key)
    return min(vals) if vals else None


def spread(point: dict[str, Any], key: str) -> float | None:
    """Within-night range as a percentage of the median, from one point's samples."""
    vals = point["measurements"].get(key)
    if not vals or len(vals) < 2:
        return None
    mid = statistics.median(vals)
    return (max(vals) - min(vals)) / mid * 100 if mid else None


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
        # Cost per operation, which is the efficiency question with graph size
        # divided out: a night whose points got bigger costs more without the
        # compiler having got worse, and the seconds chart cannot tell those
        # apart. Uses the fastest sample for the same reason the time trend does.
        "ms_per_op": round(sum(best(p, "frontend_ms") or 0 for p in points) / ops, 1)
        if ops
        else None,
        # The worst point's peak RSS, not the sum: each sample is its own process,
        # so what matters is whether any single compile is approaching a limit.
        "peak_rss_mb": round(max((med(p, "peak_rss_kb") or 0) for p in points) / 1024)
        if points
        else None,
        # Nights are only comparable if the backend was skipped on both. A night
        # that compiled kernels is measuring something else entirely.
        "kernels_skipped": sum(med(p, "kernels_skipped") or 0 for p in points),
        "git_sha": rows["meta"].get("git_sha"),
        "torch": rows["meta"].get("torch_version"),
    }
    # Every aggregate above is summed over whatever points the night ran. Two
    # nights on different tiers sum over different point sets, so a step in any
    # of them can be the tier rather than the compiler -- the seeded baseline is
    # 50 points against the nightly 26. The anchor-point series are like-for-like
    # and are the ones to read across a tier change.
    for key in COUNTERS:
        total = sum(med(p, key) or 0 for p in points)
        out[key] = round(total / ops, 2) if ops else None
    # Time spent inside read/write extraction, which is the one counter that is
    # already a duration and so prices its own count. A night predating the
    # counter carries no key at all, which is a gap: reported as 0.0 it would
    # claim extraction was free rather than unmeasured.
    key = "counter.read_writes.extract_ns"
    measured = [p for p in points if key in p["measurements"]]
    extract = sum(med(p, key) or 0 for p in measured)
    out["extract_share"] = (
        round(100 * extract / 1e6 / frontend, 2) if frontend and measured else None
    )
    for key in HOT_SUBSTAGES:
        total = sum(med(p, key) or 0 for p in points)
        out[key] = round(100 * total / frontend, 2) if frontend else None
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


def night_samples(
    rows: dict[str, Any], labels: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Every timing sample of every point, for the one chart that hides nothing.

    The aggregates elsewhere each pick a statistic and so each hide the shape of
    what they summarise -- and on this hardware the shape is the finding: one
    point's three samples have been seen 63% apart. A reader deciding whether to
    believe a move needs the raw values, not a third summary of them.
    """
    labels = labels or {}
    out = []
    for p in rows["points"]:
        vals = sorted(v / 1000 for v in (p["measurements"].get("frontend_ms") or []))
        if not vals:
            continue
        out.append(
            {
                "name": p["name"],
                "label": labels.get(p["name"], p["name"]),
                "samples": [round(v, 2) for v in vals],
                "mid": round(statistics.median(vals), 2),
                "ops": med(p, "graph_operations"),
            }
        )
    return sorted(out, key=lambda r: -r["mid"])


#: The counter the coupling charts use. Extractions track the work the frontend
#: actually repeats, and of the counters they are the one with a per-operation
#: rate large enough that a single extra call is visible.
COUPLE_COUNTER = "counter.read_writes.extractions"


def indexed(nights: list[dict[str, Any]]) -> dict[str, list[float | None]]:
    """Time and work as percentages of the first measured night.

    The only honest way to put a duration and a count on one axis: index both and
    the axis is "percent of where we started". Two lines that diverge mean the
    compiler is doing the same work at a different speed, which is the machine;
    two that move together mean the work itself changed.
    """
    out: dict[str, list[float | None]] = {"frontend time": [], "work per operation": []}
    base = next((n for n in nights if n["rows"]), None)
    if not base:
        return out
    ref = {p["name"]: p for p in base["rows"]["points"]}

    def totals(pts: list[dict[str, Any]]) -> tuple[float, float | None]:
        t = sum(best(p, "frontend_ms") or 0 for p in pts)
        ops = sum(med(p, "graph_operations") or 0 for p in pts)
        c = sum(med(p, COUPLE_COUNTER) or 0 for p in pts) / ops if ops else None
        return t, c

    for night in nights:
        rows = night["rows"]
        if not rows:
            out["frontend time"].append(None)
            out["work per operation"].append(None)
            continue
        # Both sides summed over the points this night and the reference night
        # share, not over each night's own set. A nightly tier against a weekly
        # baseline otherwise reads as a 67% saving purely from running 26 points
        # instead of 50 -- which it did, before this.
        shared = [p for p in rows["points"] if p["name"] in ref]
        t, c = totals(shared)
        bt, bc = totals([ref[p["name"]] for p in shared])
        out["frontend time"].append(round(100 * t / bt, 1) if bt and t else None)
        out["work per operation"].append(round(100 * c / bc, 1) if bc and c else None)
    return out


def coupling(
    nights: list[dict[str, Any]], labels: dict[str, str] | None = None
) -> dict[str, Any]:
    """Per-point time move against work move, for the two latest measured nights.

    The quadrant is the verdict. Work unchanged and time moved is the machine;
    both moved is a real change; work moved and time did not is a change that
    happens to be cheap, which is worth knowing before anyone optimises it.
    """
    labels = labels or {}
    measured = [n for n in nights if n["rows"]]
    if len(measured) < 2:
        return {"pairs": [], "from": None, "to": None}
    prev, last = measured[-2], measured[-1]
    before = {p["name"]: p for p in prev["rows"]["points"]}
    pairs = []
    for p in last["rows"]["points"]:
        q = before.get(p["name"])
        if not q:
            continue
        ta, tb = best(q, "frontend_ms"), best(p, "frontend_ms")
        oa, ob = med(q, "graph_operations"), med(p, "graph_operations")
        if not (ta and tb and oa and ob):
            continue
        ca = (med(q, COUPLE_COUNTER) or 0) / oa
        cb = (med(p, COUPLE_COUNTER) or 0) / ob
        # As a percentage, like the time axis. One extra extraction per operation
        # is a large-looking absolute step and 0.5% of a ~200/op base; plotted
        # absolute it puts every point far from the work axis, which reads as a
        # real change in all of them.
        if not ca:
            continue
        dc_pct = round(100 * (cb - ca) / ca, 2)
        va = q["measurements"].get("frontend_ms") or []
        vb = p["measurements"].get("frontend_ms") or []
        # Whether the two nights' sample ranges overlap at all. A move whose
        # ranges overlap was not resolved by either night.
        overlap = bool(va and vb) and min(max(va), max(vb)) >= max(min(va), min(vb))
        pairs.append(
            {
                "label": labels.get(p["name"], p["name"]),
                "dt": round(100 * (tb - ta) / ta, 1),
                "dc": dc_pct,
                "dc_abs": round(cb - ca, 2),
                "overlap": overlap,
            }
        )
    return {
        "pairs": sorted(pairs, key=lambda r: -abs(r["dt"])),
        "from": prev["day"],
        "to": last["day"],
    }


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
    band: dict[str, list[list[float] | None]] = {key[a]: [] for a in anchors}
    noise: list[float | None] = []
    substages: dict[str, list[float | None]] = {
        k.replace("stage.Scratchpad.", "").replace("_self_ms", ""): []
        for k in HOT_SUBSTAGES
    }
    efficiency: dict[str, list[float | None]] = {k: [] for k in EFFICIENCY}
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
                # Each night is a fresh pod the scheduler may place anywhere, and
                # compile time differs between nodes by more than any change we
                # are looking for. A time step across a node change is not a
                # measurement of anything.
                "node": status.get("node"),
                # Which point set the night's aggregates are summed over.
                "tier": status.get("tier"),
                "points": len((rows or {}).get("points") or []) or None,
            }
        )
        if not rows:
            hot_share.append(None)
            noise.append(None)
            for lst in (*substages.values(), *efficiency.values()):
                lst.append(None)
            for a in anchors:
                per_point[key[a]].append(None)
                band[key[a]].append(None)
            for c in COUNTERS:
                counters[c].append(None)
            continue
        agg = summarize_night(rows)
        hot_share.append(agg["hot_share"])
        for c in COUNTERS:
            counters[c].append(agg[c])
        for k in HOT_SUBSTAGES:
            label = k.replace("stage.Scratchpad.", "").replace("_self_ms", "")
            # A night taken before a substage timer existed has no key for it,
            # which is a gap and not a zero: drawing it as zero would claim the
            # work was not happening.
            substages[label].append(agg[k] or None)
        for k in efficiency:
            efficiency[k].append(agg[k])
        by_name = {p["name"]: p for p in rows["points"]}
        for a in anchors:
            p = by_name.get(a)
            ms = best(p, "frontend_ms") if p else None
            per_point[key[a]].append(round(ms / 1000, 2) if ms else None)
            vals = p["measurements"].get("frontend_ms") if p else None
            band[key[a]].append(
                [round(min(vals) / 1000, 2), round(max(vals) / 1000, 2)]
                if vals
                else None
            )
        spreads = [x for x in (spread(p, "frontend_ms") for p in rows["points"]) if x]
        noise.append(round(statistics.median(spreads), 1) if spreads else None)
    return {
        "days": days,
        "notes": notes,
        "frontend_s": per_point,
        "frontend_band": band,
        "noise": noise,
        "hot_share": hot_share,
        "substages": substages,
        "efficiency": efficiency,
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
        "indexed": indexed(nights),
        "coupling": coupling(nights, labels_all),
        "anchors": anchors,
        "latest": None,
    }
    if latest:
        labels = labels_all
        data["latest"] = {
            "day": latest["day"],
            "agg": summarize_night(latest["rows"]),
            "regions": regions(latest["rows"]),
            "samples": night_samples(latest["rows"], labels_all),
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
