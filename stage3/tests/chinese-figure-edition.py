#!/usr/bin/env python3
"""仅替换 SVG 注释并导出中文 PNG；保留数值、几何轨迹及原审计语义。"""
import argparse
import ctypes
import hashlib
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
LEDGER = 'stage3/reports/figures/figure-source-data.json'
FONT = 'Microsoft YaHei, SimHei, Noto Sans CJK SC, sans-serif'
spec = importlib.util.spec_from_file_location('figure_cn_labels', Path(__file__).with_name('chinese-figure-labels.py'))
LABELS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LABELS)
SVG_NS = '{http://www.w3.org/2000/svg}'
RETIRED = {
    **{f'stage3/reports/figures/p1/p1-{name}.svg':
       f'stage3/reports/figures/review-edition-20261101/p1/p1-{name}.svg'
       for name in ('oldvd', 'v0', 'true')},
    **{f'stage2/reports/figures/e16-summary/module-e16-{name}.svg':
       f'stage2/reports/figures/review-edition-20261101/e16-summary/module-e16-{name}.svg'
       for name in ('positive', 'negative')},
    **{f'stage3/reports/figures/functional-signals/{name}.svg':
       f'stage3/reports/figures/functional/{replacement}.svg'
       for name, replacement in [('positive36','positive'), ('positive120','positive-asymmetric'),
                                 ('positive-endpoint','all127'), ('negative','negative'),
                                 ('maximum','maximum'), ('minimum','minimum'), ('zero','zero')]},
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def translate_svg(content):
    """只处理 text 节点；不重建波形路径、网格或任何事件坐标。"""
    def replace(match):
        attrs, value = match.group(1), html.unescape(match.group(2))
        assert '<' not in match.group(2), 'nested SVG text requires explicit handling'
        translated = LABELS.translate(value)
        if re.search(r'[\u3400-\u9fff]', translated):
            attrs = re.sub(r'\sfont-family="[^"]*"', '', attrs)
            attrs += f' font-family="{FONT}"'
        return '<text'+attrs+'>'+html.escape(translated, quote=False)+'</text>'
    result = re.sub(r'<text\b([^>]*)>(.*?)</text>', replace, content, flags=re.S)
    assert shape(content) == shape(result), 'signal geometry was changed'
    return result


def shape(content):
    def node(n):
        attributes = dict(n.attrib)
        is_text = n.tag == SVG_NS+'text'
        if is_text:
            attributes.pop('font-family', None)
        return [n.tag, sorted(attributes.items()), None if is_text else (n.text or '').strip(),
                [node(c) for c in n]]
    return node(ET.fromstring(content))


def register_font(path=None):
    """只向当前进程注册本机字体，不复制或分发字体文件。"""
    candidates = [path, os.environ.get('VDOT_CJK_FONT'), '/mnt/c/Windows/Fonts/msyh.ttc',
                  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    selected = next((Path(p) for p in candidates if p and Path(p).is_file()), None)
    if selected is None:
        raise ValueError('需要本机中文字体；请用 --font 指定，或设置 VDOT_CJK_FONT')
    fc = ctypes.CDLL('libfontconfig.so.1')
    fc.FcConfigGetCurrent.restype = ctypes.c_void_p
    fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    fc.FcConfigAppFontAddFile.restype = ctypes.c_int
    config = fc.FcConfigGetCurrent()
    assert fc.FcConfigAppFontAddFile(config, os.fsencode(selected)), 'font registration failed'
    return str(selected)


def render(svg, png):
    root = ET.parse(svg).getroot()
    width, height = [int(root.attrib[k]) for k in ('width','height')]
    rsvg = ctypes.CDLL('librsvg-2.so.2'); cairo = ctypes.CDLL('libcairo.so.2'); obj = ctypes.CDLL('libgobject-2.0.so.0')
    rsvg.rsvg_handle_new_from_data.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
    rsvg.rsvg_handle_new_from_data.restype = ctypes.c_void_p
    rsvg.rsvg_handle_render_cairo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    rsvg.rsvg_handle_render_cairo.restype = ctypes.c_int
    cairo.cairo_image_surface_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    cairo.cairo_image_surface_create.restype = ctypes.c_void_p
    cairo.cairo_create.argtypes = [ctypes.c_void_p]; cairo.cairo_create.restype = ctypes.c_void_p
    cairo.cairo_surface_write_to_png.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    cairo.cairo_surface_write_to_png.restype = ctypes.c_int
    cairo.cairo_destroy.argtypes = [ctypes.c_void_p]; cairo.cairo_surface_destroy.argtypes = [ctypes.c_void_p]
    obj.g_object_unref.argtypes = [ctypes.c_void_p]
    data = Path(svg).read_bytes(); error = ctypes.c_void_p()
    handle = rsvg.rsvg_handle_new_from_data(data, len(data), ctypes.byref(error))
    assert handle and not error.value, 'invalid SVG'
    surface = cairo.cairo_image_surface_create(0, width, height); context = cairo.cairo_create(surface)
    try:
        assert rsvg.rsvg_handle_render_cairo(handle, context)
        assert cairo.cairo_surface_write_to_png(surface, os.fsencode(png)) == 0
    finally:
        cairo.cairo_destroy(context); cairo.cairo_surface_destroy(surface); obj.g_object_unref(handle)


def references(root):
    result = set()
    for md in Path(root).rglob('*.md'):
        if any(x in ('.git','private','build') for x in md.relative_to(root).parts):
            continue
        for raw in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', md.read_text()):
            raw = raw.strip('<>').split('#')[0]
            if '://' in raw:
                continue
            path = (md.parent/raw).resolve()
            if path.suffix in ('.png','.svg') and path.is_relative_to(Path(root).resolve()):
                result.add(str(path.relative_to(Path(root).resolve())))
    return result


def record(root):
    return json.loads((Path(root)/LEDGER).read_text())


def verify_one(root, name, data=None):
    root = Path(root); data = data or record(root)
    entry = data['figures'][name]
    before = entry['original_svg_content']
    assert sha(before.encode()) == entry['original_svg_sha256'], name
    actual = (root/name).read_text()
    assert actual == translate_svg(before), ('unrecorded annotation or signal change', name)
    assert sha(actual.encode()) == entry['translated_svg_sha256'], name
    png = (root/name).with_suffix('.png')
    assert sha(png.read_bytes()) == entry['translated_png_sha256'], name
    return entry


def original_svg(root, path):
    root = Path(root).resolve(); path = Path(path).resolve(); name = str(path.relative_to(root))
    data = record(root)
    if name in data['figures']:
        return verify_one(root, name, data)['original_svg_content']
    if name in data['retired']:
        entry = data['retired'][name]
        assert not path.exists() and not path.with_suffix('.png').exists(), name
        verify_one(root, entry['successor'], data)
        assert sha(entry['original_svg_content'].encode()) == entry['original_svg_sha256'], name
        return entry['original_svg_content']
    return path.read_text()


def original_digest(root, path):
    root=Path(root).resolve(); path=Path(path).resolve(); name=str(path.with_suffix('.svg').relative_to(root))
    data=record(root)
    if name in data['figures'] or name in data['retired']:
        original_svg(root, path.with_suffix('.svg'))
        return (data['figures'].get(name) or data['retired'][name])['original_'+('png' if path.suffix=='.png' else 'svg')+'_sha256']
    return sha(path.read_bytes())


def check(root):
    root=Path(root).resolve(); data=record(root)
    for name in data['figures']:
        verify_one(root,name,data)
    for name in data['retired']:
        original_svg(root,root/name)
    refs=references(root)
    assert not refs.intersection(data['retired']), 'document still references a retired figure'
    assert sha((root/'stage1/hello截图.png').read_bytes())==data['unaltered_terminal_screenshot_sha256']
    assert all((root/name).exists() for name in refs), 'missing figure link'
    return dict(status='PASS',chinese_figure_pairs=len(data['figures']),retired_pairs=len(data['retired']),
                data_and_geometry='UNCHANGED',terminal_log_screenshot='UNCHANGED',simulation=False)


def apply(root, font=None):
    root=Path(root).resolve(); assert not (root/LEDGER).exists(), 'Chinese edition already exists; use --check'
    refs=references(root); stems=sorted({str(Path(n).with_suffix('.svg')) for n in refs if not n.startswith('stage1/')})
    assert len(stems)==39 and not set(stems).intersection(RETIRED), 'unexpected figure selection'
    font_path=register_font(font)
    data=dict(schema=1,authorization='用户要求全部文档图内注释改为中文并删除旧图；原始信号、日志和数值保留。',
              figures={},retired={},font=Path(font_path).name,
              unaltered_terminal_screenshot_sha256=sha((root/'stage1/hello截图.png').read_bytes()))
    for name, successor in RETIRED.items():
        path=root/name
        assert path.is_file() and path.with_suffix('.png').is_file(),name
        data['retired'][name]=dict(original_svg_content=path.read_text(),original_svg_sha256=sha(path.read_bytes()),
                                  original_png_sha256=sha(path.with_suffix('.png').read_bytes()),successor=successor)
    with tempfile.TemporaryDirectory(prefix='vdot-chinese-figures-') as temporary:
        temporary=Path(temporary)
        for index,name in enumerate(stems):
            path=root/name; before=path.read_text(); after=translate_svg(before)
            svg=temporary/(str(index)+'.svg'); png=svg.with_suffix('.png'); svg.write_text(after); render(svg,png)
            data['figures'][name]=dict(original_svg_content=before,original_svg_sha256=sha(path.read_bytes()),
                                      original_png_sha256=sha(path.with_suffix('.png').read_bytes()),
                                      translated_svg_sha256=sha(after.encode()),translated_png_sha256=sha(png.read_bytes()))
        # 全部导出成功后再替换；原 SVG 文字和审计仍在内部记录，旧 PNG 不另存副本。
        with (root/LEDGER).open('x') as stream:json.dump(data,stream,ensure_ascii=False,indent=2);stream.write('\n')
        for index,name in enumerate(stems):
            (root/name).write_bytes((temporary/(str(index)+'.svg')).read_bytes())
            (root/name).with_suffix('.png').write_bytes((temporary/(str(index)+'.png')).read_bytes())
        for name in RETIRED:
            (root/name).unlink(); (root/name).with_suffix('.png').unlink()
    return check(root)


def export(root, destination, font=None):
    root=Path(root).resolve(); destination=Path(destination).resolve()
    assert not destination.exists() and not destination.is_relative_to(root), '请选择项目之外的新目录'
    check(root); data=record(root); register_font(font)
    for name, entry in data['figures'].items():
        svg=destination/name; svg.parent.mkdir(parents=True,exist_ok=True)
        svg.write_text(translate_svg(entry['original_svg_content']))
        render(svg,svg.with_suffix('.png'))
    return dict(status='PASS',exported_pairs=len(data['figures']),out=str(destination),simulation=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--apply',action='store_true');mode.add_argument('--check',action='store_true');mode.add_argument('--export',type=Path)
    p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--font',type=Path)
    a=p.parse_args()
    result=apply(a.root,a.font) if a.apply else export(a.root,a.export,a.font) if a.export else check(a.root)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
