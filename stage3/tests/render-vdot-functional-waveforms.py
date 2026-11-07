#!/usr/bin/env python3
"""从已有整核 VCD 提取实际信号跳变，不启动仿真。"""
import argparse
import html
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = 'TOP.SimTop.l_soc.core_with_l2.core.backend.inner_vfExuBlock.exus.Vimac'
FIELDS = {'top_clock':'TOP.clock', 'clock':BASE+'.vdot.clock', 'reset':BASE+'.reset',
          'enable0':BASE+'.vdot.io_enable_0', 'enable1':BASE+'.vdot.io_enable_1',
          'vs1':BASE+'.vdot.io_vs1', 'vs2':BASE+'.vdot.io_vs2',
          'sum':BASE+'.vdot.sum', 'dot_result':BASE+'.vdot.io_result',
          'result':BASE+'.io_out_bits_res_data', 'valid':BASE+'.io_out_valid',
          'op':BASE+'.io_in_bits_ctrlPipe_2_fuOpType',
          'rob_flag':BASE+'.io_out_bits_ctrl_robIdx_flag', 'rob_index':BASE+'.io_out_bits_ctrl_robIdx_value',
          'vl':BASE+'.io_in_bits_dataPipe_2_src_4', 'vm':BASE+'.io_in_bits_ctrlPipe_2_vpu_vm',
          'vstart':BASE+'.io_in_bits_ctrlPipe_2_vpu_vstart',
          'illegal':BASE+'.io_out_bits_ctrl_exceptionVec_2', 'vxsat':BASE+'.io_out_bits_res_vxsat'}
FIELDS.update({f'p{i}':BASE+f'.vdot.products_{i}' for i in range(8)})
CASES = [('positive36',36),('positive120',120),('negative',-36),('maximum',131072),
         ('minimum',-130048),('positive-endpoint',129032),('zero',0)]


def need(value,message):
    if not value:raise ValueError(message)


def signed(value,bits):
    return value-(1<<bits) if value & (1<<(bits-1)) else value


def operands(value):
    return [signed((value>>(8*i))&255,8) for i in range(8)]


def reference(left,right,time):
    a,b=operands(left),operands(right)
    products=[x*y for x,y in zip(a,b)]
    return dict(input_time=time,a=a,b=b,products=products,expected=sum(products))


def audit_output(snapshot,reference_value):
    expected=reference_value['expected']&0xffffffff
    need(snapshot['result']==snapshot['dot_result']==expected,'full128 result mismatch')
    need(signed(snapshot['sum'],19)==reference_value['expected'],'registered sum mismatch')
    need((snapshot['vl'],snapshot['vm'],snapshot['vstart'])==(8,1,0),'illegal selected configuration')
    need(snapshot['illegal']==snapshot['vxsat']==0,'exception/saturation on legal dot')


def extract(path,observed):
    """逐时间戳保留精确 VCD 数值，并独立审核低相位。"""
    targets={}
    for name,value in CASES:
        row=next(r for r in observed if r['signed']==value)
        targets[row['time']]=dict(name=name,expected=value,row=row,samples=[])
    stop=max(r['time'] for r in observed)+10
    scope=[];codes={};values={};selected=set();time=0;previous_clock=None
    products_ref=sum_ref=None;checked=[]

    def snapshot():
        nonlocal previous_clock,products_ref,sum_ref
        if not codes:return
        sample={key:values.get(code) for key,code in codes.items()}
        sample['time']=time
        for target in targets.values():
            if target['row']['time']-12<=time<=target['row']['time']+8:
                target['samples'].append(sample.copy())
        clock=sample['top_clock'];low=previous_clock==1 and clock==0;previous_clock=clock
        if not low or sample['reset']:return
        for key in ('enable0','enable1','valid','op'):
            need(sample[key] is not None,'unknown control at low phase')
        if products_ref is not None:
            need([signed(sample[f'p{i}'],16) for i in range(8)]==products_ref['products'],
                 'product register mismatch')
            products_ref.setdefault('products_time',time)
        if sum_ref is not None:
            need(signed(sample['sum'],19)==sum_ref['expected'],'sum pipeline mismatch')
            sum_ref.setdefault('sum_time',time)
        if sample['valid'] and sample['op']==0x160 and sum_ref is not None:
            audit_output(sample,sum_ref)
            row=next((r for r in observed if r['time']==time),None)
            need(row is not None and row['value']==sample['result']
                 and row['tag']==f"{sample['rob_flag']}:{sample['rob_index']}",
                 'original CPU audit identity differs')
            checked.append(time)
            if time in targets:
                target=targets[time];target['input']=sum_ref.copy();target['output']=sample.copy()
        if sample['enable1']:sum_ref=None if products_ref is None else products_ref.copy()
        if sample['enable0']:
            products_ref=reference(sample['vs1'],sample['vs2'],time)

    before=path.stat()
    with path.open(encoding='ascii') as stream:
        for raw in stream:
            fields=raw.split()
            if not fields:continue
            if fields[0]=='$scope':scope.append(fields[2])
            elif fields[0]=='$upscope':scope.pop()
            elif fields[0]=='$var':
                name='.'.join(scope+[fields[4]])
                for key,wanted in FIELDS.items():
                    if name==wanted:codes[key]=fields[3]
            elif fields[0]=='$enddefinitions':break
        need(set(codes)==set(FIELDS),'missing actual CPU signal hierarchy')
        selected=set(codes.values())
        for raw in stream:
            line=raw.strip()
            if line.startswith('#'):
                snapshot();time=int(line[1:])
                if time>stop:break
            elif line.startswith('b'):
                bits,code=line[1:].split()
                if code in selected:values[code]=None if any(c in bits.lower() for c in 'xz') else int(bits,2)
            elif line and line[0] in '01xz':
                code=line[1:]
                if code in selected:values[code]=int(line[0]) if line[0] in '01' else None
    need(checked==[r['time'] for r in observed],'incomplete original 29-output recheck')
    after=path.stat()
    need((before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'source waveform changed')
    result=[]
    for name,value in CASES:
        target=next(v for v in targets.values() if v['name']==name)
        need('input' in target and 'output' in target and target['input']['expected']==value,'missing case')
        need(target['samples'][0]['time']<=target['input']['input_time'],'input outside selected window')
        result.append(target)
    return dict(status='PASS',source=str(path),hierarchy=BASE,fields=FIELDS,checked_outputs=len(checked),cases=result,
                interpretation='Exact timestamp-stable VCD values. Low-phase checks independently reconstruct products and sum. FU result is not retirement.')


def fmt(value):
    return 'x' if value is None else str(value)


def figure(case):
    title=f"vdot: {case['name']} | expected = actual = {case['expected']}"
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1560" height="1110" viewBox="0 0 1560 1110">',
           '<rect width="1560" height="1110" fill="#f4f7fb"/>',
           '<style>text{font-family:DejaVu Sans,sans-serif;fill:#172b4d}</style>']
    def text(x,y,value,size=18,color='#172b4d'):
        parts.append(f'<text x="{x}" y="{y}" font-size="{size}" style="fill:{color}">{html.escape(str(value))}</text>')
    def line(x1,y1,x2,y2,color='#175cd3',width=2):
        parts.append(f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="{color}" stroke-width="{width}"/>')
    text(30,38,title,28)
    output=case['output'];ref=case['input'];samples=case['samples'];lo=samples[0]['time'];hi=samples[-1]['time']+1
    text(30,68,f"Existing v0.1 CPU VCD | ROB={output['rob_flag']}:{output['rob_index']} | chronological first matching result",18)
    text(30,96,'Actual signal transitions at every VCD timestamp; labels use signed decimal or explicitly marked hexadecimal.',18)
    x=lambda t:360+(t-lo)*1150/(hi-lo)
    for t,color in [(ref['input_time'],'#dceaff'),(output['time'],'#dcfce7')]:
        parts.append(f'<rect x="{x(t)}" y="116" width="{x(t+1)-x(t)}" height="704" fill="{color}"/>')
    rows=[('TOP.clock','top_clock','bit'),('VDot8.clock','clock','bit'),
          ('io_enable_0','enable0','bit'),('io_enable_1','enable1','bit'),
          ('vs1[63:0] (hex)','vs1','hex64'),('vs2[63:0] (hex)','vs2','hex64'),
          ('products_0 (s16)','p0','s16'),('products_7 (s16)','p7','s16'),
          ('sum (s19)','sum','s19'),('result (full128 hex)','result','hex128'),
          ('io_out_valid','valid','bit'),('output fuOpType (hex)','op','hex'),
          ('ROB flag:index','tag','tag'),('VL / vm / vstart','config','config'),
          ('illegal / vxsat','flags','flags')]
    def value(row,key,kind):
        if kind=='tag':return f"{fmt(row['rob_flag'])}:{fmt(row['rob_index'])}"
        if kind=='config':return ' / '.join(fmt(row[k]) for k in ('vl','vm','vstart'))
        if kind=='flags':return f"{fmt(row['illegal'])} / {fmt(row['vxsat'])}"
        v=row[key]
        if v is None:return 'x'
        if kind=='hex64':return f'{v&((1<<64)-1):016x}'
        if kind=='hex128':return f'{v:032x}'
        if kind=='hex':return f'{v:x}'
        if kind.startswith('s'):return str(signed(v,int(kind[1:])))
        return v
    for i,(label,key,kind) in enumerate(rows):
        y=139+i*45;text(30,y+6,label,19);line(350,y+22,1510,y+22,'#e1e7ef',1)
        if kind=='bit':
            for j,row in enumerate(samples):
                end=samples[j+1]['time'] if j+1<len(samples) else hi
                v=row[key];level=y+(10 if v==0 else -10 if v==1 else 0)
                line(x(row['time']),level,x(end),level,'#175cd3' if v is not None else '#a0a0a0')
                if j and v!=samples[j-1][key]:line(x(row['time']),y-10,x(row['time']),y+10)
        else:
            groups=[]
            for row in samples:
                v=value(row,key,kind)
                if not groups or groups[-1][2]!=v:groups.append([row['time'],hi,v])
                else:groups[-1][1]=hi
            for j,(start,_,v) in enumerate(groups):
                end=groups[j+1][0] if j+1<len(groups) else hi;left,right=x(start),x(end)
                parts.append(f'<path d="M{left}, {y} l4,-11 H{right-4} l4,11 l-4,11 H{left+4} Z" fill="white" stroke="#175cd3"/>')
                # 过短的总线区段仅标注编号，不填入虚构数值。
                if len(str(v))*9+12<right-left:text(left+7,y+6,v,16)
                else:text(left+5,y+5,f'[{j+1}]',13,'#667085')
    for t in range(lo,hi,2):text(x(t)-9,852,t-lo,15)
    text(360,883,f'Relative VCD time (t0={lo}); one observed TOP.clock period = 2 time units, not GHz.',17)
    text(30,917,f"A[0..7] = {ref['a']}",21)
    text(30,949,f"B[0..7] = {ref['b']}",21)
    text(30,981,f"Observed registered products = {ref['products']}",19)
    text(30,1013,f"Sum = {ref['expected']}; actual full128 = 0x{output['result']:032x}; upper96 = 0",21,'#15803d')
    text(30,1046,f"Input enable @ {ref['input_time']} -> products checked @ {ref['products_time']} -> sum/output checked @ {output['time']}",18)
    text(30,1076,'PASS: all 8 product registers, signed sum, full128 output, legal config and original ROB record. [n] = short bus segment; see data.',16)
    return '\n'.join(parts+['</svg>'])+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'stage3/reports/figures/functional-signals')
    args=parser.parse_args();need(not args.out.exists(),'output exists: refuse overwrite')
    spec=importlib.util.spec_from_file_location('existing_records',Path(__file__).with_name('render-document-evidence.py'))
    records=importlib.util.module_from_spec(spec);spec.loader.exec_module(records)
    observed=records.dot_records((ROOT/records.DOT).read_text())
    print('Reading existing CPU VCD; no simulator or waveform writer is used.',flush=True)
    data=extract(ROOT/'stage2/waveform/vdot-core-20261002.vcd',observed)
    spec=importlib.util.spec_from_file_location('existing_png_renderer',Path(__file__).with_name('render-p1-wave-figures.py'))
    renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
    args.out.mkdir(parents=True,exist_ok=False)
    for case in data['cases']:
        svg=args.out/(case['name']+'.svg');png=args.out/(case['name']+'.png')
        svg.write_text(figure(case));renderer.png_from_svg(svg,png)
    (args.out/'signal-excerpts.json').write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps(dict(status='PASS',figures=len(data['cases']),checked_outputs=data['checked_outputs'],
                          new_waveform_files=0,bytes=sum(p.stat().st_size for p in args.out.iterdir()))))


if __name__=='__main__':main()
