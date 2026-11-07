#!/usr/bin/env python3
"""核对评审正文、边界图的数据范围及内部原件，不执行处理器。"""
import copy
import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('current_boundary',ROOT/'stage2/tests/render-current-boundaries.py')
B=importlib.util.module_from_spec(spec);spec.loader.exec_module(B)


def visible(text):
    return re.sub(r'\]\([^)]+\)','](附件)',text)


class ReviewerDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.edition=json.loads((ROOT/'manifest/reviewer-delivery-edition.json').read_text())
        self.cache=json.loads((ROOT/'stage2/reports/figures/current-boundary/boundary-evidence-excerpts.json').read_text())

    def test_visible_documents_have_no_calendar_dates(self):
        pattern=re.compile(r'20\d{2}[-/]\d{1,2}[-/]\d{1,2}|20\d{6}(?:T\d{6})?|\d{1,2}\s*月\s*\d{1,2}\s*日')
        for path in ROOT.rglob('*.md'):
            if not any(x in ('private','.git') for x in path.relative_to(ROOT).parts):
                self.assertIsNone(pattern.search(visible(path.read_text())),str(path))

    def test_original_timeline_is_retained_outside_delivery_text(self):
        archive=json.loads((ROOT/self.edition['archive']).read_text())
        self.assertEqual(len(archive['documents']),63)
        for name,entry in self.edition['documents'].items():
            self.assertEqual(entry['before_content'],archive['documents'][name]['content'],name)
            self.assertEqual((ROOT/name).read_text(),entry['after_content'],name)
        for folder in ('stage2/reports','stage3/reports'):
            for path in (ROOT/folder).glob('*.md'):
                self.assertNotRegex(path.read_text(),r'(?m)^## (?:操作日志|操作记录|本轮操作记录|实际进度)$')

    def test_complete_and_partial_boundary_evidence_are_distinct(self):
        B.validate_cache(self.cache)
        cases={x['expected']:x for x in self.cache['arithmetic']}
        self.assertTrue(cases[131072]['output_complete'])
        self.assertTrue(cases[0]['output_complete'])
        self.assertFalse(cases[-130048]['output_complete'])
        doc=(ROOT/'stage2/reports/固定八项e8e16实施与验收报告.md').read_text()
        self.assertEqual(len(re.findall(r'!\[[^\]]*\]\(',doc)),6)
        self.assertIn('不能用保持的旧输出证明',doc)
        self.assertIn('现有归档没有对应的完整逐级波形',doc)

    def test_stale_minimum_output_cannot_be_promoted_to_completion(self):
        bad=copy.deepcopy(self.cache)
        next(x for x in bad['arithmetic'] if x['expected']==-130048)['output_complete']=True
        with self.assertRaises(AssertionError):B.validate_cache(bad)

    def test_invalid_output_configuration_cannot_be_relabelled(self):
        bad=copy.deepcopy(self.cache);c=bad['illegal']
        out=next(x['post'] for x in c['samples'] if x['edge']==c['output_edge'])
        out[B.F+'outVConfig_vl']=8
        with self.assertRaises(AssertionError):B.validate_cache(bad)

    def test_formal_numeric_tables_are_preserved(self):
        def numbers(text):
            rows=[]
            for line in text.splitlines():
                if not line.startswith('|'):continue
                values=[v.strip(' `') for v in line.strip('|').split('|')]
                numeric=[v for v in values if re.fullmatch(r'[+−\-]?\d[\d., %～~×+-]*',v)]
                if numeric:rows.append(numeric)
            return rows
        names=['e8e16正式性能分析报告v4.md','隔离核正式性能分析报告v3.md','P1核正式性能实测报告.md',
               'vdot正式性能实测报告v2.md','原始核正式性能实测报告v3.md','vdot原始版本等价基线与性能实测.md']
        for name in names:
            entry=self.edition['documents']['stage3/reports/'+name]
            self.assertEqual(numbers(entry['before_content']),numbers(entry['after_content']),name)


if __name__=='__main__':unittest.main()
