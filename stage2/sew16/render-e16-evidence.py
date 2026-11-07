#!/usr/bin/env python3
"""绘制已有 e16 模块 VCD 采样，并单独标明整核事件。

图件和精确机器采样均来自已归档并核验的证据，
不启动整核或模块仿真，也不使用虚构激励。
"""
import argparse
import gzip
import hashlib
import html
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
T='TOP.'
H=T+'VDotIntegrationHarness.'
F=H+'fu.'
D=F+'vdot.'

def module(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def signed(x,w):return x-(1<<w) if x&(1<<(w-1)) else x

def tracks():
    rows=[('clock','bit',T+'clock'),('FU input valid','bit',H+'fu_io_in_valid'),
      ('cancel','bit',T+'io_cancel'),('input op / tag','op',None),
      ('input vsew (0=e8, 1=e16)','dec',T+'io_config_vtype_vsew'),
      ('input VL','dec',T+'io_config_vl'),('vs1 [127:0]','hex',T+'io_vs1'),
      ('vs2 [127:0]','hex',T+'io_vs2'),
      ('isolatedVs1 [127:0]','hex',D+'isolatedVs1'),
      ('isolatedVs2 [127:0]','hex',D+'isolatedVs2'),
      ('dot enable[0]','bit',D+'io_enable_0'),
      ('dot enable[1]','bit',D+'io_enable_1'),('SEW16 mode S1','bit',D+'sew16S1'),
      ('SEW16 mode S2','bit',D+'sew16S2')]
    rows += [(f'products_{i} signed32','s32',D+f'products_{i}') for i in range(8)]
    return rows+[('sum signed35','s35',D+'sum'),('MAC0 input fire','bit',F+'vimacs_0.io_fire'),
      ('output valid','bit',T+'io_outValid'),('output tag (valid only)','tag',T+'io_outTag'),
      ('output illegal (valid only)','legal',T+'io_illegal'),
      ('output low64 (hex, valid)','low',T+'io_result'),
      ('output high64 (hex, valid)','high',T+'io_result')]

def read_wave(path):
    wanted={key for _,_,key in tracks() if key}|{T+'reset',T+'io_tag',T+'io_op'}
    scope=[];names={};decl={};values={};last=None;time=0;edges=[]
    def sample():
        nonlocal last
        if not names:return
        now={name:values.get(code) for name,code in names.items()};now['time']=time
        if last is not None and last[T+'clock']==0 and now[T+'clock']==1 and not last[T+'reset'] and not now[T+'reset']:
            assert wanted<=names.keys(),'missing VCD signals'
            assert all(v is not None for s in (last,now) for v in s.values()),'unknown VCD sample'
            edges.append((last,now))
        last=now
    digest=hashlib.sha256()
    with gzip.open(path,'rb') as stream:
        for raw in stream:
            digest.update(raw);line=raw.decode('ascii').strip();parts=line.split()
            if line.startswith('$scope'):scope.append(parts[2])
            elif line.startswith('$upscope'):scope.pop()
            elif line.startswith('$var'):
                name='.'.join(scope+[parts[4]])
                if name in wanted:
                    names[name]=parts[3];decl[name]=dict(width=int(parts[2]),code=parts[3])
            elif line.startswith('#'):sample();time=int(line[1:])
            elif line.startswith('b'):
                bits,code=line[1:].split()
                values[code]=None if any(c in bits.lower() for c in 'xz') else int(bits,2)
            elif line and line[0] in '01xXzZ':values[line[1:]]=int(line[0]) if line[0] in '01' else None
    sample();return edges,decl,digest.hexdigest()

def select_cases(edges):
    cases=[]
    for polarity,test in [('positive',lambda x:x>2**31-1),('negative',lambda x:x<-(2**31))]:
        for i,(p,q) in enumerate(edges[:-1]):
            if not (p[D+'io_enable_0'] and p[T+'io_config_vtype_vsew']==1):continue
            a=[signed((p[T+'io_vs1']>>(16*j))&65535,16) for j in range(8)]
            b=[signed((p[T+'io_vs2']>>(16*j))&65535,16) for j in range(8)]
            products=[x*y for x,y in zip(a,b)];total=sum(products)
            if not test(total):continue
            nextpre,nextpost=edges[i+1]
            assert [signed(q[D+f'products_{j}'],32) for j in range(8)]==products
            assert nextpre[D+'io_enable_1']==1 and nextpre[F+'vimacs_0.io_fire']==1
            assert nextpost[T+'io_outValid']==1 and nextpost[T+'io_outTag']==p[T+'io_tag']
            assert signed(nextpost[D+'sum'],35)==total
            assert nextpost[T+'io_result']==total%2**64 and nextpost[T+'io_illegal']==0
            cases.append(dict(name=polarity,edge=i,tag=p[T+'io_tag'],a=a,b=b,products=products,total=total,
              input_pre_time=p['time'],product_post_time=q['time'],result_post_time=nextpost['time'],
              result_hex=f'{nextpost[T+"io_result"]:032x}',
              samples=[dict(edge=j,pre=edges[j][0],post=edges[j][1]) for j in range(i-1,i+4)]))
            break
        else:raise AssertionError('no qualifying signed e16 case '+polarity)
    return cases

class SVG:
    def __init__(self,title,subtitle):
        self.parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1560" height="1110" viewBox="0 0 1560 1110">',
          '<rect width="100%" height="100%" fill="#f6f8fc"/>',
          '<style>text{font-family:DejaVu Sans,sans-serif;fill:#172b4d}</style>']
        self.text(28,35,title,23);self.text(28,64,subtitle,14)
    def text(self,x,y,value,size=13,color='#172b4d'):
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}">{html.escape(str(value))}</text>')
    def line(self,x,y,x2,y2,color='#087f5b',width=2):
        self.parts.append(f'<path d="M{x},{y} L{x2},{y2}" fill="none" stroke="{color}" stroke-width="{width}"/>')
    def rect(self,x,y,w,h,color):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}"/>')
    def finish(self):return '\n'.join(self.parts+['</svg>'])

def display(sample,kind,key):
    if kind in ('tag','legal','low','high') and not sample[T+'io_outValid']:return '-'
    if kind=='op':return f'{sample[T+"io_op"]:03x}/{sample[T+"io_tag"]}'
    value=sample[key]
    if kind=='hex':
        s=f'{value:032x}';return s[:5]+'..'+s[-5:]
    if kind=='low':return f'{value&((1<<64)-1):016x}'
    if kind=='high':return f'{value>>64:016x}'
    if kind.startswith('s'):return str(signed(value,int(kind[1:])))
    return str(value)

def module_figure(case):
    g=SVG(f'MODULE VCD: signed e16 {case["name"]} result and mixed-stage overlap',
      f'Archived current e8/e16 wrapper RTL; input tag {case["tag"]}; exact dot sum = {case["total"]}. No new simulation.')
    g.text(28,91,'Each column shows settled PRE > POST around one rising edge; raw VCD timestamps, not CPU cycles.',14)
    x0=325;cw=240;y0=163;dy=28
    for ci,row in enumerate(case['samples']):
        x=x0+ci*cw
        if row['edge'] in (case['edge'],case['edge']+1):g.rect(x,103,cw,880,'#eaf4ef')
        g.text(x+5,123,f'edge {row["edge"]}: t={row["pre"]["time"]}/{row["post"]["time"]}',12)
        g.text(x+5,143,'PRE',11);g.text(x+cw/2+5,143,'POST',11)
        g.line(x,148,x,975,'#d4dfeb',1)
        for ri,(label,kind,key) in enumerate(tracks()):
            y=y0+ri*dy
            if ci==0:g.text(20,y+4,label,13)
            p,q=row['pre'],row['post'];mid=x+cw/2
            if kind=='bit':
                yp=y-7 if p[key] else y+7;yq=y-7 if q[key] else y+7
                g.line(x+4,yp,mid,yp);g.line(mid,yp,mid,yq);g.line(mid,yq,x+cw-4,yq)
            else:
                # 同时展示沿前与沿后快照，不虚构未采样的总线跳变。
                g.text(x+5,y+4,display(p,kind,key)+' > '+display(q,kind,key),10)
    g.text(28,1020,'Green columns: S1 captures eight signed32 products; next edge S2 captures signed35 sum while ordinary MAC enters S1.',14)
    g.text(28,1047,'Target DOT output: high64 = zero; low64 = sign-extended sum. Ordinary MAC outputs have their own full-vector semantics.',14)
    g.text(28,1074,'Exact full-width samples, declarations, lane inputs/products and source hashes are saved in e16-evidence-excerpts.json.',14)
    g.text(28,1098,'Scope: real module VCD, fixed-ready wrapper. This figure is not a whole-core VCD or a physical timing/power measurement.',13)
    return g.finish()

def core_case(result,kind):
    audit=result['audit'];event=audit['proof'][kind][0]
    victims=[r for r in audit['records'] if r['seq'] in event['victims']]
    pulses=[]
    for r in victims:
        pulses += [(f'FU accept: tag {r["tag"]} / seq {r["seq"]}',[r['input']['cycle']]),
                   (f'FU result: tag {r["tag"]} / seq {r["seq"]}',[r['output']['cycle']])]
    if kind=='branch':pulses.append(('WB taken + mispredict',[event['decision']]))
    pulses.append(('accepted redirect' if kind=='branch' else 'ROB exception flush',[event['cycle']]))
    if kind=='exception':pulses.append(('registered illegal exception',[event['exception_confirmed']]))
    pulses.append(('branch commit' if kind=='branch' else 'resume-PC commit',[event['settled']]))
    for r in victims:
        assert 'commit' not in r
        pulses.append((f'commit same allocation {r["tag"]}/{r["seq"]}',[]))
    left=min(r['input']['cycle'] for r in victims)-2
    right=max(r['output']['cycle'] for r in victims)+3
    windows=[(left,right),(event.get('decision',event['cycle'])-2,event['cycle']+4)]
    if kind=='branch':windows[-1]=(windows[-1][0],event['settled']+3)
    else:windows.append((event['settled']-2,event['settled']+3))
    return dict(kind=kind,event=event,victims=victims,pulses=pulses,windows=windows)

def core_figure(case):
    g=SVG('CPU EVENT TIMELINE: e16 '+case['kind']+' cancellation',
      'Actual seed101 JSONL events, settled_low phase. Event lanes are derived predicates, not a continuous RTL VCD.')
    g.text(28,92,'Broken time axis: absolute cycle labels retained in every panel. Gaps are omitted, never compressed into adjacent cycles.',14)
    windows=case['windows'];x0=420;pw=1100/len(windows);y0=178;dy=48
    for wi,(lo,hi) in enumerate(windows):
        px=x0+wi*pw;scale=(pw-22)/(hi-lo+1)
        g.text(px,124,f'cycles {lo}..{hi}',14)
        for c in range(lo,hi+1):
            x=px+(c-lo)*scale
            g.line(x,153,x,y0+(len(case['pulses'])-1)*dy+18,'#dce4ef',1)
            if (c-lo)%2==0:g.text(x,146,c,10)
        for ri,(label,times) in enumerate(case['pulses']):
            y=y0+ri*dy
            if wi==0:g.text(24,y+5,label,13)
            last=None
            for c in range(lo,hi+1):
                x=px+(c-lo)*scale;now=y-10 if c in times else y+10
                if last is not None:g.line(x,last,x,now)
                g.line(x,now,x+scale,now);last=now
        if wi<len(windows)-1:g.text(px+pw-15,132,'//',20)
    y=905
    for r in case['victims']:
        g.text(28,y,f'PC 0x{r["pc"]:x}, tag {r["tag"]}, seq {r["seq"]}: result 0x{r["output"]["result"]}; no same-allocation commit.',13)
        y+=25
    g.text(28,1010,'Input configuration checked: vsew=1 (e16), VL=8, m1, vm=1, vstart=0, vill=0; full128 result matches an independent oracle.',13)
    g.text(28,1036,'Flat commit lanes mean no such event in the shown windows; the full-run audit also excludes a later same-allocation commit.',13)
    g.text(28,1062,'The first qualifying complete cancellation is selected from the audited run; ROB flag/value and allocation sequence prevent tag-reuse confusion.',13)
    g.text(28,1090,'This records real CPU behavior, but does not expose multiplier products or every internal transition. Those are shown separately by module VCD.',13)
    return g.finish()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'stage2/reports/figures/e16-summary')
    p.add_argument('--refresh-generated',action='store_true',help='refresh only verified generator-owned derived figures')
    args=p.parse_args();out=args.out.resolve()
    if out.exists():
        assert args.refresh_generated,'refusing to overwrite figures'
        old=json.loads((out/'e16-evidence-manifest.json').read_text())
        assert old['generator']==str(Path(__file__).relative_to(ROOT))
        assert all(sha(out/name)==h for name,h in old['outputs'].items()),'derived assets changed externally'
    wave=ROOT/'stage2/sew16/mixed-module.vcd.gz'
    isolation=ROOT/'stage2/logs/20261026-sew16-isolation.json'
    edges,decl,unpacked_sha=read_wave(wave)
    assert unpacked_sha==json.loads(isolation.read_text())['sha256'],'module VCD identity changed'
    cases=select_cases(edges)
    result_path=ROOT/'stage2/logs/20261027T131534-e16-events.results.json'
    result=json.loads(result_path.read_text());run=result['runs'][0]
    audit=module('e16audit',ROOT/'stage2/e16-events/audit.py')
    assert audit.load_events(run['events'],run['architecture']['symbols'])==run['audit']
    core=[core_case(run,kind) for kind in ('branch','exception')]
    out.mkdir(parents=True,exist_ok=args.refresh_generated)
    raster=module('existing_raster',ROOT/'stage3/tests/render-p1-wave-figures.py')
    for name,svg in [(f'module-e16-{c["name"]}',module_figure(c)) for c in cases]+[(f'core-e16-{c["kind"]}',core_figure(c)) for c in core]:
        target=out/(name+'.svg');target.write_text(svg)
        raster.png_from_svg(target,target.with_suffix('.png'))
    excerpts=dict(status='PASS',module=dict(uncompressed_vcd_sha256=unpacked_sha,edges=len(edges),declarations=decl,cases=cases),
      core=dict(source_events=run['events'],event_sha256=sha(run['events']),cases=core),
      distinction='module figures are settled real VCD snapshots; CPU figures are observed-event predicates, not continuous CPU VCD')
    (out/'e16-evidence-excerpts.json').write_text(json.dumps(excerpts,indent=2)+'\n')
    sources=[wave,isolation,result_path,Path(run['events']),ROOT/'stage2/e16-events/audit.py',
      ROOT/'stage3/tests/render-p1-wave-figures.py',ROOT/'stage3/tests/check-oldvd-wave.py']
    manifest=dict(status='PASS',generator=str(Path(__file__).relative_to(ROOT)),generator_sha256=sha(__file__),
      sources={str(s.relative_to(ROOT)):sha(s) for s in sources},
      outputs={str(s.name):sha(s) for s in sorted(out.iterdir()) if s.name!='e16-evidence-manifest.json'},no_new_simulation=True)
    (out/'e16-evidence-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(status='PASS',out=str(out),module_cases=[{k:c[k] for k in ('name','edge','tag','total','input_pre_time','result_post_time')} for c in cases],figures=4),indent=2))

if __name__=='__main__':main()
