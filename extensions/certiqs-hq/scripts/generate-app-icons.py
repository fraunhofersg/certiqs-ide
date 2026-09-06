#!/usr/bin/env python3
"""Build certiqs app icons from HQ logo SVGs.

Mac .icns artwork follows the Apple macOS App Icon template:
- 1024x1024 master canvas
- 824pt rounded well centered with 100pt inset so Dock / menu-bar
  icons match neighboring apps (full-bleed squircles read too large)
- superellipse (~22% continuous corner) on that well
- 10% content safe zone inside the well
- transparent pixels outside the rounded frame

Electron cannot use Icon Composer / system layer masking, so the
Apple shape is applied in the flattened ICNS/ICO masters.
"""

from __future__ import annotations

import math
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOGO = ROOT / "extensions/certiqs-hq/media/assets/logo/SVG"
HQ_OUT = ROOT / "extensions/certiqs-hq/media/assets/app-icons"
WORKBENCH = ROOT / "src/vs/workbench/browser/media"
RESOURCES = ROOT / "resources"

# Apple macOS App Icon template: 824pt well on a 1024 canvas.
CANVAS = 1024
ICON_WELL = 824
ICON_INSET = (CANVAS - ICON_WELL) / 2
SQUIRCLE_N = 5
SAFE_ZONE = 0.10
LOGO_BOX = ICON_WELL * (1 - 2 * SAFE_ZONE) * 0.86
LOGO_ASPECT = 500.01 / 461.75

VARIANTS = (
    ("color-on-white", "certiqs-logo-color.svg", "#ffffff"),
    ("black-on-white", "certiqs-logo-black.svg", "#ffffff"),
    ("white-on-black", "certiqs-logo-white.svg", "#000000"),
)

ICONSET_SIZES = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def superellipse_path(size: float = ICON_WELL, inset: float = ICON_INSET, n: float = SQUIRCLE_N, samples: int = 196) -> str:
    radius = size / 2
    pts: list[tuple[float, float]] = []
    for i in range(samples):
        angle = 2 * math.pi * i / samples
        cos_t, sin_t = math.cos(angle), math.sin(angle)
        x = radius * math.copysign(abs(cos_t) ** (2 / n), cos_t) + radius + inset
        y = radius * math.copysign(abs(sin_t) ** (2 / n), sin_t) + radius + inset
        pts.append((x, y))
    commands = [f"M{pts[0][0]:.3f},{pts[0][1]:.3f}"]
    commands.extend(f"L{x:.3f},{y:.3f}" for x, y in pts[1:])
    commands.append("Z")
    return " ".join(commands)


def wrap_logo(source: Path, background: str, clip_id: str) -> str:
    inner = source.read_text()
    inner = re.sub(r"<\?xml[^>]+\?>", "", inner).strip()
    logo_w = LOGO_BOX
    logo_h = LOGO_BOX / LOGO_ASPECT
    logo_x = (CANVAS - logo_w) / 2
    logo_y = (CANVAS - logo_h) / 2
    inner = inner.replace(
        "<svg ",
        f'<svg x="{logo_x:.3f}" y="{logo_y:.3f}" width="{logo_w:.3f}" height="{logo_h:.3f}" ',
        1,
    )
    path = superellipse_path()
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS} {CANVAS}">\n'
        "  <defs>\n"
        f'    <clipPath id="{clip_id}"><path d="{path}"/></clipPath>\n'
        "  </defs>\n"
        f'  <g clip-path="url(#{clip_id})">\n'
        f'    <rect width="{CANVAS}" height="{CANVAS}" fill="{background}"/>\n'
        f"    {inner}\n"
        "  </g>\n"
        "</svg>\n"
    )


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def write_ico(path: Path, png_paths: list[Path]) -> None:
    images: list[tuple[int, int, bytes]] = []
    for png in png_paths:
        data = png.read_bytes()
        width, height = png_size(data)
        images.append((width, height, data))
    count = len(images)
    offset = 6 + 16 * count
    chunks = [struct.pack("<HHH", 0, 1, count)]
    blobs: list[bytes] = []
    for width, height, data in images:
        chunks.append(
            struct.pack(
                "<BBBBHHII",
                width if width < 256 else 0,
                height if height < 256 else 0,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        blobs.append(data)
        offset += len(data)
    path.write_bytes(b"".join(chunks) + b"".join(blobs))


def rasterize(svg: Path, dest: Path, size: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["rsvg-convert", "-w", str(size), "-h", str(size), "-o", str(dest), str(svg)],
        check=True,
    )


def resize_png(src: Path, dest: Path, size: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["sips", "-z", str(size), str(size), str(src), "--out", str(dest)],
        check=True,
        capture_output=True,
    )


def build_icns(master: Path, dest: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for name, size in ICONSET_SIZES:
            resize_png(master, iconset / name, size)
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest)], check=True)


def main() -> None:
    HQ_OUT.mkdir(parents=True, exist_ok=True)
    (RESOURCES / "certiqs").mkdir(parents=True, exist_ok=True)
    (RESOURCES / "darwin").mkdir(parents=True, exist_ok=True)
    (RESOURCES / "win32").mkdir(parents=True, exist_ok=True)
    (RESOURCES / "linux").mkdir(parents=True, exist_ok=True)

    masters: dict[str, Path] = {}
    for name, logo, background in VARIANTS:
        svg_text = wrap_logo(LOGO / logo, background, f"apple-icon-{name}")
        hq_svg = HQ_OUT / f"{name}.svg"
        wb_svg = WORKBENCH / f"certiqs-app-icon-{name}.svg"
        hq_svg.write_text(svg_text)
        wb_svg.write_text(svg_text)

        master = RESOURCES / "certiqs" / f"app-icon-{name}.png"
        rasterize(hq_svg, master, 1024)
        masters[name] = master
        resize_png(master, HQ_OUT / f"{name}.png", 256)

    default = masters["color-on-white"]
    default_svg = HQ_OUT / "color-on-white.svg"
    shutil.copyfile(default_svg, WORKBENCH / "code-icon.svg")
    extra_svgs = (
        ROOT / "extensions/github-authentication/media/code-icon.svg",
        ROOT / "src/vs/sessions/browser/media/vscode-icon.svg",
    )
    for dest in extra_svgs:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(default_svg, dest)
    shutil.copyfile(default, RESOURCES / "linux" / "code.png")
    resize_png(default, RESOURCES / "win32" / "code_150x150.png", 150)
    resize_png(default, RESOURCES / "win32" / "code_70x70.png", 70)

    with tempfile.TemporaryDirectory() as tmp:
        ico_pngs = []
        for size in ICO_SIZES:
            png = Path(tmp) / f"{size}.png"
            resize_png(default, png, size)
            ico_pngs.append(png)
        write_ico(RESOURCES / "win32" / "code.ico", ico_pngs)

    icns = RESOURCES / "darwin" / "code.icns"
    build_icns(default, icns)

    electron_root = ROOT / ".build" / "electron"
    if electron_root.exists():
        for app in electron_root.glob("*.app"):
            dest = app / "Contents" / "Resources" / f"{app.stem}.icns"
            if dest.parent.is_dir():
                shutil.copyfile(icns, dest)

    out_media = ROOT / "out" / "vs" / "workbench" / "browser" / "media"
    if out_media.is_dir():
        for name in (
            "code-icon.svg",
            "certiqs-app-icon-color-on-white.svg",
            "certiqs-app-icon-black-on-white.svg",
            "certiqs-app-icon-white-on-black.svg",
        ):
            src = WORKBENCH / name
            if src.exists():
                shutil.copyfile(src, out_media / name)

    print("generated app icons")


if __name__ == "__main__":
    main()
