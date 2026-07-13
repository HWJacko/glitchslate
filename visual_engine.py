from __future__ import annotations

import argparse
import hashlib
import random
import shutil
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


WIDTH = 3840
HEIGHT = 2160


@dataclass(frozen=True)
class RenderResult:
    timestamped_path: Path
    current_path: Path
    score: int
    glitch_factor: float


def calculate_glitch_factor(score: int) -> float:
    return max(0.0, min(1.0, (100 - score) / 100))


def _seed_for(day: str, score: int, seed: int | None = None) -> int:
    if seed is not None:
        return seed
    digest = hashlib.sha256(f"{day}:{score}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _base_canvas(width: int, height: int):
    import numpy as np

    x = np.linspace(0, 1, width, dtype=np.float32)
    y = np.linspace(0, 1, height, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    red = 24 + (xx * 80) + (yy * 20)
    green = 32 + (yy * 120)
    blue = 48 + ((1 - xx) * 160)
    canvas = np.stack([red, green, blue], axis=2)

    line_mask = ((np.sin((xx * 18) + (yy * 10)) > 0.985) | (np.cos((xx * 12) - (yy * 16)) > 0.99))
    canvas[line_mask] = [235, 245, 240]
    return np.clip(canvas, 0, 255).astype(np.uint8)


def _apply_glitch(canvas, glitch_factor: float, rng):
    import numpy as np

    if glitch_factor <= 0:
        return canvas

    height, width, _ = canvas.shape
    glitched = canvas.copy()
    band_count = max(1, int(6 + glitch_factor * 34))
    max_shift = max(1, int(width * 0.08 * glitch_factor))

    for _ in range(band_count):
        band_height = int(rng.integers(8, max(12, int(80 + 180 * glitch_factor))))
        y = int(rng.integers(0, max(1, height - band_height)))
        shift = int(rng.integers(-max_shift, max_shift + 1))
        channel = int(rng.integers(0, 3))
        glitched[y : y + band_height, :, channel] = np.roll(
            glitched[y : y + band_height, :, channel],
            shift,
            axis=1,
        )

    noise_bars = max(1, int(glitch_factor * 16))
    for _ in range(noise_bars):
        band_height = int(rng.integers(4, max(8, int(24 + 90 * glitch_factor))))
        y = int(rng.integers(0, max(1, height - band_height)))
        shade = int(rng.integers(0, 255))
        alpha = min(0.85, 0.2 + glitch_factor * 0.55)
        glitched[y : y + band_height] = (
            glitched[y : y + band_height] * (1 - alpha) + shade * alpha
        ).astype(np.uint8)

    block_count = max(1, int(glitch_factor * 12))
    for _ in range(block_count):
        block_w = int(rng.integers(120, max(130, int(360 + 900 * glitch_factor))))
        block_h = int(rng.integers(80, max(90, int(220 + 500 * glitch_factor))))
        x = int(rng.integers(0, max(1, width - block_w)))
        y = int(rng.integers(0, max(1, height - block_h)))
        region = glitched[y : y + block_h, x : x + block_w]
        region_h, region_w, _ = region.shape
        factor = int(rng.integers(6, max(7, int(8 + 30 * glitch_factor))))
        small = region[::factor, ::factor]
        if small.size == 0:
            continue
        pixelated = np.repeat(np.repeat(small, factor, axis=0), factor, axis=1)
        glitched[y : y + region_h, x : x + region_w] = pixelated[:region_h, :region_w]

    return glitched


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(data, checksum)
    return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", checksum & 0xFFFFFFFF)


def _write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    rows = []
    stride = width * 3
    for y in range(height):
        rows.append(b"\x00" + pixels[y * stride : (y + 1) * stride])
    raw = b"".join(rows)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, level=6))
        + _png_chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _fallback_pixels(width: int, height: int, score: int, day: str, seed: int | None) -> bytes:
    factor = calculate_glitch_factor(score)
    rng = random.Random(_seed_for(day, score, seed))
    pixels = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 3
            pixels[idx] = int(24 + (x / max(1, width - 1)) * 80 + (y / max(1, height - 1)) * 20)
            pixels[idx + 1] = int(32 + (y / max(1, height - 1)) * 120)
            pixels[idx + 2] = int(48 + (1 - (x / max(1, width - 1))) * 160)

    if factor <= 0:
        return bytes(pixels)

    band_count = max(1, int(4 + factor * 16))
    max_shift = max(1, int(width * 0.08 * factor))
    for _ in range(band_count):
        band_height = rng.randint(2, max(3, int(12 + 40 * factor)))
        y0 = rng.randint(0, max(0, height - band_height))
        shift = rng.randint(-max_shift, max_shift)
        channel = rng.randint(0, 2)
        for y in range(y0, min(height, y0 + band_height)):
            row = [pixels[(y * width + x) * 3 + channel] for x in range(width)]
            for x in range(width):
                pixels[(y * width + x) * 3 + channel] = row[(x - shift) % width]

    noise_bars = max(1, int(factor * 8))
    for _ in range(noise_bars):
        band_height = rng.randint(1, max(2, int(8 + 30 * factor)))
        y0 = rng.randint(0, max(0, height - band_height))
        shade = rng.randint(0, 255)
        for y in range(y0, min(height, y0 + band_height)):
            for x in range(width):
                idx = (y * width + x) * 3
                pixels[idx] = shade
                pixels[idx + 1] = shade
                pixels[idx + 2] = shade
    return bytes(pixels)


def render_wallpaper(
    *,
    score: int,
    day: str,
    output_dir: str | Path = "assets",
    timestamp: datetime | None = None,
    width: int = WIDTH,
    height: int = HEIGHT,
    seed: int | None = None,
) -> RenderResult:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    factor = calculate_glitch_factor(score)
    stamp = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
    timestamped = output_path / f"wallpaper_{stamp}.png"
    current = output_path / "wallpaper_current.png"

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        pixels = _fallback_pixels(width, height, score, day, seed)
        _write_png(timestamped, width, height, pixels)
    else:
        rng = np.random.default_rng(_seed_for(day, score, seed))
        canvas = _base_canvas(width, height)
        canvas = _apply_glitch(canvas, factor, rng)
        image = Image.fromarray(canvas, mode="RGB")
        image.save(timestamped)

    shutil.copyfile(timestamped, current)
    return RenderResult(timestamped_path=timestamped, current_path=current, score=score, glitch_factor=factor)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Glitchslate wallpaper.")
    parser.add_argument("--score", type=int, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--output-dir", default="assets")
    parser.add_argument("--width", type=int, default=WIDTH)
    parser.add_argument("--height", type=int, default=HEIGHT)
    args = parser.parse_args()
    result = render_wallpaper(
        score=args.score,
        day=args.date,
        output_dir=args.output_dir,
        width=args.width,
        height=args.height,
    )
    print(result.timestamped_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
