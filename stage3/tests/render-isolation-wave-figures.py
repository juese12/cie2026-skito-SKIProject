#!/usr/bin/env python3
"""绘制真实 wrapper 的隔离前后证据，不据此宣称物理功耗收益。"""
import argparse
import hashlib
import html
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


A = module('isolation_audit', ROOT / 'stage2/tests/check-isolation-wave.py')
RENDER = module('p1_render', Path(__file__).with_name('render-p1-wave-figures.py'))
DEFAULT = ROOT / 'stage3/reports/figures/isolation'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def choose(before, after):
    """选择首个满足条件的真实边沿，按相同激励和边沿序号配对。"""
    p = A.DOT + 'products_0'
    w = A.GROUPS['mac_wallace_stage1'][0]
    predicates = [
        ('dot-hold', 'Inactive dot path: operands clamped, product registers held',
         lambda bp, bq, ap, aq: ap[A.FU + 'vimacs_0.io_fire']
         and not ap[A.DOT + 'io_enable_0'] and bp[p] != bq[p] and ap[p] == aq[p]),
        ('mac-hold', 'Inactive ordinary MAC path during dot: inputs clamped, registers held',
         lambda bp, bq, ap, aq: ap[A.DOT + 'io_enable_0']
         and not ap[A.FU + 'vimacs_0.io_fire'] and bp[w] != bq[w] and ap[w] == aq[w]),
        ('overlap', 'Mixed issue: ordinary MAC stage 1 and older dot stage 2 both advance',
         lambda bp, bq, ap, aq: ap[A.FU + 'vimacs_0.io_fire']
         and ap[A.DOT + 'io_enable_1'] and not ap[A.DOT + 'io_enable_0']),
    ]
    cases = []
    for name, title, predicate in predicates:
        start = 44 if name == 'overlap' else 3
        i = next(i for i, ((bp, bq), (ap, aq)) in enumerate(zip(before, after))
                 if i >= start and predicate(bp, bq, ap, aq))
        cases.append({'name': name, 'title': title, 'index': i,
                      'pre_time': after[i][0]['time'], 'post_time': after[i][1]['time'],
                      'tag': after[i][0]['TOP.io_tag'], 'window': [max(0, i - 2), min(len(after), i + 5)]})
    return cases


def tracks(role):
    # 每列同时显示稳定的沿前和沿后快照，不推断中间变化。
    def raw(name):
        return lambda pre, post: (pre[name], post[name])
    def operand(name):
        if role == 'before':
            return lambda pre, post: (pre['TOP.' + name] & ((1 << 64) - 1),
                                     post['TOP.' + name] & ((1 << 64) - 1))
        return raw(A.DOT + ('isolatedVs1' if name == 'io_vs1' else 'isolatedVs2'))
    def output(name):
        return lambda pre, post: (pre['TOP.' + name] if pre['TOP.io_outValid'] else None,
                                 post['TOP.' + name] if post['TOP.io_outValid'] else None)
    return [
        ('input valid (wrapper)', 'bit', raw(A.HARNESS + 'fu_io_in_valid')),
        ('input op / input tag', 'bus', lambda p, q: tuple(f'{v["TOP.io_op"]:x}/{v["TOP.io_tag"]}' for v in (p, q))),
        ('dot enable[0] (products)', 'bit', raw(A.DOT + 'io_enable_0')),
        ('dot enable[1] (sum)', 'bit', raw(A.DOT + 'io_enable_1')),
        ('dot multiplier vs1 [63:0]', 'bus', operand('io_vs1')),
        ('dot multiplier vs2 [63:0]', 'bus', operand('io_vs2')),
        ('dot products_0 [15:0]', 'bus', raw(A.DOT + 'products_0')),
        ('dot sum [18:0]', 'bus', raw(A.DOT + 'sum')),
        ('MAC0 io_fire (stage 1)', 'bit', raw(A.FU + 'vimacs_0.io_fire')),
        ('MAC0 fireS1_last_r (stage 2)', 'bit', raw(A.FU + 'vimacs_0.fireS1_last_r')),
        ('MAC0 vs1 input', 'bus', raw(A.FU + 'vimacs_0.io_vs1')),
        ('MAC0 Wallace stage1 reg0', 'bus', raw(A.GROUPS['mac_wallace_stage1'][0])),
        ('MAC0 walOut_r (stage 2)', 'bus', raw(A.GROUPS['mac_result_stage2'][0])),
        ('output valid', 'bit', raw('TOP.io_outValid')),
        ('output tag (valid only)', 'bus', output('io_outTag')),
        ('output low32 (valid only)*', 'bus', lambda p, q: tuple(
            v['TOP.io_result'] & 0xffffffff if v['TOP.io_outValid'] else None for v in (p, q))),
    ]


def bus(value):
    if value is None:
        return '-'
    if isinstance(value, str):
        return value
    text = f'{value:x}'
    return text if len(text) <= 8 else text[:3] + '..' + text[-3:]


def figure(case, excerpts):
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1560" height="1110" viewBox="0 0 1560 1110">',
             '<rect width="100%" height="100%" fill="#f4f7fb"/>',
             '<style>text{font-family:DejaVu Sans,sans-serif;fill:#172b4d}</style>']

    def text(x, y, value, size=15, color='#172b4d'):
        parts.append(f'<text x="{x}" y="{y}" font-size="{size}" style="fill:{color}">{html.escape(str(value))}</text>')

    def line(x1, y1, x2, y2, color, weight=1):
        parts.append(f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="{color}" stroke-width="{weight}"/>')

    text(30, 37, case['title'], 23)
    text(30, 64, f'Fixed stimulus wrapper; focus edge {case["index"]}, pre/post time {case["pre_time"]}/{case["post_time"]}, input tag {case["tag"]}', 17)
    text(30, 89, 'Real settled PRE/POST samples around rising edges. Hex buses; a..b abbreviates values (exact values in JSON).', 16)
    for pane, role in enumerate(('before', 'after')):
        top = 108 + 454 * pane
        color = '#b54708' if role == 'before' else '#087f5b'
        label = 'BEFORE: ungated datapath (shared by v0.1 / P1)' if role == 'before' else 'AFTER: operand isolation + register update enables'
        parts.append(f'<rect x="20" y="{top}" width="1520" height="442" rx="12" fill="white" stroke="#d5dfeb"/>')
        text(35, top + 27, label, 20, color)
        rows = excerpts[role]
        x0, cw = 340, 1170 / len(rows)
        y0 = top + 67
        for ci, row in enumerate(rows):
            left = x0 + ci * cw
            if row['index'] == case['index']:
                parts.append(f'<rect x="{left}" y="{top + 34}" width="{cw}" height="399" fill="#805ad5" opacity="0.07"/>')
            text(left + 6, top + 49, f'#{row["index"]}  t={row["pre"]["time"]}/{row["post"]["time"]}', 12)
            line(left, top + 55, left, top + 426, '#dce4ee')
            for ri, (label, kind, getter) in enumerate(tracks(role)):
                yc = y0 + 22 * ri
                if ci == 0:
                    text(35, yc + 5, label, 14)
                pre, post = getter(row['pre'], row['post'])
                mid = left + cw / 2
                if kind == 'bit':
                    yp, yq = yc - 6 if pre else yc + 6, yc - 6 if post else yc + 6
                    line(left + 2, yp, mid, yp, color, 2)
                    line(mid, yp, mid, yq, color, 2)
                    line(mid, yq, left + cw - 2, yq, color, 2)
                    for x, y in ((left + 2, yp), (mid, yq)):
                        parts.append(f'<circle cx="{x}" cy="{y}" r="2" fill="{color}"/>')
                else:
                    # 成对打印快照，避免暗示已采集周期内未观察到的总线跳变。
                    text(left + 4, yc + 4, bus(pre) + ' > ' + bus(post), 11, color)
        text(35, top + 434, 'Each column: settled pre-edge > settled post-edge. Focus column shaded purple; decimal edge index / raw VCD time.', 13)
    text(30, 1045, '* low32 is derived for readability; all 128 result bits, tags, flags and output timing are checked across the full trace.', 15)
    text(30, 1071, 'BEFORE enable/fire tracks belong to the ungated design; they are not operation-specific enables. Do not reinterpret them as AFTER.', 15)
    text(30, 1097, 'Fixed-ready module evidence, NOT whole-core traces, committed architectural state, physical clock gating or power estimation.', 15)
    parts.append('</svg>')
    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT)
    args = parser.parse_args()
    out = args.out.resolve()
    assert not out.exists(), 'refusing to overwrite an existing output directory'
    audit_path = ROOT / 'stage2/logs/isolation-wave-audit-20261005.json'
    expected = json.loads(audit_path.read_text())
    paths = {role: ROOT / f'stage2/waveform/isolation/{role}.vcd' for role in ('before', 'after')}
    hashes = {role: sha(path) for role, path in paths.items()}
    assert hashes == expected['wave_sha256'], 'source VCD identity changed'
    edges = {role: A.edges(path, role == 'after') for role, path in paths.items()}
    result = A.audit(edges['before'], edges['after'])
    assert all(result[k] == expected[k] for k in result), 'full audit differs from saved evidence'
    print('[full source/audit cross-check PASS]', result['counts'], flush=True)
    cases = choose(edges['before'], edges['after'])
    selections = {c['name']: {role: [{'index': i, 'pre': pair[0], 'post': pair[1]}
        for i, pair in enumerate(values) if c['window'][0] <= i < c['window'][1]]
        for role, values in edges.items()} for c in cases}
    # JSON 使用原层次信号名作为键，并记录 VCD 声明的位宽及标识码。
    declarations = {}
    for role, path in paths.items():
        scope, found = [], {}
        with path.open() as stream:
            for raw in stream:
                fields = raw.split()
                if not fields:
                    continue
                if fields[0] == '$scope':
                    scope.append(fields[2])
                elif fields[0] == '$upscope':
                    scope.pop()
                elif fields[0] == '$var':
                    name = '.'.join(scope + [fields[4]])
                    if name in edges[role][0][0]:
                        found[name] = {'width': int(fields[2]), 'code': fields[3]}
                elif fields[0] == '$enddefinitions':
                    break
        declarations[role] = found
    out.mkdir(parents=True)
    data = {'status': 'PASS', 'scope': result['scope'], 'selection': 'first qualifying edge; overlap search starts at edge 44 to show a separate mixed window',
        'source_sha256': hashes, 'full_audit': result, 'declarations': declarations,
        'cases': cases, 'excerpts': selections,
        'method': 'Settled pre/post rising-edge snapshots; buses hexadecimal, long values abbreviated only in images'}
    (out / 'isolation-wave-excerpts.json').write_text(json.dumps(data, indent=2) + '\n')
    for case in cases:
        svg = out / ('isolation-' + case['name'] + '.svg')
        svg.write_text(figure(case, selections[case['name']]))
        RENDER.png_from_svg(svg, svg.with_suffix('.png'))
        print('[figure PASS]', case, flush=True)
    manifest = {'status': 'PASS', 'generator': str(Path(__file__).relative_to(ROOT)), 'generator_sha256': sha(__file__),
        'dependencies': {str(p.relative_to(ROOT)): sha(p) for p in (audit_path,
            ROOT / 'stage2/tests/check-isolation-wave.py', Path(__file__).with_name('render-p1-wave-figures.py'))},
        'source_wave_sha256': hashes, 'files': {p.name: sha(p) for p in sorted(out.iterdir())}}
    (out / 'isolation-wave-figure-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('[all figures PASS]', flush=True)


if __name__ == '__main__':
    main()
