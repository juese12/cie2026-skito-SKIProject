#!/usr/bin/env python3
"""仅绘制已有且审核通过的事件记录，不读取或生成 VCD/FST。"""
import argparse
import csv
import html
import importlib.util
import io
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
VADD = 'stage1/logs/vector-add-wave-analysis.log'
DOT = 'stage2/logs/20261002T114458-core-wave-commit-audit.full.log'
CONTROL = 'stage2/waveform/20261006T033620-isolation-control-resumed.vcd.control.json'
TIMER = 'stage3/logs/timer-probe-20261003-window2-audit.json'
FAST = 'stage3/logs/20261008T114325-original-e2e-events-resumed.events.json'
MIDDLE = 'stage3/logs/20261008T200238-original-other-bins.events.json'


def need(value, message):
    if not value:
        raise ValueError(message)


def vadd_records(text):
    inputs = re.findall(r'EXEC cycle=(\d+).*ready=1.*src0_lane0=(-?\d+) src1_lane0=(-?\d+)', text)
    outputs = re.findall(r'WB\s+cycle=(\d+) channel=(\d+) result_lane0=(-?\d+)', text)
    need(len(inputs) == len(outputs) == 10 and 'execution_count=10 writeback_count=10' in text,
         'incomplete vadd audit')
    result = []
    for (start, a, b), (end, channel, value) in zip(inputs, outputs):
        start, a, b, end, channel, value = map(int, (start, a, b, end, channel, value))
        need(end-start == 2 and a+b == value, 'vadd data/time mismatch')
        result.append(dict(start=start, end=end, a=a, b=b, channel=channel, value=value))
    return result


def dot_records(text):
    need('execution_observations=29 vdot_commits=29' in text and '[exit] 0' in text,
         'missing original execution/commit audit')
    lines = [s for s in text.splitlines() if re.match(r'^\d+,TOP\.', s)]
    rows = list(csv.DictReader(io.StringIO('time,hierarchy,rob_flag,rob_index,pdest,v0_wen,result_128\n'+'\n'.join(lines))))
    need(len(rows) == 29, 'incomplete dot records')
    result = []
    for row in rows:
        value = int(row['result_128'], 16)
        need(0 <= value < 2**32, 'upper96 not zero')
        result.append(dict(time=int(row['time']), tag=f"{row['rob_flag']}:{row['rob_index']}",
                           value=value, signed=value if value < 2**31 else value-2**32))
    need({36, 120, -36, 131072, -130048, 129032, 0} <= {r['signed'] for r in result},
         'missing signed/extreme coverage')
    return result


def control_records(data):
    need(data['architectural_status'] == data['control_status'] == 'PASS'
         and data['coverage_required'], 'incomplete core control audit')
    by_index = {r['index']: r for r in data['records']}
    selected = []
    for kind, count in [('branch', 2), ('exception', 4)]:
        flushes = data['proof'][kind]
        need(len(flushes) == count, 'wrong actual flush coverage')
        for event in flushes:
            need(event['settled'], 'unsettled flush')
            victims = [by_index[i] for i in event['victims']]
            need(len(victims) == (2 if kind == 'branch' else 3), 'missing victims')
            for r in victims:
                need('commit_time' not in r and r['dispatch_time'] < r['execution_time'] < event['time']
                     and r['squashed_time'] == event['time'] and r['squash_kind'] == kind,
                     'victim execution/cancellation mismatch')
        event = flushes[0]  # 按时间选择首个满足条件的记录，不选择延迟最小的记录。
        victims = [by_index[i] for i in event['victims']]
        # origin 是 ROB 标签，不能当作 records 数组索引。
        origin = max((r for r in data['records'] if r['tag'] == event['origin']
                      and r['dispatch_time'] < victims[0]['dispatch_time']), key=lambda r:r['dispatch_time'])
        selected.append(dict(kind=kind, event=event, origin=origin, victims=victims))
    return selected


def timer_records(data):
    need(data['status'] == 'PASS' and len(data['checked_pairs']) == 6, 'incomplete six timer pairs')
    need(data['checked_markers'] == 19 and data['blocked_low_phases'] == 179,
         'unexpected marker/block observation counts')
    for pair in data['checked_pairs']:
        markers = pair['markers']
        need(len(markers) == 2 and all(m['rob_empty_at_dispatch'] for m in markers), 'marker not isolated')
        need(pair['start']['output_time'] < markers[0]['dispatch_time']
             and markers[1]['output_time'] < pair['end']['dispatch_time'], 'timestamp/marker reordering')
        need(pair['end']['data'] - pair['start']['data'] == pair['cycles'], 'timestamp delta mismatch')
    need([(p['kind'],p['impl']) for p in data['checked_pairs']] == [(k,i) for k in range(3) for i in range(2)],
         'wrong timer pair ordering')
    return data['checked_pairs'][0]


def period_records(fast, middle):
    need(fast['status'] == middle['status'] == 'PASS', 'incomplete e2e audit')
    mid = middle['comparisons'][0]
    records = []
    for label, window, interval in [
        ('fast',fast['windows']['fast'],fast['interval_attribution']['fast']),
        ('middle',mid['windows']['slow'],mid['interval_attribution']['slow']),
        ('slow',fast['windows']['slow'],fast['interval_attribution']['slow'])]:
        pattern = interval['steady_patterns']
        need(interval['real_iterations'] == 256 and len(pattern) == 1 and pattern[0]['count'] == 255,
             'mixed/unverified loop period')
        need(interval['prefix_cycles'] + interval['first_to_last_real_start_cycles']
             + interval['suffix_cycles'] == window['target']['cycles'], 'interval sum mismatch')
        need(window['mac_input_handshakes'] == window['mac_output_handshakes'] == 1024
             and interval['mac_low_phase_input_to_output_cycles'] == {'2':1024}, 'MAC event counts differ')
        records.append(dict(label=label, cycles=window['target']['cycles'], **pattern[0]))
    need([r['period'] for r in records] == [17,19,20], 'unexpected observed periods')
    return records


class Figure:
    def __init__(self, title, subtitle):
        self.parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1560" height="1110" viewBox="0 0 1560 1110">',
                      '<rect width="1560" height="1110" fill="#f4f7fb"/>',
                      '<style>text{font-family:DejaVu Sans,sans-serif;fill:#172b4d}</style>']
        self.text(35,48,title,30)
        self.text(35,82,subtitle,19)

    def text(self,x,y,value,size=20,color='#172b4d'):
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" style="fill:{color}">{html.escape(str(value))}</text>')

    def line(self,x1,y1,x2,y2,color='#9aabc0',width=2):
        self.parts.append(f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{color}" stroke-width="{width}" fill="none"/>')

    def dot(self,x,y,color='#175cd3',label=None):
        self.parts.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{color}"/>')
        if label is not None:self.text(x+10,y-10,label,18,color)

    def panel(self,y,height):
        self.parts.append(f'<rect x="24" y="{y}" width="1512" height="{height}" rx="10" fill="white" stroke="#d5dfeb"/>')

    def axis(self,y,lo,hi,step,label):
        x = lambda value: 370+(value-lo)*1060/(hi-lo)
        for value in range(lo,hi+1,step):
            self.line(x(value),y-5,x(value),y+8)
            self.text(x(value)-8,y+31,value,16)
        self.line(370,y,1430,y)
        self.text(370,y+64,label,18)
        return x

    def finish(self):
        return '\n'.join(self.parts+['</svg>'])+'\n'


def vadd_figure(rows):
    f=Figure('Standard RVV vadd: observed execution and writeback',
             'Existing parser log; each segment joins one accepted execution to its matching result.')
    f.panel(115,900);x=f.axis(880,2910,3080,10,'DUT cycle; dots are events, not continuous valid levels')
    for i,r in enumerate(rows):
        y=158+i*68
        f.text(45,y+7,f"#{i+1}: {r['a']} + ({r['b']}) = {r['value']}",21)
        f.line(x(r['start']),y,x(r['end']),y,'#175cd3',4)
        f.dot(x(r['start']),y,'#175cd3');f.dot(x(r['end']),y,'#15803d')
        f.text(1130 if x(r['end'])<1080 else 380,y-13,
               f"EXEC {r['start']} -> WB {r['end']}; channel {r['channel']}",17)
    f.text(45,982,'10 executions / 10 writebacks; all observed differences are 2 DUT cycles.',23)
    f.text(35,1060,'Source: stage1/logs/vector-add-wave-analysis.log | Low 32-bit lane shown; full software check covers 37 elements.',17)
    return f


def dot_figure(rows):
    f=Figure('vdot v0.1: positive, negative and boundary result events',
             'First occurrence of each result category in the existing 29-execution audit; raw VCD timestamps.')
    f.panel(115,900);x=f.axis(875,40000,52000,2000,'VCD timestamp (not physical time / not FU latency)')
    for i,value in enumerate([36,-36,131072,-130048,129032,0]):
        r=next(r for r in rows if r['signed']==value);y=183+i*112
        f.text(45,y-17,f'Result {value}',24)
        f.text(45,y+16,f"low32 = 0x{r['value']:08x}",18)
        f.line(370,y,1430,y,'#e1e7ef');f.dot(x(r['time']),y,label=f"t={r['time']}; ROB={r['tag']}")
    f.text(45,970,'Every plotted full 128-bit result has upper96 = 0.',24)
    f.text(35,1048,'Source: original CPU execution/commit audit (2026-10-02). Points are FU results, not plotted retirement times.',17)
    f.text(35,1080,'The original audit correlates all 29 results to 29 commits; this figure does not extend coverage to flush/v0 cases.',17)
    return f


def control_figure(records):
    f=Figure('Isolated core: executed young vdot instructions are cancelled',
             'Existing full-core control audit; first actual branch flush and first precise illegal-instruction flush.')
    for panel,case in enumerate(records):
        top=115+panel*445;f.panel(top,425)
        origin=case['origin'];base=origin['dispatch_time'];event=case['event']
        end=max(event.get('exception_time',event['time']),origin.get('commit_time',0))-base+20
        f.text(45,top+36,case['kind'].upper()+f" | origin ROB tag={event['origin']} | t0={base}",23)
        x=f.axis(top+312,0,((end+49)//50)*50,50,'Relative VCD timestamp; no continuous ready/valid inferred')
        for j,r in enumerate(case['victims']):
            y=top+88+j*69
            value=r['result'] if r['result']<2**31 else r['result']-2**32
            f.text(45,y+6,f"vdot ROB={r['tag']}; value={value}",20)
            f.line(x(r['dispatch_time']-base),y,x(event['time']-base),y,'#9aabc0')
            for key,color in [('dispatch_time','#175cd3'),('execution_time','#15803d'),('squashed_time','#b42318')]:
                f.dot(x(r[key]-base),y,color)
            f.text(500,y-13,f"dispatch +{r['dispatch_time']-base}; FU +{r['execution_time']-base}; flush +{r['squashed_time']-base}",17)
        if case['kind']=='branch':
            f.text(45,top+395,f"Decision +{event['decision_time']-base}; accepted redirect +{event['time']-base}; victims never commit.",18)
        else:
            f.text(45,top+395,f"ROB flush +{event['time']-base}; exception redirect +{event['exception_time']-base}; victims never commit.",18)
    f.text(35,1042,'Blue = dispatch; green = useful physical FU result; red = cancellation. No commit recorded for these ROB allocations.',17)
    f.text(35,1074,'Full audit: 2 actual branch flushes / 4 dot victims; 4 precise exceptions / 12 dot victims; architecture checked separately.',17)
    return f


def timer_figure(pair):
    f=Figure('Timing boundary: CSR timestamps and serializing markers',
             'Existing 8-batch CPU probe, batch4 / vdot. This example is not a formal full-size performance sample.')
    f.panel(115,880);base=pair['start']['dispatch_time']
    events=[('mcycle start: dispatch',pair['start']['dispatch_time']),
            ('mcycle start: output',pair['start']['output_time']),
            ('start marker: dispatch',pair['markers'][0]['dispatch_time']),
            ('start marker: output',pair['markers'][0]['output_time']),
            ('end marker: dispatch',pair['markers'][1]['dispatch_time']),
            ('end marker: output',pair['markers'][1]['output_time']),
            ('mcycle end: dispatch',pair['end']['dispatch_time']),
            ('mcycle end: output',pair['end']['output_time'])]
    x=f.axis(835,0,360,40,'Relative VCD timestamp; serial-marker overhead remains inside the measured interval')
    for i,(name,time) in enumerate(events):
        y=176+i*78;f.text(45,y+6,name,21);f.line(370,y,1430,y,'#e1e7ef')
        f.dot(x(time-base),y,'#175cd3' if 'mcycle' in name else '#15803d')
        f.text(610 if time-base<100 else 400,y-14,f"t={time}; offset +{time-base}",18)
    f.text(45,938,f"Both marker dispatches observe an empty ROB. End counter - start counter = {pair['cycles']} DUT cycles.",22)
    f.text(35,1045,'Six complete probe pairs pass ordering and timestamp checks; 19 markers and 179 blocked low-phase observations audited.',17)
    f.text(35,1077,'Source: timer-probe-20261003-window2-audit.json | This pinned XS CSR-write behavior is not a universal RISC-V barrier.',17)
    return f


def period_figure(records):
    f=Figure('Original e2e calls: observed repeated dispatch patterns',
             'Audited steady-state event offsets, anchored at a real loop-head load; not a reconstructed continuous waveform.')
    for i,r in enumerate(records):
        top=115+i*285;f.panel(top,265)
        f.text(45,top+34,f"{r['label'].upper()}: {r['cycles']} cycles | period {r['period']} | 255 real intervals",23)
        x=f.axis(top+165,0,21,1,'DUT cycles relative to the loop anchor')
        for j,(title,values,color) in enumerate([
            ('Real load anchors',[0,r['period']],'#175cd3'),
            ('No dispatch valid',r['dispatch_empty_offsets'],'#b42318'),
            ('IQ2 third request blocked',r['iq2_block_offsets'],'#b54708')]):
            y=top+67+j*39;f.text(45,y+6,title,20);f.line(370,y,1430,y,'#e1e7ef')
            for value in values:f.dot(x(value),y,color)
            if not values:f.text(420,y-6,'none in the repeated interval',17,'#667085')
    f.text(35,1012,'256 committed iterations in each call. MAC input/output = 1024 each; sampled MAC interval = 2 in all three windows.',19)
    f.text(35,1048,'4924 - 4415 = 255 x 2 - 1 = 509; 5178 - 4924 = 255 x 1 - 1 = 254.',21)
    f.text(35,1080,'Source: existing original-window event audits. These observations do not establish a unique upstream trigger.',17)
    return f


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'stage3/reports/figures/evidence')
    args=parser.parse_args();need(not args.out.exists(),'output exists: refuse overwrite')
    read=lambda path:json.loads((ROOT/path).read_text())
    figures={
        'stage1-vadd-events':vadd_figure(vadd_records((ROOT/VADD).read_text())),
        'vdot-result-events':dot_figure(dot_records((ROOT/DOT).read_text())),
        'control-cancellation':control_figure(control_records(read(CONTROL))),
        'timer-boundaries':timer_figure(timer_records(read(TIMER))),
        'e2e-periods':period_figure(period_records(read(FAST),read(MIDDLE)))}
    spec=importlib.util.spec_from_file_location('existing_png_renderer',Path(__file__).with_name('render-p1-wave-figures.py'))
    renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
    args.out.mkdir(parents=True,exist_ok=False)
    for name,figure in figures.items():
        svg=args.out/(name+'.svg');png=args.out/(name+'.png')
        svg.write_text(figure.finish());renderer.png_from_svg(svg,png)
    print(json.dumps(dict(status='PASS',figures=len(figures),wave_files_created=0,
                          bytes=sum(p.stat().st_size for p in args.out.iterdir()))))


if __name__=='__main__':main()
