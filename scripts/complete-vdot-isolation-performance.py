#!/usr/bin/env python3
"""可恢复的隔离核 v3 队列；已审核成功的任务不重跑，失败记录不隐藏。"""
import argparse
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'stage3/logs/20261005T004545-274-series-full-runtime.paths'
EXPECTED = {
    'emu': 'd67519c61294dff5606d7f932a4545291dd5766828363710055279734932c054',
    'ref': '2ad56dc58975ed98748a7c76e014d8ac2a4576b327adbb6324f7f7082b25cb74',
    'full': '2adc73bbe4a0e01d183b93fc7a38613438b979af955ef8d2201904db6e0e1c24',
    'smoke': 'f351c87fe9f29cc1aafaca00c2f8f6c770288a894bfa92eed512985934a52ba5',
}


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'stage3/tests' / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


bench = module('iso_bench', 'analyze-bench.py')
comparison = module('iso_comparison', 'compare-bench-cores.py')
renderer = module('iso_renderer', 'render-bench-report.py')


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            result.update(chunk)
    return result.hexdigest()


def save(path, value):
    # 只更新本队列的恢复状态；证据输出使用独占创建，避免覆盖旧结果。
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def exclusive(path, text):
    with path.open('x') as stream:
        stream.write(text)


def check_frozen(state):
    for name, expected in state['frozen'].items():
        bench.need(digest(name) == expected, f'frozen artifact changed: {name}')
    print('[frozen PASS]', flush=True)


def validate_slot(slot):
    run = bench.audit(slot['log'])
    bench.need(run['meta']['schema'] == 3 and run['meta']['profile'] == slot['profile'],
               'wrong measurement schema/profile')
    bench.need(run['meta']['first'] == slot['index'] % 2, 'wrong counterbalanced order')
    for role in ('emu', 'ref'):
        bench.need(run['artifacts'][role] == EXPECTED[role], f'wrong {role} identity')
    bench.need(run['artifacts']['image'] == EXPECTED[slot['profile']], 'wrong frozen image')
    return run


def recover_pending(state, state_path):
    if not state.get('pending'):
        return
    pending = state['pending']
    bench.need(len(state['slots']) < 6, 'pending attempt after completed queue')
    expected = ([('smoke', i) for i in range(2)] + [('full', i) for i in range(4)])[len(state['slots'])]
    bench.need((pending['profile'], pending['index']) == expected, 'pending slot order changed')
    log = Path(pending['log'])
    text = log.read_text(errors='replace') if log.exists() else ''
    bench.need(not re.search(r'benchmark FAIL|HIT BAD TRAP|ABORT|different at pc', text),
               'failed attempt needs diagnosis, not an interrupted-run retry')
    if re.search(r'^\[process exit\]', text, re.M):
        run = validate_slot(pending)  # 已记录的非零退出或数据失败必须停止后续执行。
        pending['log_sha256'] = run['log_sha256']
        state['slots'].append(pending)
        del state['pending']
    else:
        print(f'[interrupted attempt preserved] {log}', flush=True)
        state.setdefault('interrupted', []).append(state.pop('pending'))
    save(state_path, state)


def write_reports(state, prefix):
    smoke = [validate_slot(s) for s in state['slots'] if s['profile'] == 'smoke']
    full = [validate_slot(s) for s in state['slots'] if s['profile'] == 'full']
    bench.need(len(smoke) == 2 and len(full) == 4, 'incomplete queue')
    for profile in ('smoke', 'full'):
        manifest = prefix.with_name(prefix.name + f'-{profile}.paths')
        content = ''.join(s['summary'] + '\n' for s in state['slots'] if s['profile'] == profile)
        if manifest.exists():
            bench.need(manifest.read_text() == content, 'completed manifest changed')
        else:
            exclusive(manifest, content)
    full_manifest = prefix.with_name(prefix.name + '-full.paths')
    compared = comparison.compare(BASELINE, full_manifest)
    data = renderer.gather(full_manifest)
    report_path = ROOT / 'stage3/reports' / (prefix.name + '-performance.md')
    report = renderer.render(data, full_manifest, report_path)
    report = report.replace('# vdot 正式性能实测报告 v3', '# 隔离核 vdot 正式性能实测报告 v3', 1)
    report = report.replace('本轮未改 vdot RTL/NEMU，未做 oldVd 去依赖、门控、PPA；不据方法变化宣称硬件性能提升。',
        '本轮测量既有隔离核，包含P1 oldVd去依赖及操作数隔离/寄存器使能；测量期间没有修改RTL或NEMU。没有物理PPA结果，不据RTL活动计数宣称功耗收益。')
    report += '\n## P1 → 隔离核同协议对比\n\n'
    report += '| 内核 | vdot P1/隔离核周期比中位数 | RVV对照P1/隔离核 | first=0 | first=1 |\n|---|---:|---:|---:|---:|\n'
    for kind, group in compared['groups'].items():
        report += (f"| {kind} | {group['vdot_gain']['median']:.6f} | "
                   f"{group['rvv_control']['median']:.6f} | {group['by_order']['0']:.6f} | "
                   f"{group['by_order']['1']:.6f} |\n")
    report += '\n比值>1表示隔离核该区间周期更少，<1表示更多；不与RVV/vdot内核比混淆。\n\n'
    report += '这是历史P1与当前隔离核的同顺序进程中位数对比，不是同步随机化试验。代码/镜像/ref/运行参数一致，保留双方所有原始样本及稳定性警告；不做样本筛选，不外推为FU延迟、应用或PPA收益。\n\n'
    report += 'P1稳定性警告：\n\n' + ('\n'.join('- ' + w for w in compared['before']['series']['warnings']) or '无。') + '\n'
    report += '\n## 队列恢复记录\n\n检查点：`' + prefix.name + '.state.json`。\n\n'
    report += ('\n'.join('- 基础设施中断尝试（没有完整退出记录，不算正式样本）：`' + s['log'] + '`'
                         for s in state.get('interrupted', [])) or '没有基础设施中断重跑。') + '\n'
    outputs = {
        prefix.with_name(prefix.name + '-smoke-audit.json'):
            json.dumps(dict(runs=smoke, series=bench.aggregate(smoke)), indent=2) + '\n',
        prefix.with_name(prefix.name + '-comparison.json'): json.dumps(compared, indent=2) + '\n',
        prefix.with_name(prefix.name + '-report.json'): json.dumps(data, indent=2) + '\n',
        report_path: report,
    }
    for path, content in outputs.items():
        if path.exists():
            bench.need(path.read_text() == content, f'refusing to alter existing evidence: {path}')
        else:
            exclusive(path, content)
    strict = 0 if data['series']['stable'] else 3
    print(f'[data/report PASS] strict_stability_exit={strict} report={report_path}', flush=True)
    return strict, report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path, help='exact existing queue .state.json')
    args = parser.parse_args()
    os.chdir(ROOT)
    locks = []
    for name in ('isolation-performance.lock', 'benchmark-series.lock'):
        handle = (ROOT / 'stage3/logs' / name).open('a')
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locks.append(handle)
    emu = ROOT.parent / 'XiangShan/build/operand-isolation/emu'
    ref = ROOT.parent / 'NEMU/build/riscv64-nemu-interpreter-so'
    images = {p: ROOT / f'stage3/vdot-bench-p0/build/cie2026-stage3-vdot-bench-v3-{p}-riscv64-xs.bin'
              for p in ('smoke', 'full')}
    if args.resume:
        state_path = args.resume.resolve()
        bench.need(state_path.parent == ROOT / 'stage3/logs', 'checkpoint outside queue log directory')
        state = json.loads(state_path.read_text())
        prefix = ROOT / 'stage3/logs' / state['id']
        bench.need(re.fullmatch(r'\d{8}T\d{6}-\d+-isolation-perf', state['id']), 'invalid queue identity')
    else:
        queue_id = datetime.datetime.now().strftime('%Y%m%dT%H%M%S') + f'-{os.getpid()}-isolation-perf'
        prefix = ROOT / 'stage3/logs' / queue_id
        state_path = prefix.with_name(prefix.name + '.state.json')
        bench.need(not state_path.exists(), 'queue collision')
        for name, expected in EXPECTED.items():
            path = emu if name == 'emu' else ref if name == 'ref' else images[name]
            bench.need(digest(path) == expected, f'preflight identity mismatch: {name}')
        baseline = comparison.gather(BASELINE)
        bench.need(baseline['runs'][0]['artifacts']['emu'] ==
                   'dfb6d9af4c84f490ae2b5ea9ab42553ee59860d980cc71fb82f9e8219c2176a5', 'not P1 baseline')
        subprocess.run(['sha256sum', '-c', 'build/operand-isolation/source-before.sha256'],
                       cwd=ROOT.parent / 'XiangShan', check=True)
        subprocess.run(['sha256sum', '-c', 'stage2/logs/20261006T021301-isolation-regression.sha256'], check=True)
        files = [emu, ref, BASELINE, Path(__file__).resolve(),
                 ROOT / 'stage3/reports/P1核正式性能实测报告.md']
        for run in baseline['runs']:
            files.append(Path(run['log']))
        files += list(images.values()) + [p.with_suffix('.elf') for p in images.values()]
        files += [ROOT / n for n in (
            'scripts/run-vdot-bench.sh', 'scripts/run-vdot-bench-series.sh',
            'stage3/tests/analyze-bench.py', 'stage3/tests/render-bench-report.py',
            'stage3/tests/compare-bench-cores.py', 'stage3/tests/prepare-runtime-order.py',
            'stage3/tests/test-isolation-performance.py',
            'stage3/vdot-bench-p0/main.c', 'stage3/vdot-bench-p0/bench.S',
            'stage3/vdot-bench-p0/Makefile', 'stage3/vdot-bench-p0/runtime-config.S',
            'stage3/vdot-bench/main.c', 'stage3/vdot-bench/bench.S',
            '../XiangShan/build/emu', '../XiangShan/build/p1-oldvd/emu',
            '../XiangShan/src/main/scala/xiangshan/backend/fu/wrapper/VIMacU.scala',
            '../XiangShan/src/main/scala/xiangshan/backend/fu/vector/VDot8.scala',
            '../XiangShan/src/main/scala/xiangshan/backend/decode/DecodeUnitComp.scala')]
        state = dict(id=queue_id, frozen={str(p.resolve()): digest(p) for p in files}, slots=[],
                     status='RUNNING', note='two smoke then four full; first 0/1, all samples retained')
        save(state_path, state)
    print(f'[checkpoint] {state_path}', flush=True)
    check_frozen(state)
    plan = [('smoke', i) for i in range(2)] + [('full', i) for i in range(4)]
    bench.need(len(state['slots']) <= len(plan), 'invalid slot count')
    for slot, (profile, index) in zip(state['slots'], plan):
        bench.need((slot['profile'], slot['index']) == (profile, index), 'checkpoint order changed')
        validate_slot(slot)
        bench.need(digest(slot['log']) == slot['log_sha256'], 'completed log changed')
    recover_pending(state, state_path)
    for profile, index in plan[len(state['slots']):]:
        check_frozen(state)
        if profile == 'full' and index == 0:
            smoke_summary = bench.aggregate([validate_slot(s) for s in state['slots']])
            print('[two smoke data PASS] warnings=' + json.dumps(smoke_summary['warnings']), flush=True)
        attempt = datetime.datetime.now().strftime('%Y%m%dT%H%M%S') + f'-{os.getpid()}'
        run_id = prefix.name + f'-{profile}-run{index}-{attempt}'
        summary = ROOT / 'stage3/logs' / (run_id + '-bench.log')
        log = summary.with_name(summary.name.replace('.log', '.full.log'))
        slot = dict(profile=profile, index=index, summary=str(summary), log=str(log))
        state['pending'] = slot
        save(state_path, state)
        env = dict(os.environ, VDOT_EMU=str(emu), VDOT_REF_SO=str(ref),
                   VDOT_IMAGE=str(images[profile]), VDOT_RUNTIME_ELF=str(images[profile].with_suffix('.elf')),
                   VDOT_RUNTIME_FIRST=str(index % 2), VDOT_BENCH_RUN_ID=run_id)
        env.pop('VDOT_BENCH_RESULT_FILE', None)
        env.pop('VDOT_BENCH_RUNNER_SNAPSHOT', None)
        env.pop('VDOT_BENCH_REPO_DIR', None)
        print(f'[slot start] {profile} {index} first={index % 2}', flush=True)
        subprocess.run(['bash', 'scripts/run-vdot-bench.sh'], env=env, check=True)
        run = validate_slot(slot)
        slot['log_sha256'] = run['log_sha256']
        state['slots'].append(slot)
        del state['pending']
        save(state_path, state)
        print(f'[slot PASS] {profile} {index} completed={len(state["slots"])}/6', flush=True)
    check_frozen(state)
    strict, report = write_reports(state, prefix)
    check_frozen(state)
    state.update(status='DATA_REPORT_PASS', strict_stability_exit=strict, report=str(report))
    save(state_path, state)
    with (ROOT / 'stage2/logs/operations.tsv').open('a') as stream:
        stream.write(f'{datetime.datetime.now().astimezone().isoformat()}\tisolation-performance-strict-stability\t{strict}\t{state_path}\n')
    print(f'[queue PASS] {state_path}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'isolation performance STOP: {error}')
