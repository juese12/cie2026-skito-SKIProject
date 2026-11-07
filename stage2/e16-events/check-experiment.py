#!/usr/bin/env python3
"""复核四组事件审核及运行材料，无需启动处理器。"""
import argparse
import importlib.util
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
edition_spec=importlib.util.spec_from_file_location('event_chinese_edition',ROOT/'scripts/chinese-edition.py')
EDITION=importlib.util.module_from_spec(edition_spec);edition_spec.loader.exec_module(EDITION)
spec=importlib.util.spec_from_file_location('audit',Path(__file__).with_name('audit.py'))
A=importlib.util.module_from_spec(spec);spec.loader.exec_module(A)
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('results',type=Path)
p.add_argument('--coordinator',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
args=p.parse_args()
r=json.loads(args.results.read_text())
A.need(r['status']=='PASS','experiment not complete')
for path,expected in r['plan']['hashes'].items():
    # 仅接受原输入或已登记且核验通过的中文注释版本，事件和日志仍严格核对。
    A.need(EDITION.matches_expected(ROOT,path,expected),'frozen experiment input changed: '+path)
baseline=r['baseline'];arch=A.audit_log(baseline['log'])
A.need(arch==baseline['architecture'],'baseline audit mismatch')
reuse=r['plan'].get('reused_baseline')
if reuse:
    A.need(A.sha(reuse['log'])==reuse['log_sha256'],'reused baseline changed')
    A.need(A.sha(baseline['reused_from_plan'])==reuse['plan_sha256'],'original baseline plan changed')
def commits(log):
    text=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',Path(log).read_text())
    return re.findall(r'\[\d{2}\] commit pc [^\n]*',text)
before=commits(baseline['log']);after=commits(r['runs'][0]['log'])
A.need(before and before==after and len(before)==r['observer']['commits'],'observer commit mismatch')
for name in ('instructions','cycles'):
    A.need(arch[name]==r['runs'][0]['architecture'][name]==r['observer'][name],
           'observer changed '+name)
A.need([x['init_seed'] for x in r['runs']]==[101,202,303,404],'wrong independent initialization seed list')
A.need(len({x['log'] for x in r['runs']})==4 and len({x['events'] for x in r['runs']})==4,
       'reused process log/event path')
summary=[]
for x in r['runs']:
    text=Path(x['log']).read_text()
    A.need(f'Using seed = {x["init_seed"]}\n' in text and
           f'Seed={x["init_seed"]} Guest cycle spent:' in text,'runtime seed mismatch')
    arch=A.audit_log(x['log']);A.need(arch==x['architecture'],'architecture audit mismatch')
    event=A.load_events(x['events'],arch['symbols']);A.need(event==x['audit'],'event audit mismatch')
    proof={kind:len(events) for kind,events in event['proof'].items()}
    summary.append(dict(seed=x['init_seed'],instructions=arch['instructions'],cycles=arch['cycles'],
      proof=proof,canceled_outputs=sum(len(e['victims']) for events in event['proof'].values() for e in events),
      event_rows=event['event_rows'],event_bytes=event['event_bytes'],event_sha256=event['event_sha256']))
coordinator=args.coordinator.read_text()
A.need(re.findall(r'^\[PASS\] (seed\d+)$',coordinator,re.M)==['seed101','seed202','seed303','seed404'],
       'missing ordered independent process completion')
A.need(coordinator.count('[e16 experiment COMPLETE]')==1 and
       re.findall(r'^\[exit\] (\d+)$',coordinator,re.M)==['0'],'coordinator not completed successfully')
result=dict(status='PASS',runs=summary,observer=r['observer'],
  distinct_event_traces=len({x['event_sha256'] for x in summary}),
  total_event_bytes=sum(x['event_bytes'] for x in summary),
  qualification='four independently seeded processes; identical traces do not imply four different control histories',
  results_sha256=A.sha(args.results),coordinator_sha256=A.sha(args.coordinator))
with args.out.open('x') as f:json.dump(result,f,indent=2)
print(json.dumps(result,ensure_ascii=False))
