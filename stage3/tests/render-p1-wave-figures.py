#!/usr/bin/env python3
"""读取真实 P1 前后 VCD，绘制按 ROB 分配限定的采样波形。

不启动仿真、不改写原始证据，也不构造虚假信号轨迹。
以 SVG 为矢量源，使用系统 librsvg 和 Cairo 导出 PNG。
"""
import argparse
import ctypes
import hashlib
import html
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('oldvd_audit', Path(__file__).with_name('check-oldvd-wave.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
DEFAULT_OUTPUT = ROOT / 'stage3/reports/figures/p1'
SOURCES = {
    'before': ('stage3/logs/p1-before-20261004.vcd', 'stage3/logs/p1-before-wave-source-audit.json'),
    'after': ('stage3/logs/20261004T232857-17-p1-after.vcd', 'stage3/logs/20261004T232857-17-p1-after-wave-audit.json'),
}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def choose(before, after):
    cases = [
        ('oldvd', 'Independent destination: oldVd false dependency',
         lambda r: r['vd'] == 10 and r['vd'] not in (r['vs1'], r['vs2'])
         and r['example'] is not None and r['example']['blocked_sources'] == [2]),
        ('v0', 'Independent v0 destination: auxiliary v0 false dependency',
         lambda r: r['vd'] == 0 and r['vd'] not in (r['vs1'], r['vs2'])
         and r['example'] is not None and r['example']['blocked_sources'] == [3]),
        ('true', 'Safety control: real vs1 dependency remains',
         lambda r: r['vd'] == r['vs1'] == 10 and r['wait_phases']
         and r.get('source_observation', {}).get('states', [1])[0] == 0),
    ]
    result = []
    for name, title, predicate in cases:
        # 按固定规则选择首个完成且满足条件的记录，不挑最短或最快样本。
        b = next(r for r in before['records'] if 'output_time' in r and predicate(r))
        a = next(r for r in after['records'] if r['index'] == b['index'])
        assert 'output_time' in a
        assert all(a[k] == b[k] for k in ('pc', 'call', 'vd', 'vs1', 'vs2'))
        result.append({'name': name, 'title': title, 'before': b, 'after': a})
    return result


def extract(path, cases, role):
    """流式读取 VCD，只保存三个小窗口中的下降沿快照。"""
    scopes, names, declarations, values = [], {}, {}, {}
    entries, selected = [], set()
    current_time, old_clock = 0, None
    records = {c['name']: c[role] for c in cases}
    windows = {k: (r['dispatch_time'] - 2, r['output_time'] + 4) for k, r in records.items()}
    end_time = max(end for _, end in windows.values())
    rows = {k: [] for k in records}

    def get(name):
        value = values.get(names[name])
        if value is None:
            raise ValueError(f'unknown required signal {name} at {current_time}')
        return value

    def sample():
        nonlocal old_clock
        clock = get('TOP.clock')
        falling = old_clock == 1 and clock == 0
        old_clock = clock
        if not falling:
            return
        for key, (start, end) in windows.items():
            if not start <= current_time <= end:
                continue
            rec = records[key]
            target = tuple(rec['tag'])
            row = {'time': current_time, 'cycle': (current_time - rec['dispatch_time']) / 2,
                   'iq_present': 0, 'target_out': 0, 'false_wait': 0, 'real_wait': 0,
                   'entry': None, 'result': None}
            if current_time == rec['dispatch_time']:
                matches = []
                if get(audit.DISPATCH + 'io_enqRob_canAccept'):
                    for i in range(6):
                        p = audit.DISPATCH + f'io_enqRob_req_{i}_bits_'
                        if get(audit.DISPATCH + f'io_enqRob_req_{i}_valid'):
                            tag = (get(p + 'robIdx_flag'), get(p + 'robIdx_value'))
                            if tag == target:
                                matches.append((get(p + 'pc'), get(p + 'instr')))
                assert len(matches) == 1 and matches[0][0] == int(rec['pc'], 16)
                assert matches[0][1] & 0xfc00707f == 0x0000200b
            for entry in entries:
                if not get(entry + 'io_commonOut_valid'):
                    continue
                p = entry + 'entryReg_status_'
                tag = (get(p + 'robIdx_flag'), get(p + 'robIdx_value'))
                if tag != target or get(entry + 'entryReg_payload_fuOpType') != 0x160:
                    continue
                assert not row['iq_present'], 'duplicate target allocation in IQ'
                row.update(iq_present=1, entry=entry,
                    states=[get(p + f'srcStatus_{j}_srcState') for j in range(5)],
                    types=[get(p + f'srcStatus_{j}_srcType') for j in range(5)],
                    psrc=[get(p + f'srcStatus_{j}_psrc') for j in range(5)],
                    issued=get(p + 'issued'), blocked=get(p + 'blocked'),
                    can_issue=get(entry + 'io_commonOut_canIssue'))
                busy = [j for j, value in enumerate(row['states']) if value == 0]
                waiting = bool(busy and not row['issued'] and not row['blocked'])
                if waiting:
                    assert row['can_issue'] == 0
                independent = rec['vd'] not in (rec['vs1'], rec['vs2'])
                old_only = set(busy) <= ({2, 3} if rec['vd'] == 0 else {2})
                row['false_wait'] = int(waiting and independent and old_only)
                row['real_wait'] = int(waiting and not independent)
                if row['false_wait']:
                    assert rec['producer']['pdest'] in [row['psrc'][j] for j in busy]
            if get(audit.FU + 'io_out_valid') and get(audit.FU + 'io_in_bits_ctrlPipe_2_fuOpType') == 0x160:
                tag = (get(audit.FU + 'io_out_bits_ctrl_robIdx_flag'), get(audit.FU + 'io_out_bits_ctrl_robIdx_value'))
                if tag == target:
                    row.update(target_out=1, result=get(audit.FU + 'io_out_bits_res_data'))
            rows[key].append(row)

    with Path(path).open(encoding='ascii') as stream:
        for raw in stream:
            line = raw.strip()
            if line.startswith('$scope'):
                scopes.append(line.split()[2])
            elif line.startswith('$upscope'):
                scopes.pop()
            elif line.startswith('$var'):
                fields = line.split()
                name = '.'.join(scopes + [fields[4]])
                if name == 'TOP.clock' or name.startswith((audit.IQ, audit.DISPATCH, audit.FU)):
                    names[name] = fields[3]
                    declarations[name] = {'code': fields[3], 'width': int(fields[2])}
            elif line.startswith('$enddefinitions'):
                entries = sorted(n.removesuffix('io_commonOut_valid') for n in names
                    if n.startswith(audit.IQ) and '.othersEntries' in n and n.endswith('.io_commonOut_valid'))
                required = ['TOP.clock', audit.DISPATCH + 'io_enqRob_canAccept']
                for i in range(6):
                    required += [audit.DISPATCH + f'io_enqRob_req_{i}_valid']
                    required += [audit.DISPATCH + f'io_enqRob_req_{i}_bits_' + field
                                 for field in ('pc', 'instr', 'robIdx_flag', 'robIdx_value')]
                for entry in entries:
                    required += [entry + n for n in ('io_commonOut_valid', 'io_commonOut_canIssue', 'entryReg_payload_fuOpType')]
                    required += [entry + 'entryReg_status_' + n for n in ('robIdx_flag', 'robIdx_value', 'issued', 'blocked')]
                    required += [entry + f'entryReg_status_srcStatus_{j}_' + n
                                 for j in range(5) for n in ('srcState', 'srcType', 'psrc')]
                required += [audit.FU + n for n in ('io_out_valid', 'io_in_bits_ctrlPipe_2_fuOpType',
                    'io_out_bits_ctrl_robIdx_flag', 'io_out_bits_ctrl_robIdx_value', 'io_out_bits_res_data')]
                assert entries and all(n in names for n in required), 'missing VCD signals'
                selected = {names[n] for n in required}
                declarations = {n: declarations[n] for n in required}
            elif line.startswith('#'):
                if values:
                    sample()
                current_time = int(line[1:])
                if current_time > end_time + 2:
                    break
            elif line.startswith('b'):
                bits, code = line[1:].split()
                if code in selected:
                    values[code] = None if any(c in bits.lower() for c in 'xz') else int(bits, 2)
            elif line and line[0] in '01xz' and line[1:] in selected:
                values[line[1:]] = int(line[0]) if line[0] in '01' else None

    for name, snapshots in rows.items():
        rec = records[name]
        assert all(b['time'] - a['time'] == 2 for a, b in zip(snapshots, snapshots[1:]))
        obs = next(r for r in snapshots if r['time'] == rec['source_observation']['time'])
        assert all(obs[k] == rec['source_observation'][k] for k in ('entry', 'states', 'types', 'psrc'))
        assert [r['time'] for r in snapshots if r['false_wait']] == rec['false_wait_phases']
        if rec['vd'] in (rec['vs1'], rec['vs2']):
            assert [r['time'] for r in snapshots if r['real_wait']] == rec['wait_phases']
        outputs = [(r['time'], r['result']) for r in snapshots if r['target_out']]
        assert outputs == [(rec['output_time'], rec['result'])]
    return {'declarations': declarations, 'windows': rows}


TRACKS = [
    ('IQ target present *', 'bool', lambda s: s['iq_present']),
    ('src0 ready (real vs1)', 'bool', lambda s: s.get('states', [None] * 5)[0]),
    ('src1 ready (real vs2)', 'bool', lambda s: s.get('states', [None] * 5)[1]),
    ('src2 type (oldVd)', 'bus', lambda s: s.get('types', [None] * 5)[2]),
    ('src2 ready', 'bool', lambda s: s.get('states', [None] * 5)[2]),
    ('src3 type (aux v0)', 'bus', lambda s: s.get('types', [None] * 5)[3]),
    ('src3 ready', 'bool', lambda s: s.get('states', [None] * 5)[3]),
    ('canIssue (eligibility)', 'bool', lambda s: s.get('can_issue')),
    ('issued / blocked', 'bus', lambda s: None if not s['iq_present'] else f'{s["issued"]}/{s["blocked"]}'),
    ('false readiness wait *', 'bool', lambda s: s['false_wait']),
    ('real readiness wait *', 'bool', lambda s: s['real_wait']),
    ('Vimac target out *', 'bool', lambda s: s['target_out']),
    ('result [127:0]', 'bus', lambda s: s['result']),
]


def svg_figure(case, extracts):
    width, height = 1560, 1110
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f4f7fb"/>',
        '<style>text{font-family:DejaVu Sans,sans-serif;fill:#172b4d}.mono{font-family:DejaVu Sans Mono,monospace}</style>']
    def text(x, y, value, size=17, color='#172b4d', weight='normal'):
        parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" style="fill:{color}">{html.escape(str(value))}</text>')
    def line(x1, y1, x2, y2, color, stroke=1):
        parts.append(f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="{color}" stroke-width="{stroke}"/>')
    text(35, 39, case['title'], 25, weight='bold')
    rec = case['before']
    text(35, 68, f'Same probe: record {rec["index"]}, call {rec["call"]}, PC {rec["pc"]}, vd=v{rec["vd"]}, vs1=v{rec["vs1"]}, vs2=v{rec["vs2"]}', 17)
    text(35, 94, 'Measured falling-edge samples; ROB-qualified IQ/FU tracks. Gray = target absent (not logic zero).', 16)
    max_cycle = max((case[r]['output_time'] - case[r]['dispatch_time']) / 2 + 3 for r in ('before', 'after'))
    x0, plot_width = 355, 1150
    def x(cycle):
        return x0 + (cycle + 1) * plot_width / (max_cycle + 1)
    for pane, role in enumerate(('before', 'after')):
        top = 114 + pane * 454
        samples = extracts[role]['windows'][case['name']]
        rec = case[role]
        parts.append(f'<rect x="24" y="{top}" width="1512" height="442" rx="12" fill="white" stroke="#d5dfeb"/>')
        label = 'v0.1 BEFORE' if role == 'before' else 'P1 AFTER'
        color = '#b54708' if role == 'before' else '#087f5b'
        delay = (rec['output_time'] - rec['dispatch_time']) // 2
        text(40, top + 29, f'{label}   ROB({rec["tag"][0]},{rec["tag"][1]})   dispatch {rec["dispatch_time"]} -> output {rec["output_time"]}   interval {delay} DUT cycles', 19, color, 'bold')
        producer = rec['producer']
        obs = rec['source_observation']
        text(40, top + 52, f'Previous writer ROB{tuple(producer["tag"])} -> P{producer["pdest"]}; first IQ psrc={obs["psrc"]}; types={obs["types"]}', 15)
        y0, row_height = top + 82, 25
        for c in range(-1, int(max_cycle) + 1):
            line(x(c), y0 - 12, x(c), y0 + len(TRACKS) * row_height - 3, '#e7edf4')
            text(x(c) - 5, top + 433, c, 13)
        for ri, (label, kind, getter) in enumerate(TRACKS):
            yc = y0 + ri * row_height
            text(40, yc + 5, label, 15)
            for i, sample in enumerate(samples):
                left = x(sample['cycle'])
                right = x(sample['cycle'] + 1)
                value = getter(sample)
                if value is None:
                    parts.append(f'<rect x="{left:.2f}" y="{yc - 9}" width="{right - left:.2f}" height="18" fill="#edf1f5"/>')
                    continue
                if kind == 'bool':
                    yy = yc - 7 if value else yc + 7
                    line(left, yy, right, yy, color, 2)
                    if i and getter(samples[i - 1]) is not None and getter(samples[i - 1]) != value:
                        prev = yc - 7 if getter(samples[i - 1]) else yc + 7
                        line(left, prev, left, yy, color, 2)
                    # 用圆点区分真实采样点与保持显示的区段。
                    parts.append(f'<circle cx="{left:.2f}" cy="{yy}" r="2" fill="{color}"/>')
                else:
                    line(left, yc - 9, right, yc - 9, color)
                    line(left, yc + 9, right, yc + 9, color)
                    if not i or getter(samples[i - 1]) != value:
                        line(left, yc - 9, left, yc + 9, color)
                        rendered = {0: 'no', 4: 'vp', 8: 'v0'}.get(value, str(value)) if 'type' in label else str(value)
                        text(left + 3, yc + 5, rendered, 13, color)
        line(x(0), y0 - 12, x(0), y0 + len(TRACKS) * row_height - 3, '#2c6ecb', 2)
        out_cycle = (rec['output_time'] - rec['dispatch_time']) / 2
        line(x(out_cycle), y0 - 12, x(out_cycle), y0 + len(TRACKS) * row_height - 3, '#805ad5', 2)
    text(35, 1049, 'Horizontal axis: DUT cycles relative to this target dispatch. 2 VCD ticks/cycle; dump times are NOT physical chip timing.', 15)
    text(35, 1073, '* Derived tag-qualified indicator, not an RTL port. canIssue is eligibility, NOT an actual issue grant or commit.', 15)
    text(35, 1097, 'Sources: original before/after VCD + PASS audits. Exact names, sampled values and hashes are in p1-wave-excerpts.json.', 15)
    parts.append('</svg>')
    return '\n'.join(parts)


def png_from_svg(svg_path, png_path):
    """使用已有系统图形库将数据生成的 SVG 转为 PNG。"""
    rsvg = ctypes.CDLL('librsvg-2.so.2')
    cairo = ctypes.CDLL('libcairo.so.2')
    obj = ctypes.CDLL('libgobject-2.0.so.0')
    rsvg.rsvg_handle_new_from_data.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
    rsvg.rsvg_handle_new_from_data.restype = ctypes.c_void_p
    rsvg.rsvg_handle_render_cairo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    rsvg.rsvg_handle_render_cairo.restype = ctypes.c_int
    cairo.cairo_image_surface_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    cairo.cairo_image_surface_create.restype = ctypes.c_void_p
    cairo.cairo_create.argtypes = [ctypes.c_void_p]
    cairo.cairo_create.restype = ctypes.c_void_p
    cairo.cairo_surface_write_to_png.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    cairo.cairo_surface_write_to_png.restype = ctypes.c_int
    cairo.cairo_destroy.argtypes = [ctypes.c_void_p]
    cairo.cairo_surface_destroy.argtypes = [ctypes.c_void_p]
    obj.g_object_unref.argtypes = [ctypes.c_void_p]
    data = svg_path.read_bytes()
    error = ctypes.c_void_p()
    handle = rsvg.rsvg_handle_new_from_data(data, len(data), ctypes.byref(error))
    assert handle and not error.value, 'SVG parser failed'
    surface = cairo.cairo_image_surface_create(0, 1560, 1110)
    context = cairo.cairo_create(surface)
    try:
        assert rsvg.rsvg_handle_render_cairo(handle, context), 'SVG rendering failed'
        assert cairo.cairo_surface_write_to_png(surface, str(png_path).encode()) == 0
    finally:
        cairo.cairo_destroy(context)
        cairo.cairo_surface_destroy(surface)
        obj.g_object_unref(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    outputs = ['p1-wave-excerpts.json', 'p1-wave-figure-manifest.json']
    outputs += [f'p1-{name}.{ext}' for name in ('oldvd', 'v0', 'true') for ext in ('svg', 'png')]
    assert not any((out / name).exists() for name in outputs), 'refusing to overwrite existing figures'
    audits, sources = {}, {}
    for role, (wave_name, audit_name) in SOURCES.items():
        a = json.loads((ROOT / audit_name).read_text())
        assert a['status'] == 'PASS'
        assert sha(ROOT / wave_name) == a['wave_sha256'], 'original wave identity changed'
        audits[role] = a
        sources[role] = {'wave': wave_name, 'wave_sha256': a['wave_sha256'],
            'audit': audit_name, 'audit_sha256': sha(ROOT / audit_name)}
        print('[source hash PASS]', role, flush=True)
    cases = choose(audits['before'], audits['after'])
    extracts = {}
    for role, (wave_name, _) in SOURCES.items():
        print('[extract start]', role, flush=True)
        extracts[role] = extract(ROOT / wave_name, cases, role)
        print('[snapshot cross-check PASS]', role, flush=True)
    contract = {'method': 'Real VCD falling-edge samples, target ROB allocation qualification; gray means absent',
        'selection': 'first qualifying completed record per category, paired by record index and probe identity',
        'source_hashes_checked': True, 'cycles_per_vcd_tick': 0.5,
        'sources': sources, 'cases': cases, 'extracts': extracts,
        'limitations': 'Not full-transition GUI screenshots, actual issue grant/commit proof, isolated FU latency or PPA.'}
    (out / 'p1-wave-excerpts.json').write_text(json.dumps(contract, indent=2) + '\n')
    for case in cases:
        svg_path = out / ('p1-' + case['name'] + '.svg')
        png_path = svg_path.with_suffix('.png')
        svg_path.write_text(svg_figure(case, extracts))
        png_from_svg(svg_path, png_path)
        print('[figure PASS]', png_path, flush=True)
    manifest = {'status': 'PASS', 'generator': str(Path(__file__).relative_to(ROOT)),
        'generator_sha256': sha(__file__), 'sources': sources,
        'files': {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()},
        'cross_checks': 'dispatch opcode/PC/ROB, first IQ observation, all wait phases, FU output time/full128 result'}
    (out / 'p1-wave-figure-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('[all figures PASS]', flush=True)


if __name__ == '__main__':
    main()
