#!/usr/bin/env python3
"""从已有 VCD/逐周期缓存保存旧隔离核关键真实信号；不启动仿真。"""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'stage3/reports/figures/isolation-retained'
WAVE=ROOT/'stage2/waveform/20261006T033620-isolation-control-resumed.vcd'
CONTROL=ROOT/'stage2/waveform/20261006T033620-isolation-control-resumed.vcd.control.json'
FAST=ROOT/'stage3/logs/20261008T114325-original-e2e-events-resumed'
MIDDLE=ROOT/'stage3/logs/20261008T200238-original-other-bins'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


ART=module('retained_art','stage3/tests/render-document-evidence.py')
PNG=module('retained_png','stage3/tests/render-p1-wave-figures.py')
CTRL=module('retained_control','scripts/check-vdot-control.py')
EV=module('retained_events','stage3/tests/analyze-original-e2e-events.py')
need=ART.need


def extract_control(cases):
    columns=['vcd_time',*sorted(set(CTRL.required_signals()+['TOP.reset']))]
    ranges=[(c['kind'],c['origin']['dispatch_time']-2,c['event']['time']+20) for c in cases]
    windows={key:[] for key,_,_ in ranges};scope=[];found={};values={};time=None;header=True
    wanted=set(columns[1:]);selected=set();before=WAVE.stat()
    def snapshot():
        if time is None:return
        for key,lo,hi in ranges:
            if lo<=time<=hi:windows[key].append([time]+[values.get(found[n]) for n in columns[1:]])
    with WAVE.open('rb',buffering=8<<20) as stream:
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
                    need(wanted<=found.keys(),'missing control signals');selected=set(found.values());header=False
                continue
            if raw.startswith(b'#'):
                snapshot();time=int(raw[1:])
                if time>max(hi for _,_,hi in ranges):break
            elif raw.startswith(b'b'):
                bits,code=raw[1:].split()
                if code in selected:values[code]=None if b'x' in bits or b'z' in bits else int(bits,2)
            elif raw[:1] in (b'0',b'1',b'x',b'z'):
                code=raw[1:].strip()
                if code in selected:values[code]=int(raw[:1]) if raw[:1] in (b'0',b'1') else None
    after=WAVE.stat();need((before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'wave changed')
    return dict(columns=columns,windows=windows,cases=cases)


def tag(get,prefix):return get(prefix+'robIdx_flag')*256+get(prefix+'robIdx_value')


def low_rows(data,kind):
    columns=data['columns'];idx={n:i for i,n in enumerate(columns)};rows=data['windows'][kind]
    return [(r,lambda n,r=r:r[idx[n]]) for prev,r in zip(rows,rows[1:])
            if prev[idx['TOP.clock']]==1 and r[idx['TOP.clock']]==0]


def target_output(get,tags):
    return int(bool(get(CTRL.FU+'io_out_valid')) and get(CTRL.FU+'io_in_bits_ctrlPipe_2_fuOpType')==0x160
               and tag(get,CTRL.FU+'io_out_bits_ctrl_') in tags)


def target_commit(get,tags):
    return int(bool(get(CTRL.ROB+'io_commits_isCommit')) and any(
        get(CTRL.ROB+f'io_commits_commitValid_{i}') and
        (get(CTRL.ROB+f'io_commits_robIdx_{i}_flag')*256+get(CTRL.ROB+f'io_commits_robIdx_{i}_value')) in tags
        for i in range(8)))


def validate_control(data):
    for case in data['cases']:
        low=low_rows(data,case['kind']);bytime={r[0]:get for r,get in low}
        need(all(get('TOP.reset')==0 for _,get in low),'control reset in window')
        tags={r['tag'] for r in case['victims']}
        for record in case['victims']:
            get=bytime[record['execution_time']]
            need(target_output(get,{record['tag']}) and get(CTRL.FU+'io_out_bits_res_data')==record['result'],
                 'raw control result/ROB differs from audit')
        get=bytime[case['event']['time']]
        prefix=CTRL.CTRL+'io_redirect_' if case['kind']=='branch' else CTRL.ROB+'io_flushOut_'
        need(get(prefix+'valid') and tag(get,prefix+'bits_')==case['event']['origin'],'raw flush origin differs')
        need(not any(target_commit(get,tags) for _,get in low),'cancelled victim committed in saved window')
        if case['kind']=='exception':
            get=bytime[case['event']['exception_time']]
            need(get(CTRL.ROB+'io_exception_valid') and get(CTRL.ROB+'io_exception_bits_exceptionVec_2')
                 and get(CTRL.ROB+'io_exception_bits_instr')==0xffffffff,'precise exception differs')
    return True


def extract_e2e():
    full=json.loads(FAST.with_suffix('.cycles.json').read_text());middle=json.loads(MIDDLE.with_suffix('.cycles.json').read_text())
    a=json.loads(FAST.with_suffix('.events.json').read_text());b=json.loads(MIDDLE.with_suffix('.events.json').read_text())
    need(a['status']==b['status']=='PASS','unverified e2e evidence')
    result=[]
    for label,source,window,period in [('fast',full,a['windows']['fast'],17),
                                      ('middle',middle,b['comparisons'][0]['windows']['slow'],19),
                                      ('slow',full,a['windows']['slow'],20)]:
        anchor=window['loop_anchors'][1];next_anchor=window['loop_anchors'][2]
        need(next_anchor['cycle']-anchor['cycle']==period,'loop period differs')
        rows=[r for r in source['rows'] if anchor['time']<=r[0]<=anchor['time']+44]
        need(len(rows)==23,'missing e2e raw samples')
        result.append(dict(label=label,period=period,cycles=window['target']['cycles'],
                           anchor=anchor,columns=source['columns'],rows=rows))
    return result


def bits(f,points,x,y,color='#175cd3'):
    vertices=[]
    for t,value in points:
        need(value in (0,1),'unknown signal level')
        xx=x(t);yy=y-16*value
        if vertices:vertices.append(f'{xx},{last}')
        vertices.append(f'{xx},{yy}');last=yy
    f.parts.append('<polyline points="'+' '.join(vertices)+'" fill="none" stroke="'+color+'" stroke-width="1.5"/>')


def control_figure(data):
    validate_control(data)
    f=ART.Figure('Old isolated core: raw control/valid traces before waveform retirement',
                 'Actual original VCD transitions. Starred target predicates are derived using the recorded ROB tags.')
    for panel,case in enumerate(data['cases']):
        top=115+panel*445;f.panel(top,425);base=case['origin']['dispatch_time']
        tags={r['tag'] for r in case['victims']};columns=data['columns'];idx={n:i for i,n in enumerate(columns)}
        f.text(45,top+33,case['kind'].upper()+f" | victim ROB tags = {sorted(tags)} | original t0 = {base}",23)
        x=lambda t:360+(t-base)/2*7
        tracks=[('TOP.clock',lambda g:g('TOP.clock')),('Vimac.out.valid',lambda g:g(CTRL.FU+'io_out_valid')),
                ('target FU.valid *',lambda g:target_output(g,tags)),
                ('accepted redirect.valid',lambda g:g(CTRL.CTRL+'io_redirect_valid')),
                ('ROB flush.valid',lambda g:g(CTRL.ROB+'io_flushOut_valid')),
                ('precise exception.valid',lambda g:g(CTRL.ROB+'io_exception_valid')),
                ('victim ROB commit *',lambda g:target_commit(g,tags))]
        for i,(label,getter) in enumerate(tracks):
            y=top+80+i*34;f.text(45,y+3,label,18)
            points=[]
            for row in data['windows'][case['kind']]:
                if row[0]<base:continue
                points.append((row[0],getter(lambda n,row=row:row[idx[n]])))
            bits(f,points,x,y)
        for cycle in range(0,161,20):
            xx=360+cycle*7;f.line(xx,top+320,xx,top+326);f.text(xx-8,top+349,cycle,16)
        f.line(360,top+320,1480,top+320)
        cancel_x=x(case['event']['time'])
        f.line(cancel_x,top+55,cancel_x,top+293,'#b42318',2)
        f.text(cancel_x-110,top+53,'target cancel',16,'#b42318')
        f.text(360,top+378,'DUT cycles from origin dispatch; 2 original VCD ticks / cycle',17)
        values=', '.join(str(r['result'] if r['result']<2**31 else r['result']-2**32) for r in case['victims'])
        f.text(45,top+410,'Matched full128 result(s): '+values+'; no victim commit in this window.',18)
    f.text(35,1044,'Narrow traces show selected examples only. Full no-commit/coverage conclusions remain in the original audit/logs.',17)
    f.text(35,1077,'These are old e8 isolation-core observations, not the latest e8/e16 core. No new CPU simulation.',17)
    return f


def e2e_figure(cases):
    f=ART.Figure('E2E 4415 / 4924 / 5178: actual settled-low signal samples',
                 'Second real loop anchor in each saved call; stairs connect samples, not inferred intra-cycle transitions.')
    for panel,case in enumerate(cases):
        top=115+panel*285;f.panel(top,265);idx={n:i for i,n in enumerate(case['columns'])};base=case['anchor']['time']
        f.text(45,top+32,f"{case['label'].upper()} | call={case['cycles']} cycles | real loop period={case['period']}",23)
        x=lambda t:360+(t-base)/2*50
        d=EV.DIS;decode=EV.CORE+'backend.inner_ctrlBlock.decode.'
        tracks=[('complex decoder in.valid',lambda g:g(decode+'decoderComp.io_in_valid')),
                ('decode.out.any *',lambda g:int(any(g(decode+f'io_out_{i}_valid') for i in range(6)))),
                ('dispatch accepted.any *',lambda g:int(g(d+'io_enqRob_canAccept') and any(g(d+f'io_enqRob_req_{i}_valid') for i in range(6)))),
                ('slot4 -> IQ2 blocked *',lambda g:int(bool(g(d+'uopSelIQ_4_2') and g(d+'uopBlockByIQ_4'))))]
        for i,(label,getter) in enumerate(tracks):
            y=top+78+i*34;f.text(45,y+2,label,18)
            bits(f,[(r[0],getter(lambda n,r=r:r[idx[n]])) for r in case['rows']],x,y)
        for cycle in range(0,23,2):
            xx=360+cycle*50;f.line(xx,top+208,xx,top+215);f.text(xx-7,top+237,cycle,16)
        f.line(360,top+208,1460,top+208)
        anchor_x=360+case['period']*50
        f.line(anchor_x,top+43,anchor_x,top+193,'#15803d',2)
    f.text(35,1025,'Horizontal axis: DUT cycles from the second accepted real loop-head load; each saved observation is a low phase.',17)
    f.text(35,1057,'Starred lines aggregate the named raw fields; they are not new RTL ports. Full 693-signal cycle JSON is retained.',17)
    f.text(35,1089,'Old isolated core / selected calls only; no new full waveform, no new CPU simulation, original stability warnings retained.',17)
    return f


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cached',action='store_true');args=parser.parse_args()
    cache=OUT/'signal-excerpts.json'
    if args.cached:data=json.loads(cache.read_text())
    else:
        need(not OUT.exists(),'output already exists; use --cached')
        cases=ART.control_records(json.loads(CONTROL.read_text()))
        data=dict(control=extract_control(cases),e2e=extract_e2e())
        OUT.mkdir();cache.write_text(json.dumps(data,separators=(',',':'))+'\n')
    for name,figure in [('control-signals',control_figure(data['control'])),('e2e-signals',e2e_figure(data['e2e']))]:
        svg=OUT/(name+'.svg');svg.write_text(figure.finish());PNG.png_from_svg(svg,OUT/(name+'.png'))
    print('Saved original control/e2e signal excerpts and figures: PASS')


if __name__=='__main__':main()
