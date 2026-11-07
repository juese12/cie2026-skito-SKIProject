#!/usr/bin/env python3
"""解析中文文件名，并严格核对中文注释版本与原实验文件的对应关系。"""
import ast
import hashlib
import json
from pathlib import Path
import re


_CACHE = {}
REVIEW_ADAPTERS = {
    'scripts/cleanup-v01-p1-waves-20261026.py',
    'scripts/check-documentation.py',
    'scripts/complete-vdot-isolation-performance.py',
    'stage3/sew16-perf/common.py',
    'stage3/sew16-perf/review.py',
    'stage3/tests/test-review-document-edition.py',
    'stage2/e16-events/check-experiment.py',
    'stage2/patches/xiangshan-vdot-sew16-fixed8.patch',
    'stage2/patches/nemu-vdot-sew16-fixed8.patch',
}


def ledger(root):
    """按文件修改时间缓存修订记录，测试临时目录没有记录时返回空集合。"""
    path = Path(root)/'manifest/chinese-edition-20261102.json'
    if not path.exists():
        return {'documents': {}, 'code': {}}
    stamp = (path.stat().st_mtime_ns, path.stat().st_size)
    cached = _CACHE.get(path)
    if cached is None or cached[0] != stamp:
        _CACHE[path] = (stamp, json.loads(path.read_text()))
    return _CACHE[path][1]


def _record(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    data = ledger(root)
    if path.is_relative_to(root):
        name = str(path.relative_to(root))
        for original, entry in data['documents'].items():
            if name in (original, entry['new_path']):
                return root/entry['new_path'], root/original, entry, True
    if path.is_relative_to(root.parent):
        entry = data['code'].get(str(path.relative_to(root.parent)))
        if entry is not None:
            return path, path, entry, False
    return path, path, None, False


def resolve_path(root, path):
    """将已登记的历史文档路径映射到当前中文文件名。"""
    return _record(root, path)[0]


def _document_before_review(root, current, content):
    """核对交付稿后还原整理前内容，供既有实验和改名记录继续逐层复核。"""
    path=Path(root)/'manifest/reviewer-delivery-edition.json'
    if not path.exists() or not current.is_relative_to(Path(root).resolve()):
        return content
    stamp=(path.stat().st_mtime_ns,path.stat().st_size)
    cached=_CACHE.get(path)
    if cached is None or cached[0]!=stamp:
        _CACHE[path]=(stamp,json.loads(path.read_text()))
    entry=_CACHE[path][1]['documents'].get(str(current.relative_to(Path(root).resolve())))
    if entry is None:
        return content
    before=entry['before_content'].encode()
    if hashlib.sha256(before).hexdigest()!=entry['before_sha256']:
        raise ValueError('交付稿整理前记录不完整：'+str(current))
    if content!=entry['after_content'].encode():
        raise ValueError('当前交付稿与已登记内容不一致：'+str(current))
    return before


def _python_structure(text):
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    value.value = '说明'
    return ast.dump(tree, include_attributes=False)


def _code_without_comments(text, suffix):
    if suffix == '.py':
        return _python_structure(text)
    if suffix == '.sh':
        return re.sub(r'(?m)^(\s*)#(?!\!)[^\n]*', r'\1#', text)
    pattern = r'(?P<string>"""[\s\S]*?"""|"(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27)|(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)'
    if suffix == '.S':
        pattern += r'|(?P<asm>#[^\n]*)'
    def keep_code(match):
        if match.lastgroup == 'string':
            return match.group()
        if match.lastgroup == 'asm':
            prefix = text[text.rfind('\n', 0, match.start())+1:match.start()]
            if not prefix.strip() and re.match(r'#\s*(?:if|ifdef|ifndef|elif|else|endif|define|include|undef|error|pragma|line)\b', match.group()):
                return match.group()
        return ' '
    return re.sub(pattern, keep_code, text)


def prior_view(root, path):
    """先严格核对当前原件，再返回中文化之前的内容及其历史路径。"""
    current, original, entry, is_document = _record(root, path)
    if entry is None:
        return current, original, current.read_bytes()
    before = entry['before_content'].encode()
    if hashlib.sha256(before).hexdigest() != entry['before_sha256']:
        raise ValueError('中文化前记录不完整：'+str(original))
    actual=current.read_bytes()
    if is_document:actual=_document_before_review(root,current,actual)
    if actual != entry['after_content'].encode():
        raise ValueError('当前文件与已登记中文版本不一致：'+str(current))
    if not is_document and entry['edit_kind'] == 'review_compatibility':
        if not current.is_relative_to(Path(root).resolve()) or str(current.relative_to(Path(root).resolve())) not in REVIEW_ADAPTERS:
            raise ValueError('该文件不属于文档复核适配范围：'+str(current))
    if not is_document and entry['edit_kind'] != 'review_compatibility':
        intermediate = entry.get('comment_edition', entry['after_content'])
        if _code_without_comments(entry['before_content'], current.suffix) != _code_without_comments(intermediate, current.suffix):
            raise ValueError('注释修改包含可执行代码变化：'+str(current))
        expected = intermediate
        names = {(Path(old).name, Path(value['new_path']).name)
                 for old, value in ledger(root)['documents'].items()}
        for old, new in entry.get('path_replacements', []):
            # 路径修订只允许同目录中的已登记 Markdown 改名，不能夹带代码。
            if not all(re.fullmatch(r'[\w./-]+\.md', value) for value in (old, new)):
                raise ValueError('路径修订包含非文件名内容：'+str(current))
            if Path(old).parent != Path(new).parent or (Path(old).name, Path(new).name) not in names:
                raise ValueError('路径修订不属于已登记文档改名：'+str(current))
            expected = expected.replace(old, new)
        if expected != entry['after_content']:
            raise ValueError('文档路径更新不符合登记替换：'+str(current))
    return current, original, before


def matches_expected(root, path, expected):
    """只接受原文件本身，或当前内容完全匹配的已登记中文修订版。"""
    path = Path(path)
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
        return True
    if _record(root, path)[2] is None:
        return False
    try:
        return hashlib.sha256(prior_view(root, path)[2]).hexdigest() == expected
    except (ValueError, OSError, SyntaxError):
        return False
