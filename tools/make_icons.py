#!/usr/bin/env python3
"""make_icons.py - 生成 fn-emule 的应用图标

图标素材 = eMule 官方吉祥物（驴头），来自 emule-project.net 的 GPL 素材
（Wikimedia Commons: File:EMule logo.svg，见 tools/icon-src/README.md）。这里做两件事：
  1. 读取已渲染好的 2x 位图 tools/icon-src/emule-logo-2x.png
  2. 裁掉透明留白，放到圆角方形底板上，导出 fnOS 需要的各尺寸
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "emule")
RAW = os.path.join(ROOT, "tools", "icon-src", "emule-logo-2x.png")

S = 1024  # 底板边长


def load_art():
    im = Image.open(RAW).convert("RGBA")
    bbox = im.getchannel("A").getbbox()
    if not bbox:
        raise SystemExit("素材没有可见像素：%s" % RAW)
    return im.crop(bbox)


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def make_base(size):
    """浅蓝到白的圆角底板，深浅主题下都不脏。"""
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(grad)
    top, bottom = (255, 255, 255), (222, 235, 252)
    for y in range(size):
        d.line([(0, y), (size, y)], fill=lerp(top, bottom, y / max(1, size - 1)))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                          radius=int(size * 0.225), fill=255)
    base.paste(grad.convert("RGBA"), (0, 0), mask)
    return base, mask


def compose(art, size):
    base, mask = make_base(size)
    # 驴头按高度占 84% 居中
    target_h = int(size * 0.84)
    scale = target_h / float(art.height)
    w = max(1, int(round(art.width * scale)))
    h = max(1, int(round(art.height * scale)))
    glyph = art.resize((w, h), Image.LANCZOS)

    # 投影
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sh = Image.new("L", (size, size), 0)
    px = (size - w) // 2
    py = (size - h) // 2
    sh.paste(glyph.getchannel("A"), (px + int(size * 0.004), py + int(size * 0.010)))
    shadow.putalpha(sh.point(lambda v: int(v * 0.22)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(size * 0.012))
    shadow.putalpha(Image.composite(shadow.getchannel("A"), Image.new("L", (size, size), 0), mask))
    base.alpha_composite(shadow)

    base.paste(glyph, (px, py), glyph)

    d = ImageDraw.Draw(base)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.225),
                        outline=(255, 255, 255, 90), width=max(2, int(size * 0.005)))
    return base


def save(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG", optimize=True)
    print("  %-58s %dx%d %7d B" % (os.path.relpath(path, ROOT), img.width, img.height,
                                   os.path.getsize(path)))


def build_svg(art_png_bytes_b64, size=1024):
    """web favicon：官方矢量原稿内嵌在圆角底板里，保证缩放清晰。"""
    svg_path = os.path.join(ROOT, "tools", "icon-src", "emule-logo.svg")
    with open(svg_path, encoding="utf-8") as f:
        raw = f.read()
    head_end = raw.index(">", raw.index("<svg")) + 1
    body_end = raw.rindex("</svg>")
    inner = raw[head_end:body_end]
    margin = 0.08
    inner_size = int(size * (1 - margin * 2))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" '
        'width="1024" height="1024">\n'
        '  <defs>\n'
        '    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">\n'
        '      <stop offset="0" stop-color="#ffffff"/>\n'
        '      <stop offset="1" stop-color="#deebfc"/>\n'
        '    </linearGradient>\n'
        '    <clipPath id="round"><rect width="1024" height="1024" rx="230"/></clipPath>\n'
        '  </defs>\n'
        '  <g clip-path="url(#round)">\n'
        '    <rect width="1024" height="1024" fill="url(#bg)"/>\n'
        '    <svg x="%d" y="%d" width="%d" height="%d" viewBox="0 0 500 498">\n'
        '%s\n'
        '    </svg>\n'
        '    <rect x="3" y="3" width="1018" height="1018" rx="228" fill="none" '
        'stroke="#ffffff" stroke-opacity="0.55" stroke-width="6"/>\n'
        '  </g>\n'
        '</svg>\n'
    ) % (int(size * margin), int(size * margin), inner_size, inner_size, inner)


def main():
    art = load_art()
    print("== 官方 eMule 图标素材：%dx%d（已裁掉透明留白）" % (art.size))
    master = compose(art, S)
    print("== 生成图标 ==")
    # 外层 ICON.PNG / ICON_256.PNG 是 fnpack 要求的固定名字；
    # ui/images 里则要按 fnOS 模板的约定用小写 icon_{0}.png ——
    # ui/config 写成 "images/icon_{0}.png"，应用中心会把 {0} 换成尺寸去取文件，
    # 文件名大小写或命名方式不符，图标位置就是空的。
    for rel, size in [
        ("ICON_256.PNG", 256),
        ("ICON.PNG", 64),
        ("app/ui/images/icon_256.png", 256),
        ("app/ui/images/icon_64.png", 64),
        ("app/web/images/icon.png", 192),
    ]:
        save(master.resize((size, size), Image.LANCZOS), os.path.join(SRC, rel.replace("/", os.sep)))
    svg = build_svg(None)
    p = os.path.join(SRC, "app", "web", "images", "icon.svg")
    with open(p, "w", encoding="utf-8") as f:
        f.write(svg)
    print("  %-58s %7d B" % (os.path.relpath(p, ROOT), os.path.getsize(p)))


if __name__ == "__main__":
    main()
