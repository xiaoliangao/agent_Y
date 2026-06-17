"""生成 Agent Y 的 macOS 应用图标（.icns）。

设计：暖陶土渐变 squircle + 奶白「在场感」发光球体（立体高光 + 柔晕 + 细环），
呼应 app 的暖纸主题与光球意象 —— 温暖、有质感、Dock 里也醒目。
用法：python packaging/make_icon.py  → packaging/AgentY.iconset + packaging/icon.icns
依赖：Pillow + numpy。生成 .icns 需 macOS 的 iconutil。
"""
from __future__ import annotations

import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

_SERIFS = [
    ("/System/Library/Fonts/Supplemental/Hoefler Text.ttc", 2),  # Black
    ("/System/Library/Fonts/Supplemental/Hoefler Text.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Didot.ttc", 1),
    ("/System/Library/Fonts/Supplemental/Georgia.ttf", 0),
]


def _serif(px: int) -> ImageFont.FreeTypeFont:
    for path, idx in _SERIFS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, px, index=idx)
            except Exception:
                continue
    return ImageFont.load_default()

S = 2048  # 高分辨率作画，最后降采样到 1024
HERE = os.path.dirname(os.path.abspath(__file__))


def _hex(c: str):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def squircle_mask(size: int, n: float = 5.0) -> Image.Image:
    xs = np.linspace(-1, 1, size)
    X, Y = np.meshgrid(xs, xs)
    r = np.abs(X) ** n + np.abs(Y) ** n
    a = np.clip((1 - r ** (1 / n)) * size * 0.06, 0, 1)
    a[r <= 1] = np.maximum(a[r <= 1], 1.0)
    return Image.fromarray((a * 255).astype("uint8"))


def vertical_gradient(size: int, top: str, bottom: str) -> Image.Image:
    t, b = np.array(_hex(top)), np.array(_hex(bottom))
    ramp = np.linspace(0, 1, size)[:, None]
    col = (t[None, :] * (1 - ramp) + b[None, :] * ramp).astype("uint8")
    return Image.fromarray(np.repeat(col[:, None, :], size, axis=1))


def radial_glow(size, cx, cy, radius, color, alpha, power=2.0) -> Image.Image:
    xs = np.linspace(0, size, size)
    X, Y = np.meshgrid(xs, xs)
    d = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2) / radius
    a = np.clip(1 - d, 0, 1) ** power * alpha
    arr = np.zeros((size, size, 4), "uint8")
    arr[..., :3] = _hex(color)
    arr[..., 3] = (a * 255).astype("uint8")
    return Image.fromarray(arr, "RGBA")


def sphere(size, cx, cy, r, bright, deep) -> Image.Image:
    """立体球体：光源在左上，奶白高光 → 陶土暗部，柔边 alpha。"""
    xs = np.linspace(0, size, size)
    X, Y = np.meshgrid(xs, xs)
    d = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    lx, ly = cx - r * 0.34, cy - r * 0.40
    dl = np.sqrt((X - lx) ** 2 + (Y - ly) ** 2) / (r * 1.7)
    shade = np.clip(1 - dl, 0, 1) ** 1.25
    b, dp = np.array(_hex(bright)), np.array(_hex(deep))
    col = dp[None, None, :] * (1 - shade[..., None]) + b[None, None, :] * shade[..., None]
    arr = np.zeros((size, size, 4), "uint8")
    arr[..., :3] = col.astype("uint8")
    arr[..., 3] = (np.clip((r - d) / 6.0, 0, 1) * 255).astype("uint8")  # 柔边
    return Image.fromarray(arr, "RGBA")


def build() -> Image.Image:
    cream = (255, 247, 238)
    img = vertical_gradient(S, "#d6855a", "#8a3d22").convert("RGBA")
    cx, cy = S / 2, S / 2
    comp = Image.alpha_composite

    img = comp(img, radial_glow(S, cx, cy * 0.66, S * 0.62, "#ffdcc2", 0.20))  # 顶部柔光

    font = _serif(int(S * 0.66))

    # 阴影 Y（下移 + 模糊，制造立体/印压感）
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((cx, cy + S * 0.02 + S * 0.012), "Y", font=font,
                                fill=(80, 30, 15, 150), anchor="mm")
    img = comp(img, shadow.filter(ImageFilter.GaussianBlur(S * 0.012)))

    # 主体 Y（奶白）
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((cx, cy + S * 0.02), "Y", font=font, fill=(*cream, 255), anchor="mm")
    img = comp(img, layer)

    # 细奶白边
    rim = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle([7, 7, S - 7, S - 7], radius=int(S * 0.225),
                                          outline=(*cream, 42), width=6)
    img = comp(img, rim)

    img.putalpha(squircle_mask(S, n=5.0))
    return img.resize((1024, 1024), Image.LANCZOS)


def main() -> None:
    master = build()
    iconset = os.path.join(HERE, "AgentY.iconset")
    os.makedirs(iconset, exist_ok=True)
    for base, scale in [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
                        (256, 1), (256, 2), (512, 1), (512, 2)]:
        px = base * scale
        name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
        master.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))
    out = os.path.join(HERE, "icon.icns")
    try:
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)
        print("wrote", out)
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        master.save(os.path.join(HERE, "icon_1024.png"))
        print("iconutil 不可用，已存 PNG：", e)


if __name__ == "__main__":
    main()
