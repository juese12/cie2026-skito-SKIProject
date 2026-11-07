#!/usr/bin/env python3
"""描述全部端到端样本的偏差与关联，不将统计关联当作根因。"""
import argparse
import importlib.util
import json
import statistics
from pathlib import Path

spec = importlib.util.spec_from_file_location("audit", Path(__file__).with_name("analyze-bench.py"))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def diagnose(runs):
    result = []
    for n, run in enumerate(runs):
        first = run["meta"]["first"]
        values = run["groups"]["e2e"]["vdot"]["raw"]
        early = [v for rep,v in enumerate(values) if (first ^ (rep & 1)) == 0]
        late = [v for rep,v in enumerate(values) if (first ^ (rep & 1)) == 1]
        delta = statistics.median(early)-statistics.median(late)
        result.append(dict(run=n, first=first, all_raw=values, first_in_pair=early,
                           second_in_pair=late, median_slot_delta=delta,
                           delta_per_batch=delta/run["meta"]["batches"],
                           stats=run["groups"]["e2e"]["vdot"]))
    return dict(runs=result, caveat="Position association, not causal cache/store/branch attribution. No sample removed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+")
    args = parser.parse_args()
    print(json.dumps(diagnose([bench.audit(p) for p in args.logs]), indent=2))
