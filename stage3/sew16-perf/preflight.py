#!/usr/bin/env python3
"""当前核的短计时边界探针及平衡烟雾测试入口，尚不启动正式长测。"""
from datetime import datetime
import json
import common as C

prefix=C.ROOT/'stage3/logs'/datetime.now().strftime('%Y%m%dT%H%M%S-sew16-perf4-preflight')
runs=[]
for label,core,profile,first,wide in [('probe','events',0,0,1),('smoke0','new',1,0,1),
                                    ('smoke1','new',1,1,1),('old-smoke','old',1,0,0)]:
    r=C.run(prefix,label,core,profile,first,wide,0x56444f54,101)
    runs.append(r)
    with open(str(prefix)+'.state.json','w') as f:json.dump(dict(status='RUNNING',runs=runs),f,indent=2)
with open(str(prefix)+'.results.json','x') as f:json.dump(dict(status='PASS',runs=runs),f,indent=2)
print('[preflight CPU COMPLETE]',prefix,flush=True)
