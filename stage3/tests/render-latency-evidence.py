#!/usr/bin/env python3
"""从已保存的正式日志与事件绘制延迟分层图，不运行处理器或读取 VCD。"""
import argparse
import html
import importlib.util
import json
from pathlib import Path
import statistics as S
import sys


ROOT = Path(__file__).resolve().parents[2]
PREFIX = ROOT / 'stage3/logs/20261027T190338-sew16-perf4-full'
EVENTS = ROOT / 'stage3/logs/20261027T174613-sew16-perf4-preflight-probe.jsonl'
AUDIT = ROOT / 'stage3/logs/20261027T174613-sew16-perf4-preflight.timer-audit.json'
OUT = ROOT / 'stage3/reports/figures/latency-levels'
sys.path.insert(0, str(ROOT / 'stage3/sew16-perf'))
import common as C


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def port_examples(events, audit):
    """按分配代次关联输入、输出、提交，并复查全部计时调用中的点积。"""
    C.need(audit['status'] == 'PASS' and audit['phase'] == 'settled_low', 'unapproved timer audit')
    C.need(len(audit['boundaries']) == 168 and set(audit['calls'].values()) == {42},
           'incomplete timer calls')
    live, records, footer = {}, [], None
    seq = rows = 0
    last = -1
    with Path(events).open() as stream:
        C.need(json.loads(next(stream)) == dict(type='header', schema=1, phase='settled_low',
               rob_entries=160, allocation_gate='firstUop', stop_cycle=100000), 'wrong event schema')
        for line in stream:
            r = json.loads(line)
            if r.get('type') == 'footer':
                footer = r
                C.need(not stream.read().strip(), 'events after footer')
                break
            rows += 1
            c = r['c']
            C.need(c > last, 'unordered events')
            last = c
            for tag, pc, instr, _ in r.get('d', []):
                old = live.get(tag)
                C.need(old is None or 'commit' in old or 'cancel' in old, 'live tag reused')
                rec = dict(seq=seq, tag=tag, pc=pc, instr=instr, dispatch=c)
                seq += 1
                live[tag] = rec
                records.append(rec)
            if 'i' in r:
                v = r['i']
                rec = live.get(v['tag'])
                C.need(rec is not None and 'input' not in rec, 'untracked/duplicate dot input')
                rec['input'] = dict(v, cycle=c)
            if 'o' in r:
                v = r['o']
                rec = live.get(v['tag'])
                if rec is not None and 'input' in rec:
                    C.need('output' not in rec, 'duplicate dot output')
                    rec['output'] = dict(v, cycle=c)
            for tag in r.get('k', []):
                rec = live.get(tag)
                C.need(rec is not None and 'commit' not in rec and 'cancel' not in rec,
                       'untracked/duplicate/canceled commit')
                rec['commit'] = c
            for key in ('f', 'r'):
                if key not in r:
                    continue
                origin, level = r[key]
                for tag, rec in live.items():
                    delta = (tag - origin) % 512
                    if 'commit' not in rec and 'cancel' not in rec and (0 < delta < 256 or (level and delta == 0)):
                        rec['cancel'] = c
    C.need(footer and footer['bounded'] and footer['rows'] == rows and
           footer['last_cycle'] == 100001 and last <= 100001, 'incomplete event footer')
    examples, checked, used = {}, 0, set()
    for call in audit['boundaries']:
        body = [r for r in records if 'commit' in r and
                call['first_body_dispatch'] <= r['dispatch'] < call['end_guard_dispatch'] and
                r['instr'] & 0xfc00707f == 0x200b]
        C.need(len(body) == call['dots'], 'timer body dot count differs')
        for rec in body:
            C.need(rec['seq'] not in used and 'input' in rec and 'output' in rec,
                   'reused allocation or missing accepted result')
            used.add(rec['seq'])
            bits = 16 if '_e16_' in call['function'] else 8
            v, out = rec['input'], rec['output']
            config = [int(bits == 16), 8, 0, 1, 0, 0]
            for value in (v, out):
                C.need([value[k] for k in ('sew', 'vl', 'lmul', 'vm', 'start', 'vill')] == config,
                       'misaligned dot configuration')
            C.need(out['cycle'] - v['cycle'] == 2 and out['illegal'] == 0, 'wrong FU port latency')
            C.need(int(out['result'], 16) == C.oracle(v['a'], v['b'], bits), 'full128 oracle mismatch')
            C.need(call['start_guard_commit'] <= v['cycle'] < out['cycle'] <= rec['commit'] <=
                   call['last_body_commit'] < call['end_guard_dispatch'], 'dot outside audited boundaries')
            examples.setdefault(bits, dict(bits=bits, **rec))
            checked += 1
    C.need(checked == audit['observed_dot_outputs'] == 400 and set(examples) == {8, 16},
           'incomplete port coverage')
    return dict(checked_outputs=checked, calls=168, examples=[examples[8], examples[16]])


def load_evidence():
    reviewer = module('latency_public_review', ROOT / 'stage3/sew16-perf/review-public-data.py')
    review = reviewer.review(Path(str(PREFIX) + '.results.json'))
    C.need(review['status'] == 'PASS' and review['raw_sample_rows'] == 1920, 'formal data review failed')
    result = json.loads(Path(str(PREFIX) + '.analysis.json').read_text())
    current = [r for r in result['runs'] if r['core'] == 'new']
    fits = []
    for bits in (8, 16):
        for impl in (0, 1):
            group = [f for r in current for f in r['fits'] if f['bits'] == bits and f['impl'] == impl]
            C.need(len(group) == 4, 'incomplete current-core fits')
            fits.append(dict(bits=bits, impl=impl, processes=group,
                             slope=S.median(f['slope_cycles_per_dot'] for f in group),
                             max_relative_residual=max(f['max_relative_residual'] for f in group)))
    return dict(formal_rows=1920, formal_processes=8, current_processes=4,
                stable=result['stable'], warnings=len(result['warnings']),
                strict_exit=result['strict_exit'], summary=result['summary'], fits=fits,
                port=port_examples(EVENTS, json.loads(AUDIT.read_text())),
                sources=dict(results=str(Path(str(PREFIX) + '.results.json').relative_to(ROOT)),
                             statistics=str(Path(str(PREFIX) + '.analysis.json').relative_to(ROOT)),
                             events=str(EVENTS.relative_to(ROOT)), timer_audit=str(AUDIT.relative_to(ROOT))))


BLUE, GRAY, INK, ORANGE = '#176db5', '#68798d', '#192f46', '#a35412'


class Figure:
    def __init__(self, title, subtitle):
        self.items = ['<svg xmlns="http://www.w3.org/2000/svg" width="1560" height="1110" viewBox="0 0 1560 1110">',
                      '<rect width="1560" height="1110" fill="#fff"/>',
                      '<g font-family="DejaVu Sans, sans-serif">']
        self.text(44, 51, title, 31, weight='bold')
        self.text(44, 84, subtitle, 19, GRAY)

    def text(self, x, y, value, size=19, color=INK, weight='normal', anchor='start'):
        self.items.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{html.escape(str(value))}</text>')

    def line(self, x1, y1, x2, y2, color='#dce3eb', width=2):
        self.items.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"/>')

    def rect(self, x, y, w, h, color):
        self.items.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{color}"/>')

    def point(self, x, y, color):
        self.items.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{color}"/>')

    def finish(self):
        return '\n'.join(self.items + ['</g></svg>', ''])


def port_chain(data):
    f = Figure('Port latency and effective dependency path',
               'Current fixed-eight e8/e16 core | saved events and v4 formal samples | DUT cycles')
    f.text(44, 131, 'A. Accepted FU input to matching valid output: 2 cycles', 25, weight='bold')
    for i, rec in enumerate(data['port']['examples']):
        y = 193 + i * 104
        start, end = rec['input']['cycle'], rec['output']['cycle']
        f.text(54, y, f'e{rec["bits"]}  /  tag {rec["tag"]}', 21, weight='bold')
        f.line(440, y-7, 950, y-7, BLUE, 4)
        f.point(440, y-7, BLUE)
        f.point(950, y-7, BLUE)
        f.text(440, y+24, f'input @ {start}', 19, anchor='middle')
        f.text(950, y+24, f'output @ {end}', 19, anchor='middle')
        f.text(695, y-21, '+2 DUT cycles', 22, BLUE, 'bold', 'middle')
        f.text(1110, y-6, f'full128 result = {int(rec["output"]["result"],16)}', 19)
        f.text(1110, y+24, f'allocation seq = {rec["seq"]}', 17, GRAY)
    f.text(54, 365, 'Sparse accepted/result events; no continuous signal level or retirement latency is inferred.', 18, GRAY)
    f.text(44, 420, 'B. Dependency chain: C(N) = intercept + slope x N', 25, weight='bold')
    f.text(44, 451, '16 / 64 / 256 nonzero feedback steps; loop, configuration and dependency path remain inside.', 19, GRAY)
    for bits, x0 in ((8, 125), (16, 885)):
        y0, width, height = 880, 560, 300
        xx = lambda n: x0 + width*n/256
        yy = lambda c: y0 - height*c/8000
        f.text(x0, 501, f'e{bits}: four independent current-core processes', 21, weight='bold')
        for value in (0, 2000, 4000, 6000, 8000):
            y = yy(value)
            f.line(x0, y, x0+width, y)
            f.text(x0-12, y+6, value, 17, GRAY, anchor='end')
        for n in (16, 64, 256):
            f.text(xx(n), y0+29, n, 18, anchor='middle')
        f.text(x0+width/2, y0+59, 'Feedback steps N', 18, GRAY, anchor='middle')
        for impl, color in ((1, GRAY), (0, BLUE)):
            fit = next(g for g in data['fits'] if g['bits'] == bits and g['impl'] == impl)
            for proc in fit['processes']:
                b, m = proc['intercept_cycles'], proc['slope_cycles_per_dot']
                f.line(xx(16), yy(b+16*m), xx(256), yy(b+256*m), color, 2)
            for case in data['summary']:
                if case['bits'] == bits and case['kind'] >= 2:
                    f.point(xx(case['dots']), yy(case['rvv_cycles' if impl else 'dot_cycles']), color)
            name = 'RVV' if impl else 'vdot'
            f.text(x0+20, 563 if impl else 534, f'{name}: slope {fit["slope"]:.6f} cycles/dot', 20, color, 'bold')
    f.text(44, 996, 'Dots: median of per-process medians. Lines: each process fit; most overlap at this scale.', 19, GRAY)
    f.text(44, 1030, 'The ~7 / ~29 slopes measure effective chain cost; neither is the 2-cycle FU port latency.', 21, ORANGE, 'bold')
    f.text(44, 1072, '400 port outputs checked; formal data replay retains all 1920 warm-up and measurement rows.', 18, GRAY)
    return f.finish()


def intervals(data):
    f = Figure('Independent-stream kernel and end-to-end interval',
               'Current core | 256 dot products per sample | lower cycles are better | v4 formal data')
    f.rect(44, 112, 23, 16, BLUE)
    f.text(77, 128, 'vdot', 20, BLUE)
    f.rect(180, 112, 23, 16, GRAY)
    f.text(213, 128, 'precise RVV baseline', 20, GRAY)
    f.text(940, 128, 'RVV / vdot: four process ratios', 20, weight='bold')
    x0, width, rx, rw = 190, 625, 1010, 440
    for v in (0, 1000, 2000, 3000):
        x = x0+width*v/3000
        f.line(x, 165, x, 855)
        f.text(x, 884, v, 18, GRAY, anchor='middle')
    for v in (0, 1, 2, 3, 4, 5):
        x = rx+rw*v/5
        f.line(x, 165, x, 855)
        f.text(x, 884, f'{v}x', 18, GRAY, anchor='middle')
    for i, (bits, kind) in enumerate(((8, 0), (16, 0), (8, 1), (16, 1))):
        case = next(s for s in data['summary'] if s['bits'] == bits and s['kind'] == kind)
        y = 217 + i*167
        f.text(44, y+17, f'e{bits}', 23, weight='bold')
        f.text(44, y+48, 'batch4' if kind == 0 else 'e2e', 21)
        for j, (key, color) in enumerate((('dot_cycles', BLUE), ('rvv_cycles', GRAY))):
            val = case[key]
            bar = width*val/3000
            f.rect(x0, y+j*39, bar, 27, color)
            f.text(x0+bar+10, y+j*39+21, f'{val:g}', 19, color, 'bold')
        lo, hi = case['speedup_min'], case['speedup_max']
        f.line(rx+rw*lo/5, y+35, rx+rw*hi/5, y+35, BLUE, 5)
        for ratio in case['process_ratios']:
            f.point(rx+rw*ratio/5, y+35, BLUE)
        f.text(rx, y+80, f'median {case["speedup_median"]:.6f}x', 20, BLUE, 'bold')
        f.text(rx, y+109, f'range {lo:.6f} - {hi:.6f}', 16, GRAY)
    f.text(44, 947, 'batch4: preloaded operands, four independent destinations, kernel interval.', 21, weight='bold')
    f.text(44, 985, 'e2e: includes operand loads, initialization and result stores in the measured interval.', 21)
    f.text(44, 1030, f'e2e: {data["warnings"]} stability warnings retained; stable=False, strict=3.', 22, ORANGE, 'bold')
    f.text(44, 1072, 'Bars: median of process medians. Ratios: median and range of process ratios; no empty-loop subtraction.', 18, GRAY)
    return f.finish()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=OUT, help='新输出目录，拒绝覆盖已有图件')
    args = p.parse_args()
    names = ['evidence.json'] + [name+'.'+ext for name in ('port-and-chain', 'kernel-intervals') for ext in ('svg', 'png')]
    C.need(not any((args.out/name).exists() for name in names), 'output exists; choose a new directory')
    data = load_evidence()
    C.need(not data['stable'] and data['warnings'] == 12 and data['strict_exit'] == 3,
           'changed formal qualification; review the figure captions')
    args.out.mkdir(parents=True, exist_ok=True)
    renderer = module('latency_png', Path(__file__).with_name('render-p1-wave-figures.py'))
    for name, draw in (('port-and-chain', port_chain), ('kernel-intervals', intervals)):
        svg, png = args.out/(name+'.svg'), args.out/(name+'.png')
        svg.write_text(draw(data))
        renderer.png_from_svg(svg, png)
    with (args.out/'evidence.json').open('x') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps(dict(status='PASS', outputs=len(names), rows=data['formal_rows'],
                         port_outputs=data['port']['checked_outputs'], warnings=data['warnings'],
                         cpu_simulation=False, vcd_read=False)))


if __name__ == '__main__':
    main()
