#!/usr/bin/env python3
"""绘制可编辑架构图与高清文档图片。

图件描述当前 RTL，不启动模拟器；使用系统 librsvg、Cairo
及已安装的中文字体渲染，不复制字体文件。
"""
import argparse
import ctypes
import html
import json
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
INK = '#23364d'
BLUE = '#416b96'
GREEN = '#287b69'
AMBER = '#a57225'
GRAY = '#64748b'
FONT = 'Microsoft YaHei,Noto Sans CJK SC,WenQuanYi Micro Hei,DejaVu Sans,sans-serif'


class Drawing:
    def __init__(self, title, subtitle, height):
        self.width, self.height = 1680, height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1680" height="{height}" viewBox="0 0 1680 {height}">',
            f'<title>{html.escape(title)}</title>',
            f'<desc>{html.escape(subtitle)}</desc>',
            '<defs>',
            *[f'<marker id="arrow{key}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>'
              for key, color in [('Blue', BLUE), ('Green', GREEN), ('Gray', GRAY)]],
            '</defs>',
            '<rect width="100%" height="100%" fill="white"/>',
        ]
        self.text(48, 60, title, 34, weight='700')
        self.text(48, 99, subtitle, 19, color=GRAY)
        self.line([(48, 119), (1632, 119)], color='#d6dfe9', width=1.5)

    def text(self, x, y, text, size=22, color=INK, weight='400', anchor='start'):
        self.parts.append(f'<text x="{x:g}" y="{y:g}" font-family="{FONT}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{html.escape(text)}</text>')

    def rect(self, x, y, w, h, fill='#f2f6fb', stroke=BLUE, radius=7, dash=None):
        extra = f' stroke-dasharray="{dash}"' if dash else ''
        self.parts.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"{extra}/>')

    def box(self, x, y, w, h, title, lines=(), kind='existing', size=22):
        fill, stroke = {
            'existing': ('#eef4fb', BLUE),
            'new': ('#ecf7f3', GREEN),
            'register': ('#fff6e5', AMBER),
            'neutral': ('#f7f9fc', '#8b9aab'),
        }[kind]
        self.parts.append('<g>')
        self.rect(x, y, w, h, fill, stroke)
        if kind == 'register':
            self.line([(x + 8, y + 10), (x + 8, y + h - 10)], color=stroke, width=2)
        total = size + len(lines) * 27
        baseline = y + (h - total) / 2 + size - 2
        self.text(x + w / 2, baseline, title, size, stroke, '700', 'middle')
        for i, line in enumerate(lines):
            self.text(x + w / 2, baseline + (i + 1) * 27, line, 18, anchor='middle')
        self.parts.append('</g>')

    def line(self, points, color=BLUE, width=2.5, arrow=False, dash=False):
        marker = {BLUE: 'Blue', GREEN: 'Green', GRAY: 'Gray'}.get(color, 'Blue')
        extra = f' marker-end="url(#arrow{marker})"' if arrow else ''
        if dash:
            extra += ' stroke-dasharray="8 6"'
        data = ' '.join(f'{x:g},{y:g}' for x, y in points)
        self.parts.append(f'<polyline points="{data}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"{extra}/>')

    def group(self, x, y, w, h, title, fill='#fafcfe', stroke='#b2c2d4'):
        self.rect(x, y, w, h, fill, stroke, 10)
        self.text(x + 20, y + 34, title, 23, stroke if stroke == GREEN else BLUE, '700')

    def legend(self, y):
        for x, fill, color, title in [(55, '#eef4fb', BLUE, '既有通路 / 共享接口'),
                                      (460, '#ecf7f3', GREEN, '新增点积算术 / 隔离逻辑'),
                                      (990, '#fff6e5', AMBER, '受使能控制的寄存器')]:
            self.rect(x, y - 19, 26, 23, fill, color, 3)
            self.text(x + 39, y, title, 19)

    def finish(self):
        return '\n'.join(self.parts + ['</svg>', ''])


def architecture():
    d = Drawing('图 4-1　vdot.vv 整核微架构通路',
                '固定八项 e8/e16 · VLEN=128 · 复用向量乱序后端、VIMacU 与顺序提交通路', 1260)
    d.group(40, 140, 1600, 230, '前端译码、依赖建立与发射')
    nodes = [
        (65, 270, '取指与精确译码', ['custom-0 指令族', 'vm=0 仍进入非法检查']),
        (373, 270, '固定一条 uop', ['VEC_VDOT', '一个完整向量目的']),
        (681, 270, '向量重命名', ['vs1 / vs2 / 目的', '保留配置与真实源依赖']),
        (989, 270, '向量 IQ', ['等待 vs1 / vs2 / VL', '复用既有调度与唤醒']),
        (1297, 315, '读源与旁路', ['两路 128 位向量数据', 'VL 数据及 VPU 控制']),
    ]
    for x, w, title, lines in nodes:
        d.box(x, 194, w, 108, title, lines)
    for i in range(4):
        x, w, *_ = nodes[i]
        d.line([(x + w, 248), (nodes[i + 1][0], 248)], arrow=True)
    d.text(70, 342, '配置：VL 走依赖数据；SEW / LMUL / vill 随本条 uop 控制传递', 19)
    d.text(850, 342, '点积去掉 oldVd 假读依赖，保留真实 v0 读写', 19, color=GREEN)

    d.group(40, 394, 1600, 510, 'VIMacU　共享执行接口', fill='#fafdfc', stroke=GREEN)
    d.box(70, 448, 1540, 70, '共享输入与类型判别',
          ['fuOpType / vs1 / vs2 / oldVd / VL / VPU 控制 / ROB 标签与目的'], size=23)
    d.line([(1454.5, 302), (1454.5, 448)], arrow=True)
    d.box(70, 564, 710, 96, '新增 VDot8 点积分支',
          ['S1：隔离、八路乘法　　S2：35 位精确归约', 'e8 / e16 共用八个 signed16 × signed16 乘法器'], 'new')
    d.box(900, 564, 710, 96, '原普通向量乘法 / 乘加分支',
          ['普通输入有效时开启；vdot 输入时夹零', '两个 VIMac64b，保留内部 fireS1 完成较老指令'])
    d.line([(425, 518), (425, 564)], color=GREEN, arrow=True)
    d.line([(1255, 518), (1255, 564)], arrow=True)
    d.box(70, 699, 710, 70, '点积结果打包',
          ['e8：低 32 位 / 高 96 位零；e16：低 64 位 / 高 64 位零'], 'new')
    d.box(900, 699, 710, 70, '原 MGU 合并', ['普通指令的掩码与尾部处理'])
    d.line([(425, 660), (425, 699)], color=GREEN, arrow=True)
    d.line([(1255, 660), (1255, 699)], arrow=True)
    d.box(530, 816, 620, 65, '输出级选择与异常复核',
          ['按 outIsVdot 选结果，携带对应控制与异常'], size=22)
    d.line([(425, 769), (425, 848), (530, 848)], color=GREEN, arrow=True)
    d.line([(1255, 769), (1255, 848), (1150, 848)], arrow=True)

    d.box(90, 956, 410, 98, '共享写回与旁路唤醒',
          ['完整 128 位 / pdest / ROB', '异常随同一条 uop 上报'])
    d.box(635, 956, 410, 98, 'ROB 顺序提交 / 取消',
          ['误预测或较老异常触发取消', '提交后更新架构可见状态'])
    d.box(1180, 956, 430, 98, 'NEMU / Difftest',
          ['参考模型按提交执行', '完整向量状态及相关 CSR 核对'])
    d.line([(840, 881), (840, 926), (295, 926), (295, 956)], arrow=True)
    d.line([(500, 1005), (635, 1005)], arrow=True)
    d.line([(1045, 1005), (1180, 1005)], arrow=True)
    d.rect(55, 1090, 1570, 78, '#f7f9fc', '#b2c2d4')
    d.text(78, 1122, '提交约束：物理结果产生或写回不等于架构提交；取消按 ROB 标签与分配代次核对。', 21)
    d.text(78, 1150, '点积绕过 MGU，整条指令沿既有写回、异常、恢复及顺序提交流程完成。', 19, color=GRAY)
    d.legend(1216)
    return d


def datapath():
    d = Drawing('图 5-1　八项 e8/e16 点积数据通路',
                'S1 并行乘法与乘积捕获；S2 三层平衡归约与总和捕获；全部加法保留进位', 1390)
    d.group(40, 139, 1600, 604, 'S1　输入隔离、元素选择与八路乘法', fill='#fafdfc', stroke=GREEN)
    d.group(40, 772, 1600, 406, 'S2', fill='#fafdfc', stroke=GREEN)
    d.box(70, 196, 710, 64, 'vs1：128 位向量源', size=23)
    d.box(900, 196, 710, 64, 'vs2：128 位向量源', size=23)
    d.box(70, 297, 1540, 68, '乘法前操作数隔离',
          ['isolatedVs1 / isolatedVs2 = enable[0] ? 输入源 : 0'], 'new')
    d.line([(425, 260), (425, 297)], arrow=True)
    d.line([(1255, 260), (1255, 297)], arrow=True)
    d.box(70, 402, 1540, 76, '按本条指令的 SEW 选择八对 signed16 元素',
          ['e8：低八字节分别符号扩展到 16 位　　e16：八个 16 位半字直接解释为有符号数'], 'new')
    d.line([(840, 365), (840, 402)], color=GREEN, arrow=True)
    centers = [157.5 + 195 * i for i in range(8)]
    d.line([(840, 478), (840, 510)], color=GREEN)
    d.line([(centers[0], 510), (centers[-1], 510)], color=GREEN)
    for i, center in enumerate(centers):
        x = center - 87.5
        d.box(x, 542, 175, 70, f'a{i} × b{i}', ['signed16 × 16'], 'new', 23)
        d.box(x, 650, 175, 66, f'p[{i}]', ['signed32'], 'register', 23)
        d.line([(center, 510), (center, 542)], color=GREEN, arrow=True)
        d.line([(center, 612), (center, 650)], color=GREEN, arrow=True)
    pairs = [(centers[2*i] + centers[2*i+1])/2 for i in range(4)]
    quads = [(pairs[2*i] + pairs[2*i+1])/2 for i in range(2)]
    for i, center in enumerate(pairs):
        d.box(center - 126, 836, 252, 63, f'p[{2*i}] + p[{2*i+1}]', ['q['+str(i)+']：signed33'], 'new', 22)
        left, right = centers[2*i:2*i+2]
        d.line([(left, 716), (left, 808), (center, 808)], color=GREEN)
        d.line([(right, 716), (right, 808), (center, 808)], color=GREEN)
        d.line([(center, 808), (center, 836)], color=GREEN, arrow=True)
    for i, center in enumerate(quads):
        d.box(center - 176, 951, 352, 63, f'q[{2*i}] + q[{2*i+1}]', ['r['+str(i)+']：signed34'], 'new', 22)
        left, right = pairs[2*i:2*i+2]
        d.line([(left, 899), (left, 925), (center, 925)], color=GREEN)
        d.line([(right, 899), (right, 925), (center, 925)], color=GREEN)
        d.line([(center, 925), (center, 951)], color=GREEN, arrow=True)
    d.box(625, 1066, 430, 68, 'sum = r[0] + r[1]', ['signed35 总和寄存器 · enable[1]'], 'register', 23)
    for center in quads:
        d.line([(center, 1014), (center, 1041), (840, 1041)], color=GREEN)
    d.line([(840, 1041), (840, 1066)], color=GREEN, arrow=True)
    d.text(71, 1158, 'S2 内部为三层组合加法，只有一个总和寄存器边界。', 19, color=GREEN)
    d.box(300, 1221, 1080, 84, '按对齐的 sew16S2 打包完整 128 位结果',
          ['e8：{96 位零，signed32(sum)}　　e16：{64 位零，signed64(sum)}'], 'new', 23)
    d.line([(840, 1134), (840, 1221)], color=GREEN, arrow=True)
    d.text(48, 1352, 'enable[0] 同时控制 products 与 sew16S1；enable[1] 同时控制 sum 与 sew16S2。禁用时寄存器保持。', 20)
    return d


def pipeline():
    d = Drawing('图 6-1　两级流水框架与普通乘法混发',
                '数据、e8/e16 模式和指令控制分别对齐；S2 使用本级较老指令类型，独立于当前输入', 1190)
    columns = [(50, 465), (607, 465), (1164, 465)]
    for x, w in columns:
        d.rect(x, 152, w, 551, '#fafcfe', '#b2c2d4', 10)
    d.text(282.5, 190, 'S1　乘积级', 26, BLUE, '700', 'middle')
    d.text(839.5, 190, 'S2　归约级', 26, BLUE, '700', 'middle')
    d.text(1396.5, 190, '输出接口', 26, BLUE, '700', 'middle')
    d.text(282.5, 224, 'enable0 = regEnable(1) && inIsVdot', 18, GREEN, anchor='middle')
    d.text(839.5, 224, 'enable1 = regEnable(2) && S1IsVdot', 18, GREEN, anchor='middle')
    d.text(1396.5, 224, '共享两周期输出 · CertainLatency(2)', 18, BLUE, anchor='middle')
    for index, (x, w) in enumerate(columns):
        if index == 0:
            d.box(x+20, 266, w-40, 132, '隔离 → 元素选择 → 八路乘法',
                  ['捕获 8 × signed32 products', 'enable0=0 时夹零输入、保持乘积'], 'register', 21)
            d.box(x+20, 455, w-40, 73, '模式：sew16S1', ['与 products 使用相同 enable0'], 'register')
            d.box(x+20, 580, w-40, 84, '控制：ctrlVec(1)', ['操作类型 / ROB / pdest / VPU 配置'])
        elif index == 1:
            d.box(x+20, 266, w-40, 132, '4×33 → 2×34 → 1×35 位归约',
                  ['捕获 signed35 sum', 'enable1=0 时保持总和'], 'register', 21)
            d.box(x+20, 455, w-40, 73, '模式：sew16S2', ['与 sum 使用相同 enable1'], 'register')
            d.box(x+20, 580, w-40, 84, '控制：outCtrl / outVl', ['携带同一条指令的配置、目的与 ROB'])
        else:
            d.box(x+20, 266, w-40, 132, '结果打包：低 32 / 64 位',
                  ['高 96 / 64 位清零', '按输出类型选择点积或 MGU 结果'], 'new', 22)
            d.box(x+20, 455, w-40, 73, '结果格式选择', ['使用 sew16S2，保持模式对齐'], 'new')
            d.box(x+20, 580, w-40, 84, '有效输出与异常', ['完整数据 / pdest / ROB → 共享写回'])
    for i in range(2):
        x, w = columns[i]; nx, _ = columns[i+1]
        for y, color, dash in [(332, GREEN, False), (491.5, BLUE, True), (622, BLUE, True)]:
            d.line([(x+w-20, y), (nx+20, y)], color=color, arrow=True, dash=dash)
    d.line([(1396.5, 455), (1396.5, 398)], color=BLUE, arrow=True, dash=True)
    d.text(50, 750, '相邻混发示例　A 为 vdot，B 为普通向量乘法', 25, BLUE, '700')
    d.text(50, 784, 'S1IsVdot = (ctrlVec(1).fuOpType == VdotOpType.vdot)，即 S1 中那条指令的类型。', 20)
    xs = [50, 385, 696, 1007, 1318, 1629]
    ys = [810, 860, 940, 1020]
    d.rect(50, 810, 1579, 210, '#ffffff', '#b2c2d4', 5)
    d.parts.append('<rect x="51" y="811" width="1577" height="48" fill="#eef4fb"/>')
    for x in xs[1:-1]:
        d.line([(x, 810), (x, 1020)], color='#b2c2d4', width=1.4)
    for y in ys[1:-1]:
        d.line([(50, y), (1629, y)], color='#b2c2d4', width=1.4)
    headers = ['指令 / 通路', 'T0 接收 A', 'T1 接收 B', 'T2 输出 A', 'T3 输出 B']
    for i, label in enumerate(headers):
        d.text((xs[i]+xs[i+1])/2, 843, label, 21, BLUE, '700', 'middle')
    row1 = ['A：点积', '输入进入 S1', 'A 的 S2 继续归约', 'A 完整结果有效', '随后指令继续']
    row2 = ['B：普通乘法', '—', 'B 进入普通分支', '内部较老级继续推进', 'B 普通结果有效']
    for i, label in enumerate(row1):
        d.text((xs[i]+xs[i+1])/2, 908, label, 20, GREEN, '700' if i == 0 else '400', 'middle')
    for i, label in enumerate(row2):
        d.text((xs[i]+xs[i+1])/2, 988, label, 20, BLUE, '700' if i == 0 else '400', 'middle')
    d.text(50, 1070, '两周期为 FU 接收至输出的接口延迟；IQ 等待、取指译码与 ROB 提交在该范围之外。', 21)
    d.text(50, 1105, '虚线：模式 / 控制传递；实线：数据通路。图中 enable 为逻辑更新使能，尚未插入物理 ICG。', 20, color=GRAY)
    d.text(50, 1140, 'VDot8 的级推进由两级 enable 控制；valid、ready、目的及取消处理沿用共享执行控制。', 20, color=GRAY)
    return d


def rasterize(svg_path, png_path, scale):
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
    cairo.cairo_scale.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
    cairo.cairo_surface_write_to_png.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    cairo.cairo_surface_write_to_png.restype = ctypes.c_int
    cairo.cairo_destroy.argtypes = [ctypes.c_void_p]
    cairo.cairo_surface_destroy.argtypes = [ctypes.c_void_p]
    obj.g_object_unref.argtypes = [ctypes.c_void_p]
    data = svg_path.read_bytes()
    root = ET.fromstring(data)
    error = ctypes.c_void_p()
    handle = rsvg.rsvg_handle_new_from_data(data, len(data), ctypes.byref(error))
    if not handle or error.value:
        raise RuntimeError('SVG parser failed: '+str(svg_path))
    surface = cairo.cairo_image_surface_create(0, int(root.attrib['width'])*scale, int(root.attrib['height'])*scale)
    context = cairo.cairo_create(surface)
    try:
        cairo.cairo_scale(context, scale, scale)
        if not rsvg.rsvg_handle_render_cairo(handle, context):
            raise RuntimeError('SVG rasterization failed')
        if cairo.cairo_surface_write_to_png(surface, os.fsencode(png_path)) != 0:
            raise RuntimeError('PNG write failed')
    finally:
        cairo.cairo_destroy(context)
        cairo.cairo_surface_destroy(surface)
        obj.g_object_unref(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'stage2/docs/figures/vdot-design')
    parser.add_argument('--scale', type=int, choices=(1, 2, 3), default=2)
    parser.add_argument('--font-dir', type=Path, default=Path('/mnt/c/Windows/Fonts'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='vdot-diagram-fonts-') as temp:
        config = Path(temp)/'fonts.conf'
        dirs = [Path('/usr/share/fonts'), Path('/usr/local/share/fonts'), args.font_dir]
        config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd"><fontconfig>'
                          + ''.join('<dir>'+html.escape(str(p))+'</dir>' for p in dirs if p.exists())
                          + '<cachedir>'+html.escape(temp)+'</cachedir></fontconfig>')
        os.environ['FONTCONFIG_FILE'] = str(config)
        figures = []
        for name, make in [('microarchitecture', architecture), ('datapath', datapath), ('pipeline', pipeline)]:
            drawing = make()
            svg_path = args.out/(name+'.svg')
            svg_path.write_text(drawing.finish())
            rasterize(svg_path, svg_path.with_suffix('.png'), args.scale)
            figures.append(dict(name=name, svg=svg_path.name, png=svg_path.with_suffix('.png').name,
                                vector_size=[drawing.width, drawing.height],
                                image_size=[drawing.width*args.scale, drawing.height*args.scale]))
            print(f'{name}: SVG {drawing.width}x{drawing.height}, PNG {drawing.width*args.scale}x{drawing.height*args.scale}')
        (args.out/'figure-index.json').write_text(json.dumps(dict(
            edition='2026-11-02', kind='RTL design illustrations, not sampled waveforms',
            generator='stage2/tests/render-vdot-design-diagrams.py',
            implementation='fixed-eight e8/e16, VLEN=128, VIMacU two-stage interface',
            figures=figures), ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
