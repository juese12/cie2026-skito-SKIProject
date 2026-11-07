#!/usr/bin/env python3
"""筛选发布源码、评审图文和可复算数据，拒绝复制历史核及完整波形。"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {'.py', '.sh', '.c', '.h', '.S', '.s', '.scala', '.sc', '.patch', '.mk', '.ld', '.md'}
ARCHIVE_NOTE = 'manifest/开发归档说明.md'


def source_patch(path):
    """将讲稿中的依赖源码链接映射到包内可交付的整合补丁。"""
    path = path.resolve()
    if not path.is_file():
        return None
    for repository, prefix, suffixes, patch in (
        ('XiangShan', 'src/main/scala/xiangshan', {'.scala'}, 'xiangshan-vdot-sew16-fixed8.patch'),
        ('NEMU', 'src/isa/riscv64', {'.c', '.h'}, 'nemu-vdot-sew16-fixed8.patch'),
    ):
        dependency = (ROOT.parent / repository / prefix).resolve()
        if path.is_relative_to(dependency) and path.suffix in suffixes:
            return ROOT / 'stage2/patches' / patch
    return None


def allowed(path):
    rel = path.relative_to(ROOT)
    if path.name == 'my_submission.txt' or path.name.startswith('.env'):
        return False
    if any(s in ('.git', 'build', 'private', '__pycache__') or s.startswith('vdot-run.') for s in rel.parts):
        return False
    if path.suffix in ('.vcd', '.fst', '.fsdb', '.bin', '.elf', '.a', '.o') or path.name.endswith('.vcd.gz'):
        return False
    if path.is_file():
        with path.open('rb') as stream:
            if stream.read(4) == b'\x7fELF':
                return False
    return True


def export(destination):
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(ROOT):
        raise ValueError('发布目标必须是作品目录之外的全新目录')
    selected = {}
    def add(path, role):
        path = path.resolve()
        if path.is_relative_to(ROOT) and path.is_file() and allowed(path):
            selected.setdefault(path, role)
    for path in ROOT.rglob('*'):
        if not path.is_file() or not allowed(path):
            continue
        rel = path.relative_to(ROOT)
        if 'logs' in rel.parts:
            continue
        if path.suffix in SOURCE_SUFFIXES or path.name in ('Makefile', '.gitignore'):
            add(path, 'source/documentation')
        elif rel.parts[0] == 'manifest' or 'figures' in rel.parts or path.suffix in ('.png', '.svg'):
            add(path, 'manifest/figure evidence')
        elif path.suffix == '.pdf':
            add(path, 'competition reference')
        elif path.suffix in ('.json', '.csv', '.txt'):
            add(path, 'protocol/test data')
    # 保留所有 Markdown 能直接访问的证据；大二进制、原始波形仍留开发归档。
    omitted = {}
    for md in [p for p in selected if p.suffix == '.md']:
        for match in re.finditer(r'\]\(([^)]+)\)', md.read_text()):
            url = match.group(1).strip('<>').split('#')[0]
            if not url or '://' in url or url.startswith('mailto:'):
                continue
            path = (md.parent / url).resolve()
            if not path.is_relative_to(ROOT):
                patch = source_patch(path)
                if patch is None:
                    raise ValueError('文档存在包外本地链接：' + str(md))
                add(patch, 'dependency source patch')
                continue
            if path.is_file() and not allowed(path):
                omitted[str(path.relative_to(ROOT))] = path.stat().st_size
            elif path.is_file():
                add(path, 'linked evidence')
            elif not path.is_dir():
                raise ValueError('原文档链接缺失：' + str(path))
    public = subprocess.check_output([
        sys.executable, str(ROOT / 'stage3/sew16-perf/review-public-data.py'),
        str(ROOT / 'stage3/logs/20261027T190338-sew16-perf4-full.results.json'), '--list-files'], text=True)
    for name in public.splitlines():
        add(ROOT / name, 'portable performance replay')
    destination.mkdir(parents=True)
    rows = []
    for source, role in sorted(selected.items()):
        rel = source.relative_to(ROOT)
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if target.suffix == '.md':
            def rewrite(match):
                url = match.group(1).strip('<>').split('#')[0]
                if not url or '://' in url or url.startswith('mailto:'):
                    return match.group()
                old = (source.parent / url).resolve()
                patch = source_patch(old) if not old.is_relative_to(ROOT) else None
                if patch is not None:
                    relative = Path(os.path.relpath(destination / patch.relative_to(ROOT), target.parent))
                    return '](' + relative.as_posix() + ')'
                if old.is_file() and not allowed(old):
                    relative = Path(os.path.relpath(destination / ARCHIVE_NOTE, target.parent))
                    return '](' + relative.as_posix() + ')'
                return match.group()
            target.write_text(re.sub(r'\]\(([^)]+)\)', rewrite, target.read_text()))
        rows.append({'path': str(rel), 'role': role, 'bytes': target.stat().st_size,
                     'public_link_adjustment': target.read_bytes() != source.read_bytes()})
    note = destination / ARCHIVE_NOTE
    note.parent.mkdir(exist_ok=True)
    note.write_text('# 开发归档说明\n\n源码发布包保留评审图件及选定原始数据。以下历史二进制或完整波形保存在开发工作区，未打入公开源码包。原文指向这些产物的附件链接在发布副本中改为本页；它们不是可在包内打开的原始附件。图件注明的实验版本和结论保持原范围。\n\n| 开发归档路径 | 字节数 |\n| --- | --- |\n' +
                    ''.join(f'| `{name}` | {size} |\n' for name, size in sorted(omitted.items())))
    result = {'schema': 1, 'status': 'EXPORTED', 'files': rows,
              'generated': [ARCHIVE_NOTE, 'manifest/public-release-files.json'],
              'omitted_linked_artifacts': omitted,
              'scope': 'source plus review figures and selected data; no historical core binaries/full waveforms'}
    (destination / 'manifest/public-release-files.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    # 公开副本只验链接和附件；历史完整审计需要开发归档中的真实二进制。
    for md in destination.rglob('*.md'):
        for raw in re.findall(r'\]\(([^)]+)\)', md.read_text()):
            url = raw.strip('<>').split('#')[0]
            if url and '://' not in url and not url.startswith('mailto:'):
                if not (md.parent / url).exists():
                    raise ValueError('发布副本文档链接缺失：' + str(md) + ': ' + url)
    print(json.dumps({'status': 'EXPORTED', 'files': len(rows),
                      'bytes': sum(r['bytes'] for r in rows), 'destination': str(destination),
                      'omitted_large_artifacts': len(omitted)}, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    try:
        export(a.out)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('[release export FAIL]', error, file=sys.stderr)
        raise SystemExit(1)
