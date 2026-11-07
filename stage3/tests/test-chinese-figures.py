#!/usr/bin/env python3
"""中文注释版本必须保持波形几何、数据和原审计可复核。"""
import importlib.util
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

spec=importlib.util.spec_from_file_location('chinese_figures_test',Path(__file__).with_name('chinese-figure-edition.py'))
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


class ChineseFigureTests(unittest.TestCase):
    def test_all_current_figures_and_retired_duplicates(self):
        result=M.check(M.ROOT)
        self.assertEqual((result['chinese_figure_pairs'],result['retired_pairs']),(39,12))

    def test_signal_paths_and_event_geometry_are_preserved(self):
        for name,entry in M.record(M.ROOT)['figures'].items():
            current=(M.ROOT/name).read_text()
            self.assertEqual(M.shape(current),M.shape(entry['original_svg_content']),name)
            self.assertEqual(current,M.translate_svg(entry['original_svg_content']),name)

    def test_geometry_change_is_detected(self):
        name,entry=next(iter(M.record(M.ROOT)['figures'].items()))
        root=ET.fromstring(entry['original_svg_content'])
        root.attrib['width']=str(int(root.attrib['width'])+1)
        self.assertNotEqual(M.shape(entry['original_svg_content']),M.shape(ET.tostring(root,encoding='unicode')))

    def test_annotations_are_chinese_and_case_meanings_stay_distinct(self):
        labels=M.LABELS
        self.assertIn('正负相消',labels.translate('vdot / cancellation: real CPU input -> products -> valid result'))
        self.assertEqual(labels.translate('vdot.enable[0]'),'vdot.enable[0]')
        self.assertEqual(labels.translate('0xfffe0400'),'0xfffe0400')
        self.assertIn('未新增仿真',labels.translate('Archived current e8/e16 wrapper RTL; input tag 23; exact dot sum = -2266173193. No new simulation.'))
        for name in M.record(M.ROOT)['figures']:
            texts=[''.join(n.itertext()) for n in ET.parse(M.ROOT/name).iter(M.SVG_NS+'text')]
            self.assertTrue(any(re.search(r'[\u3400-\u9fff]',t) for t in texts),name)
            for text in texts:
                if text=='result [127:0]':continue
                if re.search(r'\b(?:the|each|original|observed|cycles|result|before|after|existing|source|statistical|waveform)\b',text,re.I):
                    self.assertRegex(text,r'[\u3400-\u9fff]',name+': '+text)


if __name__=='__main__':unittest.main()
