#!/usr/bin/env python3
"""用人工恢复状态验证工具，不作为处理器性能或 RTL 证据。"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


queue = load('isolation_queue', ROOT / 'scripts/complete-vdot-isolation-performance.py')
fixtures = load('isolation_fixtures', Path(__file__).with_name('test-analyze-bench.py'))


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'stage3/logs').mkdir(parents=True)
        (self.root / 'stage3/reports').mkdir()
        self.checkpoint = self.root / 'checkpoint.json'

    def slot(self, profile='smoke', index=0, emu=None, suffix=''):
        first = index % 2
        image = queue.EXPECTED[profile]
        text = fixtures.fixture(first, index, profile).replace('schema=2', 'schema=3')
        text = text.replace('a'*64, emu or queue.EXPECTED['emu'])
        text = text.replace('b'*64, queue.EXPECTED['ref'])
        text = text.replace(('c' if first == 0 else 'd')*64, image)
        record = dict(first=first, image_sha256=image, offset=16, overwrite_nbytes=17,
                      changed_offsets=[16] if first else [], parameter_address='0x80000010',
                      overlay_sha256=('e' if first else 'f')*64)
        text += '[runtime parameter] ' + json.dumps(record) + '\n'
        summary = self.root / 'stage3/logs' / f'synthetic-{profile}-{index}{suffix}-bench.log'
        log = summary.with_name(summary.name.replace('.log', '.full.log'))
        log.write_text(text)
        summary.write_text('synthetic summary only\n')
        return dict(profile=profile, index=index, summary=str(summary), log=str(log))

    def test_interrupted_attempt_preserved_and_not_marked_completed(self):
        slot = self.slot()
        log = Path(slot['log'])
        log.write_text('Difftest enabled\npartial UART\n')
        original = log.read_bytes()
        state = dict(slots=[], pending=slot)
        queue.recover_pending(state, self.checkpoint)
        self.assertEqual(state['slots'], [])
        self.assertEqual(state['interrupted'], [slot])
        self.assertNotIn('pending', state)
        self.assertEqual(log.read_bytes(), original)
        self.assertEqual(json.loads(self.checkpoint.read_text()), state)

    def test_completed_pending_accepted_exactly_once(self):
        slot = self.slot()
        state = dict(slots=[], pending=slot)
        queue.recover_pending(state, self.checkpoint)
        queue.recover_pending(state, self.checkpoint)
        self.assertEqual(len(state['slots']), 1)
        self.assertIn('log_sha256', state['slots'][0])
        self.assertNotIn('pending', state)

    def test_recorded_failure_and_explicit_failure_are_not_retried(self):
        for text in ('[process exit] 17\n', 'benchmark FAIL\n', 'HIT BAD TRAP\n'):
            with self.subTest(text=text):
                slot = self.slot()
                Path(slot['log']).write_text(text)
                state = dict(slots=[], pending=slot)
                with self.assertRaises(ValueError):
                    queue.recover_pending(state, self.checkpoint)
                self.assertIn('pending', state)
                self.assertEqual(state['slots'], [])

    def test_wrong_identity_order_and_schema_rejected(self):
        slot = self.slot(emu='9'*64)
        with self.assertRaises(ValueError):
            queue.validate_slot(slot)
        slot = self.slot()
        with self.assertRaises(ValueError):
            queue.validate_slot(dict(slot, index=1))
        Path(slot['log']).write_text(Path(slot['log']).read_text().replace('schema=3', 'schema=2'))
        with self.assertRaises(ValueError):
            queue.validate_slot(slot)
        with self.assertRaises(ValueError):
            queue.recover_pending(dict(slots=[], pending=dict(slot, index=1)), self.checkpoint)

    def test_frozen_change_and_evidence_overwrite_rejected(self):
        path = self.root / 'frozen'
        path.write_text('original')
        state = dict(frozen={str(path): queue.digest(path)})
        queue.check_frozen(state)
        path.write_text('changed')
        with self.assertRaises(ValueError):
            queue.check_frozen(state)
        with self.assertRaises(FileExistsError):
            queue.exclusive(path, 'overwrite')
        self.assertEqual(path.read_text(), 'changed')

    def test_reports_keep_all_samples_and_are_idempotent(self):
        slots = [self.slot('smoke', i) for i in range(2)] + [self.slot('full', i) for i in range(4)]
        before = [self.slot('full', i, emu='9'*64, suffix='-before') for i in range(4)]
        baseline = self.root / 'stage3/logs/baseline.paths'
        baseline.write_text(''.join(s['summary']+'\n' for s in before))
        prefix = self.root / 'stage3/logs/synthetic-isolation'
        with patch.object(queue, 'ROOT', self.root), patch.object(queue, 'BASELINE', baseline):
            strict, report = queue.write_reports(dict(slots=slots), prefix)
            text = report.read_text()
            self.assertIn('合成测试报告（不是硬件实测）', text)
            self.assertIn('P1 → 隔离核同协议对比', text)
            self.assertEqual(text.count('100, 100, 100, 100, 100, 100, 100, 100'), 12)
            self.assertEqual(strict, 0)
            self.assertEqual(queue.write_reports(dict(slots=slots), prefix)[0], strict)
            self.assertEqual(report.read_text(), text)
            report.write_text('changed evidence')
            with self.assertRaises(ValueError):
                queue.write_reports(dict(slots=slots), prefix)


if __name__ == '__main__':
    unittest.main()
