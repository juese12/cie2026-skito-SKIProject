#!/usr/bin/env python3
"""复算 v4 原始数据，保留稳定性警告，并比较配对的新旧核。"""
import argparse
import csv
import json
from pathlib import Path
import statistics as S
import common as C

THRESHOLDS=json.loads((C.SRC/'protocol.json').read_text())['thresholds']

def metrics(rows,warm):
    values=[int(r['cycles']) for r in rows];median=S.median(values);n=len(values)
    drift=S.median(values[n//2:])/S.median(values[:n//2])-1
    slots={i:[int(r['cycles']) for r in rows if int(r['slot'])==i] for i in (0,1)}
    order=S.median(slots[1])/S.median(slots[0])-1
    cv=S.pstdev(values)/S.mean(values)
    tail=int(warm[-1]['cycles'])/median-1 if warm else None
    warnings=[]
    for name,v in [('cv',cv),('drift',drift),('order',order),('warm_tail',tail)]:
        threshold=THRESHOLDS[name]
        if v is not None and abs(v)>threshold+1e-12:warnings.append(dict(metric=name,value=v,threshold=threshold))
    return dict(n=n,median=median,minimum=min(values),maximum=max(values),cv=cv,drift=drift,
      order=order,warm_tail=tail,warnings=warnings,raw=values,warm_raw=[int(r['cycles']) for r in warm])

def linear(points):
    xs=[p[0] for p in points];ys=[p[1] for p in points];xm=S.mean(xs);ym=S.mean(ys)
    slope=sum((x-xm)*(y-ym) for x,y in points)/sum((x-xm)**2 for x in xs)
    intercept=ym-slope*xm;residuals=[y-(intercept+slope*x) for x,y in points]
    ss=sum((y-ym)**2 for y in ys)
    return dict(slope_cycles_per_dot=slope,intercept_cycles=intercept,points=points,residuals=residuals,
      max_relative_residual=max(abs(e)/y for e,y in zip(residuals,ys)),
      r_squared=1-sum(e*e for e in residuals)/ss if ss else None,
      interpretation='effective dependency-chain slope including loop/configuration costs; not isolated FU latency')

def analyze(state):
    C.need(state['status']=='CPU_PASS' and len(state['runs'])==8,'incomplete eight-process experiment')
    C.frozen(state['frozen']);runs=[];all_warnings=[]
    for source in state['runs']:
        C.need(source['core'] in ('new','old') and source['params']['profile']==2 and
               source['params']['wide']==int(source['core']=='new'),'smoke/wrong core mixed into formal data')
        audit=C.parse(source['log'],source['params']);C.need(audit==source['audit'],'raw replay mismatch')
        per=[];fits=[]
        for case in audit['cases']:
            bits,kind=int(case['bits']),int(case['kind']);stats=[]
            for impl in (0,1):
                rows=[r for r in audit['samples'] if int(r['bits'])==bits and int(r['kind'])==kind and int(r['impl'])==impl]
                measured=sorted((r for r in rows if int(r['phase'])==1),key=lambda r:int(r['rep']))
                warm=sorted((r for r in rows if int(r['phase'])==0),key=lambda r:int(r['rep']))
                m=metrics(measured,warm);m.update(impl=impl,cycles_per_dot=m['median']/int(case['dots']));stats.append(m)
                for w in m['warnings']:all_warnings.append(dict(label=source['label'],bits=bits,kind=kind,impl=impl,**w))
            per.append(dict(bits=bits,kind=kind,dots=int(case['dots']),case=case,implementations=stats,
              rvv_over_dot=stats[1]['median']/stats[0]['median']))
        for bits in sorted({p['bits'] for p in per}):
            for impl in (0,1):
                fit=linear([(p['dots'],p['implementations'][impl]['median']) for p in per if p['bits']==bits and p['kind']>=2])
                fits.append(dict(bits=bits,impl=impl,**fit))
                if fit['max_relative_residual']>THRESHOLDS['chain_linearity']+1e-12:all_warnings.append(dict(label=source['label'],bits=bits,impl=impl,metric='chain_linearity',value=fit['max_relative_residual'],threshold=THRESHOLDS['chain_linearity']))
        runs.append(dict(label=source['label'],core=source['core'],params=source['params'],cases=per,fits=fits,
          instructions=audit['instructions'],cycles=audit['cycles'],log=source['log'],log_sha256=audit['log_sha256']))
    new=[r for r in runs if r['core']=='new'];old=[r for r in runs if r['core']=='old']
    for group in (new,old):
        C.need([r['params']['seed'] for r in group]==[101,202,303,404],'wrong independent seed set')
        C.need([r['params']['first'] for r in group]==[0,1,0,1],'unbalanced process first order')
        C.need([r['params']['data'] for r in group]==[0x56444f54,1,0x9e3779b9,0xdeadbeef],'wrong actual data seed set')
    summary=[]
    for bits in (8,16):
        for kind in range(5):
            cases=[next(p for p in r['cases'] if p['bits']==bits and p['kind']==kind) for r in new]
            ratios=[p['rvv_over_dot'] for p in cases]
            firsts={f:[p['rvv_over_dot'] for r,p in zip(new,cases) if r['params']['first']==f] for f in (0,1)}
            initial=S.median(firsts[1])/S.median(firsts[0])-1
            if abs(initial)>THRESHOLDS['between_process_first_and_data']+1e-12:all_warnings.append(dict(bits=bits,kind=kind,metric='between_process_first_and_data',value=initial,threshold=THRESHOLDS['between_process_first_and_data'],
              qualification='first is paired with different data/init seeds; this is not an isolated causal order effect'))
            summary.append(dict(bits=bits,kind=kind,dots=cases[0]['dots'],
              dot_cycles=S.median(p['implementations'][0]['median'] for p in cases),
              rvv_cycles=S.median(p['implementations'][1]['median'] for p in cases),
              speedup_median=S.median(ratios),speedup_min=min(ratios),speedup_max=max(ratios),
              process_ratios=ratios,first_group_difference=initial))
    extension=[]
    for kind in range(5):
        for impl in (0,1):
            pairs=[]
            for n,o in zip(new,old):
                C.need(n['params']['seed']==o['params']['seed'] and n['params']['data']==o['params']['data'] and n['params']['first']==o['params']['first'],'unmatched core comparison')
                a=next(p for p in n['cases'] if p['bits']==8 and p['kind']==kind)
                b=next(p for p in o['cases'] if p['bits']==8 and p['kind']==kind)
                C.need(a['case']==b['case'],'e8 vectors/oracle/length changed across cores')
                pairs.append(a['implementations'][impl]['median']/b['implementations'][impl]['median'])
            extension.append(dict(kind=kind,impl=impl,new_over_old_median=S.median(pairs),pair_ratios=pairs))
    return dict(status='DATA_PASS',stable=not all_warnings,strict_exit=3 if all_warnings else 0,
      independent_processes=8,new_processes=4,old_processes=4,runs=runs,summary=summary,e8_extension=extension,warnings=all_warnings,
      qualification='v4 current e8/e16 measurements; all raw samples and warnings retained; simulated cycles, not physical timing/PPA or real-application speedup')

def report(result,state_path):
    state=json.loads(Path(state_path).read_text())
    stem=Path(state_path).name.removesuffix('.results.json')
    labels={0:'batch4',1:'e2e',2:'chain16',3:'chain64',4:'chain256'}
    rows=['# 当前 e8/e16 vdot 正式性能报告 v4','',
      '由本轮八个完整进程的原始日志复算生成；旧 v3 性能样本不参与统计。',
      '',f'数据有效性：**PASS**。稳定性：**{"PASS" if result["stable"] else "存在警告，不能宣称整体稳定"}**；strict={result["strict_exit"]}。',
      '', '## 实验身份与方法','',
      '- 当前核 `sew16-fixed8/emu`＋`NEMU/build/sew16`，四独立初始化 seed=101/202/303/404；旧 e8 隔离核使用对应旧参考库另跑四进程。',
      '- 单一镜像，仅启动参数决定 e16 路径是否执行、初始选序和数据 seed；所有代码地址相同。新核 e8 与旧核按相同种子、同一输入和相同长度配对。',
      '- 每位宽每实现 96 项完整 128 位/CSR 等价性检查（32 定向＋64 随机），每场景每实现 8 预热＋8 正式样本，全部成功路径打印延后。',
      '- batch4/e2e 每样本 64 批×4=256 点积；非零反馈链为 16/64/256 条点积，逐步 oracle 排除零和固定点。',
      '- e8 RVV：signed8 宽乘到 signed16，再宽归约到 signed32；e16 RVV：signed16 宽乘到 signed32，再宽归约到 signed64。双方返回完整寄存器高位零及相同配置。',
      '- 起止为 mcycle＋vstart CSR-write 排空标记，内部包含标记与必要循环/配置成本，不扣空循环。当前事件模型对本轮 probe 完成动态边界审计，详见队列门槛文件。',
      '', '## 当前核 RVV/vdot 周期对比','',
      '周期列为四进程各自中位数的中位数；加速比为各进程 RVV/vdot 比的中位数，两个口径不混用。',
      '', '| SEW | 场景 | 点积数 | vdot 周期 | RVV 周期 | 比值中位数 | 比值范围 |',
      '| --- | --- | --- | --- | --- | --- | --- |']
    for s in result['summary']:
        rows.append(f'| {s["bits"]} | {labels[s["kind"]]} | {s["dots"]} | {s["dot_cycles"]:g} | {s["rvv_cycles"]:g} | {s["speedup_median"]:.6f} | {s["speedup_min"]:.6f}～{s["speedup_max"]:.6f} |')
    rows+=['','## e16 扩展前后 e8 的同镜像对照','',
      '下表为当前核/旧 e8 隔离核周期比，1 表示本轮中位数相同；大于 1 表示当前核周期更多。不能解释为物理频率或面积变化。旧核启动参数为 e8-only，新核为 e8/e16；e8 的代码地址、输入、长度和选序相同，但整体运行配置包含 wide 参数差异，因此不将所有周期差都归因为单一硬件变量。',
      '', '| 场景 | 实现 | new/old 中位数 | 四组配对比值 |','| --- | --- | --- | --- |']
    for s in result['e8_extension']:
        rows.append(f'| {labels[s["kind"]]} | {"RVV" if s["impl"] else "vdot"} | {s["new_over_old_median"]:.6f} | '+', '.join(f'{v:.6f}' for v in s['pair_ratios'])+' |')
    rows+=['','## 非零依赖链的长度分析','',
      '对三个链长拟合 C(N)=C0+N×L，L 包括循环和配置等成本，仅为有效反馈链周期斜率。每进程拟合及残差全部保存在 JSON，不以拟合斜率代替 FU 端口两周期延迟。',
      '', '| SEW | 实现 | 四新核进程 L 的中位数 | 最大相对拟合残差 |','| --- | --- | --- | --- |']
    for bits in (8,16):
        for impl in (0,1):
            fits=[f for r in result['runs'] if r['core']=='new' for f in r['fits'] if f['bits']==bits and f['impl']==impl]
            rows.append(f'| {bits} | {"RVV" if impl else "vdot"} | {S.median(f["slope_cycles_per_dot"] for f in fits):.6f} | {max(f["max_relative_residual"] for f in fits):.3%} |')
    rows+=['','## 稳定性与边界','',
      f'共 {len(result["warnings"])} 项预定门槛警告。CV>5%，半程漂移/槽位差/末次预热相对正式中位数偏差绝对值>10%，以及链长拟合最大相对残差>10%时保留警告。进程初始选序与数据/init seed 配对变化，其组间差异不作纯顺序因果归因。',
      '', '所有警告及每个进程的原始采样在分析 JSON 中保留；不选最快进程、不删除预热异常、不池化重复采样冒充独立进程，也不据此宣称统计置信区间。',
      '', 'batch4 是预加载内核；e2e 含加载/初始化/存储，但不等于 DRAM 持久完成或应用推理；chain 使用有界受控奇数反馈序列，不代表随机模型分布。当前 RTL 不变，本轮没有综合/时序/PPA。',
      '', '## 原始数据与复核','',
      f'完整状态/冻结指纹与全部运行路径：`{Path(state_path).relative_to(C.ROOT)}`。分析 JSON 与报告同前缀，原始日志含实际退出、差分、参数、所有预热和正式采样；运行/复核入口见 [v4 协议](../sew16-perf/性能测量与复核手册v4.md)。','']
    if result['warnings']:
        rows+=['','## 全部门槛警告','',
          '| 进程/组 | SEW | 场景 | 实现 | 指标 | 数值 | 门槛 |',
          '| --- | --- | --- | --- | --- | --- | --- |']
        for w in result['warnings']:
            rows.append(f'| {w.get("label","cross-process")} | {w["bits"]} | {labels.get(w.get("kind"),"chain-fit")} | {"RVV" if w.get("impl")==1 else "vdot" if w.get("impl")==0 else "ratio"} | {w["metric"]} | {w["value"]:+.3%} | {w["threshold"]:.1%} |')
    rows+=['','## 冻结身份和门槛证据','',
      '| 对象 | SHA256 |','| --- | --- |']
    for name,paths in [('当前核',C.CORES['new']),('旧核',C.CORES['old'])]:
        for role,path in zip(('emu','ref'),paths):rows.append(f'| {name} {role} | `{state["frozen"][str(path)]}` |')
    rows.append(f'| 同一基础镜像 | `{state["frozen"][str(C.IMAGE)]}` |')
    rows+=['',f'- [八进程原始结果与全部输入指纹](../logs/{stem}.results.json)',
      f'- [统计、每个进程全部周期、输入和全部警告](../logs/{stem}.analysis.json)',
      f'- [全部 1920 行预热与正式样本 CSV](../logs/{stem}.analysis.samples.csv)']
    for gate in state['gates']:rows.append(f'- [预飞/动态边界证据：{Path(gate).name}](../logs/{Path(gate).name})')
    rows+=['','## 软件范围说明','',
      '四个独立目的共用同一对源向量，用于测试指令流；不是四组不同数据的应用。e2e 使用双方共同的目的与 seed 初始化框架，不能称为所有实现中最优的端到端算法；batch4 初始化在计时外。实际计时输入的完整 128 位值与独立 oracle 随每个场景保存。',
      '', '同前缀 `.samples.csv` 导出全部 1920 行预热/正式样本，可按进程、位宽、场景、实现和先后槽位复算；分析器源代码及冻结协议随作品交付。','']
    return '\n'.join(rows)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('state',type=Path);p.add_argument('--out',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--strict',action='store_true')
    a=p.parse_args();a.state=a.state.resolve();state=json.loads(a.state.read_text());r=analyze(state)
    with a.out.open('x') as f:json.dump(r,f,indent=2)
    with a.report.open('x') as f:f.write(report(r,a.state))
    with a.out.with_suffix('.samples.csv').open('x',newline='') as f:
        writer=csv.writer(f);writer.writerow(['label','core','init_seed','data_seed','first','bits','kind','phase','rep','slot','impl','dots','cycles'])
        total=0
        for run in state['runs']:
            cases={(int(c['bits']),int(c['kind'])):int(c['dots']) for c in run['audit']['cases']}
            for row in run['audit']['samples']:
                writer.writerow([run['label'],run['core'],run['params']['seed'],f'{run["params"]["data"]:08x}',run['params']['first'],
                  *[row[k] for k in ('bits','kind','phase','rep','slot','impl')],cases[int(row['bits']),int(row['kind'])],row['cycles']]);total+=1
        C.need(total==1920,'incomplete complete-sample export')
    print(json.dumps(dict(status=r['status'],stable=r['stable'],strict=r['strict_exit'],warnings=len(r['warnings']))))
    if a.strict:raise SystemExit(r['strict_exit'])
