#!/usr/bin/env python3
"""Re-audit every completed full log and render Markdown without sample selection."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("bench_audit", Path(__file__).with_name("analyze-bench.py"))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def gather(manifest):
    entries = [Path(p) for p in Path(manifest).read_text().splitlines() if p]
    bench.need(len(entries) >= 4, "need at least four completed full processes")
    bench.need(all(p.name.endswith("-bench.log") for p in entries), "unexpected manifest entry")
    logs = [p.with_name(p.name.removesuffix(".log") + ".full.log") for p in entries]
    runs = [bench.audit(p) for p in logs]
    bench.need(all(r["meta"]["profile"] == "full" for r in runs), "smoke is not formal performance")
    return dict(runs=runs, series=bench.aggregate(runs), thresholds=dict(cv=0.05, drift=0.10))


def render(data, manifest, output):
    runs, series = data["runs"], data["series"]
    texts = [Path(r["log"]).read_text(errors="replace") for r in runs]
    meta = runs[0]["meta"]
    synthetic = any("synthetic parser fixture" in t for t in texts)
    title = "合成测试报告（不是硬件实测）" if synthetic else "vdot 正式性能实测报告 v2"
    lines = [f"# {title}", "", f"队列 `{Path(manifest).stem}`：从全部 {len(runs)} 个进程完整日志复算生成，不选最快样本。",
             "", "数据合同、等价性、差分检查、GOOD TRAP 与零进程退出码均通过。",
             f"稳定性：**{'通过启发式门槛' if series['stable'] else '存在警告，不能宣称整体稳定'}**。数据有效不等于稳定。",
             "", "## 方法", "",
             f"每进程双方各 {32+meta['random']} 次 oracle 检查，含 {meta['random']} 组随机、8 组定向的四种 ta/ma 策略。每实现/内核预热 {meta['warmup']} 次、采样 {meta['reps']} 次，每样本 {meta['batches']} 批 × 4 = {4*meta['batches']} 次点积。对内交替顺序，进程起始顺序均衡；计时/自检结束后统一打印。",
             "固定 XS 的 vstart CSR-write 串行标记包围内核，含标记、循环及必要配置；不减空循环。RVV 精确宽乘+宽归约与 vdot 的八项 signed int8 点积、32 位结果及 upper96 清零等价。",
             "随机输入只用于等价性检查，不是计时输入分布。正式计时的低八项固定为 a=1、b=2（结果 16），其余字节是干扰值；chain 则采用零固定点。不能据此推断不同矩阵/数据分布的应用收益。",
             "batch4：预加载四个独立目标；e2e：含加载、初始化、存储；chain：零固定点但存在真实 vd=vs1 依赖。跨进程以各进程中位数/比值为单位，不池化重复，不宣称置信区间。确定性仿真不代表现实芯片的随机独立样本。",
             "详见 [测量合同与操作](vdot-measurement-v2.md)。[v1 历史数据](vdot-performance.md) 协议不同，不直接比较提升幅度。",
             "", "## 跨进程统计", "",
             "周期列为各进程中位数的中位数，比值列为各进程 RVV/vdot 比值的中位数。",
             "", "| 内核 | RVV 周期 | vdot 周期 | 比值中位数 | 比值范围 | 比值 CV | 初始顺序影响 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for kind, g in series["groups"].items():
        s = g["speedup"]
        lines.append(f"| {kind} | {g['rvv']['median']:.12g} | {g['vdot']['median']:.12g} | {s['median']:.6f} | {s['min']:.6f}–{s['max']:.6f} | {s['cv']:.3%} | {g['order_effect']:+.3%} |")
    maximum_cv = max(run["groups"][kind][impl]["cv"] for run in runs for kind in bench.KINDS for impl in bench.IMPLS)
    lines += ["", f"单组采样最大 CV 为 {maximum_cv:.3%}。即使通过门槛，也不等于毫无波动；需结合每组范围、全部样本和位置/漂移指标阅读，尤其是含访存的 e2e。"]
    lines += ["", "初始顺序影响 = first=0 比值中位数 / first=1 比值中位数 − 1。两个镜像的 C/数据布局不同，不是纯单变量实验。",
              "", "## 每进程与全部原始样本", "", "按 rep=0 起列出；同一对的先后由 first XOR (rep & 1) 决定。", "",
              "| 进程/first | 内核 | RVV 中位数 | vdot 中位数 | RVV/vdot | RVV 周期序列 | vdot 周期序列 |", "|---|---|---:|---:|---:|---|---|"]
    for n, run in enumerate(runs):
        for kind, g in run["groups"].items():
            r, v = g["rvv"], g["vdot"]
            lines.append(f"| {n}/{run['meta']['first']} | {kind} | {r['median']:.12g} | {v['median']:.12g} | {g['raw_speedup']:.6f} | {', '.join(map(str,r['raw']))} | {', '.join(map(str,v['raw']))} |")
    lines += ["", "空循环对照（不相减）：", ""]
    for n, text in enumerate(texts):
        vals = re.findall(r"bench raw kind=empty impl=control rep=\d+ loops=\d+ cycles=(\d+)", text)
        lines.append(f"- 进程 {n}：{', '.join(vals)}。")
    lines += ["", "## 稳定性审计", "",
              "固定门槛：CV > 5% 或漂移/位置/顺序影响绝对值 > 10% 警告。项目启发式门槛，非官方标准；没有事后放宽。预热末次偏差 = 末次预热 / 采样中位数 − 1；半程漂移 = 后半程 / 前半程中位数 − 1；位置影响 = 对内先运行 / 后运行中位数 − 1。预热与测量外部控制流不同，预热偏差不能单独归因于缓存。",
              "", "| 进程 | 内核/实现 | CV | 预热末次偏差 | 半程漂移 | 位置影响 |", "|---|---|---:|---:|---:|---:|"]
    for n, run in enumerate(runs):
        for kind in bench.KINDS:
            for impl in bench.IMPLS:
                g = run["groups"][kind][impl]
                lines.append(f"| {n} | {kind}/{impl} | {g['cv']:.3%} | {g['warm_tail_drift']:+.3%} | {g['half_drift']:+.3%} | {g['slot_effect']:+.3%} |")
    lines += ["", "全部警告：", ""]
    lines += [f"- {w}" for w in series["warnings"]] or ["无（只表示通过上述门槛，不证明所有机器状态已稳定）。"]
    lines += ["", "## 日志与版本追溯", "", "完整日志及 SHA-256（包含原始预热首末值）：", ""]
    for n, run in enumerate(runs):
        relative = os.path.relpath(run["log"], Path(output).parent)
        lines.append(f"- 进程 {n}：[日志](<{relative}>)，`{run['log_sha256']}`。")
    lines += ["", "| 进程 | first | 指令数 | DUT 周期数 | 宿主 ms（非性能指标） |", "|---|---:|---:|---:|---:|"]
    for n, text in enumerate(texts):
        counts = re.search(r"instrCnt = (\d+), cycleCnt = (\d+)", text)
        host = re.search(r"Host time spent: (\d+)ms", text)
        lines.append(f"| {n} | {runs[n]['meta']['first']} | {counts[1] if counts else '未记录'} | {counts[2] if counts else '未记录'} | {host[1] if host else '未记录'} |")
    lines += ["", "| artifact | SHA-256 |", "|---|---|"]
    for role in ("emu", "ref"):
        lines.append(f"| {role} | `{runs[0]['artifacts'][role]}` |")
    for first in (0, 1):
        run = next(r for r in runs if r["meta"]["first"] == first)
        lines.append(f"| image order{first} | `{run['artifacts']['image']}` |")
    lines += ["", "报告生成时的源码指纹（仍须结合构建日志，hash 不证明可重现构建）：", "", "| 文件 | SHA-256 |", "|---|---|"]
    for name in ("stage3/vdot-bench/main.c", "stage3/vdot-bench/bench.S", "stage3/vdot-bench/Makefile", "stage3/tests/analyze-bench.py", "stage3/tests/render-bench-report.py", "scripts/run-vdot-bench.sh", "scripts/run-vdot-bench-series.sh", "scripts/validate-vdot-bench-v2.sh"):
        lines.append(f"| {name} | `{hashlib.sha256((ROOT/name).read_bytes()).hexdigest()}` |")
    lines += ["", "## 结论边界与后续", "",
              "周期比仅针对三个微基准及固定 XS/EMU/ref，不是孤立 FU 延迟、峰值 II、GEMM 收益或 PPA。CSR 边界已有源码/静态依据，专门动态时间戳/ROB 边界波形尚未取得；ROB 空不保证 e2e 存储已写入外部 DRAM。",
              "两个正式镜像的计时汇编地址与指令一致，但 C 控制流和输入地址不同。后续可采用同一镜像的运行时顺序参数进一步排除布局影响。若有警告，检查完整样本及预热/测量上下文，再预先定义下一轮均衡重测；不剔除不利样本或放宽门槛。",
              "本轮未改 vdot RTL/NEMU，未做 oldVd 去依赖、门控、PPA；不据方法变化宣称硬件性能提升。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--json-out")
    args = parser.parse_args()
    try:
        bench.need(not Path(args.output).exists(), "refusing to overwrite an existing report")
        if args.json_out:
            bench.need(not Path(args.json_out).exists(), "refusing to overwrite existing JSON")
        data = gather(args.manifest)
        content = render(data, args.manifest, args.output)
        if args.json_out:
            with Path(args.json_out).open("x") as stream:
                stream.write(json.dumps(data, indent=2)+"\n")
        with Path(args.output).open("x") as stream:
            stream.write(content)
        print(f"[report data PASS] stable={data['series']['stable']} output={args.output}")
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"[report FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
