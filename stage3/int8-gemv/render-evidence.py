#!/usr/bin/env python3
"""Audit actual GEMV VCD and create PNGs from measured signals, never mock traces."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import run as R
from signals import read_wave,lanes,signed

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
DRAW=module('gemv_actual_drawing',R.ROOT/'stage2/tests/render-vdot-design-diagrams.py')
AUDIT=module('gemv_actual_timer',Path(__file__).with_name('audit-timer.py'))
def audit(wave,probe):
    capture=json.loads((wave/'capture.json').read_text());assert capture['status']=='PASS'
    original=AUDIT.audit(probe/'probe.events.jsonl');observed=AUDIT.audit(wave/'wave.events.jsonl')
    assert original['calls']==observed['calls'],'observer changed cycle/ROB history'
    pattern=r'^gemv probe m=4 k=17 kp=24 seed=56444f54 cycles=(\d+) y=([\d,\-]+)$'
    plain=re.findall(pattern,R.clean(probe/'probe.full.log'),re.M)
    instrumented=re.findall(pattern,R.clean(wave/'wave.full.log'),re.M)
    assert len(plain)==1 and plain==instrumented,'observer changed output or measured cycles'
    frames,widths=read_wave(wave/'key-signals.vcd.gz');low={f['cycle']:f for f in frames if f['phase']==1}
    call=observed['calls'][0];assert len(call['dots'])==12
    state=0x56444f54
    def nxt():
        nonlocal state
        state=(state^(state<<13))&0xffffffff;state=(state^(state>>17))&0xffffffff;state=(state^(state<<5))&0xffffffff
        return signed(state&255,8)
    x=[nxt() for _ in range(17)]+[0]*7
    w=[[nxt() for _ in range(17)]+[0]*7 for _ in range(4)]
    checked=[];sums=[0]*4
    for i,rec in enumerate(call['dots']):
        block,row=divmod(i,4);src=rec['input'];out=rec['output'];c=src['cycle']
        a,b=lanes(int(src['a'],16)),lanes(int(src['b'],16));want_a=w[row][8*block:8*block+8];want_b=x[8*block:8*block+8]
        assert a==want_a and b==want_b,'actual input block/row differs'
        products=[u*v for u,v in zip(a,b)];total=sum(products);sums[row]+=total
        f=low[c];p=low[c+1];o=low[c+2]
        assert f['enable0'] and f['in_sew']==0 and 256*f['in_tag_flag']+f['in_tag_index']==rec['tag']
        assert f['vs1']==int(src['a'],16) and f['vs2']==int(src['b'],16)
        assert [signed(p[f'p{j}'],32) for j in range(8)]==products,'actual product registers differ'
        assert signed(o['sum'],35)==total,'actual sum register differs'
        assert o['out_valid'] and o['out_op']==0x160 and o['out_data']==total&0xffffffff
        assert (o['out_vl'],o['out_sew'],o['out_illegal'])==(8,0,0)
        assert 256*o['out_tag_flag']+o['out_tag_index']==rec['tag']
        assert rec['commit']>=out['cycle']
        checked.append(dict(row=row,block=block,input_cycle=c,output_cycle=c+2,commit_cycle=rec['commit'],
            tag=rec['tag'],a=a,b=b,products=products,total=total,accumulated=sums[row]))
    assert sums==list(map(int,plain[0][1].split(','))),'final rows differ'
    return dict(status='PASS',sampling=capture['scope'],begin=capture['begin'],end=capture['end'],
        compressed_bytes=capture['compressed_bytes'],uncompressed_bytes=capture['uncompressed_bytes'],
        observer_control='all nine calls have identical cycles, ROB records, dot values and final output',
        widths=widths,checked=checked,y=sums,frames=frames,
        qualification='VCD is actual signal samples after each high/low eval; event commits are separate ROB evidence; accumulation expressions are arithmetic annotations')

def validate_excerpt(data):
    """Recheck arithmetic against saved actual frames without needing old binaries."""
    assert data['status']=='PASS' and len(data['checked'])==12
    frames=data['frames'];low={f['cycle']:f for f in frames if f['phase']==1};sums=[0]*4
    assert all(f['time']==2*f['cycle']+f['phase'] and f['clock']==1-f['phase'] for f in frames)
    assert len(frames)==2*(data['end']-data['begin']+1)
    for i,r in enumerate(data['checked']):
        block,row=divmod(i,4);assert (r['block'],r['row'])==(block,row)
        c=r['input_cycle'];f=low[c];p=low[c+1];o=low[c+2]
        a,b=lanes(f['vs1']),lanes(f['vs2']);assert a==r['a'] and b==r['b']
        products=[x*y for x,y in zip(a,b)];total=sum(products);sums[row]+=total
        assert products==r['products']==[signed(p[f'p{j}'],32) for j in range(8)]
        assert signed(o['sum'],35)==total==r['total']
        assert o['out_data']==total&0xffffffff and o['out_valid'] and o['out_op']==0x160
        assert (o['out_vl'],o['out_sew'],o['out_illegal'])==(8,0,0)
        assert f['enable0'] and f['in_sew']==0
        assert r['tag']==256*f['in_tag_flag']+f['in_tag_index']==256*o['out_tag_flag']+o['out_tag_index']
        assert r['output_cycle']==c+2 and r['commit_cycle']>=c+2 and r['accumulated']==sums[row]
        if block==2:assert a[1:]==b[1:]==[0]*7
    assert data['y']==sums

def waveform(data,index,title):
    item=data['checked'][index];c=item['input_cycle'];lo,hi=c-2,c+5
    frames=[f for f in data['frames'] if 2*lo<=f['time']<=2*hi+1]
    assert frames[0]['cycle']==lo and frames[-1]['cycle']==hi
    d=DRAW.Drawing(title,'真实整核关键信号 VCD · 高/低相位各采样一次 · 横轴为仿真周期，不代表物理频率',1080)
    x=lambda t:390+(t-2*lo)*(1230/(2*(hi-lo+1)))
    rows=[('clock','实际时钟','bit'),('enable0','点积第一级使能','bit'),('enable1','点积第二级使能','bit'),
        ('vs1','权重源低 64 位','hex'),('vs2','输入源低 64 位','hex'),
        ('p0','products_0（signed32）','s32'),('p1','products_1（signed32）','s32'),('p7','products_7（signed32）','s32'),
        ('sum','sum（signed35）','s35'),('out_valid','VIMac 输出有效','bit'),
        ('out_op','输出操作类型','op'),('out_data','输出低 32 位（signed）','result'),
        ('out_vl','输出随行 VL','int'),('out_illegal','非法异常','bit')]
    for cyc,color in ((c,'#e7f0fc'),(c+1,'#fff3d9'),(c+2,'#e5f5ee')):
        d.rect(x(2*cyc),145,x(2*cyc+2)-x(2*cyc),650,color,color,0)
    def val(f,key,kind):
        v=f[key]
        if kind=='hex':return f'{v&((1<<64)-1):016x}'
        if kind.startswith('s'):return str(signed(v,int(kind[1:])))
        if kind=='result':return str(signed(v&0xffffffff,32))
        if kind=='op':return f'0x{v:x}'
        return str(v)
    for ri,(key,label,kind) in enumerate(rows):
        y=170+ri*45;d.text(45,y+5,label,19);d.line([(385,y+23),(1630,y+23)],'#dbe3ed',1)
        if kind=='bit':
            for j,f in enumerate(frames):
                end=frames[j+1]['time'] if j+1<len(frames) else 2*(hi+1)
                level=y+11-22*f[key];d.line([(x(f['time']),level),(x(end),level)],DRAW.BLUE,2)
                if j and f[key]!=frames[j-1][key]:d.line([(x(f['time']),y-11),(x(f['time']),y+11)],DRAW.BLUE,2)
        else:
            groups=[]
            for f in frames:
                value=val(f,key,kind)
                if not groups or groups[-1][1]!=value:groups.append([f['time'],value])
            for j,(t,v) in enumerate(groups):
                end=groups[j+1][0] if j+1<len(groups) else 2*(hi+1)
                left,right=x(t),x(end);d.line([(left,y),(left+4,y-11),(right-4,y-11),(right,y),(right-4,y+11),(left+4,y+11),(left,y)],DRAW.BLUE,1.4)
                if right-left>len(v)*8+8:d.text((left+right)/2,y+5,v,15,anchor='middle')
    for cyc in range(lo,hi+1):
        d.line([(x(2*cyc),147),(x(2*cyc),805)],'#d9e1eb',1,dash=True)
        d.text(x(2*cyc)+4,827,str(cyc),15)
    d.text(45,870,f'行 {item["row"]}，块 {item["block"]}；输入 C={c} → 乘积 C+1 → 输出 C+2；ROB 提交 C={item["commit_cycle"]}',21,DRAW.GREEN)
    d.text(45,910,'W 八项：'+', '.join(map(str,item['a'])),21)
    d.text(45,945,'x 八项：'+', '.join(map(str,item['b'])),21)
    d.text(45,980,'实际乘积：'+', '.join(map(str,item['products'])),20)
    d.text(45,1020,f'独立求和 = 实际 sum = 输出低 32 位有符号值 = {item["total"]}；输出高 96 位为 0。',21,DRAW.GREEN)
    d.text(45,1054,'总线只有足够显示宽度时标数值；完整帧、八项乘积与全部十二条点积核对结果保存在配套 JSON。',17,DRAW.GRAY)
    return d

def timeline(data):
    d=DRAW.Drawing('GEMV 四行、三块点积与顺序提交','真实执行/ROB 事件图；下方累计式为独立算术核对，不是累加寄存器波形',880)
    lo=min(r['input_cycle'] for r in data['checked'])-3;hi=max(r['commit_cycle'] for r in data['checked'])+4
    x=lambda c:210+1400*(c-lo)/(hi-lo)
    for row in range(4):
        y=205+row*112;d.text(48,y+8,f'输出行 {row}',24)
        d.line([(210,y),(1610,y)],'#d9e1eb',1.5)
        for rec in (r for r in data['checked'] if r['row']==row):
            a,b,z=map(x,(rec['input_cycle'],rec['output_cycle'],rec['commit_cycle']))
            d.line([(a,y),(b,y)],DRAW.BLUE,4)
            d.rect(a-3,y-6,6,12,'#416b96','#416b96',0)
            d.rect(b-4,y-6,8,12,'#287b69','#287b69',0)
            d.line([(b,y),(z,y-27)],DRAW.GRAY,1.5,dash=True)
            d.rect(z-3,y-33,6,12,'#a57225','#a57225',0)
            d.text((a+b)/2,y+37,f'块{rec["block"]}: {rec["total"]}',17,anchor='middle')
    for j in range(9):
        c=round(lo+(hi-lo)*j/8);d.text(x(c),665,str(c),16,anchor='middle')
    d.text(45,711,'蓝：实际接收　绿：两周期后实际输出　棕：该 ROB 指令实际提交',21)
    for row in range(4):
        parts=[r['total'] for r in data['checked'] if r['row']==row]
        d.text(48+(row%2)*810,760+(row//2)*40,f'y[{row}] = '+ ' + '.join(f'({p})' for p in parts)+f' = {data["y"][row]}',20,DRAW.GREEN)
    d.text(45,855,'最终四行输出同时由 C 独立参考、实际程序逐行检查和 NEMU/RTL 差分确认；FU 输出与 ROB 提交分别标注。',18,DRAW.GRAY)
    return d

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--wave',type=Path);p.add_argument('--probe',type=Path)
    p.add_argument('--from-excerpts',type=Path);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.from_excerpts:
        assert not a.wave and not a.probe
        data=json.loads(a.from_excerpts.read_text())
    else:
        assert a.wave and a.probe
        data=audit(a.wave,a.probe)
    validate_excerpt(data);a.out.mkdir(parents=True,exist_ok=False)
    figures=[('点积两级流水',waveform(data,0,'INT8 GEMV：八项乘积与两级流水')),
        ('尾部七项补零',waveform(data,8,'INT8 GEMV：K=17 最后一块的七项补零')),
        ('四行结果与提交',timeline(data))]
    with tempfile.TemporaryDirectory(prefix='gemv-fonts-') as tmp:
        config=Path(tmp)/'fonts.conf';config.write_text('<fontconfig><dir>/usr/share/fonts</dir><dir>/mnt/c/Windows/Fonts</dir><cachedir>'+tmp+'</cachedir></fontconfig>')
        os.environ['FONTCONFIG_FILE']=str(config)
        for name,drawing in figures:
            svg=a.out/(name+'.svg');svg.write_text(drawing.finish());DRAW.rasterize(svg,svg.with_suffix('.png'),2)
    R.write(a.out/'signal-evidence.json',data)
    print('GEMV actual waveform PASS: 12 inputs/products/sums/full128 outputs, same observer control, 3 PNGs')
if __name__=='__main__':main()
