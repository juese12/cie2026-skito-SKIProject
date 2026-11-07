#!/usr/bin/env python3
"""通过稳定的套件名称复核已有交付记录；所有模式均不启动仿真。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT=Path(__file__).resolve().parents[1]
RECORDS={
    'function': ['stage2/sew16/check-core.py',
                 'stage2/logs/20261026T205315-sew16-core.full.log',
                 '--coordinator','stage2/logs/20261026T205315-sew16-core-regression.full.log'],
    'control': ['stage2/e16-events/check-experiment.py',
                'stage2/logs/20261027T131534-e16-events.results.json',
                '--coordinator','stage2/logs/20261027T131534-e16-event-experiment-uart-fix.full.log'],
    'performance': ['stage3/sew16-perf/review.py',
                    'stage3/logs/20261027T190338-sew16-perf4-full.results.json',
                    '--review-edition','--strict'],
    'performance-data': ['stage3/sew16-perf/review-public-data.py',
                         'stage3/logs/20261027T190338-sew16-perf4-full.results.json',
                         '--strict'],
    'preservation': ['stage2/sew16/check-preservation.py'],
}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--suite',choices=RECORDS,required=True)
    p.add_argument('--out',type=Path,required=True,help='不存在的新输出文件')
    args=p.parse_args();out=args.out.resolve()
    if out.exists():p.error('输出已存在，请使用新的文件名')
    r=subprocess.run([sys.executable,*RECORDS[args.suite],'--out',str(out)],cwd=ROOT,capture_output=True,text=True)
    if r.returncode not in (0,3):
        sys.stderr.write(r.stderr or r.stdout)
        raise SystemExit(r.returncode)
    result=json.loads(out.read_text())
    print(json.dumps({'suite':args.suite,'status':result.get('status'),
                      'strict_stability_exit':result.get('strict_exit'),
                      'output':str(out)},ensure_ascii=False))
    raise SystemExit(r.returncode)


if __name__=='__main__':main()
