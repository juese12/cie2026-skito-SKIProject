#!/usr/bin/env python3
"""搬迁后仅复核已保存的公开性能数据，不要求仿真器、参考库或镜像。"""
import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
import sys

import analyze as A
import common as C


ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    'stage3/sew16-perf/' + name for name in
    ('main.c', 'bench.S', 'params.S', 'Makefile', 'common.py', 'analyze.py',
     'series.py', 'protocol.json')
}
CSV_HEADER = ['label', 'core', 'init_seed', 'data_seed', 'first', 'bits', 'kind',
              'phase', 'rep', 'slot', 'impl', 'dots', 'cycles']


def inside(path):
    path = Path(path).resolve()
    C.need(path.is_relative_to(ROOT), 'public data path escapes package')
    return path


def layout(results, state):
    results = inside(results)
    prefix = Path(state['prefix'])
    C.need(prefix.is_absolute() and '..' not in prefix.parts and
           prefix.parent.name == 'logs' and prefix.parent.parent.name == 'stage3',
           'invalid recorded experiment root')
    C.need(results.name == prefix.name + '.results.json', 'wrong completed results name')
    origin = prefix.parents[2]

    def relocated(name):
        old = Path(name)
        C.need(old.is_absolute() and '..' not in old.parts and old.is_relative_to(origin),
               'recorded evidence is outside experiment project')
        return inside(ROOT / old.relative_to(origin))

    return origin, relocated


def source_inputs(state, origin, relocated):
    # 只选公共数据解释所需的源码；二进制身份仍由原完整审计负责。
    selected = {}
    for table in (state['frozen'], state['analysis_sources']):
        for name, expected in table.items():
            old = Path(name)
            if old.is_relative_to(origin) and str(old.relative_to(origin)) in SOURCES:
                current = relocated(name)
                C.need(current not in selected or selected[current] == expected,
                       'inconsistent recorded analysis source')
                selected[current] = expected
    C.need({str(p.relative_to(ROOT)) for p in selected} == SOURCES,
           'incomplete public analysis sources')
    for current, expected in selected.items():
        if C.EDITION.matches_expected(ROOT, current, expected):
            continue
        # 整个作品目录改名时，旧中文修订记录仍使用原作品目录名。
        # 只接受记录中的精确前后内容，不以路径不同为由忽略源码检查。
        key = str(Path(origin.name) / current.relative_to(ROOT))
        entry = C.EDITION.ledger(ROOT)['code'].get(key)
        C.need(entry is not None and
               hashlib.sha256(entry['before_content'].encode()).hexdigest() == expected and
               entry['before_sha256'] == expected and
               current.read_bytes() == entry['after_content'].encode(),
               'public analysis source changed: ' + str(current.relative_to(ROOT)))
    return {current: C.sha(current) for current in selected}


def files(results):
    state = json.loads(inside(results).read_text())
    origin, relocated = layout(results, state)
    selected = source_inputs(state, origin, relocated)
    prefix = str(inside(results)).removesuffix('.results.json')
    paths = {inside(results), Path(prefix + '.analysis.json'),
             Path(prefix + '.analysis.samples.csv'), *selected,
             ROOT / 'stage3/sew16-perf/review-public-data.py',
             ROOT / 'scripts/review-submission.py',
             ROOT / 'scripts/chinese-edition.py',
             ROOT / 'manifest/chinese-edition-20261102.json'}
    paths.update(relocated(r['log']) for r in state['runs'])
    return sorted(str(inside(p).relative_to(ROOT)) for p in paths)


def review(results):
    results = inside(results)
    state = json.loads(results.read_text())
    origin, relocated = layout(results, state)
    selected = source_inputs(state, origin, relocated)
    C.need(state['status'] == 'CPU_PASS' and len(state['runs']) == 8,
           'incomplete eight-process record')
    C.need(len({r['label'] for r in state['runs']}) == 8, 'duplicate process labels')
    replay = copy.deepcopy(state)
    replay['frozen'] = selected
    expected_csv = []
    for source, run in zip(state['runs'], replay['runs']):
        path = relocated(source['log'])
        raw = path.read_text()
        C.need('synthetic parser fixture' not in raw.lower(),
               'synthetic input is not CPU evidence')
        params = source['params']
        C.need(f'Using seed = {params["seed"]}\n' in raw and
               f'Seed={params["seed"]} Guest cycle spent:' in raw,
               'runtime initialization seed mismatch')
        for name, expected in source['inputs'].items():
            C.need(state['frozen'].get(name) == expected,
                   'run inputs disagree with experiment record')
        audit = C.parse(path, params)
        C.need(audit == source['audit'], 'raw data differ from recorded audit')
        run['log'] = str(path)
        cases = {(int(c['bits']), int(c['kind'])): int(c['dots']) for c in audit['cases']}
        for row in audit['samples']:
            expected_csv.append([
                run['label'], run['core'], str(params['seed']),
                f'{params["data"]:08x}', str(params['first']),
                *[row[k] for k in ('bits', 'kind', 'phase', 'rep', 'slot', 'impl')],
                str(cases[int(row['bits']), int(row['kind'])]), row['cycles']])

    # 复用正式统计函数，仅将本次需要检查的输入限定为上述已核对源码。
    # 所有原记录保持原样；比较时只翻译结果中的日志路径。
    computed = json.loads(json.dumps(A.analyze(replay)))
    prefix = str(results).removesuffix('.results.json')
    saved = json.loads(Path(prefix + '.analysis.json').read_text())
    for run in saved['runs']:
        run['log'] = str(relocated(run['log']))
    C.need(saved == computed, 'saved statistics differ from raw-data replay')
    with Path(prefix + '.analysis.samples.csv').open(newline='') as stream:
        reader = csv.reader(stream)
        C.need(next(reader) == CSV_HEADER, 'wrong sample CSV header')
        C.need(list(reader) == expected_csv and len(expected_csv) == 1920,
               'incomplete or changed sample CSV')
    return dict(
        status='PASS', mode='public-data-only', data_status=computed['status'],
        stable=computed['stable'], strict_exit=computed['strict_exit'],
        warnings=computed['warnings'], formal_processes=8, raw_sample_rows=1920,
        results=str(results.relative_to(ROOT)),
        checked=['raw logs', 'runtime seeds', 'independent signed integer oracle',
                 'full sample order', 'analysis sources and protocol',
                 'all statistics and stability warnings', 'complete sample CSV'],
        artifact_identity='NOT_AUDITED', parameter_overlays='NOT_AUDITED',
        timer_events='NOT_AUDITED', report_document='NOT_AUDITED',
        scope='saved public data replay only; no CPU simulation or executable identity audit')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('results', type=Path)
    p.add_argument('--out', type=Path, help='不存在的新结果文件')
    p.add_argument('--strict', action='store_true')
    p.add_argument('--list-files', action='store_true', help='列出本模式所需公开材料的相对路径')
    args = p.parse_args()
    if args.list_files:
        C.need(args.out is None, '--list-files cannot write a review result')
        print('\n'.join(files(args.results)))
        return 0
    if args.out is None:
        p.error('--out is required unless --list-files is selected')
    C.need(not args.out.exists(), 'output exists; choose a new filename')
    result = review(args.results)
    with args.out.open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps({k: result[k] for k in
                     ('status', 'mode', 'stable', 'strict_exit', 'formal_processes',
                      'raw_sample_rows', 'artifact_identity')}, ensure_ascii=False))
    return result['strict_exit'] if args.strict else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, StopIteration) as error:
        print(f'[public data review FAIL] {error}', file=sys.stderr)
        raise SystemExit(1)
