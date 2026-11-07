#!/usr/bin/env python3
"""检查图件取数和端口事件的拒错能力，不执行处理器。"""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location('latency_figures', Path(__file__).with_name('render-latency-evidence.py'))
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)
spec = importlib.util.spec_from_file_location('latency_chinese_figures', Path(__file__).with_name('chinese-figure-edition.py'))
CN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CN)


class LatencyEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = L.load_evidence()
        cls.audit = json.loads(L.AUDIT.read_text())

    def test_saved_figures_replay_all_formal_rows_and_current_fits(self):
        saved = json.loads((L.OUT/'evidence.json').read_text())
        self.assertEqual(saved, self.data)
        self.assertEqual(saved['formal_rows'], 1920)
        self.assertEqual(saved['port']['checked_outputs'], 400)
        self.assertEqual((saved['stable'], saved['warnings'], saved['strict_exit']), (False, 12, 3))
        for fit in saved['fits']:
            self.assertEqual(len(fit['processes']), 4)
            self.assertAlmostEqual(fit['slope'], 29 if fit['impl'] else 7, delta=0.002)
        for name, draw in (('port-and-chain', L.port_chain), ('kernel-intervals', L.intervals)):
            self.assertEqual(CN.original_svg(L.ROOT,L.OUT/(name+'.svg')), draw(saved))
            CN.verify_one(L.ROOT,str((L.OUT/(name+'.svg')).relative_to(L.ROOT)))

    def altered_events(self, change):
        rows = [json.loads(line) for line in L.EVENTS.read_text().splitlines()]
        target = self.data['port']['examples'][0]
        row = next(r for r in rows if r.get('c') == target['output']['cycle'])
        self.assertEqual(row['o']['tag'], target['tag'])
        change(row)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'events.jsonl'
            path.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
            return L.port_examples(path, self.audit)

    def test_next_instruction_mode_cannot_relabel_older_output(self):
        with self.assertRaisesRegex(ValueError, 'misaligned dot configuration'):
            self.altered_events(lambda r: r['o'].update(sew=1))

    def test_upper_result_bits_are_checked(self):
        with self.assertRaisesRegex(ValueError, 'full128 oracle mismatch'):
            self.altered_events(lambda r: r['o'].update(result=f'{(1 << 96) | 36:032x}'))

    def test_incomplete_port_coverage_is_rejected(self):
        bad = copy.deepcopy(self.audit)
        bad['observed_dot_outputs'] -= 1
        with self.assertRaisesRegex(ValueError, 'incomplete port coverage'):
            L.port_examples(L.EVENTS, bad)


if __name__ == '__main__':
    unittest.main()
