#!/usr/bin/env python3
"""只读核对发布清单、文档附件和可选的完整性能数据复算。"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def check(root):
    root = root.resolve()
    manifest = json.loads((root / 'manifest/public-release-files.json').read_text())
    names = [r['path'] for r in manifest['files']]
    assert len(names) == len(set(names)), '发布清单存在重复项'
    for row in manifest['files']:
        path = (root / row['path']).resolve()
        assert path.is_relative_to(root) and path.is_file(), row['path']
        assert path.stat().st_size == row['bytes'], '大小与清单不一致：' + row['path']
        assert not any(t in ('.git', 'build', 'private') for t in Path(row['path']).parts), row['path']
        assert path.name != 'my_submission.txt', row['path']
        assert path.suffix not in ('.vcd', '.fst', '.fsdb', '.bin', '.elf', '.a', '.o'), row['path']
        assert not path.name.endswith('.vcd.gz'), row['path']
        with path.open('rb') as stream:
            assert stream.read(4) != b'\x7fELF', row['path']
    for name in manifest['generated']:
        assert (root / name).is_file(), name
    actual = {str(p.relative_to(root)) for p in root.rglob('*')
              if p.is_file() and '__pycache__' not in p.relative_to(root).parts}
    assert actual == set(names) | set(manifest['generated']), '发布目录有未登记文件或缺项'
    count = 0
    for md in root.rglob('*.md'):
        count += 1
        content = md.read_text()
        assert content.count('```') % 2 == 0, '代码段未闭合：' + str(md)
        assert all(x.rstrip() == x for x in content.splitlines()), '行尾空白：' + str(md)
        for raw in re.findall(r'\]\(([^)]+)\)', content):
            url = raw.strip('<>').split('#')[0]
            if url and '://' not in url and not url.startswith('mailto:'):
                path = (md.parent / url).resolve()
                assert path.is_relative_to(root) and path.exists(), str(md) + ': ' + url
    return {'status': 'PASS', 'listed_files': len(names), 'markdown_files': count,
            'listed_bytes': sum(r['bytes'] for r in manifest['files']),
            'omitted_large_artifacts': len(manifest['omitted_linked_artifacts']),
            'scope': 'release file sizes, source-only boundary and local document links; not original binary identity audit'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--with-performance-data', action='store_true')
    a = p.parse_args()
    assert not a.out.exists(), '结果文件已存在'
    result = check(a.root)
    exit_code = 0
    if a.with_performance_data:
        perf = a.out.with_name(a.out.stem + '.performance.json')
        assert not perf.exists(), '性能复核结果已存在'
        process = subprocess.run([sys.executable, 'scripts/review-submission.py', '--suite',
                                  'performance-data', '--out', str(perf.resolve())],
                                 cwd=a.root, text=True, capture_output=True)
        assert process.returncode in (0, 3), process.stderr or process.stdout
        data = json.loads(perf.read_text())
        assert data['status'] == 'PASS' and data['raw_sample_rows'] == 1920
        result['performance_data'] = {'status': data['status'], 'stable': data['stable'],
                                      'strict_exit': data['strict_exit'], 'samples': 1920,
                                      'warnings': len(data['warnings']), 'record': str(perf)}
        exit_code = data['strict_exit']
    with a.out.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (AssertionError, ValueError, OSError, KeyError) as error:
        print('[public release FAIL]', error, file=sys.stderr)
        raise SystemExit(1)
