#!/usr/bin/env python3
"""只读复核 v4 运行材料、原始数据、统计、报告和完整 CSV。"""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import common as C
import analyze as A

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('results',type=Path);p.add_argument('--out',type=Path,required=True);p.add_argument('--strict',action='store_true')
p.add_argument('--review-edition',action='store_true',help='accept only the explicitly recorded editorial report edition')
args=p.parse_args();results=args.results.resolve()
C.need(results.name.endswith('.results.json'),'use exact completed results file')
state=json.loads(results.read_text());prefix=Path(str(results).removesuffix('.results.json'))
C.frozen(state['frozen']);C.frozen(state['analysis_sources'])
original=C.IMAGE.read_bytes();offset=C.symbols()['perf_params']-0x80000000
expected_csv=[]
for run in state['runs']:
    C.frozen(run['inputs'])
    for path,h in run['inputs'].items():C.need(state['frozen'].get(path)==h,'run not from frozen formal experiment')
    raw=Path(run['log']).read_text()
    C.need('synthetic parser fixture' not in raw.lower(),'synthetic input is not CPU evidence')
    C.need(f'Using seed = {run["params"]["seed"]}\n' in raw and
      f'Seed={run["params"]["seed"]} Guest cycle spent:' in raw,'runtime initialization seed mismatch')
    C.need(C.parse(run['log'],run['params'])==run['audit'],'run raw data changed')
    overlay_path=next(v.split('=',1)[1] for v in run['command'] if v.startswith('--gcpt-restore='))
    overlay=Path(overlay_path).read_bytes();params=run['params']
    C.need(C.sha(overlay_path)==run['overlay']['overlay_sha256'],'overlay changed')
    C.need(len(overlay)==offset+8==run['overlay']['overwrite_nbytes'],'wrong overwrite length')
    C.need(overlay[:offset]==original[:offset],'overlay changes instructions')
    C.need(overlay[offset:]==bytes([4,params['profile'],params['first'],params['wide']])+params['data'].to_bytes(4,'little'),'wrong boot parameters')
    cases={(int(c['bits']),int(c['kind'])):int(c['dots']) for c in run['audit']['cases']}
    for row in run['audit']['samples']:
        expected_csv.append([run['label'],run['core'],str(params['seed']),f'{params["data"]:08x}',str(params['first']),
          *[row[k] for k in ('bits','kind','phase','rep','slot','impl')],str(cases[int(row['bits']),int(row['kind'])]),row['cycles']])
for path,h in state['gates'].items():C.need(C.sha(path)==h,'preflight/timer gate changed')
pre_path=next(path for path in state['gates'] if path.endswith('.results.json'))
pre=json.loads(Path(pre_path).read_text())
for run in pre['runs']:
    C.frozen(run['inputs']);C.need(C.parse(run['log'],run['params'])==run['audit'],'preflight replay changed')
timer_path=next(path for path in state['gates'] if path.endswith('.timer-audit.json'))
spec=importlib.util.spec_from_file_location('timer_audit',C.SRC/'audit-timer.py')
timer=importlib.util.module_from_spec(spec);spec.loader.exec_module(timer)
C.need(timer.audit(pre['runs'][0]['events'])==json.loads(Path(timer_path).read_text()),'bounded timer proof changed')
computed=A.analyze(state);computed=json.loads(json.dumps(computed))
analysis=Path(str(prefix)+'.analysis.json');saved=json.loads(analysis.read_text())
C.need(saved==computed,'statistics differ from full raw-data replay')
report=C.EDITION.resolve_path(C.ROOT,C.ROOT/'stage3/reports'/(prefix.name+'-performance.md'))
expected_report=A.report(computed,results)
if args.review_edition:
    # 用原分析器的报告模板核对历史结果；当前统计仍由当前分析器完整复算。
    original_analyzer=C.EDITION.prior_view(C.ROOT,C.SRC/'analyze.py')[2]
    original_namespace={'__name__':'original_report_template','__file__':str(C.SRC/'analyze.py')}
    exec(compile(original_analyzer,str(C.SRC/'analyze.py'),'exec'),original_namespace)
    expected_report=original_namespace['report'](computed,results)
    spec=importlib.util.spec_from_file_location('report_documentation',C.ROOT/'scripts/check-documentation.py')
    documentation=importlib.util.module_from_spec(spec);spec.loader.exec_module(documentation)
    C.need(documentation.matches_recorded_file(C.ROOT,report,
      hashlib.sha256(expected_report.encode('utf-8')).hexdigest(),review_edition=True),
      'report is neither the generated original nor its recorded editorial edition')
else:
    C.need(report.read_text()==expected_report,'report differs from data generator')
csv_path=Path(str(prefix)+'.analysis.samples.csv')
with csv_path.open(newline='') as stream:
    reader=csv.reader(stream);next(reader);actual_csv=list(reader)
C.need(actual_csv==expected_csv and len(actual_csv)==1920,'sample CSV is incomplete or differs')
r=dict(status='PASS',data_status=saved['status'],stable=saved['stable'],strict_exit=saved['strict_exit'],
  formal_processes=8,preflight_processes=4,raw_sample_rows=1920,
  evidence={str(path):C.sha(path) for path in (results,analysis,report,csv_path)},
  reviewer_sha256=C.sha(__file__),scope='all saved results, parameter overlays, identities, timer proof, statistics, report and complete CSV replayed without CPU simulation')
with args.out.open('x') as f:json.dump(r,f,indent=2)
print(json.dumps(r,ensure_ascii=False))
if args.strict:raise SystemExit(r['strict_exit'])
