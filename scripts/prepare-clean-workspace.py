#!/usr/bin/env python3
"""从发布目录和指定依赖基线准备独立工作区，不复制任何编译产物。"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare(destination, mirror=None, resume=False):
    destination = destination.resolve()
    if destination.exists() and not resume:
        raise ValueError('目标已存在，请使用新的空目录：' + str(destination))
    if resume and (destination / ROOT.name).exists():
        raise ValueError('作品目录已复制，不能重复准备；请检查先前日志')
    lock = json.loads((ROOT / 'manifest/release-dependencies.json').read_text())
    destination.mkdir(parents=True, exist_ok=resume)
    log = destination / 'prepare-workspace.log'
    def run(args, cwd=destination):
        with log.open('a') as stream:
            stream.write(json.dumps({'cwd': str(cwd), 'command': args}, ensure_ascii=False) + '\n')
            stream.flush()
            result = subprocess.run(args, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            raise ValueError('依赖准备失败，请查日志：' + str(log))
    records = []
    for repo in lock['repositories']:
        rel = Path(repo['path'])
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('依赖路径越界')
        target = destination / rel
        source = str(mirror.resolve() / rel) if mirror else repo['url']
        print('[prepare repository]', rel, flush=True)
        if not (target / '.git').exists():
            run(['git', 'clone', '--no-hardlinks', '--no-checkout', '--', source, str(target)])
        elif not resume:
            raise ValueError('依赖目标已存在：' + str(rel))
        else:
            dirty = subprocess.check_output(['git', '-C', str(target), 'status', '--porcelain',
                                             '--untracked-files=all', '--ignore-submodules=all'], text=True)
            if dirty:
                raise ValueError('恢复时依赖源码已修改：' + str(rel))
        run(['git', '-C', str(target), 'remote', 'set-url', 'origin', repo['url']])
        available = subprocess.run(['git', '-C', str(target), 'cat-file', '-e', repo['commit'] + '^{commit}'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not available:
            run(['git', '-C', str(target), 'fetch', '--depth=1', 'origin', repo['commit']])
        run(['git', '-C', str(target), 'checkout', '--detach', repo['commit']])
        actual = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != repo['commit']:
            raise ValueError('依赖版本不一致：' + str(rel))
        # softfloat 的 build/ 存放受版本管理的 Makefile，不能按目录名判为产物。
        records.append({'path': str(rel), 'commit': actual, 'source': 'local object mirror' if mirror else 'upstream'})
    # 从已经筛选好的发布树复制作品，不从原开发目录收集产物。
    project = destination / ROOT.name
    shutil.copytree(ROOT, project, ignore=shutil.ignore_patterns('.git', '__pycache__', 'build', '*.lock'))
    env = '''#!/usr/bin/env bash
export XS_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export NOOP_HOME="$XS_PROJECT_ROOT/XiangShan"
export NEMU_HOME="$XS_PROJECT_ROOT/NEMU"
export AM_HOME="$XS_PROJECT_ROOT/nexus-am"
export DRAMSIM3_HOME="$XS_PROJECT_ROOT/DRAMsim3"
'''
    (destination / 'env.sh').write_text(env)
    for rel, patch in [('XiangShan', 'xiangshan-vdot-sew16-fixed8.patch'),
                       ('NEMU', 'nemu-vdot-sew16-fixed8.patch')]:
        file = project / 'stage2/patches' / patch
        run(['git', '-C', str(destination / rel), 'apply', '--check', str(file)])
        run(['git', '-C', str(destination / rel), 'apply', str(file)])
    run(['bash', str(project / 'scripts/prepare-vdot-difftest.sh'), '--apply'])
    result = {'status': 'PREPARED', 'repositories': records, 'project': str(project),
              'compiled_artifacts_copied': False, 'patches_applied': 3,
              'scope': 'new source checkout, same host toolchain; not a new OS/container'}
    (destination / 'prepare-workspace.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'repositories': len(records), 'project': str(project)}, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destination', type=Path, required=True)
    p.add_argument('--source-workspace', type=Path, help='可选的本地只读 Git 对象来源，避免重复下载')
    p.add_argument('--resume', action='store_true', help='只恢复作品目录复制之前的依赖检出，拒绝已有源码修改')
    a = p.parse_args()
    try:
        prepare(a.destination, a.source_workspace, a.resume)
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        print('[workspace prepare FAIL]', e, file=sys.stderr)
        raise SystemExit(1)
