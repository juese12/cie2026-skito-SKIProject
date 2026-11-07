#!/usr/bin/env python3
"""仅验证人工绘图用例，不作为处理器验收证据。"""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


M = load('isolation_plot', Path(__file__).with_name('render-isolation-wave-figures.py'))
F = load('isolation_fixture', M.ROOT / 'stage2/tests/test-isolation-wave.py')


class IsolationFigureTests(unittest.TestCase):
    def test_selection_is_deterministic_and_paired(self):
        before, after = F.fixture()
        cases = M.choose(before, after)
        self.assertEqual(cases, M.choose(before, after))
        self.assertEqual([c['name'] for c in cases], ['dot-hold', 'mac-hold', 'overlap'])
        self.assertGreaterEqual(cases[2]['index'], 44)
        for case in cases:
            i = case['index']
            self.assertEqual(case['pre_time'], after[i][0]['time'])
            self.assertEqual(before[i][0]['TOP.io_tag'], after[i][0]['TOP.io_tag'])

    def test_no_qualifying_observation_is_rejected(self):
        before, after = F.fixture()
        for pre, post in after:
            pre[M.A.FU + 'vimacs_0.io_fire'] = 0
        with self.assertRaises(StopIteration):
            M.choose(before, after)

    def test_before_multiplier_observation_uses_only_low64(self):
        getter = next(t[2] for t in M.tracks('before') if t[0] == 'dot multiplier vs1 [63:0]')
        self.assertEqual(getter({'TOP.io_vs1': (1 << 100) + 19}, {'TOP.io_vs1': (1 << 90) + 27}), (19, 27))

    def test_invalid_output_is_not_shown_as_architectural_data(self):
        getter = next(t[2] for t in M.tracks('after') if t[0] == 'output low32 (valid only)*')
        self.assertEqual(getter({'TOP.io_outValid': 0, 'TOP.io_result': 123},
                                {'TOP.io_outValid': 1, 'TOP.io_result': (1 << 100) + 45}), (None, 45))

    def test_bus_hex_and_abbreviation(self):
        self.assertEqual(M.bus(736), '2e0')
        self.assertEqual(M.bus(0x123456789abcdef), '123..def')
        self.assertEqual(M.bus(None), '-')

    def test_svg_and_png_renderer(self):
        before, after = F.fixture()
        for pair in before + after:
            pair[0]['TOP.io_outValid'] = 0
        case = M.choose(before, after)[0]
        excerpts = {role: [{'index': i, 'pre': pair[0], 'post': pair[1]}
            for i, pair in enumerate(values) if case['window'][0] <= i < case['window'][1]]
            for role, values in [('before', before), ('after', after)]}
        svg = M.figure(case, excerpts)
        self.assertEqual(ET.fromstring(svg).attrib['width'], '1560')
        self.assertIn('NOT whole-core traces', svg)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.svg'
            path.write_text(svg)
            M.RENDER.png_from_svg(path, path.with_suffix('.png'))
            self.assertEqual(path.with_suffix('.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')


if __name__ == '__main__':
    unittest.main()
