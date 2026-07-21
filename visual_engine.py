from __future__ import annotations

import argparse
import shutil
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config import VisualConfig


WIDTH = 3840
HEIGHT = 2160


@dataclass(frozen=True)
class RenderDiagnostics:
    backend: str
    bar_count: int
    latest_day_points: int
    max_day_points: int
    bar_scale_points: float
    status: str
    today_points: int
    gap_days: int
    vignette_mode: str
    sentient_log_present: bool


@dataclass(frozen=True)
class RenderResult:
    timestamped_path: Path
    current_path: Path
    score: int
    glitch_factor: float
    diagnostics: RenderDiagnostics


def calculate_glitch_factor(score: int) -> float:
    return max(0.0, min(1.0, (100 - score) / 100))


def system_status(score: int) -> str:
    if score >= 80:
        return "STABLE"
    if score >= 50:
        return "DRIFTING"
    if score >= 20:
        return "AT RISK"
    return "CRITICAL"


def vignette_mode(score: int) -> str:
    if score > 80:
        return "cyan"
    if score < 50:
        return "warning"
    return "neutral"


def systemd_status_lines(today_points: int, gap_days: int, *, alert_gap_days: int = 3) -> list[str]:
    if today_points > 0:
        return [
            "● kinetic_drive.service - Active (Running) since 4h ago",
            "● cardio_subsystem.status - NOMINAL (98% efficiency)",
            "● motivation_daemon.bin - Active (Running)",
        ]
    if gap_days >= alert_gap_days:
        return [
            "● kinetic_drive.service - Inactive (Dead)",
            "● cardio_subsystem.status - DEGRADED (Low physical input)",
            "⚠ [ERR] motivation_daemon.bin dumped core (Exit code: 127)",
        ]
    return [
        "● kinetic_drive.service - Idle (Monitoring)",
        "● cardio_subsystem.status - WARNING (Awaiting physical input)",
        "● motivation_daemon.bin - Active (Backoff timer)",
    ]


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def _lerp_color(start: tuple[int, int, int], end: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return _lerp(start[0], end[0], t), _lerp(start[1], end[1], t), _lerp(start[2], end[2], t)


def _format_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h{mins:02d}"


def _format_points(points: int) -> str:
    if points >= 1000:
        return f"{points / 1000:.1f}kpt"
    return f"{points}pt"


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


def _fallback_pixels(width: int, height: int, config: VisualConfig) -> bytes:
    bg = _hex_to_rgb(config.bg_color)
    return bytes(bg) * width * height


def _font(size: int):
    from PIL import ImageFont

    candidates = [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rounded_rectangle(draw, xy, radius: int, fill, outline=None, width: int = 1) -> None:
    try:
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
    except AttributeError:
        draw.rectangle(xy, fill=fill, outline=outline)


def _draw_vertical_gradient(draw, xy, radius: int, start_color, end_color) -> None:
    x0, y0, x1, y1 = [int(v) for v in xy]
    height = max(1, y1 - y0)
    for y in range(y0, y1 + 1):
        t = (y - y0) / height
        color = _lerp_color(start_color, end_color, t)
        draw.line([(x0, y), (x1, y)], fill=color)
    _rounded_rectangle(draw, xy, radius=radius, fill=None, outline=start_color, width=max(1, int((x1 - x0) * 0.05)))


def _draw_segment(draw, xy, fill, *, radius: int = 0) -> None:
    if radius > 0:
        _rounded_rectangle(draw, xy, radius=radius, fill=fill)
    else:
        draw.rectangle(xy, fill=fill)


def _draw_centered_text(draw, y: int, text: str, *, width: int, fill, font) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((int((width - (bbox[2] - bbox[0])) / 2), y), text, fill=fill, font=font)


def _draw_vignette(image, score: int) -> None:
    from PIL import Image, ImageDraw

    mode = vignette_mode(score)
    if mode == "neutral":
        color = (0, 0, 0)
        max_alpha = 40
    elif mode == "cyan":
        color = (6, 182, 212)
        max_alpha = 34
    else:
        color = (239, 68, 68) if score < 25 else (245, 158, 11)
        max_alpha = 112 if score < 25 else 84

    width, height = image.size
    steps = max(12, int(min(width, height) * 0.075))
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for step in range(steps):
        alpha = int(max_alpha * (1 - step / steps) ** 1.8)
        if alpha <= 0:
            continue
        draw.rectangle(
            (step, step, width - step - 1, height - step - 1),
            outline=(*color, alpha),
            width=1,
        )
    image.alpha_composite(overlay)


def _label_indices(values: list[int]) -> set[int]:
    indices = {len(values) - 1}
    indices.update(range(4, len(values), 5))
    for index in range(1, len(values) - 1):
        if values[index] > 0 and values[index] >= values[index - 1] and values[index] >= values[index + 1]:
            indices.add(index)
    return indices


def _field(point: Any, name: str, default: Any = 0) -> Any:
    if isinstance(point, dict):
        return point.get(name, default)
    return getattr(point, name, default)


def _coerce_chart_points(points: list[Any], day: str) -> list[dict[str, Any]]:
    if not points:
        return [{"day": day, "run_points": 0, "other_points": 0, "total_points": 0, "is_best": False} for _ in range(30)]
    coerced: list[dict[str, Any]] = []
    for point in points:
        if isinstance(point, tuple) and len(point) == 2:
            point_day, total = point
            run_points = 0
            other_points = int(total)
            is_best = False
        else:
            point_day = str(_field(point, "day", day))
            run_points = int(_field(point, "run_points", 0))
            other_points = int(_field(point, "other_points", 0))
            total = int(_field(point, "total_points", run_points + other_points))
            is_best = bool(_field(point, "is_best", False))
        coerced.append(
            {
                "day": str(point_day),
                "run_points": run_points,
                "other_points": other_points,
                "total_points": int(total),
                "is_best": is_best,
            }
        )
    return coerced


def _format_pace(minutes_per_km: float) -> str:
    if minutes_per_km <= 0:
        return "--"
    minutes = int(minutes_per_km)
    seconds = int(round((minutes_per_km - minutes) * 60))
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d}/km"


def render_wallpaper(
    *,
    score: int,
    day: str,
    output_dir: str | Path = "assets",
    timestamp: datetime | None = None,
    width: int = WIDTH,
    height: int = HEIGHT,
    seed: int | None = None,
    visual_config: VisualConfig | None = None,
    chart_points: list[Any] | None = None,
    streak_days: int = 0,
    streak_pending: bool = False,
    expected_recent_points: float = 1500.0,
    today_points: int = 0,
    gap_days: int = 0,
    last_run_details: Any | None = None,
    sentient_log: str | None = None,
    show_systemd_box: bool = True,
    show_vignette: bool = True,
    systemd_alert_gap_days: int = 3,
) -> RenderResult:
    config = visual_config or VisualConfig(target_resolution=f"{width}x{height}")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    stamp = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
    timestamped = output_path / f"wallpaper_{stamp}.png"
    current = output_path / "wallpaper_current.png"

    points = _coerce_chart_points(chart_points or [], day)
    values = [int(point["total_points"]) for point in points]
    latest_populated_index = next((index for index in range(len(values) - 1, -1, -1) if values[index] > 0), None)
    latest = values[latest_populated_index] if latest_populated_index is not None else 0
    max_points = max(values) if values else 0
    bar_scale = max(float(expected_recent_points), float(max_points), 1.0)
    status = system_status(score)
    vignette = vignette_mode(score) if show_vignette else "off"

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        _write_png(timestamped, width, height, _fallback_pixels(width, height, config))
        backend = "stdlib"
    else:
        bg = _hex_to_rgb(config.bg_color)
        grid = _hex_to_rgb(config.grid_color)
        empty = _hex_to_rgb(config.empty_color)
        text = _hex_to_rgb(config.text_color)
        muted = _hex_to_rgb(config.muted_text_color)
        alert = _hex_to_rgb(config.alert_color)
        run_color = _hex_to_rgb(config.active_gradient[0])
        other_color = _hex_to_rgb(config.active_gradient[1])
        best_color = (245, 208, 66)

        image = Image.new("RGBA", (width, height), (*bg, 255))
        draw = ImageDraw.Draw(image)
        title_font = _font(max(18, int(height * 0.026)))
        meta_font = _font(max(14, int(height * 0.021)))
        label_font = _font(max(10, int(height * 0.015)))
        small_font = _font(max(9, int(height * 0.012)))
        log_font = _font(max(10, int(height * 0.014)))

        chart_left = int(width * 0.09)
        chart_right = int(width * 0.91)
        chart_top = int(height * 0.38)
        chart_bottom = int(height * 0.74)
        chart_width = chart_right - chart_left
        chart_height = chart_bottom - chart_top

        for step in range(6):
            y = chart_bottom - int(chart_height * step / 5)
            draw.line((chart_left, y, chart_right, y), fill=grid, width=max(1, width // 960))

        count = max(1, len(points))
        slot = chart_width / count
        bar_width = max(4, int(slot * 0.62))
        radius = max(3, bar_width // 2)
        label_every = {latest_populated_index} if latest_populated_index is not None else set()

        for index, point in enumerate(points):
            point_day = str(point["day"])
            run_points = int(point["run_points"])
            other_points = int(point["other_points"])
            point_value = int(point["total_points"])
            center_x = chart_left + (index + 0.5) * slot
            x0 = int(center_x - bar_width / 2)
            x1 = int(center_x + bar_width / 2)
            empty_y0 = chart_top
            empty_y1 = chart_bottom
            _rounded_rectangle(draw, (x0, empty_y0, x1, empty_y1), radius=radius, fill=empty)
            if point_value > 0:
                ratio = min(1.0, point_value / bar_scale)
                fill_height = max(24, int(chart_height * ratio))
                y0 = chart_bottom - fill_height
                run_height = int(fill_height * (run_points / point_value)) if point_value else 0
                other_height = fill_height - run_height
                if other_height > 0:
                    _draw_segment(draw, (x0, chart_bottom - other_height, x1, chart_bottom), other_color, radius=radius if run_height <= 0 else 0)
                if run_height > 0:
                    run_y0 = y0
                    run_y1 = chart_bottom - other_height
                    _draw_segment(draw, (x0, run_y0, x1, run_y1), run_color, radius=radius if other_height <= 0 else 0)
                if bool(point["is_best"]):
                    _rounded_rectangle(draw, (x0 - 2, y0 - 2, x1 + 2, chart_bottom + 2), radius=radius + 2, fill=None, outline=best_color, width=max(1, width // 960))
            if index in label_every and point_value > 0:
                label = _format_points(point_value)
                bbox = draw.textbbox((0, 0), label, font=label_font)
                lx = int(center_x - (bbox[2] - bbox[0]) / 2)
                ly = chart_top - int(height * 0.035)
                draw.text((lx, ly), label, fill=text if index == count - 1 else muted, font=label_font)
            if index % 5 == 4 or index == count - 1:
                day_label = point_day[5:]
                bbox = draw.textbbox((0, 0), day_label, font=small_font)
                draw.text((int(center_x - (bbox[2] - bbox[0]) / 2), chart_bottom + int(height * 0.02)), day_label, fill=muted, font=small_font)

        status_color = alert if score < 50 else text
        header_x = int(width * 0.07)
        header_y = int(height * 0.08)
        lines = [
            "// GLITCHSLATE TELEMETRY CORE v1.0 //",
            "-------------------------------------------",
            f"CURRENT SCORE : [ {score:3d} / 100  ]",
            f"ACTIVE STREAK : [ {streak_days:3d} DAYS{'*' if streak_pending else ' '} ]",
            f"TODAY VOLUME  : [ {_format_points(today_points):>8} ]",
            f"LATEST DAY    : [ {_format_points(latest):>8} ]",
            f"SYSTEM STATUS : [ {status:<9} ]",
        ]
        for offset, line in enumerate(lines):
            fill = status_color if "SYSTEM STATUS" in line else text if offset in {0, 2, 3, 4} else muted
            draw.text((header_x, header_y + offset * int(height * 0.04)), line, fill=fill, font=title_font if offset == 0 else meta_font)

        footer = f"DAILY TOTALS // TARGET {int(round(expected_recent_points))}pt/DAY // RUN + OTHER // WINDOW END {day}"
        draw.text((chart_left, int(height * 0.80)), footer, fill=muted, font=small_font)

        if last_run_details is not None:
            detail_x = int(width * 0.62)
            detail_y = int(height * 0.845)
            detail_lines = [
                "LAST RUN",
                f"{_field(last_run_details, 'day', '--')}  {_field(last_run_details, 'distance_km', 0):.2f}km",
                f"{_format_minutes(int(_field(last_run_details, 'duration_minutes', 0)))}  {_format_pace(float(_field(last_run_details, 'pace_min_per_km', 0)))}",
                f"{_format_points(int(_field(last_run_details, 'points', 0)))}  +{_field(last_run_details, 'elevation_m', 0):.0f}m elev",
            ]
            for offset, line in enumerate(detail_lines):
                fill = text if offset == 0 else muted
                draw.text((detail_x, detail_y + offset * max(11, int(height * 0.017))), line, fill=fill, font=small_font)

        if show_systemd_box:
            systemd_lines = systemd_status_lines(today_points, gap_days, alert_gap_days=systemd_alert_gap_days)
            log_x = chart_left
            log_y = int(height * 0.845)
            line_step = max(11, int(height * 0.017))
            for offset, line in enumerate(systemd_lines):
                fill = alert if "ERR" in line or "DEGRADED" in line else muted
                draw.text((log_x, log_y + offset * line_step), line, fill=fill, font=small_font)

        if sentient_log:
            _draw_centered_text(
                draw,
                int(height * 0.94),
                sentient_log,
                width=width,
                fill=text,
                font=log_font,
            )

        if show_vignette:
            _draw_vignette(image, score)

        image.convert("RGB").save(timestamped)
        backend = "pillow"

    shutil.copyfile(timestamped, current)
    return RenderResult(
        timestamped_path=timestamped,
        current_path=current,
        score=score,
        glitch_factor=calculate_glitch_factor(score),
        diagnostics=RenderDiagnostics(
            backend=backend,
            bar_count=len(points),
            latest_day_points=latest,
            max_day_points=max_points,
            bar_scale_points=bar_scale,
            status=status,
            today_points=today_points,
            gap_days=gap_days,
            vignette_mode=vignette,
            sentient_log_present=bool(sentient_log),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Glitchslate telemetry wallpaper.")
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
    print(
        "diagnostics="
        f"backend={result.diagnostics.backend} "
        f"bar_count={result.diagnostics.bar_count} "
        f"latest_day_points={result.diagnostics.latest_day_points} "
        f"max_day_points={result.diagnostics.max_day_points} "
        f"bar_scale_points={result.diagnostics.bar_scale_points:.2f} "
        f"status={result.diagnostics.status} "
        f"vignette={result.diagnostics.vignette_mode}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
