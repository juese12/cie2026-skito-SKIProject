#!/usr/bin/env python3
"""从已有最新模块 VCD 和整核事件提取边界证据，不启动任何仿真。"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SANDBOX = ROOT.parent/'XiangShan/out/xiangshan/test/testOnly.dest/sandbox/test_run_dir'
ARITHMETIC = SANDBOX/'VDot8_should_produce_exact_signed_sums_with_enabled_stages_bubbles_and_poisoned_upper_bytes/VDot8.vcd'
WRAPPER = SANDBOX/'VIMacU_vdot_integration_should_align_mixed_operations_tags_full_writes_runtime_legality_and_canceled_operations/VDotIntegrationHarness.vcd'
EVENTS = ROOT/'stage2/logs/20261027T131534-e16-events.results.json'
T = 'TOP.'
D = T+'VDot8.'
F = T+'VDotIntegrationHarness.fu.'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


DRAW = module('boundary_drawing', Path(__file__).with_name('render-vdot-design-diagrams.py'))


def signed(value, width):
    return value-(1 << width) if value & (1 << (width-1)) else value


def read_edges(path, wanted):
    """保存上升沿前后稳定值；信号名、位宽和原时间戳直接来自 VCD。"""
    scopes, names, declarations, values, edges = [], {}, {}, {}, []
    last, timestamp = None, 0
    def sample():
        nonlocal last
        if not names:
            return
        now = {name: values.get(code) for name, code in names.items()}
        now['time'] = timestamp
        if last and last[T+'clock'] == 0 and now[T+'clock'] == 1 and not last[T+'reset'] and not now[T+'reset']:
            assert wanted <= names.keys(), 'VCD 缺少必需信号'
            assert all(v is not None for row in (last, now) for v in row.values()), '目标采样含未知值'
            edges.append((last, now))
        last = now
    with path.open() as stream:
        for raw in stream:
            line = raw.strip(); fields = line.split()
            if line.startswith('$scope'):scopes.append(fields[2])
            elif line.startswith('$upscope'):scopes.pop()
            elif line.startswith('$var'):
                name = '.'.join(scopes+[fields[4]])
                if name in wanted:
                    names[name] = fields[3]
                    declarations[name] = {'width':int(fields[2]), 'code':fields[3]}
            elif line.startswith('#'):sample();timestamp = int(line[1:])
            elif line.startswith('b'):
                bits, code = line[1:].split()
                values[code] = None if any(x in bits.lower() for x in 'xz') else int(bits,2)
            elif line and line[0] in '01xXzZ':
                values[line[1:]] = int(line[0]) if line[0] in '01' else None
    sample()
    return edges, declarations


def arithmetic_cases():
    wanted = {T+x for x in ('clock','reset','io_vs1','io_vs2','io_sew16','io_enable_0','io_enable_1','io_result')}
    wanted |= {D+x for x in ('isolatedVs1','isolatedVs2','sew16S1','sew16S2','sum')}
    wanted |= {D+f'products_{i}' for i in range(8)}
    edges, declarations = read_edges(ARITHMETIC, wanted)
    assert declarations[D+'sum']['width'] == 35
    assert all(declarations[D+f'products_{i}']['width'] == 32 for i in range(8))
    targets = {131072:'e8最大正和', 0:'e8零结果'}
    chosen, stage1 = {}, None
    minimum = None
    for index, (pre, post) in enumerate(edges):
        if pre[T+'io_enable_1'] and stage1 is not None:
            expected = stage1['expected']
            assert signed(post[D+'sum'],35) == expected
            assert post[T+'io_result'] == expected % (1 << 32)
            if expected in targets and expected not in chosen:
                case = dict(stage1, name=targets[expected], output_edge=index,
                            result=post[T+'io_result'], sum_raw=post[D+'sum'], output_complete=True)
                lo, hi = max(0,stage1['input_edge']-1), min(len(edges),index+3)
                case['samples'] = [{'edge':i,'pre':edges[i][0],'post':edges[i][1]} for i in range(lo,hi)]
                chosen[expected] = case
        if pre[T+'io_enable_0']:
            assert pre[T+'io_sew16'] == 0
            a = [signed((pre[T+'io_vs1']>>(8*i))&255,8) for i in range(8)]
            b = [signed((pre[T+'io_vs2']>>(8*i))&255,8) for i in range(8)]
            products = [x*y for x,y in zip(a,b)]
            assert [signed(post[D+f'products_{i}'],32) for i in range(8)] == products
            stage1 = dict(input_edge=index, a=a, b=b, products=products,
                          expected=sum(products), vs1=pre[T+'io_vs1'], vs2=pre[T+'io_vs2'])
            if sum(products) == -130048 and minimum is None:
                # 这条已保留激励之后 S2 被关闭，只能证明乘积及旧结果保持。
                npre,npost=edges[index+1]
                assert not npre[T+'io_enable_1'] and npost[D+'sum']==post[D+'sum']
                minimum=dict(stage1,name='e8最小负和乘积与保持',output_edge=index+1,
                             result=npost[T+'io_result'],sum_raw=npost[D+'sum'],output_complete=False,
                             samples=[dict(edge=i,pre=edges[i][0],post=edges[i][1])
                                      for i in range(max(0,index-1),min(len(edges),index+4))])
    assert chosen.keys() == targets.keys(), '已有 VCD 未完整覆盖指定边界'
    assert minimum is not None
    return [chosen[131072],minimum,chosen[0]], declarations


def illegal_case():
    wanted = {T+x for x in ('clock','reset','io_valid','io_cancel','io_op','io_tag','io_config_vtype_vsew',
                            'io_config_vtype_vlmul','io_config_vtype_illegal','io_config_vl','io_vm','io_vstart',
                            'io_outValid','io_outTag','io_illegal','io_result')}
    wanted |= {F+'outVConfig_vl',T+'VDotIntegrationHarness.fu_io_in_bits_ctrlPipe_2_vpu_vsew'}
    edges, declarations = read_edges(WRAPPER,wanted)
    for index,(pre,post) in enumerate(edges[:-1]):
        if pre[T+'io_valid'] and not pre[T+'io_cancel'] and pre[T+'io_op'] == 0x160 and pre[T+'io_config_vtype_vsew'] == 1 and pre[T+'io_config_vl'] == 0:
            out = edges[index+1][1]
            assert out[T+'io_outValid'] and out[T+'io_outTag'] == pre[T+'io_tag'] and out[T+'io_illegal']
            assert out[F+'outVConfig_vl']==0 and out[T+'VDotIntegrationHarness.fu_io_in_bits_ctrlPipe_2_vpu_vsew']==1
            return dict(name='e16非法VL零', input_edge=index, output_edge=index+1, tag=pre[T+'io_tag'],
                        samples=[dict(edge=i,pre=edges[i][0],post=edges[i][1]) for i in range(max(0,index-1),min(len(edges),index+4))]), declarations
    raise AssertionError('未找到已有 e16、VL=0 的有效异常输出')


def cpu_maximum():
    result = json.loads(EVENTS.read_text())
    for record in result['runs'][0]['audit']['records']:
        if record.get('commit') and record.get('input',{}).get('expected') == 8589934592 and record.get('output'):
            assert record['input']['a'] == record['input']['b'] == '8000'*8
            assert int(record['output']['result'],16) == 8589934592 and not record['output']['illegal']
            assert record['output']['cycle']-record['input']['cycle'] == 2
            return record
    raise AssertionError('未找到已提交的 e16 最大正和')


def fmt(value, kind):
    if kind == 's32':return str(signed(value,32))
    if kind == 's35':return str(signed(value,35))
    if kind == 'low':return f'{value & 0xffffffff:08x}'
    if kind == 'high':return str(value >> 32)
    if kind == 'short':
        text=f'{value:032x}'
        return text[:4]+'…'+text[-4:]
    return str(value)


def waveform(case, tracks, extra):
    rows = case['samples']; height = max(880, 455+len(tracks)*35)
    g = DRAW.Drawing(case['name']+'：已有模块波形关键采样',
                     '每列为同一上升沿的 PRE → POST 稳定值；t 是仿真时间戳，不是运行日期或整核周期',height)
    g.rect(48,143,1584,110,'#f7f9fc','#b2c2d4')
    for i,line in enumerate(extra):g.text(68,174+i*29,line,20)
    left,cw = 370, 1250/len(rows)
    for ci,row in enumerate(rows):
        x=left+ci*cw
        if row['edge'] in (case['input_edge'],case['output_edge']):g.rect(x,273,cw,height-370,'#edf7f2','#d5e6dd',0)
        label='S1 捕获' if row['edge'] == case['input_edge'] else ('S2 禁用保持' if case.get('output_complete') is False else 'S2 结果') if row['edge'] == case['output_edge'] else '相邻采样'
        g.text(x+cw/2,295,label,18,DRAW.GREEN if label!='相邻采样' else DRAW.GRAY,'700','middle')
        g.text(x+cw/2,320,f't={row["pre"]["time"]} / {row["post"]["time"]}',17,anchor='middle')
        for ri,(label,kind,key) in enumerate(tracks):
            y=356+ri*35
            if ci == 0:g.text(55,y+5,label,19)
            p,q=row['pre'][key],row['post'][key]
            if kind == 'bit':
                mid=x+cw/2;yp=y-8 if p else y+8;yq=y-8 if q else y+8
                g.line([(x+8,yp),(mid,yp),(mid,yq),(x+cw-8,yq)],color=DRAW.GREEN,width=2)
            else:g.text(x+cw/2,y+5,fmt(p,kind)+' → '+fmt(q,kind),16,anchor='middle')
    g.text(48,height-58,'图中连线仅连接稳定采样；禁用级的旧数据由对应 enable 解释，不作为另一条指令的新结果。',19)
    g.text(48,height-25,'模块图证明数据通路或异常上报；架构提交、目的保持和完整差分分别由整核记录验证。',18,DRAW.GRAY)
    return g


def arithmetic_figure(case):
    tracks=[('clock','bit',T+'clock'),('enable[0]：乘积捕获','bit',T+'io_enable_0'),
            ('enable[1]：总和捕获','bit',T+'io_enable_1'),('sew16：0 表示 e8','bit',T+'io_sew16'),
            ('隔离后 vs1（缩写）','short',D+'isolatedVs1'),('隔离后 vs2（缩写）','short',D+'isolatedVs2')]
    tracks += [(f'products_{i}：signed32','s32',D+f'products_{i}') for i in range(8)]
    tracks += [('sum：signed35','s35',D+'sum'),('结果低 32 位：十六进制','low',T+'io_result'),
               ('结果高 96 位：必须为零','high',T+'io_result')]
    final=f'完整 128 位结果 = 0x{case["result"]:032x}'
    if not case['output_complete']:
        final='本窗口 S2 禁用；图中输出保持旧值，不是最小负和的有效输出。'
    return waveform(case,tracks,[f'a[0..7] = {case["a"]}；b[0..7] = {case["b"]}',
                                f'每项乘积 = {case["products"][0]}；数学总和 = {case["expected"]}',final])


def illegal_figure(case):
    tracks=[('clock','bit',T+'clock'),('输入 valid','bit',T+'io_valid'),('输入 tag','dec',T+'io_tag'),
            ('输入 vsew：1 表示 e16','dec',T+'io_config_vtype_vsew'),('实际 VL：目标为零','dec',T+'io_config_vl'),
            ('LMUL 编码：0 表示 m1','dec',T+'io_config_vtype_vlmul'),('vm：1 表示不使用掩码','bit',T+'io_vm'),
            ('vstart','dec',T+'io_vstart'),('输出 valid','bit',T+'io_outValid'),('输出 tag','dec',T+'io_outTag'),
            ('输出级实际 VL','dec',F+'outVConfig_vl'),
            ('输出级 vsew','dec',T+'VDotIntegrationHarness.fu_io_in_bits_ctrlPipe_2_vpu_vsew'),
            ('输出 illegal：目标为 1','bit',T+'io_illegal')]
    return waveform(case,tracks,[f'目标输入 tag={case["tag"]}，SEW=16、LMUL=1、VL=0。',
                                'VL=0 不执行零长度点积，必须报告非法指令。',
                                '输出 valid 只表示异常载荷有效，不代表架构目的已写入。'])


def cpu_figure(record):
    g=DRAW.Drawing('e16 最大正和：整核接收、有效输出与提交事件',
                   '来源为当前核稀疏实测事件；只显示已观察事件，不补造连续总线波形或乘积寄存器',960)
    g.box(60,156,1560,108,'a = b = [-32768, -32768, -32768, -32768, -32768, -32768, -32768, -32768]',
          ['8 × 1073741824 = 8589934592；完整结果 0x00000000000000000000000200000000'],kind='new',size=22)
    inp,out,commit=record['input']['cycle'],record['output']['cycle'],record['commit']
    labels=['FU 接收','配置 vsew / VL / vm','vstart / vill','输出有效与非法标志','完整结果低 64 位','完整结果高 64 位','ROB tag / 分配代次','同代次架构提交']
    columns=[(inp,[1,'1 / 8 / 1','0 / 0','—','—','—',f'{record["tag"]} / {record["seq"]}','—']),
             (out,['—','1 / 8 / 1','0 / 0','valid=1 / illegal=0','0000000200000000','0000000000000000',f'{record["tag"]} / {record["seq"]}','—']),
             (commit,['—','—','—','—','—','—',f'{record["tag"]} / {record["seq"]}',1])]
    for i,(cycle,values) in enumerate(columns):
        x=455+i*385;g.text(x+160,325,'整核周期 '+str(cycle),22,DRAW.BLUE,'700','middle')
        for row,(label,value) in enumerate(zip(labels,values)):
            y=380+row*49
            if i==0:g.text(60,y,label,22)
            g.text(x+160,y,str(value),21,DRAW.GREEN if value==1 else DRAW.INK,anchor='middle')
    g.text(900,788,'接收 → 输出：2 周期；输出 → 提交：'+str(commit-out)+' 周期',23,DRAW.BLUE,'700','middle')
    g.text(60,848,'事件列之间的时间间隙省略；“—”表示该事件没有记录该字段，不表示信号为零。',21)
    g.text(60,885,'结果超过 32 位范围，高 64 位清零；输入、输出和提交按相同 ROB 标签及分配代次关联。',20)
    g.text(60,922,'本图不包含乘法器 products 或归约 sum 的连续波形；逐级算术由模块采样另行验证。',19,DRAW.GRAY)
    return g


def validate_cache(data):
    """缓存也必须重新核对算术和事件关系，不能只信任图片标题。"""
    for c in data['arithmetic']:
        assert c['products']==[a*b for a,b in zip(c['a'],c['b'])]
        assert sum(c['products'])==c['expected']
        capture=next(s for s in c['samples'] if s['edge']==c['input_edge'])
        assert capture['pre'][T+'io_enable_0'] and not capture['pre'][T+'io_sew16']
        assert capture['pre'][T+'io_vs1']==c['vs1'] and capture['pre'][T+'io_vs2']==c['vs2']
        assert [signed(capture['post'][D+f'products_{i}'],32) for i in range(8)]==c['products']
        out=next(s['post'] for s in c['samples'] if s['edge']==c['output_edge'])
        assert out[T+'io_result']==c['result']
        if c['output_complete']:
            assert c['result']==c['expected']%(1<<32) and signed(out[D+'sum'],35)==c['expected']
            source=next(s['pre'] for s in c['samples'] if s['edge']==c['output_edge'])
            assert source[T+'io_enable_1'] and [signed(source[D+f'products_{i}'],32) for i in range(8)]==c['products']
        else:
            row=next(s for s in c['samples'] if s['edge']==c['output_edge'])
            assert not row['pre'][T+'io_enable_1'] and row['pre'][D+'sum']==row['post'][D+'sum']
    maximum=data['cpu_maximum']
    assert maximum['output']['cycle']-maximum['input']['cycle']==2
    assert int(maximum['output']['result'],16)==8589934592
    assert maximum['commit']>maximum['output']['cycle']
    illegal=data['illegal'];out=next(s['post'] for s in illegal['samples'] if s['edge']==illegal['output_edge'])
    assert out[T+'io_outValid'] and out[T+'io_illegal'] and out[T+'io_outTag']==illegal['tag']
    assert out[F+'outVConfig_vl']==0 and out[T+'VDotIntegrationHarness.fu_io_in_bits_ctrlPipe_2_vpu_vsew']==1


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'stage2/reports/figures/current-boundary')
    p.add_argument('--from-excerpts',type=Path)
    p.add_argument('--refresh-derived',action='store_true',help='仅更新本脚本已生成的图件')
    args=p.parse_args()
    if args.from_excerpts:data=json.loads(args.from_excerpts.read_text())
    else:
        cases,decl=arithmetic_cases();illegal,idecl=illegal_case()
        data=dict(arithmetic=cases,illegal=illegal,cpu_maximum=cpu_maximum(),declarations=decl,wrapper_declarations=idecl,
                  sources=[str(x) for x in (ARITHMETIC,WRAPPER,EVENTS)],
                  source_checks={str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in (ARITHMETIC,WRAPPER,EVENTS)})
    validate_cache(data)
    if args.out.exists():
        assert args.refresh_derived and (args.out/'boundary-evidence-excerpts.json').exists()
    args.out.mkdir(parents=True,exist_ok=args.refresh_derived)
    with tempfile.TemporaryDirectory(prefix='vdot-boundary-fonts-') as directory:
        config=Path(directory)/'fonts.conf'
        config.write_text('<fontconfig><dir>/usr/share/fonts</dir><dir>/mnt/c/Windows/Fonts</dir><cachedir>'+directory+'</cachedir></fontconfig>')
        os.environ['FONTCONFIG_FILE']=str(config)
        figures=[(c['name'],arithmetic_figure(c)) for c in data['arithmetic']]
        figures += [('e16非法VL零',illegal_figure(data['illegal'])),('e16最大正和整核事件',cpu_figure(data['cpu_maximum']))]
        for name,drawing in figures:
            path=args.out/(name+'.svg');path.write_text(drawing.finish())
            DRAW.rasterize(path,path.with_suffix('.png'),2)
            print(name, drawing.width*2, drawing.height*2)
    (args.out/'boundary-evidence-excerpts.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print('全部图件由已有记录生成，未启动仿真。')


if __name__=='__main__':main()
