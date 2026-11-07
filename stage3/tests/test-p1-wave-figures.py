#!/usr/bin/env python3
"""用人工反例检查提取器的拒绝行为，不代表处理器正确性证据。"""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location('figures', Path(__file__).with_name('render-p1-wave-figures.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture():
    entry = m.audit.IQ + 'othersEntriesComp_0.'
    d, f, p = m.audit.DISPATCH, m.audit.FU, entry + 'entryReg_status_'
    names = ['TOP.clock', d + 'io_enqRob_canAccept']
    for i in range(6):
        names += [d + f'io_enqRob_req_{i}_valid']
        names += [d + f'io_enqRob_req_{i}_bits_' + k for k in ('pc', 'instr', 'robIdx_flag', 'robIdx_value')]
    names += [entry + k for k in ('io_commonOut_valid', 'io_commonOut_canIssue', 'entryReg_payload_fuOpType')]
    names += [p + k for k in ('robIdx_flag', 'robIdx_value', 'issued', 'blocked')]
    names += [p + f'srcStatus_{j}_' + k for j in range(5) for k in ('srcState', 'srcType', 'psrc')]
    names += [f + k for k in ('io_out_valid', 'io_in_bits_ctrlPipe_2_fuOpType',
        'io_out_bits_ctrl_robIdx_flag', 'io_out_bits_ctrl_robIdx_value', 'io_out_bits_res_data')]
    codes = {n: 's' + str(i) for i, n in enumerate(names)}
    pre = d + 'io_enqRob_req_0_bits_'
    initial = {n: 0 for n in names}
    initial.update({d + 'io_enqRob_canAccept': 1, pre + 'pc': 0x80000182,
        pre + 'instr': 0x0200200b | 9 << 20 | 8 << 15 | 10 << 7,
        pre + 'robIdx_value': 93, p + 'robIdx_value': 93,
        entry + 'entryReg_payload_fuOpType': 0x160,
        f + 'io_in_bits_ctrlPipe_2_fuOpType': 0x160,
        f + 'io_out_bits_ctrl_robIdx_value': 93, f + 'io_out_bits_res_data': 16})
    for j, (state, typ, reg) in enumerate(zip([1, 1, 0, 1, 1], [4, 4, 4, 0, 4], [53, 55, 60, 1, 2])):
        initial.update({p + f'srcStatus_{j}_srcState': state,
            p + f'srcStatus_{j}_srcType': typ, p + f'srcStatus_{j}_psrc': reg})
    lines = ['$scope module TOP $end']
    for name in names:
        lines.append(f'$var wire 128 {codes[name]} {name.removeprefix("TOP.")} $end')
    lines += ['$upscope $end', '$enddefinitions $end']
    for time in range(17):
        vals = {**initial, 'TOP.clock': 1 if time % 2 == 0 else 0,
            d + 'io_enqRob_req_0_valid': int(time == 1),
            entry + 'io_commonOut_valid': int(3 <= time < 9),
            entry + 'io_commonOut_canIssue': int(7 <= time < 9),
            p + 'srcStatus_2_srcState': int(time >= 7), f + 'io_out_valid': int(time == 9)}
        lines.append('#' + str(time))
        lines += [f'b{value:b} {codes[name]}' for name, value in vals.items()]
    rec = {'tag': [0, 93], 'pc': '0x80000182', 'vd': 10, 'vs1': 8, 'vs2': 9,
        'dispatch_time': 1, 'output_time': 9, 'result': 16,
        'producer': {'pdest': 60}, 'false_wait_phases': [3, 5], 'wait_phases': [3, 5],
        'source_observation': {'time': 3, 'entry': entry, 'states': [1, 1, 0, 1, 1],
            'types': [4, 4, 4, 0, 4], 'psrc': [53, 55, 60, 1, 2]}}
    return '\n'.join(lines) + '\n', rec, codes


class WaveFigures(unittest.TestCase):
    def run_extract(self, text, rec):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'fixture.vcd'
            p.write_text(text)
            return m.extract(p, [{'name': 'oldvd', 'before': rec}], 'before')

    def test_realistic_fixture_and_absent_is_not_zero(self):
        text, rec, _ = fixture()
        data = self.run_extract(text, rec)
        rows = data['windows']['oldvd']
        self.assertEqual([s['time'] for s in rows if s['false_wait']], [3, 5])
        self.assertEqual([(s['time'], s['result']) for s in rows if s['target_out']], [(9, 16)])
        self.assertNotIn('states', rows[0])
        self.assertEqual(m.TRACKS[1][2](rows[0]), None)

    def test_bad_dispatch_identity_rejected(self):
        text, rec, _ = fixture()
        rec['pc'] = '0x80000186'
        with self.assertRaises(AssertionError):
            self.run_extract(text, rec)

    def test_wrong_output_rejected(self):
        text, rec, _ = fixture()
        rec['result'] = 17
        with self.assertRaises(AssertionError):
            self.run_extract(text, rec)

    def test_missing_wait_sample_rejected(self):
        text, rec, _ = fixture()
        rec['false_wait_phases'] = [3]
        with self.assertRaises(AssertionError):
            self.run_extract(text, rec)

    def test_unknown_active_source_rejected(self):
        text, rec, codes = fixture()
        name = rec['source_observation']['entry'] + 'entryReg_status_srcStatus_0_srcState'
        text = text.replace('b1 ' + codes[name] + '\n', 'bx ' + codes[name] + '\n')
        with self.assertRaises(ValueError):
            self.run_extract(text, rec)

    def test_svg_and_png_are_renderable(self):
        text, rec, _ = fixture()
        rec.update(index=0, call=0)
        rec['producer'].update(tag=[0, 92])
        data = self.run_extract(text, rec)
        case = {'name': 'oldvd', 'title': 'Synthetic test, not CPU proof', 'before': rec, 'after': copy.deepcopy(rec)}
        svg = m.svg_figure(case, {'before': data, 'after': data})
        ET.fromstring(svg)
        self.assertIn('Gray = target absent', svg)
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'test.svg'
            p.write_text(svg)
            out = p.with_suffix('.png')
            m.png_from_svg(p, out)
            self.assertTrue(out.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))


if __name__ == '__main__':
    unittest.main()
