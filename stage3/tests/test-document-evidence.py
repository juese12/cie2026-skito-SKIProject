#!/usr/bin/env python3
"""验证事件图的数据来源，不执行处理器仿真。"""
import copy
import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

spec=importlib.util.spec_from_file_location('document_evidence',Path(__file__).with_name('render-document-evidence.py'))
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


class DocumentEvidenceTests(unittest.TestCase):
    def test_vadd_count_and_data(self):
        text=(M.ROOT/M.VADD).read_text()
        self.assertEqual(len(M.vadd_records(text)),10)
        with self.assertRaises(ValueError):M.vadd_records(text.replace('result_lane0=60','result_lane0=61'))

    def test_vadd_missing_event(self):
        text=(M.ROOT/M.VADD).read_text()
        with self.assertRaises(ValueError):M.vadd_records('\n'.join(text.splitlines()[1:]))

    def test_dot_coverage_and_full_result(self):
        text=(M.ROOT/M.DOT).read_text()
        rows=M.dot_records(text)
        self.assertEqual(len(rows),29)
        with self.assertRaises(ValueError):M.dot_records(text.replace('0x24','0x100000024',1))

    def read(self,name):
        return M.json.loads((M.ROOT/name).read_text())

    def test_control_origin_is_tag_not_record_index(self):
        records=M.control_records(self.read(M.CONTROL))
        self.assertEqual(records[0]['origin']['tag'],77)
        self.assertEqual(records[0]['origin']['index'],48)
        self.assertEqual(len(records[1]['victims']),3)

    def test_control_committed_victim_rejected(self):
        data=self.read(M.CONTROL)
        data['records'][data['proof']['branch'][0]['victims'][0]]['commit_time']=25303
        with self.assertRaises(ValueError):M.control_records(data)

    def test_timer_order_and_count(self):
        data=self.read(M.TIMER)
        self.assertEqual(M.timer_records(data)['cycles'],170)
        bad=copy.deepcopy(data);bad['checked_pairs'][0]['start']['output_time']=999999
        with self.assertRaises(ValueError):M.timer_records(bad)
        bad=copy.deepcopy(data);bad['checked_pairs'].pop()
        with self.assertRaises(ValueError):M.timer_records(bad)

    def test_periods_and_svg_structure(self):
        records=M.period_records(self.read(M.FAST),self.read(M.MIDDLE))
        self.assertEqual([r['cycles'] for r in records],[4415,4924,5178])
        root=ET.fromstring(M.period_figure(records).finish())
        self.assertTrue(root.tag.endswith('svg'))
        bad=self.read(M.FAST);bad['interval_attribution']['fast']['steady_patterns'][0]['count']=254
        with self.assertRaises(ValueError):M.period_records(bad,self.read(M.MIDDLE))


if __name__=='__main__':unittest.main()
