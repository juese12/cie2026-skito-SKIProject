#!/usr/bin/env python3
"""读取已有整核 VCD，绘制实际点积输入、寄存器和输出轨迹。

不调用模拟器或写入 VCD/FST；图件保留原始跳变时刻，
数学期望由采样操作数另行计算。
"""
import argparse
import csv
import html
import importlib.util
import io
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WAVE=ROOT/'stage2/waveform/vdot-core-20261002.vcd'
AUDIT=ROOT/'stage2/logs/20261002T114458-core-wave-commit-audit.full.log'
PREFIX='TOP.SimTop.l_soc.core_with_l2.core.backend.inner_vfExuBlock.exus.Vimac'
NAMES={
    'clock':'TOP.clock','unit_clock':PREFIX+'.vdot.clock','reset':PREFIX+'.reset',
    'in_valid':PREFIX+'.io_in_valid','in_op':PREFIX+'.io_in_bits_ctrl_fuOpType',
    'en0':PREFIX+'.vdot.io_enable_0','en1':PREFIX+'.vdot.io_enable_1',
    'a':PREFIX+'.vdot.io_vs1','b':PREFIX+'.vdot.io_vs2',
    'sum':PREFIX+'.vdot.sum','dot_result':PREFIX+'.vdot.io_result',
    'out_valid':PREFIX+'.io_out_valid','out_op':PREFIX+'.io_in_bits_ctrlPipe_2_fuOpType',
    'vl':PREFIX+'.io_in_bits_dataPipe_2_src_4','vm':PREFIX+'.io_in_bits_ctrlPipe_2_vpu_vm',
    'vsew':PREFIX+'.io_in_bits_ctrlPipe_2_vpu_vsew','vstart':PREFIX+'.io_in_bits_ctrlPipe_2_vpu_vstart',
    'result':PREFIX+'.io_out_bits_res_data','illegal':PREFIX+'.io_out_bits_ctrl_exceptionVec_2',
    'vxsat':PREFIX+'.io_out_bits_res_vxsat','vec_wen':PREFIX+'.io_out_bits_ctrl_vecWen',
    'v0_wen':PREFIX+'.io_out_bits_ctrl_v0Wen','flag':PREFIX+'.io_out_bits_ctrl_robIdx_flag',
    'tag':PREFIX+'.io_out_bits_ctrl_robIdx_value',
    **{f'p{i}':PREFIX+f'.vdot.products_{i}' for i in range(8)}}


def need(condition,message):
    if not condition:raise ValueError(message)


def signed(value,width):
    need(value is not None,'unknown arithmetic signal')
    return value if value < 1<<(width-1) else value-(1<<width)


def lanes(value):
    return [signed((value>>(8*i))&255,8) for i in range(8)]


def select_cases(text):
    need('execution_observations=29 vdot_commits=29' in text and '[exit] 0' in text,
         'original CPU audit not complete')
    lines=[s for s in text.splitlines() if s[:1].isdigit() and ',TOP.' in s]
    records=list(csv.DictReader(io.StringIO('time,hierarchy,rob_flag,rob_index,pdest,v0_wen,result_128\n'+'\n'.join(lines))))
    need(len(records)==29,'expected original 29 results')
    specs=[('positive',36,0),('positive-asymmetric',120,0),('negative',-36,0),
           ('maximum',131072,0),('minimum',-130048,0),('all127',129032,0),
           ('zero',0,0),('cancellation',0,4)]
    result=[]
    for label,value,ordinal in specs:
        row=[r for r in records if signed(int(r['result_128'],16),32)==value][ordinal]
        result.append(dict(name=label,value=value,output_time=int(row['time']),
                           tag=[int(row['rob_flag']),int(row['rob_index'])]))
    return result


def read_windows(path,cases):
    before=path.stat();scope=[];codes={};values={};windows={c['name']:[] for c in cases}
    ranges=[(c['name'],c['output_time']-10,c['output_time']+6) for c in cases]
    last=max(hi for _,_,hi in ranges);time=None;header=True
    wanted=set(NAMES.values());by_full={};selected=set()
    def snapshot():
        if time is None:return
        for label,lo,hi in ranges:
            if lo<=time<=hi:
                windows[label].append(dict(time=time,**{key:values.get(code) for key,code in codes.items()}))
    with path.open('rb',buffering=8<<20) as stream:
        for raw in stream:
            if header:
                fields=raw.split()
                if not fields:continue
                if fields[0]==b'$scope':scope.append(fields[2].decode())
                elif fields[0]==b'$upscope':scope.pop()
                elif fields[0]==b'$var':
                    name='.'.join(scope+[fields[4].decode()])
                    if name in wanted:by_full[name]=fields[3]
                elif fields[0]==b'$enddefinitions':
                    need(wanted<=by_full.keys(),'missing actual core signals: '+str(wanted-by_full.keys()))
                    codes={key:by_full[name] for key,name in NAMES.items()};selected=set(codes.values());header=False
                continue
            if raw.startswith(b'#'):
                snapshot();time=int(raw[1:])
                if time>last:break
            elif raw.startswith(b'b'):
                bits,code=raw[1:].split()
                if code in selected:values[code]=None if b'x' in bits or b'z' in bits else int(bits,2)
            elif raw[:1] in (b'0',b'1',b'x',b'z'):
                code=raw[1:].strip()
                if code in selected:values[code]=int(raw[:1]) if raw[:1] in (b'0',b'1') else None
    after=path.stat()
    need((before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'source waveform changed')
    need(all(windows.values()),'missing selected windows')
    return windows


def audit_case(case,rows):
    need(all(r['reset']==0 for r in rows),'selected window includes reset')
    low=[r for prev,r in zip(rows,rows[1:]) if prev['clock']==1 and r['clock']==0]
    products_info=sum_info=None
    for r in low:
        if r['time']==case['output_time']:
            need(sum_info is not None,'window begins too late to associate input')
            need(r['out_valid']==1 and r['out_op']==0x160 and r['illegal']==r['vxsat']==0,
                 'not a legal valid dot output')
            need(r['vl']==8 and r['vm']==1 and r['vstart']==r['vsew']==0,'wrong vector configuration')
            need([r['flag'],r['tag']]==case['tag'],'output ROB does not match original audit')
            need(r['vec_wen']==1 and r['v0_wen']==0,'incorrect destination write enable')
            need(r['result']==r['dot_result']==(sum_info['expected']&0xffffffff)
                 and signed(r['sum'],19)==sum_info['expected']==case['value'],'full 128-bit result differs')
            need(r['result']>>32==0,'upper96 not zero')
            rises=[row['time'] for prev,row in zip(rows,rows[1:])
                   if prev['unit_clock']==0 and row['unit_clock']==1]
            need(sum(sum_info['input_time']<t<=sum_info['product_time'] for t in rises)==1
                 and sum(sum_info['product_time']<t<=r['time'] for t in rises)==1,
                 'missing actual unit-clock register update edges')
            a,b=sum_info['a_lanes'],sum_info['b_lanes']
            if case['name']=='zero':need(a==[0]*8 and b==[1]*8,'zero case input misidentified')
            if case['name']=='cancellation':need(a==[127,-127]*4 and b==[1]*8,'cancellation input misidentified')
            return dict(**case,**sum_info,full_result=f"{r['result']:032x}",sum_time=r['time'])
        if r['en1']:
            if products_info is not None:
                actual=[signed(r[f'p{i}'],16) for i in range(8)]
                need(actual==products_info['products'],'actual product registers differ from input multiplication')
                sum_info=dict(products_info,product_time=r['time'])
        if r['en0']:
            need(r['in_valid']==1 and r['in_op']==0x160,'selected pipeline input is not dot')
            a,b=lanes(r['a']),lanes(r['b']);products=[x*y for x,y in zip(a,b)]
            products_info=dict(input_time=r['time'],a=r['a'],b=r['b'],a_lanes=a,b_lanes=b,
                               products=products,expected=sum(products))
    raise ValueError('missing target output')


def draw(case,rows):
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1560" height="1110" viewBox="0 0 1560 1110">',
           '<rect width="1560" height="1110" fill="#f5f7fb"/>',
           '<style>text{font-family:DejaVu Sans,sans-serif;fill:#172b4d}.mono{font-family:DejaVu Sans Mono,monospace}</style>']
    def text(x,y,value,size=17,color='#172b4d'):
        parts.append(f'<text x="{x}" y="{y}" font-size="{size}" style="fill:{color}">{html.escape(str(value))}</text>')
    def line(x1,y1,x2,y2,color='#bac5d3',width=1):
        parts.append(f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="{color}" stroke-width="{width}"/>')
    text(28,37,f"vdot / {case['name']}: real CPU input -> products -> valid result",27)
    text(28,67,'Existing full-core VCD; actual signal transitions. Output data is qualified only when io_out.valid = 1.',16)
    text(28,96,'A signed int8: '+str(case['a_lanes']),19)
    text(28,123,'B signed int8: '+str(case['b_lanes']),19)
    text(28,150,'A low64 = '+f"{case['a']&((1<<64)-1):016x}"+'; B low64 = '+f"{case['b']&((1<<64)-1):016x}",17)
    lo,hi=rows[0]['time'],rows[-1]['time']
    x=lambda t:285+(t-lo)*1240/(hi-lo+1)
    for t in range(lo,hi+1):
        line(x(t),207,x(t),960,'#e3e9f0');text(x(t)-12,194,t,12)
    tracks=[('TOP.clock','clock','bit'),('vdot.clock','unit_clock','bit'),('io_in.valid','in_valid','bit'),
            ('vdot.enable[0]','en0','bit'),('vdot.enable[1]','en1','bit'),
            ('vdot.vs1[63:0]','a','input'),('vdot.vs2[63:0]','b','input')]
    tracks += [(f'vdot.products[{i}]',f'p{i}','s16') for i in range(8)]
    tracks += [('vdot.sum (signed19)','sum','s19'),('io_out.valid','out_valid','bit'),
               ('out.data[31:0]','result','low32'),('out.data[127:32]','result','upper'),
               ('exceptionVec[2]','illegal','bit'),('out.vxsat','vxsat','bit'),
               ('out.vecWen','vec_wen','bit'),('out.ROB flag:index','tag','tag')]
    for j,(label,key,kind) in enumerate(tracks):
        y=228+j*31;text(28,y+5,label,15);line(275,y+14,1530,y+14,'#e1e7ef')
        color='#175cd3' if j<7 else '#15803d' if j<16 else '#7f56d9'
        def value(r):
            v=r[key]
            if v is None:return None
            if kind=='input':return v&((1<<64)-1)
            if kind=='s16':return signed(v,16)
            if kind=='s19':return signed(v,19)
            if kind=='low32':return v&0xffffffff
            if kind=='upper':return v>>32
            if kind=='tag':return f"{r['flag']}:{v}"
            return v
        if kind=='bit':
            prev=None
            for i,r in enumerate(rows):
                v=value(r);left=x(r['time']);right=x(rows[i+1]['time']) if i+1<len(rows) else x(hi+1)
                if v is None:text(left,y+4,'X',13);continue
                height=y-7 if v else y+7
                if prev is not None:line(left,prev,left,height,color,2)
                line(left,height,right,height,color,2);prev=height
        else:
            segments=[]
            for r in rows:
                v=value(r)
                if not segments or v!=segments[-1][1]:segments.append((r['time'],v))
            for i,(t,v) in enumerate(segments):
                left=x(t);right=x(segments[i+1][0]) if i+1<len(segments) else x(hi+1)
                parts.append(f'<path d="M{left},{y} L{left+4},{y-10} L{right-4},{y-10} L{right},{y} L{right-4},{y+10} L{left+4},{y+10} Z" fill="white" stroke="{color}"/>')
                if v is None:label_value='X'
                elif kind=='input':label_value=f'{v:016x}'
                elif kind=='low32':label_value=f'{v:08x}'
                elif kind=='upper':label_value=hex(v)
                else:label_value=str(v)
                available=right-left-12
                if len(label_value)*8>available and kind=='input':label_value=label_value[:4]+'..'+label_value[-4:]
                if len(label_value)*8<=available:text(left+7,y+5,label_value,13,color)
    for label,time,color in [('INPUT',case['input_time'],'#175cd3'),('PRODUCTS',case['product_time'],'#15803d'),
                             ('OUTPUT',case['output_time'],'#7f56d9')]:
        parts.append(f'<path d="M{x(time)},210 L{x(time)},960" stroke="{color}" stroke-width="2" stroke-dasharray="4 4"/>')
        text(x(time)-15,977,label,13,color)
    text(28,1004,'Expected = '+' + '.join(map(str,case['products']))+f" = {case['expected']}",17)
    text(28,1032,'Actual full128 = 0x'+case['full_result']+f"; ROB={case['tag'][0]}:{case['tag'][1]}",18)
    text(28,1060,'Raw VCD timestamps; dashed lines mark low-phase checks. Registers update on the intervening unit-clock rising edges.',15)
    text(28,1087,'Only valid output is meaningful. Original audit also matches this result to a committed instruction; this plot is not retirement timing.',14)
    return '\n'.join(parts+['</svg>'])+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'stage3/reports/figures/functional')
    parser.add_argument('--extract-only',action='store_true')
    parser.add_argument('--render-existing',action='store_true',help='redraw only images from previously extracted samples')
    args=parser.parse_args()
    if args.render_existing:
        need(not args.extract_only,'incompatible options')
        data=json.loads((args.out/'functional-samples.json').read_text())
        need(data['status']=='PASS' and data['signals']==NAMES,'wrong cached sample set')
        cases=select_cases(AUDIT.read_text());windows=data['windows']
        checked=[audit_case(c,windows[c['name']]) for c in cases]
    else:
        need(not args.out.exists(),'refuse to overwrite output')
        cases=select_cases(AUDIT.read_text());print('Reading existing VCD once; no simulation.',flush=True)
        windows=read_windows(WAVE,cases)
        checked=[audit_case(c,windows[c['name']]) for c in cases]
        args.out.mkdir(parents=True,exist_ok=False)
        data=dict(status='PASS',source=str(WAVE.relative_to(ROOT)),signals=NAMES,cases=checked,windows=windows,
                  qualification='Actual full-clock VCD signal values, not synthetic event traces; physical execution is not ROB retirement.')
        (args.out/'functional-samples.json').write_text(json.dumps(data,indent=2)+'\n')
    if not args.extract_only:
        spec=importlib.util.spec_from_file_location('png_renderer',ROOT/'stage3/tests/render-p1-wave-figures.py')
        renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
        for case in checked:
            svg=args.out/(case['name']+'.svg');svg.write_text(draw(case,windows[case['name']]))
            renderer.png_from_svg(svg,svg.with_suffix('.png'))
    print(json.dumps(dict(status='PASS',cases=len(checked),output=str(args.out),wave_files_created=0)))


if __name__=='__main__':main()
