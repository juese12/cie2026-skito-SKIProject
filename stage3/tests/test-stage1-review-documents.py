#!/usr/bin/env python3
"""核对用户提供的 Hello 证据及当前文档导航，不启动仿真。"""
import hashlib
import json
from pathlib import Path
import re
import struct
import unittest

ROOT=Path(__file__).resolve().parents[2]


class StageOneReviewTests(unittest.TestCase):
    def setUp(self):
        self.evidence=json.loads((ROOT/'manifest/document-review-edition-20261101.json').read_text())['hello_evidence']

    def test_supplied_screenshot_is_unchanged(self):
        raw=(ROOT/self.evidence['image']).read_bytes()
        self.assertEqual(raw[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(hashlib.sha256(raw).hexdigest(),self.evidence['image_sha256'])
        self.assertEqual(struct.unpack('>II',raw[16:24]),(self.evidence['width'],self.evidence['height']))

    def test_dated_run_matches_picture_description(self):
        raw=(ROOT/self.evidence['run_log']).read_text()
        for token in ('2026-11-01T16:15:40+08:00','Difftest enabled',
                      'hello xiangshan, I am skito, IP address: 192.168.31.222',
                      'HIT GOOD TRAP at pc = 0x8000014c','[run] exit status: 0',
                      '/XiangShan/build/emu','/XiangShan/ready-to-run/riscv64-nemu-interpreter-so'):
            self.assertIn(token,raw)
        inst,cycles=map(int,re.search(r'instrCnt = (\d+), cycleCnt = (\d+)',raw).groups())
        self.assertEqual((inst,cycles),(self.evidence['instructions'],self.evidence['core_cycles']))
        self.assertIn('Guest cycle spent: '+str(self.evidence['guest_cycles']),raw)
        self.assertIn('[build] completed: 2026-11-01T16:15:32+08:00',(ROOT/self.evidence['build_log']).read_text())

    def test_historical_and_current_results_are_separate(self):
        old=(ROOT/self.evidence['historical_run_log']).read_text()
        self.assertIn('2026-09-22',old)
        self.assertIn('cycleCnt = 8148',old)
        for name in ('stage1/docs/环境部署与操作日志.md','stage1/docs/环境与RVV基线验收.md'):
            text=(ROOT/name).read_text()
            for token in ('8148','14542','20260922-hello-run.log','20261101-hello-run.log'):
                self.assertIn(token,text,name)
            self.assertIn('![',text)
            self.assertIn('../hello截图.png',text)

    def test_cross_stage_planning_not_in_deployment_log(self):
        log=(ROOT/'stage1/docs/环境部署与操作日志.md').read_text()
        self.assertNotIn('后续阶段入口',log)
        self.assertEqual(len(re.findall(r'^## \d+\.',log,re.M)),4)
        self.assertLess(log.index('### 3.3 环境检查'),log.index('## 4. Hello'))
        index=(ROOT/'stage1/第一阶段说明.md').read_text()
        for token in ('## 后续阶段材料','../stage2/第二阶段说明.md','../stage3/第三阶段说明.md'):
            self.assertIn(token,index)

    def test_current_performance_summary_uses_existing_data(self):
        data=json.loads((ROOT/'stage3/logs/20261027T190338-sew16-perf4-full.analysis.json').read_text())
        text=(ROOT/'stage3/reports/基线与vdot延迟加速图文分析.md').read_text()
        names={0:'batch4',1:'e2e',4:'chain256'}
        for row in data['summary']:
            if row['kind'] not in names:continue
            expected=f"| {row['bits']} | {names[row['kind']]} | {row['dot_cycles']:g} | {row['rvv_cycles']:g} | {row['speedup_median']:.6f} |"
            self.assertIn(expected,text)
        self.assertIn('## 2. 历史 e8',text)
        self.assertIn('12 条 e2e',text)

    def test_obsolete_current_status_removed(self):
        summary=(ROOT/'stage2/reports/e16整核仿真与关键信号图解.md').read_text()
        self.assertNotIn('也没有新核正式性能',summary)
        self.assertIn('e8e16正式性能分析报告v4.md',summary)
        report=(ROOT/'stage2/reports/固定八项e8e16实施与验收报告.md').read_text()
        self.assertNotIn('现有 e8 性能报告属于原隔离核',report)


if __name__=='__main__':unittest.main()
