#!/usr/bin/env python3
"""只读检查文档链接、格式及历史材料保护记录。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
_edition_spec = importlib.util.spec_from_file_location('chinese_edition', ROOT/'scripts/chinese-edition.py')
EDITION = importlib.util.module_from_spec(_edition_spec)
_edition_spec.loader.exec_module(EDITION)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def matches_recorded_file(root, path, expected, review_edition=False):
    """默认严格核对；仅接受有完整记录的文档修订版本。"""
    root, path = Path(root).resolve(), Path(path).resolve()
    if path.exists() and digest(path) == expected:
        return True
    if not review_edition:
        return False
    try:
        current, original, content = EDITION.prior_view(root, path)
    except (OSError, ValueError, SyntaxError):
        return False
    if hashlib.sha256(content).hexdigest() == expected:
        return True
    path = original
    if path.suffix != '.md' or not path.is_relative_to(root):
        return False
    editorial_ledger = root / 'manifest/document-review-edition-20261101.json'
    if editorial_ledger.exists():
        edition = json.loads(editorial_ledger.read_text())['documents'].get(str(path.relative_to(root)))
        if edition is not None:
            if content != edition['review_content'].encode('utf-8'):
                return False
            prior = edition['original_content'].encode('utf-8')
            if hashlib.sha256(prior).hexdigest() != edition['original_sha256']:
                return False
            if hashlib.sha256(prior).hexdigest() == expected:
                return True
            content = prior
    version_ledger = root / 'manifest/document-version-entry-20261026.json'
    if version_ledger.exists():
        version = json.loads(version_ledger.read_text())['documents'].get(str(path.relative_to(root)))
        if version is not None:
            prefix = version['prefix'].encode('utf-8')
            if prefix and content.startswith(prefix):
                content = content[len(prefix):]
                if hashlib.sha256(content).hexdigest() != version['prior_sha256']:
                    return False
                if hashlib.sha256(content).hexdigest() == expected:
                    return True
    ledger = root / 'manifest/document-review-edition-20261020.json'
    if not ledger.exists():
        return False
    entry = json.loads(ledger.read_text())['documents'].get(str(path.relative_to(root)))
    if entry is None:
        return False
    original = entry['original_content'].encode('utf-8')
    return (hashlib.sha256(original).hexdigest() == expected
            and content == entry['review_content'].encode('utf-8'))


def check(root, review_edition=False):
    root = Path(root).resolve()
    files = sorted(p for p in root.rglob('*.md')
                   if not any(part in ('private', '.git') for part in p.relative_to(root).parts))
    assert files, 'no Markdown files discovered'
    for path in files:
        content = path.read_text()
        assert content.count('```') % 2 == 0, f'unclosed code fence: {path}'
        assert all(line.rstrip() == line for line in content.splitlines()), f'trailing whitespace: {path}'
        for url in re.findall(r'\]\(([^)]+)\)', content):
            url = url.strip('<>').split('#')[0]
            if not url or '://' in url or url.startswith('mailto:'):
                continue
            assert (path.parent / url).exists(), f'missing local link: {path}: {url}'
    manifest = root / 'manifest/document-consolidation-20261006.json'
    protected = json.loads(manifest.read_text())['protected_md']
    assert protected, 'empty evidence protection list'
    for name, expected in protected.items():
        assert matches_recorded_file(root, root / name, expected, review_edition), \
            f'protected document changed: {name}'
    return {'markdown_files': len(files), 'protected_documents': len(protected)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--review-edition', action='store_true',
                        help='validate recorded text editions and exact current-version navigation prefixes')
    args = parser.parse_args()
    print('[documentation PASS]', json.dumps(check(args.root, args.review_edition)), flush=True)
    # 原队列还记录实际二进制、源码和日志，不能只检查 Markdown。
    state = args.root / 'stage3/logs/20261006T060358-16-isolation-perf.state.json'
    frozen = json.loads(state.read_text())['frozen']
    for name, expected in frozen.items():
        assert matches_recorded_file(args.root, name, expected, args.review_edition), \
            f'formal queue frozen artifact changed: {name}'
    label = 'review edition and original experiment inputs' if args.review_edition else 'formal queue frozen'
    print(f'[{label} PASS]', len(frozen), flush=True)


if __name__ == '__main__':
    main()
