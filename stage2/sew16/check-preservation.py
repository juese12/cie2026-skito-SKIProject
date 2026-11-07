#!/usr/bin/env python3
"""验证历史实验材料；两个已升级 RTL 使用修改前的原件核对。"""
import argparse
import importlib.util
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
workspace = root.parent
spec = importlib.util.spec_from_file_location('docs',root/'scripts/check-documentation.py')
docs = importlib.util.module_from_spec(spec); spec.loader.exec_module(docs)
p = argparse.ArgumentParser()
p.add_argument('--out',type=Path,required=True)
args = p.parse_args()
checked = docs.check(root, review_edition=True)
state = json.loads((root/'stage3/logs/20261006T060358-16-isolation-perf.state.json').read_text())
upgraded = {
    'XiangShan/src/main/scala/xiangshan/backend/fu/vector/VDot8.scala',
    'XiangShan/src/main/scala/xiangshan/backend/fu/wrapper/VIMacU.scala',
}
records = []
for name,expected in state['frozen'].items():
    path = Path(name)
    relative = str(path.relative_to(workspace))
    if relative in upgraded:
        archived = root/'stage2/sew16/before'/relative
        assert docs.digest(archived) == expected, f'old source archive mismatch: {archived}'
        records.append(dict(path=name, status='intentionally upgraded',before_sha256=expected,
                            archive=str(archived),current_sha256=docs.digest(path)))
    else:
        assert docs.matches_recorded_file(root,path,expected,review_edition=True), name
        records.append(dict(path=name,status='original artifact or recorded October-20 document edition'))
result=dict(status='PASS',documentation=checked,records=records,
            qualification='two current RTL source hashes intentionally changed; old snapshots match; old manifest not rewritten')
with args.out.open('x') as f:json.dump(result,f,indent=2)
print(json.dumps(dict(status='PASS',old_records=len(records),upgraded_sources=len(upgraded),documentation=checked)))
