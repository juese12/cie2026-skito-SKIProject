#!/usr/bin/env python3
"""Audit legacy/v2 logs; variation and run-level statistics, not FU latency."""
import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path

KINDS = ("batch4", "e2e", "chain")
IMPLS = ("vdot", "rvv")


def need(condition, message):
    if not condition:
        raise ValueError(message)


def distribution(values):
    mean, median = statistics.mean(values), statistics.median(values)
    return dict(n=len(values), median=median, min=min(values), max=max(values),
                mean=mean, cv=statistics.pstdev(values) / mean,
                relative_range=(max(values) - min(values)) / median)


def audit(path, max_cv=0.05, max_drift=0.10):
    path = Path(path)
    raw = path.read_bytes()
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw.decode(errors="replace"))
    need("Difftest enabled" in text and "HIT GOOD TRAP" in text, "missing difftest/GOOD TRAP")
    need("vdot benchmark PASS:" in text, "missing benchmark PASS")
    need(not re.search(r"HIT BAD TRAP|ABORT|different at pc|bench[^\r\n]*FAIL", text), "failure marker")
    need(not re.search(r"\[(?:process |verification )?exit\]\s+[1-9]\d*", text), "nonzero exit")
    eq = re.findall(r"bench equivalence PASS: vectors=(\d+) checks=(\d+) policies=4 baseline=vwmul\+vwredsum vdot=(\d+)", text)
    need(len(eq) == 1 and eq[0][2] == "1", "need one BOTH-implementation equivalence PASS")
    metas = re.findall(r"bench meta ([^\r\n]+)", text)
    if metas:
        need(len(metas) == 1, "duplicate metadata")
        need(re.findall(r"\[process exit\]\s+(\d+)", text) == ["0"], "v2 requires one recorded zero process exit")
        pairs = re.findall(r"(\w+)=(\S+)", metas[0])
        meta = dict(pairs)
        required = {"schema", "profile", "reps", "warmup", "batches", "random", "first", "deferred", "seed", "timing"}
        need(len(meta) == len(pairs) and set(meta) == required, "duplicate/unknown/missing metadata")
        need(meta["schema"] == "2" and meta["deferred"] == "1" and meta["timing"] in ("mcycle_raw", "mcycle_vstart_serialized"), "unsupported protocol")
        need(meta["profile"] in ("full", "smoke") and meta["seed"] == "56444f54", "unknown profile/seed")
        for key in ("schema", "reps", "warmup", "batches", "random", "first", "deferred"):
            meta[key] = int(meta[key])
        need(meta["reps"] >= 2 and meta["reps"] % 2 == 0, "unbalanced repetitions")
        need(meta["warmup"] >= 2 and meta["warmup"] % 2 == 0, "unbalanced warmup")
        need(0 < meta["batches"] <= 65536 and meta["random"] >= 0 and meta["first"] in (0, 1), "invalid configuration")
        if meta["profile"] == "full":
            need(meta["timing"] == "mcycle_vstart_serialized", "full profile needs serialized timestamps")
            need(meta["random"] >= 1000 and meta["reps"] >= 8 and meta["warmup"] >= 8 and meta["batches"] >= 256, "full profile below acceptance floor")
        need(tuple(map(int, eq[0][:2])) == (8 + meta["random"], 32 + meta["random"]), "equivalence counts mismatch")
    else:
        need(tuple(map(int, eq[0][:2])) == (1008, 1032), "legacy equivalence counts")
        meta = dict(schema=1, profile="legacy", reps=5, warmup=1, batches=32, random=1000, first=0, deferred=0)
    rows = re.findall(r"bench raw kind=(batch4|e2e|chain) impl=(rvv|vdot) rep=(\d+)(?: slot=(\d+))? dots=(\d+) cycles=(\d+)", text)
    empty = re.findall(r"bench raw kind=empty impl=control rep=(\d+) loops=(\d+) cycles=(\d+)", text)
    need(text.count("bench raw ") == len(rows) + len(empty), "malformed/unknown raw record")
    values = {(k, i): {} for k in KINDS for i in IMPLS}
    for kind, impl, rep, slot, dots, cycles in rows:
        rep, dots, cycles = int(rep), int(dots), int(cycles)
        need(rep not in values[kind, impl], "duplicate repetition")
        need(dots == 4 * meta["batches"] and cycles > 0, "wrong dot count/nonpositive cycles")
        values[kind, impl][rep] = cycles
        if meta["schema"] == 2:
            need(slot in ("0", "1"), "missing/invalid slot")
            need(impl == IMPLS[meta["first"] ^ (rep & 1) ^ int(slot)], "pair order mismatch")
        else:
            need(slot == "", "v2 rows without metadata")
    expected_reps = set(range(meta["reps"]))
    for key in values:
        need(set(values[key]) == expected_reps, f"missing/out-of-range repetitions: {key}")
    if meta["schema"] == 2:
        expected_rows = [(k, IMPLS[meta["first"] ^ (rep & 1) ^ slot], str(rep), str(slot))
                         for k in KINDS for rep in range(meta["reps"]) for slot in range(2)]
        need([r[:4] for r in rows] == expected_rows, "record execution order mismatch")
        warms = re.findall(r"bench warm kind=(batch4|e2e|chain) impl=(rvv|vdot) count=(\d+) first_cycles=(\d+) last_cycles=(\d+)", text)
        need(len(warms) == 6 and text.count("bench warm ") == 6, "missing/malformed warmup summaries")
        need({(w[0], w[1]) for w in warms} == set(values), "duplicate/missing warmup group")
        need(all(int(w[2]) == meta["warmup"] and int(w[3]) > 0 and int(w[4]) > 0 for w in warms), "invalid warmup summary")
    empty_values = {}
    for rep, loops, cycles in empty:
        rep, loops, cycles = int(rep), int(loops), int(cycles)
        need(rep not in empty_values and loops == meta["batches"] and cycles > 0, "invalid/duplicate empty control")
        empty_values[rep] = cycles
    need(set(empty_values) == expected_reps, "missing empty repetitions")
    groups, warnings = {}, []
    if meta.get("timing") != "mcycle_vstart_serialized":
        warnings.append("legacy/raw timestamp boundary is not serialized; do not claim complete-operation latency")
    for kind in KINDS:
        groups[kind] = {}
        for impl in IMPLS:
            vals = [values[kind, impl][r] for r in range(meta["reps"])]
            stats = distribution(vals)
            split = len(vals) // 2
            stats["half_drift"] = statistics.median(vals[split:]) / statistics.median(vals[:split]) - 1
            stats["cycles_per_dot"] = stats["median"] / (4 * meta["batches"])
            stats["raw"] = vals
            if meta["schema"] == 2:
                first_vals = [v for r, v in enumerate(vals) if IMPLS[meta["first"] ^ (r & 1)] == impl]
                second_vals = [v for r, v in enumerate(vals) if IMPLS[meta["first"] ^ (r & 1)] != impl]
                stats["slot_effect"] = statistics.median(first_vals) / statistics.median(second_vals) - 1
                warm = next(w for w in warms if w[:2] == (kind, impl))
                stats["warm_tail_drift"] = int(warm[4]) / stats["median"] - 1
            if (stats["cv"] > max_cv or abs(stats["half_drift"]) > max_drift
                    or abs(stats.get("slot_effect", 0)) > max_drift
                    or abs(stats.get("warm_tail_drift", 0)) > max_drift):
                warnings.append(f"{kind}/{impl}: variation, warm-tail/half drift or slot effect exceeds threshold")
            groups[kind][impl] = stats
        groups[kind]["raw_speedup"] = groups[kind]["rvv"]["median"] / groups[kind]["vdot"]["median"]
        groups[kind]["paired_speedups"] = [values[kind, "rvv"][r] / values[kind, "vdot"][r] for r in range(meta["reps"])]
    identities = {}
    for role in ("emu", "ref", "image"):
        matches = re.findall(rf"\[artifact {role}\] ([0-9a-f]{{64}})", text)
        need(len(matches) <= 1, "duplicate artifact identity")
        if matches:
            identities[role] = matches[0]
    return dict(log=str(path.resolve()), log_sha256=hashlib.sha256(raw).hexdigest(), meta=meta,
                artifacts=identities, groups=groups,
                warmup_summaries=warms if meta["schema"] == 2 else [],
                empty=distribution(list(empty_values.values())),
                warnings=warnings, stable=not warnings,
                qualification="smoke is flow validation only; raw guest cycles, NOT isolated latency/PPA")


def aggregate(runs, max_cv=0.05, max_drift=0.10):
    need(len({r["log"] for r in runs}) == len(runs), "repeated log path")
    need(len({r["log_sha256"] for r in runs}) == len(runs), "duplicate log content")
    meta = runs[0]["meta"]
    need(meta["schema"] == 2 and len(runs) >= (4 if meta["profile"] == "full" else 2) and len(runs) % 2 == 0, "need balanced fresh v2 runs (full>=4, smoke>=2)")
    config = {k: v for k, v in meta.items() if k != "first"}
    need(all({k: v for k, v in r["meta"].items() if k != "first"} == config for r in runs), "mixed protocol/configuration")
    need(sum(r["meta"]["first"] for r in runs) * 2 == len(runs), "unbalanced process starting orders")
    need(all(set(r["artifacts"]) == {"emu", "ref", "image"} for r in runs), "series requires artifact identities")
    for role in ("emu", "ref"):
        need(len({r["artifacts"][role] for r in runs}) == 1, f"mixed {role}")
    for first in (0, 1):
        need(len({r["artifacts"]["image"] for r in runs if r["meta"]["first"] == first}) == 1, "mixed image within one order")
    summary, warnings = {}, [f"run {n}: {w}" for n, r in enumerate(runs) for w in r["warnings"]]
    for kind in KINDS:
        item = {impl: distribution([r["groups"][kind][impl]["median"] for r in runs]) for impl in IMPLS}
        item["run_speedups"] = [r["groups"][kind]["raw_speedup"] for r in runs]
        item["speedup"] = distribution(item["run_speedups"])
        by_order = [statistics.median(r["groups"][kind]["raw_speedup"] for r in runs if r["meta"]["first"] == first) for first in (0, 1)]
        item["order_speedup_medians"] = by_order
        item["order_effect"] = by_order[0] / by_order[1] - 1
        if any(item[i]["cv"] > max_cv for i in IMPLS) or item["speedup"]["cv"] > max_cv or abs(item["order_effect"]) > max_drift:
            warnings.append(f"{kind}: cross-run variation or starting-order effect exceeds threshold")
        summary[kind] = item
    return dict(groups=summary, warnings=warnings, stable=not warnings,
                qualification="run medians are units; no pooled pseudo-replication or confidence interval claim")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+")
    parser.add_argument("--json-out")
    parser.add_argument("--max-cv", type=float, default=0.05)
    parser.add_argument("--max-drift", type=float, default=0.10)
    parser.add_argument("--strict-stability", action="store_true")
    args = parser.parse_args()
    try:
        need(0 < args.max_cv < 1 and 0 < args.max_drift < 1, "invalid stability thresholds")
        runs = [audit(p, args.max_cv, args.max_drift) for p in args.logs]
        report = dict(runs=runs, thresholds=dict(cv=args.max_cv, drift=args.max_drift))
        if len(runs) > 1:
            report["series"] = aggregate(runs, args.max_cv, args.max_drift)
        for n, run in enumerate(runs):
            print(f"run={n} schema={run['meta']['schema']} profile={run['meta']['profile']} stable={run['stable']}")
            print("kind,rvv_median,vdot_median,raw_speedup,rvv_min_max,vdot_min_max,rvv_cv,vdot_cv")
            for kind, g in run["groups"].items():
                r, v = g["rvv"], g["vdot"]
                print(f"{kind},{r['median']},{v['median']},{g['raw_speedup']:.6f},{r['min']}:{r['max']},{v['min']}:{v['max']},{r['cv']:.6f},{v['cv']:.6f}")
            print(f"empty median={run['empty']['median']}; NOT subtracted")
        if "series" in report:
            for kind, group in report["series"]["groups"].items():
                s = group["speedup"]
                print(f"series {kind}: run-speedup median={s['median']:.6f} min={s['min']:.6f} max={s['max']:.6f} cv={s['cv']:.6f} order_effect={group['order_effect']:.6f}")
        warnings = report["series"]["warnings"] if len(runs) > 1 else runs[0]["warnings"]
        for warning in warnings:
            print("STABILITY WARNING:", warning)
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n")
        print("benchmark data audit PASS; stability is separate; NOT isolated FU latency or PPA")
        return 3 if args.strict_stability and warnings else 0
    except (OSError, ValueError, KeyError) as error:
        print(f"benchmark audit FAIL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
