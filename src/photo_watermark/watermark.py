#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageColor


# --------- EXIF 拍摄时间提取 ----------
def extract_exif_date(image_path: Path) -> Optional[str]:
    try:
        with Image.open(image_path) as im:
            exif = im.getexif()
            if not exif:
                return None
            candidates = [36867, 36868, 306]  # DateTimeOriginal, DateTimeDigitized, DateTime
            dt_raw = None
            for tag in candidates:
                val = exif.get(tag)
                if val:
                    dt_raw = str(val)
                    break
            if not dt_raw:
                return None
            dt_raw = dt_raw.strip().replace('-', ':')
            dt = datetime.strptime(dt_raw.split(' ')[0], "%Y:%m:%d")
            return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def parse_color(color_str: str) -> Tuple[int, int, int]:
    try:
        rgb = ImageColor.getrgb(color_str)
        if len(rgb) == 3:
            return rgb
        elif len(rgb) == 4:
            return rgb[:3]
    except Exception:
        pass
    raise ValueError(f"无法解析颜色：{color_str}")


def try_find_font() -> Optional[str]:
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def load_font(font_path: Optional[str], font_size: int) -> ImageFont.ImageFont:
    if font_path and Path(font_path).exists():
        return ImageFont.truetype(font_path, font_size)
    auto = try_find_font()
    if auto:
        return ImageFont.truetype(auto, font_size)
    return ImageFont.load_default()


def compute_xy(img_w: int, img_h: int, text_w: int, text_h: int,
               position: str, margin: int) -> Tuple[int, int]:
    pos = position.lower()
    if pos in ("lt", "left-top", "top-left"):
        return margin, margin
    if pos in ("rt", "right-top", "top-right"):
        return img_w - text_w - margin, margin
    if pos in ("lb", "left-bottom", "bottom-left"):
        return margin, img_h - text_h - margin
    if pos in ("rb", "right-bottom", "bottom-right"):
        return img_w - text_w - margin, img_h - text_h - margin
    if pos in ("c", "center", "middle"):
        return (img_w - text_w) // 2, (img_h - text_h) // 2
    return img_w - text_w - margin, img_h - text_h - margin


def draw_watermark(
    image_path: Path,
    text: str,
    font_path: Optional[str],
    font_size: int,
    color: Tuple[int, int, int],
    opacity: int,
    position: str,
    margin: int,
    stroke_width: int,
    stroke_fill: Tuple[int, int, int],
    auto_size_ratio: float = 0.0
) -> Image.Image:
    im = Image.open(image_path).convert("RGBA")
    W, H = im.size

    # 如果设置了自动比例，则覆盖 font_size
    if auto_size_ratio and auto_size_ratio > 0:
        font_size = max(12, int(min(W, H) * float(auto_size_ratio)))

    font = load_font(font_path, font_size)
    dummy_img = Image.new("RGBA", (10, 10))
    d0 = ImageDraw.Draw(dummy_img)
    bbox = d0.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    x, y = compute_xy(W, H, text_w, text_h, position, margin)

    txt_layer = Image.new("RGBA", im.size, (255, 255, 255, 0))
    d = ImageDraw.Draw(txt_layer)
    fill_rgba = (color[0], color[1], color[2], int(max(0, min(255, opacity))))
    stroke_rgba = (stroke_fill[0], stroke_fill[1], stroke_fill[2], int(max(0, min(255, opacity))))

    d.text(
        (x, y),
        text,
        font=font,
        fill=fill_rgba,
        stroke_width=stroke_width,
        stroke_fill=stroke_rgba,
    )
    out = Image.alpha_composite(im, txt_layer)
    return out.convert("RGB")


def process_one(
    image_path: Path,
    out_root: Path, 
    font_path: Optional[str],
    font_size: int,
    color: Tuple[int, int, int],
    opacity: int,
    position: str,
    margin: int,
    stroke_width: int,
    stroke_fill: Tuple[int, int, int],
    fallback_use_mtime: bool,
    auto_size_ratio: float
) -> Optional[Path]:
    exif_date = extract_exif_date(image_path)
    if not exif_date and not fallback_use_mtime:
        print(f"[跳过] {image_path} 无 EXIF 拍摄时间。")
        return None
    if not exif_date and fallback_use_mtime:
        ts = datetime.fromtimestamp(image_path.stat().st_mtime)
        exif_date = ts.strftime("%Y-%m-%d")

    text = exif_date

    # 输出目录固定为 output/
    out_dir = out_root
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = image_path.stem
    ext = image_path.suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"]:
        ext = ".jpg"
    out_path = out_dir / f"{stem}_wm{ext}"

    try:
        out_img = draw_watermark(
            image_path=image_path,
            text=text,
            font_path=font_path,
            font_size=font_size,
            color=color,
            opacity=opacity,
            position=position,
            margin=margin,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
            auto_size_ratio=auto_size_ratio
        )
        save_kwargs = {}
        if out_path.suffix.lower() in (".jpg", ".jpeg"):
            save_kwargs.update(dict(quality=92, subsampling=0, optimize=True))
        out_img.save(out_path, **save_kwargs)
        print(f"[完成] {image_path.name} → {out_path}")
        return out_path
    except Exception as e:
        print(f"[失败] {image_path}: {e}")
        return None


def is_image_file(p: Path) -> bool:
    return p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")


def process_path(
    in_path: Path,
    font_path: Optional[str],
    font_size: int,
    color: Tuple[int, int, int],
    opacity: int,
    position: str,
    margin: int,
    stroke_width: int,
    stroke_fill: Tuple[int, int, int],
    fallback_use_mtime: bool,
    auto_size_ratio: float
):
    if in_path.is_file():
        out_root = in_path.parent.parent / "output" if in_path.parent else Path("output")
        process_one(
            image_path=in_path,
            out_root=out_root,
            font_path=font_path,
            font_size=font_size,
            color=color,
            opacity=opacity,
            position=position,
            margin=margin,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
            fallback_use_mtime=fallback_use_mtime,
            auto_size_ratio=auto_size_ratio
        )
    elif in_path.is_dir():
        out_root = in_path.parent / "output"
        for p in in_path.rglob("*"):
            if p.is_file() and is_image_file(p):
                process_one(
                    image_path=p,
                    out_root=out_root,
                    font_path=font_path,
                    font_size=font_size,
                    color=color,
                    opacity=opacity,
                    position=position,
                    margin=margin,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_fill,
                    fallback_use_mtime=fallback_use_mtime,
                    auto_size_ratio=auto_size_ratio
                )
    else:
        print(f"输入路径不存在：{in_path}")


def build_argparser():
    ap = argparse.ArgumentParser(
        prog="photo-watermark",
        description="为图片批量添加 EXIF 拍摄日期（年月日）文字水印，输出到原目录下的 output 子目录。"
    )
    ap.add_argument("path", help="图片文件或目录路径")
    ap.add_argument("--position", default="rb",
                    choices=["lt", "left-top", "top-left",
                             "rt", "right-top", "top-right",
                             "lb", "left-bottom", "bottom-left",
                             "rb", "right-bottom", "bottom-right",
                             "c", "center", "middle"],
                    help="水印位置（默认 right-bottom）")
    ap.add_argument("--font-size", type=int, default=96, help="字体大小（默认 96）")
    ap.add_argument("--auto-size", type=float, default=0.0,
                    help="按图片短边比例自动决定字体大小（如 0.12 表示短边 12%%，覆盖 --font-size）")
    ap.add_argument("--color", default="#FFFFFF", help="文字颜色，#RRGGBB 或颜色名（默认 #FFFFFF）")
    ap.add_argument("--opacity", type=int, default=220, help="不透明度 0-255（默认 220）")
    ap.add_argument("--margin", type=int, default=20, help="边距像素（默认 20）")
    ap.add_argument("--font", type=str, default=None, help="TrueType 字体路径（可选）")
    ap.add_argument("--stroke-width", type=int, default=2, help="描边宽度（默认 2）")
    ap.add_argument("--stroke-color", default="#000000", help="描边颜色（默认 #000000）")
    ap.add_argument("--fallback-mtime", action="store_true",
                    help="当无 EXIF 日期时使用文件修改时间作为水印日期")
    return ap


def main():
    ap = build_argparser()
    args = ap.parse_args()

    in_path = Path(args.path).expanduser().resolve()
    color = parse_color(args.color)
    stroke_color = parse_color(args.stroke_color)

    process_path(
        in_path=in_path,
        font_path=args.font,
        font_size=args.font_size,
        color=color,
        opacity=max(0, min(255, int(args.opacity))),
        position=args.position,
        margin=max(0, int(args.margin)),
        stroke_width=max(0, int(args.stroke_width)),
        stroke_fill=stroke_color,
        fallback_use_mtime=bool(args.fallback_mtime),
        auto_size_ratio=float(args.auto_size),
    )


if __name__ == "__main__":
    main()