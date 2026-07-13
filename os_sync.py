from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


def set_wallpaper(image_path: str | Path, *, dry_run: bool = False) -> list[str]:
    path = Path(image_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    system = platform.system()
    if system == "Darwin":
        command = [
            "osascript",
            "-e",
            f'tell application "System Events" to tell every desktop to set picture to "{path}"',
        ]
    elif system == "Linux":
        uri = path.as_uri()
        command = ["gsettings", "set", "org.gnome.desktop.background", "picture-uri", uri]
    elif system == "Windows":
        if dry_run:
            return ["ctypes.windll.user32.SystemParametersInfoW", str(path)]
        import ctypes

        ctypes.windll.user32.SystemParametersInfoW(20, 0, str(path), 3)
        return ["ctypes.windll.user32.SystemParametersInfoW", str(path)]
    else:
        raise RuntimeError(f"Unsupported OS for wallpaper sync: {system}")

    if not dry_run:
        subprocess.run(command, check=True)
    return command


def cleanup_old_wallpapers(
    assets_dir: str | Path = "assets",
    *,
    older_than_hours: int = 48,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now()) - timedelta(hours=older_than_hours)
    removed = 0
    for path in Path(assets_dir).glob("wallpaper_*.png"):
        if path.name == "wallpaper_current.png":
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        if modified < cutoff:
            path.unlink()
            removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Set the desktop wallpaper.")
    parser.add_argument("image_path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        command = set_wallpaper(args.image_path, dry_run=args.dry_run)
    except Exception as exc:
        print(f"OS sync failed: {exc}", file=sys.stderr)
        return 1
    cleanup_old_wallpapers(Path(args.image_path).parent)
    if args.dry_run:
        print("dry-run:", " ".join(command))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
