#!/usr/bin/env python3
"""绘制已有探针信号和正式统计，不启动模拟器。"""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'stage3/reports/figures/comparison'
WAVE = ROOT/'stage3/logs/timer-probe-20261003-window2.vcd'
TIMER = ROOT/'stage3/logs/timer-probe-20261003-window2-audit.json'
FORMAL = ROOT/'stage3/logs/20261006T060358-16-isolation-perf-report.json'
BASE = 'TOP.SimTop.l_soc.core_with_l2.core.backend.'
DIS = BASE+'inner_ctrlBlock.dispatch.'
NAMES = {'clock':'TOP.clock', 'accept':DIS+'io_enqRob_canAccept'}
for i in range(6):
    NAMES[f'd{i}v'] = DIS+f'io_enqRob_req_{i}_valid'
    for short, name in [('pc','pc'), ('inst','instr'), ('flag','robIdx_flag'), ('tag','robIdx_value')]:
        NAMES[f'd{i}{short}'] = DIS+f'io_enqRob_req_{i}_bits_'+name
for short, path in [('mac','inner_vfExuBlock.exus.Vimac.'), ('ipu','inner_vfExuBlock.exus_1.Vipu.')]:
    for key, signal in [('valid','io_out_valid'), ('data','io_out_bits_res_data'),
                        ('flag','io_out_bits_ctrl_robIdx_flag'), ('tag','io_out_bits_ctrl_robIdx_value')]:
        NAMES[short+key] = BASE+path+signal


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


ART = load_module('document_evidence_comparison', ROOT/'stage3/tests/render-document-evidence.py')
PNG = load_module('p1_comparison_png', ROOT/'stage3/tests/render-p1-wave-figures.py')
need = ART.need


def read_windows(pairs):
    ranges = [(str(p['impl']), p['start']['dispatch_time']-2, p['end']['output_time']+2) for p in pairs]
    windows = {key:[] for key, _, _ in ranges}
    before = WAVE.stat(); scope=[]; found={}; values={}; time=None; header=True
    wanted=set(NAMES.values()); selected=set(); codes={}
    def snapshot():
        if time is None:return
        for key, lo, hi in ranges:
            if lo <= time <= hi:
                windows[key].append(dict(time=time, **{k:values.get(code) for k,code in codes.items()}))
    with WAVE.open('rb', buffering=8<<20) as stream:
        for raw in stream:
            if header:
                fields=raw.split()
                if not fields:continue
                if fields[0]==b'$scope':scope.append(fields[2].decode())
                elif fields[0]==b'$upscope':scope.pop()
                elif fields[0]==b'$var':
                    name='.'.join(scope+[fields[4].decode()])
                    if name in wanted:found[name]=fields[3]
                elif fields[0]==b'$enddefinitions':
                    need(wanted <= found.keys(), 'missing signals: '+str(wanted-found.keys()))
                    codes={k:found[v] for k,v in NAMES.items()};selected=set(codes.values());header=False
                continue
            if raw.startswith(b'#'):
                snapshot();time=int(raw[1:])
                if time > max(hi for _,_,hi in ranges):break
            elif raw.startswith(b'b'):
                bits,code=raw[1:].split()
                if code in selected:values[code]=None if b'x' in bits or b'z' in bits else int(bits,2)
            elif raw[:1] in (b'0',b'1',b'x',b'z'):
                code=raw[1:].strip()
                if code in selected:values[code]=int(raw[:1]) if raw[:1] in (b'0',b'1') else None
    after=WAVE.stat()
    need((before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'source VCD changed')
    return windows


def audit_window(pair, rows):
    need(pair['end']['data']-pair['start']['data']==pair['cycles'],'counter difference mismatch')
    low=[r for prev,r in zip(rows,rows[1:]) if prev['clock']==1 and r['clock']==0]
    need(all(b['time']-a['time']==2 for a,b in zip(low,low[1:])),'not two VCD ticks per DUT cycle')
    pending={};events=[];counts={'dot':0,'mul':0,'red':0};results={'dot':0,'mul':0,'red':0};outputs={}
    for r in low:
        if r['accept']:
            for i in range(6):
                if not r[f'd{i}v']:continue
                pc=r[f'd{i}pc']
                kind=('dot' if pc in range(0x80000262,0x80000272,4) else
                      'mul' if pc in range(0x800001da,0x800001ea,4) else
                      'red' if pc in range(0x800001ee,0x800001fe,4) else None)
                if kind is None:continue
                inst=r[f'd{i}inst']
                need((inst & 0x7f)==(0x0b if kind=='dot' else 0x57),'wrong dispatched instruction')
                tag=(r[f'd{i}flag'],r[f'd{i}tag'])
                # 宽乘法和归约拆分的多个 uop 共用一次架构 ROB 分配。
                if tag not in pending:
                    counts[kind]+=1;pending[tag]=dict(kind=kind,dispatch=r['time'],pc=pc)
        for port in ('mac','ipu'):
            tag=(r[port+'flag'],r[port+'tag'])
            if not r[port+'valid'] or tag not in pending:continue
            record=pending[tag];kind=record['kind']
            need(port==('ipu' if kind=='red' else 'mac'),'unexpected execution port')
            data=r[port+'data']
            outputs.setdefault(tag,[]).append(dict(**record,time=r['time'],port=port,data=data,tag=list(tag)))
    for tag,seq in outputs.items():
        kind=pending[tag]['kind']
        # 当前核的宽乘法有两个输出 uop，其中第二个处理尾部；
        # 归约有四个输出 uop，中间值不能当作架构归约结果。
        limit={'dot':1,'mul':2,'red':4}[kind]
        need(len(seq)<=limit,'unexpected number of output uops per ROB allocation')
        if len(seq)<limit:continue  # 可能属于被取消的投机尾部。
        event=seq[-1] if kind=='red' else seq[0];data=event['data']
        if kind=='mul':
            need(data is not None and all((data>>(16*i))&65535==2 for i in range(8)),
                 'wide multiply active-lane result mismatch')
        else:need(data==16,'dot/reduction full 128-bit result mismatch')
        events.append(event);results[kind]+=1
    expected={'dot':32,'mul':0,'red':0} if pair['impl']==0 else {'dot':0,'mul':32,'red':32}
    need(all(counts[k]>=expected[k] if expected[k] else counts[k]==0 for k in expected),
         'wrong dispatch instruction coverage: '+str(counts))
    need(all(results[k]>=expected[k] for k in expected),'missing matching FU outputs')
    # 循环退出时的投机分派可能超过 32 条，且被取消的分配
    # 不一定产生结果，这些数量不能称为提交数。
    return dict(cycles=pair['cycles'],dispatch_allocations=counts,checked_result_groups=results,
                raw_output_uops=sum(map(len,outputs.values())),events=events)


def wave_figure(pairs, windows, checks):
    f=ART.Figure('RVV baseline vs vdot: real CPU probe signals',
                 'Existing 8-batch batch4 probe / 32 dot products each. Not the formal 256-batch experiment.')
    for j,p in enumerate(pairs):
        top=115+j*445;f.panel(top,425);base=p['start']['dispatch_time'];rows=windows[str(p['impl'])]
        f.text(45,top+34,('vdot' if p['impl']==0 else 'RVV vwmul + vwredsum')+f" | counter delta = {p['cycles']} DUT cycles",24)
        x=lambda t:350+(t-base)/2*3.5
        for k,key in enumerate(('clock','macvalid','ipuvalid')):
            y=top+92+k*60;f.text(45,y+5,{'clock':'TOP.clock','macvalid':'Vimac.out.valid','ipuvalid':'Vipu.out.valid'}[key],20)
            points=[]
            for n,r in enumerate(rows):
                if r['time']<base:continue
                value=r[key];need(value in (0,1),'unknown actual valid/clock')
                xx=x(r['time']);yy=y-18*value
                if points:points.append(f'{xx},{last_y}')
                points.append(f'{xx},{yy}');last_y=yy
            f.parts.append('<polyline points="'+' '.join(points)+'" fill="none" stroke="#175cd3" stroke-width="1"/>')
        y=top+272;f.text(45,y,'Matched results',20)
        for e in checks[str(p['impl'])]['events']:
            color={'dot':'#15803d','mul':'#a15c00','red':'#9333ea'}[e['kind']]
            f.line(x(e['time']),y-18,x(e['time']),y+2,color,2)
        for cycles in range(0,321,40):
            xx=350+cycles*3.5;f.line(xx,top+300,xx,top+308);f.text(xx-10,top+332,cycles,16)
        f.line(350,top+300,1470,top+300)
        f.text(350,top+363,'DUT cycles relative to start mcycle dispatch; 2 original VCD ticks / cycle',17)
        c=checks[str(p['impl'])]['checked_result_groups']
        f.text(45,top+400,(f"Observed {c['dot']} dot outputs = 16" if p['impl']==0 else
                         f"Observed {c['mul']} wide products (eight lanes = 2), {c['red']} reductions = 16"),19)
    f.text(35,1045,'Valid levels above are raw sampled signals; colored ticks below are ROB-matched output events, not commit.',17)
    f.text(35,1077,'Probe ratio 313 / 170 = 1.841176; illustrative only. Green=dot, amber=wide multiply, purple=wide reduction.',17)
    return f


def formal_values(data):
    result=[]
    need(len(data['runs'])==4,'four independent formal processes required')
    for kind in ('batch4','e2e','chain'):
        med={impl:[statistics.median(r['groups'][kind][impl]['raw']) for r in data['runs']]
             for impl in ('rvv','vdot')}
        ratios=[a/b for a,b in zip(med['rvv'],med['vdot'])]
        saved=data['series']['groups'][kind]
        need(ratios==saved['run_speedups'],'per-process speedup mismatch')
        for impl in med:need(statistics.median(med[impl])==saved[impl]['median'],'cycle median mismatch')
        need(statistics.median(ratios)==saved['speedup']['median'],'speedup median mismatch')
        result.append(dict(kind=kind,rvv=statistics.median(med['rvv']),vdot=statistics.median(med['vdot']),
                           speedup=statistics.median(ratios),ratios=ratios))
    return result


def formal_figure(values):
    f=ART.Figure('Formal isolated-core results: RVV baseline vs vdot',
                 'Statistical chart, NOT a waveform / isolated FU latency. Four processes; all samples retained.')
    for i,r in enumerate(values):
        top=115+i*285;f.panel(top,265)
        f.text(45,top+37,r['kind']+f" | RVV / vdot = {r['speedup']:.6f}x",26)
        for j,(impl,color) in enumerate([('rvv','#64748b'),('vdot','#175cd3')]):
            y=top+74+j*60;f.text(45,y+24,impl.upper(),22)
            width=r[impl]/32000*1070
            f.parts.append(f'<rect x="210" y="{y}" width="{width}" height="34" fill="{color}"/>')
            label=f"{r[impl]:.2f}".rstrip('0').rstrip('.')
            f.text(225+width,y+25,label+' cycles',20)
        f.text(45,top+212,'Four process ratios: '+', '.join(f'{v:.6f}' for v in r['ratios']),18)
        if r['kind']=='e2e':f.text(45,top+245,'WARNING retained: warm-tail -14.735% in runs 0/2; strict exit 3; stable=False.',18,'#b42318')
        else:f.text(45,top+245,'Same horizontal scale: 0..32000 DUT cycles; 1024 dot products per sample.',18)
    f.text(35,1025,'Cycles = median of process medians. Speedup = median of process ratios; no empty-loop subtraction.',18)
    f.text(35,1057,'Fixed low-eight inputs a=1, b=2; chain uses a zero fixed point with a real dependency.',18)
    f.text(35,1089,'This is RVV/vdot within the isolated core, NOT the performance benefit of operand isolation or a PPA result.',17)
    return f


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render-existing',action='store_true',help='read small cached signal JSON, not VCD')
    args=parser.parse_args();cache=OUT/'probe-samples.json'
    timer=json.loads(TIMER.read_text())
    ART.timer_records(timer)  # 保留原有六项顺序和计数器检查。
    pairs=timer['checked_pairs'][:2]
    need([(p['kind'],p['impl']) for p in pairs]==[(0,0),(0,1)],'wrong selected probe pairs')
    if args.render_existing:
        saved=json.loads(cache.read_text());need(saved['signals']==NAMES,'cached signal map differs');windows=saved['windows']
    else:
        need(not OUT.exists(),'output exists; use --render-existing');windows=read_windows(pairs)
    OUT.mkdir(parents=True,exist_ok=True)
    if not args.render_existing:cache.write_text(json.dumps(dict(source=str(WAVE.relative_to(ROOT)),signals=NAMES,windows=windows),separators=(',',':'))+'\n')
    checks={str(p['impl']):audit_window(p,windows[str(p['impl'])]) for p in pairs}
    values=formal_values(json.loads(FORMAL.read_text()))
    for name,figure in [('baseline-vdot-wave',wave_figure(pairs,windows,checks)),('formal-speedup',formal_figure(values))]:
        svg=OUT/(name+'.svg');svg.write_text(figure.finish());PNG.png_from_svg(svg,OUT/(name+'.png'))
    print(json.dumps(dict(status='PASS',probe={k:{n:v for n,v in c.items() if n!='events'} for k,c in checks.items()},formal=values)))


if __name__=='__main__':main()
