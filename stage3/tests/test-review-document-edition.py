#!/usr/bin/env python3
"""检查评审文案和仅改页脚的图件，保留原实验数据。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
LEDGER=ROOT/'manifest/document-review-edition-20261101.json'
_edition_spec=importlib.util.spec_from_file_location('review_chinese_edition',ROOT/'scripts/chinese-edition.py')
EDITION=importlib.util.module_from_spec(_edition_spec)
_edition_spec.loader.exec_module(EDITION)
_figure_spec=importlib.util.spec_from_file_location('review_chinese_figures',ROOT/'stage3/tests/chinese-figure-edition.py')
FIGURES=importlib.util.module_from_spec(_figure_spec)
_figure_spec.loader.exec_module(FIGURES)


def digest(path):
    if (ROOT/'manifest/chinese-figure-edition.json').exists() and path.suffix in ('.svg','.png'):
        return FIGURES.original_digest(ROOT,path)
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


class ReviewerDocumentTests(unittest.TestCase):
    def setUp(self):self.ledger=json.loads(LEDGER.read_text())

    def test_all_reviewer_markdown_is_clean(self):
        forbidden=re.compile(r'哈希|指纹|冻结|\bsha(?:[-_ ]?(?:1|256|512))?\b|\bhash(?:es)?\b|\b[0-9a-f]{40,64}\b',re.I)
        files=[p for p in ROOT.rglob('*.md') if not any(x in ('private','.git') for x in p.relative_to(ROOT).parts)]
        self.assertGreaterEqual(len(files),62)
        for p in files:self.assertIsNone(forbidden.search(p.read_text()),str(p))

    def test_editions_keep_exact_originals_and_current_text(self):
        for name,entry in self.ledger['documents'].items():
            self.assertEqual(hashlib.sha256(entry['original_content'].encode()).hexdigest(),entry['original_sha256'],name)
            # 改名后的当前文档必须完全匹配登记版本，再核对其改名前内容。
            self.assertEqual(EDITION.prior_view(ROOT,ROOT/name)[2].decode(),entry['review_content'],name)

    def test_formal_method_data_and_warnings_not_edited(self):
        name='stage3/reports/20261027T190338-sew16-perf4-full-performance.md'
        entry=self.ledger['documents'][name]
        boundary='## 原始数据与复核'
        self.assertEqual(entry['original_content'].split(boundary)[0],entry['review_content'].split(boundary)[0])
        def warnings(text):return text.split('## 全部门槛警告')[1].split('\n## ')[0].strip()
        self.assertEqual(warnings(entry['original_content']),warnings(entry['review_content']))
        self.assertIn('strict=3',entry['review_content'])

    def test_historical_footer_editions_and_current_chinese_figures(self):
        self.assertEqual(len(self.ledger['figures']),5)
        for name,entry in self.ledger['figures'].items():
            source=ROOT/name;review=ROOT/entry['review']
            self.assertEqual(digest(source),entry['original_svg_sha256'])
            self.assertEqual(digest(source.with_suffix('.png')),entry['original_png_sha256'])
            original=FIGURES.original_svg(ROOT,source)
            reviewed=FIGURES.original_svg(ROOT,review)
            self.assertEqual(original.count(entry['old_footer']),1)
            self.assertEqual(reviewed.rstrip('\n'),original.replace(entry['old_footer'],entry['new_footer']).rstrip('\n'))
            self.assertEqual(digest(review),entry['review_svg_sha256'])
            self.assertEqual(digest(review.with_suffix('.png')),entry['review_png_sha256'])
            self.assertIsNotNone(ET.fromstring(review.read_text()))
            with review.with_suffix('.png').open('rb') as stream:self.assertEqual(stream.read(8),b'\x89PNG\r\n\x1a\n')
            self.assertNotRegex(review.read_text(),r'(?i)\bhash(?:es)?\b|\bsha(?:256)?\b')


if __name__=='__main__':unittest.main()
