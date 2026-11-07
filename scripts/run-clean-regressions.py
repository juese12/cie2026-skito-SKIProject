#!/usr/bin/env python3
"""整核构建结束后自动执行独立目录回归；长进程每半小时记录一次状态。"""
import argparse
import concurrent.futures
import ctypes
import datetime
import gzip
import json
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
LOCK = threading.Lock()
STATE_PATH = WORKSPACE / 'clean-regressions.state.json'
STATE = {'status': 'WAITING_FOR_CORE', 'monitor_interval_seconds': 1800, 'steps': {}}


def stamp():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def save():
    with LOCK:
        STATE['updated'] = stamp()
        temp = STATE_PATH.with_suffix('.tmp')
        temp.write_text(json.dumps(STATE, ensure_ascii=False, indent=2) + '\n')
        temp.replace(STATE_PATH)


def wait_core(path):
    # CLOSE_WRITE 在记录管道关闭时触发，不需要高频读取进度日志。
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.inotify_init1(0)
    if fd < 0 or libc.inotify_add_watch(fd, str(path).encode(), 0x00000008) < 0:
        raise OSError('无法监听整核构建日志')
    try:
        while True:
            raw = path.read_text(errors='replace')
            if '[sew16 build COMPLETE]' in raw and re.search(r'\[exit\] 0\s*$', raw):
                return
            final = re.search(r'\[exit\] (\d+)\s*$', raw)
            if final and final[1] != '0':
                raise RuntimeError('整核构建失败，退出 ' + final[1])
            ready = select.select([fd], [], [], 1800)[0]
            if ready:
                os.read(fd, 4096)
            else:
                print('[30-minute check]', stamp(), 'waiting for core build', flush=True)
    finally:
        os.close(fd)


def run(name, command, cwd=ROOT):
    logs = ROOT / 'stage2/logs/clean-reproduction'
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / (name + '.full.log')
    if log.exists():
        raise RuntimeError('运行记录已存在，拒绝覆盖：' + str(log))
    STATE['steps'][name] = {'status': 'RUNNING', 'started': stamp(), 'command': command, 'log': str(log)}
    save()
    print('[start]', name, stamp(), flush=True)
    start = time.monotonic()
    with log.open('x') as stream:
        stream.write('[cwd] ' + str(cwd) + '\n[command] ' + json.dumps(command) + '\n')
        stream.flush()
        process = subprocess.Popen(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        while True:
            try:
                code = process.wait(timeout=1800)
                break
            except subprocess.TimeoutExpired:
                print('[30-minute check]', stamp(), name, 'still running', flush=True)
        stream.write(f'\n[process exit] {code}\n')
    STATE['steps'][name].update(status='PASS' if code == 0 else 'FAIL',
                               completed=stamp(), elapsed_seconds=round(time.monotonic() - start, 3), exit=code)
    save()
    print('[finish]', name, 'exit', code, stamp(), flush=True)
    if code:
        raise RuntimeError(name + ' failed; see ' + str(log))
    return log


def boot(name, image, marker):
    emu = WORKSPACE / 'XiangShan/build/sew16-fixed8/emu'
    ref = WORKSPACE / 'NEMU/build/sew16/riscv64-nemu-interpreter-so'
    log = run(name, [str(emu), '--diff=' + str(ref), '-i', str(ROOT / image),
                     '--max-cycles=300000', '--seed=101'])
    raw = log.read_text(errors='replace')
    if not all(s in raw for s in ('Difftest enabled', 'HIT GOOD TRAP', marker)) or \
       any(s in raw for s in ('FAIL', 'HIT BAD TRAP', 'ABORT', 'different at pc')):
        raise RuntimeError(name + ': missing required architectural success')


def basics_and_performance():
    boot('hello', 'stage1/hello-xiangshan/build/cie2026-stage1-hello-riscv64-xs.bin', 'hello xiangshan, I am skito,')
    boot('vadd', 'stage1/vector-add/build/cie2026-stage1-vector-add-riscv64-xs.bin', 'vector-add PASS')
    for first in (0, 1):
        prefix = ROOT / 'stage3/logs/clean-reproduction-perf'
        code = ('from pathlib import Path; import common as C; '
                f'C.run(Path({str(prefix)!r}), "smoke{first}", "new", 1, {first}, 1, 0x56444f54, 101)')
        run('performance-smoke' + str(first), [sys.executable, '-c', code], ROOT / 'stage3/sew16-perf')


def full_extension():
    coordinator = run('sew16-regression', ['bash', 'scripts/vdot-step.sh', 'clean-sew16-regression',
                                         'bash', 'scripts/run-vdot-sew16.sh'])
    text = coordinator.read_text()
    relative = re.search(r'\[sew16 regression COMPLETE\] (.+)', text)
    if not relative:
        raise RuntimeError('缺少完整扩展日志路径')
    raw_log = Path(relative[1].strip())
    run('sew16-audit', [sys.executable, 'stage2/sew16/check-core.py', str(raw_log),
                       '--coordinator', str(coordinator), '--out',
                       str(ROOT / 'stage2/logs/clean-reproduction/sew16-audit.json')])


def find_module_wave(xs):
    roots = [xs / 'test_run_dir', xs / 'out/xiangshan/test/testOnly.dest/sandbox/test_run_dir']
    waves = sorted({p.resolve() for root in roots for p in root.glob('*/VDotIntegrationHarness.vcd')})
    if len(waves) != 1:
        raise RuntimeError('不能唯一确定新生成的混发模块波形：' + str(waves))
    return waves[0]


def module_wave(reuse=False):
    if not reuse:
        run('module-mixed', ['mill', '-i', '-Djvm-xmx=3G', '-Djvm-xss=16m',
                            'xiangshan.test.testOnly', 'xiangshan.backend.fu.vector.VDotIntegrationTest',
                            '--', '-z', 'preserve randomized'], WORKSPACE / 'XiangShan')
    wave = find_module_wave(WORKSPACE / 'XiangShan')
    run('module-isolation-audit', [sys.executable, 'stage2/sew16/check-isolation.py', str(wave),
                                 '--out', str(ROOT / 'stage2/logs/clean-reproduction/module-isolation.json')])
    dest = ROOT / 'stage2/logs/clean-reproduction/mixed-module.vcd.gz'
    with wave.open('rb') as src, gzip.open(dest, 'xb') as target:
        shutil.copyfileobj(src, target)
    STATE['module_wave'] = {'raw': str(wave), 'compressed': str(dest), 'bytes': dest.stat().st_size}
    save()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wait-for-core', type=Path, required=True)
    p.add_argument('--finish-wave-only', action='store_true', help='仅从已全部通过的运行中恢复波形收集，不重跑测试')
    a = p.parse_args()
    os.environ.update(XS_PROJECT_ROOT=str(WORKSPACE), NOOP_HOME=str(WORKSPACE/'XiangShan'),
                      NEMU_HOME=str(WORKSPACE/'NEMU'), AM_HOME=str(WORKSPACE/'nexus-am'),
                      DRAMSIM3_HOME=str(WORKSPACE/'DRAMsim3'))
    if a.finish_wave_only:
        prior = json.loads(STATE_PATH.read_text())
        required = ('hello', 'vadd', 'sew16-regression', 'sew16-audit', 'contract-regression',
                    'performance-smoke0', 'performance-smoke1', 'module-mixed')
        if not all(prior['steps'].get(n, {}).get('status') == 'PASS' for n in required):
            p.error('先前功能、控制、性能或模块测试未全部通过，不能仅收集波形')
        for n in required:
            raw = Path(prior['steps'][n]['log']).read_text(errors='replace')
            if not re.search(r'\[process exit\] 0\s*$', raw):
                p.error('先前真实退出记录不完整：' + n)
        archived = WORKSPACE / 'clean-regressions.failed-wave-path.json'
        with archived.open('x') as stream:
            json.dump(prior, stream, ensure_ascii=False, indent=2)
        STATE.clear(); STATE.update(prior)
        STATE.pop('error', None)
        STATE['status'] = 'WAVE_COLLECTION_RUNNING'
        save()
        module_wave(reuse=True)
        STATE['status'] = 'PASS'
        STATE['scope'] = 'same-host clean builds and architectural regressions; module VCD is not CPU commit proof'
        STATE['collection_recovery'] = 'Mill sandbox wave discovered and reused; no tests or emu rerun'
        save()
        print('[clean regressions PASS; existing wave recovered]', stamp(), flush=True)
        return
    if STATE_PATH.exists():
        p.error('回归状态已经存在，拒绝重复运行')
    save()
    wait_core(a.wait_for_core.resolve())
    STATE['status'] = 'REGRESSIONS_RUNNING'
    save()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(basics_and_performance), pool.submit(full_extension),
                   pool.submit(run, 'contract-regression', ['bash', 'scripts/run-vdot-contract-tests.sh'])]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    # 模块波形另行采集，避免与整核回归争用内存。
    module_wave()
    STATE['status'] = 'PASS'
    STATE['scope'] = 'same-host clean source builds and new-core architectural regressions; module VCD is not CPU commit proof'
    save()
    print('[clean regressions PASS]', stamp(), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        STATE['status'] = 'FAIL'
        STATE['error'] = str(error)
        save()
        print('[clean regressions FAIL]', error, file=sys.stderr, flush=True)
        raise SystemExit(1)
