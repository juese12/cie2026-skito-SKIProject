#!/usr/bin/env python3
"""从独立目录新生成的混发模块波形提取两个完整 e16 算术窗口。"""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wave', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        p.error('输出目录已存在，拒绝覆盖')
    renderer = module('clean_e16_renderer', ROOT / 'stage2/sew16/render-e16-evidence.py')
    edges, declarations, digest = renderer.read_wave(a.wave)
    cases = renderer.select_cases(edges)
    raster = module('clean_wave_raster', ROOT / 'stage3/tests/render-p1-wave-figures.py')
    a.out.mkdir(parents=True)
    for case in cases:
        path = a.out / ('e16-' + case['name'] + '.svg')
        svg = renderer.module_figure(case)
        svg = svg.replace('Archived current e8/e16 wrapper RTL', 'Clean-directory e8/e16 wrapper RTL')
        svg = svg.replace('No new simulation.', 'Fresh module simulation.')
        svg = svg.replace('and source hashes are saved in e16-evidence-excerpts.json.',
                          'are saved in wave-evidence.json.')
        path.write_text(svg)
        raster.png_from_svg(path, path.with_suffix('.png'))
    record = {'status': 'PASS', 'wave': str(a.wave.resolve()), 'uncompressed_sha256': digest,
              'edges': len(edges), 'declarations': declarations, 'cases': cases,
              'scope': 'new clean-directory module VCD; exact operands/products/sum/full128 output; not CPU commit proof'}
    (a.out / 'wave-evidence.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'figures': len(cases),
                      'cases': [{'name': c['name'], 'total': c['total'], 'tag': c['tag']} for c in cases]}))


if __name__ == '__main__':
    main()
