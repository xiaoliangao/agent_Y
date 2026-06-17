"""生成 Agent Y 的 macOS 应用图标（.icns）。

设计：深色暖灰 squircle 底 + 暖金「智能体核心 + 轨道节点」标记 —— 科技感、与 app 同语言。
用法：python packaging/make_icon.py  → packaging/AgentY.iconset + packaging/icon.icns
依赖：Pillow + numpy（构建环境 llm 已有）。生成 .icns 需 macOS 的 iconutil。
"""
from __future__ import annotations

import math
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

S = 2048  # 高分辨率作画，最后降采样到 1024，边缘更顺滑
HERE = os.path.dirname(os.path.abspath(__file__))


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def squircle_mask(size: int, n: float = 5.0, pad: float = 0.0) -> Image.Image:
    """超椭圆（squircle）alpha 蒙版，贴近 macOS 图标外形。"""
    xs = np.linspace(-1, 1, size)
    X, Y = np.meshgrid(xs, xs)
    r = (np.abs(X) ** n + np.abs(Y) ** n)
    inside = r <= (1 - pad) ** n
    edge = np.clip((1 - r ** (1 / n)) * size * 0.06, 0, 1)  # 抗锯齿软边
    a = np.where(inside, 1.0, edge)
    return Image.fromarray((a * 255).astype("uint8"), "L")


def vertical_gradient(size: int, top: str, bottom: str) -> Image.Image:
    t, b = np.array(_hex(top)), np.array(_hex(bottom))
    ramp = np.linspace(0, 1, size)[:, None]
    col = (t[None, :] * (1 - ramp) + b[None, :] * ramp).astype("uint8")  # size x 3
    img = np.repeat(col[:, None, :], size, axis=1)
    return Image.fromarray(img, "RGB")


def radial_glow(size: int, cx: float, cy: float, radius: float, color: str, alpha: float) -> Image.Image:
    xs = np.linspace(0, size, size)
    X, Y = np.meshgrid(xs, xs)
    d = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2) / radius
    a = np.clip(1 - d, 0, 1) ** 2 * alpha
    rgb = np.array(_hex(color))
    arr = np.zeros((size, size, 4), "uint8")
    arr[..., :3] = rgb
    arr[..., 3] = (a * 255).astype("uint8")
    return Image.fromarray(arr, "RGBA")


def build() -> Image.Image:
    gold, gold2 = "#e7bd80", "#d6a866"
    img = vertical_gradient(S, "#1c1c20", "#0a0a0c").convert("RGBA")
    cx = cy = S / 2

    # 背景暖光
    img = Image.alpha_composite(img, radial_glow(S, cx, cy * 0.92, S * 0.42, gold2, 0.16))

    draw_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(draw_layer)

    # 两条倾斜轨道环
    for ang, rx, ry, w in ((-22, 0.40, 0.155, 10), (28, 0.40, 0.135, 8)):
        ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring)
        bbox = [cx - rx * S, cy - ry * S, cx + rx * S, cy + ry * S]
        rd.ellipse(bbox, outline=(*_hex(gold2), 170), width=w)
        ring = ring.rotate(ang, center=(cx, cy), resample=Image.BICUBIC)
        draw_layer = Image.alpha_composite(draw_layer, ring)

    # 轨道节点
    for ang, rx, ry, rot, nr in ((150, 0.40, 0.155, -22, 26), (-30, 0.40, 0.135, 28, 22)):
        a = math.radians(ang)
        px, py = rx * S * math.cos(a), ry * S * math.sin(a)
        rr = math.radians(rot)
        nx = cx + px * math.cos(rr) - py * math.sin(rr)
        ny = cy + px * math.sin(rr) + py * math.cos(rr)
        d.ellipse([nx - nr, ny - nr, nx + nr, ny + nr], fill=(*_hex(gold), 255))

    img = Image.alpha_composite(img, draw_layer)

    # 核心光球（外晕 + 实心 + 高光）
    img = Image.alpha_composite(img, radial_glow(S, cx, cy, S * 0.16, gold, 0.9))
    core = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cd = ImageDraw.Draw(core)
    cr = S * 0.085
    cd.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=(*_hex(gold), 255))
    cd.ellipse([cx - cr * 0.42 - cr * 0.3, cy - cr * 0.42 - cr * 0.3,
                cx - cr * 0.42 + cr * 0.3, cy - cr * 0.42 + cr * 0.3], fill=(255, 246, 230, 220))
    img = Image.alpha_composite(img, core)

    # 细金边
    rim = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle([6, 6, S - 6, S - 6], radius=int(S * 0.225),
                                          outline=(*_hex(gold2), 60), width=6)
    img = Image.alpha_composite(img, rim)

    # squircle 裁形
    img.putalpha(squircle_mask(S, n=5.0))
    return img.resize((1024, 1024), Image.LANCZOS)


def main() -> None:
    master = build()
    iconset = os.path.join(HERE, "AgentY.iconset")
    os.makedirs(iconset, exist_ok=True)
    specs = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
             (256, 1), (256, 2), (512, 1), (512, 2)]
    for base, scale in specs:
        px = base * scale
        name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
        master.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))
    out = os.path.join(HERE, "icon.icns")
    try:
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)
        print("wrote", out)
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        master.save(os.path.join(HERE, "icon_1024.png"))
        print("iconutil 不可用，已存 PNG 兜底：", e)


if __name__ == "__main__":
    main()
