#!/usr/bin/env python3
"""Tune the title's own settings.xml for framerate, with a backup.

The game keeps its settings in
%LOCALAPPDATA%\\victory\\data\\<titleid>\\storage\\settings\\settings.xml.
This edits only that file; victory's VICTORY_* variables stay separate.

Profiles:
    maxfps    640x480 output, uncapped FPS, VSync off, RT/SSR/grass/LOD down
    balanced  1280x720 output, uncapped FPS, lighter quality cuts
    restore   put the newest backup back

Usage:
    python tools/tweak_game_settings.py --dry-run
    python tools/tweak_game_settings.py --profile maxfps
    python tools/tweak_game_settings.py --profile maxfps --force
    python tools/tweak_game_settings.py --restore
    python tools/tweak_game_settings.py --set graphics.desiredFPS=90
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def default_settings_path() -> str:
    """The title's settings.xml under %LOCALAPPDATA%\\victory\\data."""
    local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    root = local / "victory" / "data"
    found = sorted(root.glob("*/storage/settings/settings.xml"))
    if found:
        return str(found[0])
    return str(root / "<title-id>" / "storage/settings/settings.xml")


DEFAULT_SETTINGS = default_settings_path()

# Dotted paths are element paths from the XML root.  Values are written as the
# `value` attribute exactly as given.
PROFILES = {
    "maxfps": {
        # Video: 640x480 output, no 30 fps cap, no VSync.
        "video.uiResolution.width": "640",
        "video.uiResolution.height": "480",
        "video.resolutionFullscreen.width": "640",
        "video.resolutionFullscreen.height": "480",
        "video.frameRateLimit": "0",
        "video.vSync": "0",
        "graphics.desiredFPS": "120",
        "graphics.anisotropicFiltering": "0",
        "graphics.graphicsQualityPreset": "0.000000",
        # The expensive, CPU/GPU heavy world work.
        "advancedGraphics.decorationResolutionShift": "2",
        "advancedGraphics.directionalScreenSpaceShadowQuality": "0.000000",
        "advancedGraphics.grassLod": "0.000000",
        "advancedGraphics.lodScale": "0.600000",
        "advancedGraphics.smallCullThreshold": "2.000000",
        "advancedGraphics.maxTexUpgradesPerFrame": "1",
        "advancedGraphics.texLodScale_Global": "2.000000",
        "advancedGraphics.texLodScale_Buildings": "2.000000",
        "advancedGraphics.texLodScale_Objects": "2.000000",
        "advancedGraphics.texLodScale_HD": "2.000000",
        "advancedGraphics.manualMipBias": "0.000000",
        # Effects that cost a lot and are cosmetic.
        "advancedGraphics.motionBlur": "false",
        "advancedGraphics.rtDynamicShadows": "false",
        "advancedGraphics.shadowParticleShadows": "false",
        "advancedGraphics.sharpenEnabled": "false",
        "advancedGraphics.ssroSampleCount": "0",
        "advancedGraphics.waterReflectionResX": "256",
        "advancedGraphics.waterReflectionResY": "128",
        "advancedGraphics.waterReflectionSSR": "false",
    },
    "balanced": {
        "video.uiResolution.width": "1280",
        "video.uiResolution.height": "720",
        "video.resolutionFullscreen.width": "1280",
        "video.resolutionFullscreen.height": "720",
        "video.frameRateLimit": "0",
        "video.vSync": "0",
        "graphics.desiredFPS": "120",
        "graphics.anisotropicFiltering": "0",
        "graphics.graphicsQualityPreset": "0.000000",
        "advancedGraphics.grassLod": "0.400000",
        "advancedGraphics.lodScale": "0.800000",
        "advancedGraphics.smallCullThreshold": "1.500000",
        "advancedGraphics.maxTexUpgradesPerFrame": "2",
        "advancedGraphics.motionBlur": "false",
        "advancedGraphics.rtDynamicShadows": "false",
        "advancedGraphics.shadowParticleShadows": "false",
        "advancedGraphics.ssroSampleCount": "1",
        "advancedGraphics.waterReflectionResX": "384",
        "advancedGraphics.waterReflectionResY": "192",
        "advancedGraphics.waterReflectionSSR": "false",
    },
}

# The same performance cuts, but textures/geometry stay sharp.  The heavy
# pixel work (RT shadows, grass, SSR, water SSR, motion blur) stays off; the
# texture LOD and mip-bias cuts that made maxfps look blurry are undone.
PROFILES["sharp"] = dict(
    PROFILES["maxfps"],
    **{
        "video.uiResolution.width": "1920",
        "video.uiResolution.height": "1080",
        "video.resolutionFullscreen.width": "1920",
        "video.resolutionFullscreen.height": "1080",
        "graphics.anisotropicFiltering": "4",
        "advancedGraphics.decorationResolutionShift": "1",
        "advancedGraphics.lodScale": "1.000000",
        "advancedGraphics.smallCullThreshold": "1.000000",
        "advancedGraphics.maxTexUpgradesPerFrame": "5",
        "advancedGraphics.texLodScale_Global": "1.000000",
        "advancedGraphics.texLodScale_Buildings": "1.000000",
        "advancedGraphics.texLodScale_Objects": "1.000000",
        "advancedGraphics.texLodScale_HD": "1.000000",
        "advancedGraphics.manualMipBias": "-1.500000",
        "advancedGraphics.sharpenEnabled": "true",
        "advancedGraphics.fsrSharpen": "0.500000",
    },
)


def victory_running() -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq victory.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
    ).stdout
    return "victory.exe" in out.lower()


def find(root: ET.Element, dotted: str):
    return root.find("/".join(dotted.split(".")))


def apply_profile(root: ET.Element, settings: dict[str, str]) -> list[str]:
    changes = []
    for dotted, value in settings.items():
        elem = find(root, dotted)
        if elem is None:
            raise SystemExit(f"settings.xml has no element {dotted!r}")
        old = elem.get("value")
        if old != value:
            elem.set("value", value)
            changes.append(f"{dotted}: {old} -> {value}")
    return changes


def newest_backup(path: Path):
    backups = sorted(path.parent.glob(path.name + ".bak-*"))
    return backups[-1] if backups else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=DEFAULT_SETTINGS)
    parser.add_argument("--profile", choices=sorted(PROFILES))
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="override one dotted setting (repeatable)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.is_file():
        print(f"no settings file at {path}", file=sys.stderr)
        return 1

    if args.restore:
        backup = newest_backup(path)
        if backup is None:
            print(f"no backup beside {path}", file=sys.stderr)
            return 1
        shutil.copy2(backup, path)
        print(f"restored {backup} -> {path}")
        return 0

    if not args.profile and not args.set:
        parser.error("choose --profile and/or --set")

    if victory_running() and not args.force:
        print(
            "victory.exe is running; stop it first (or pass --force). "
            "The game may overwrite settings.xml when it exits.",
            file=sys.stderr,
        )
        return 2

    tree = ET.parse(path)
    root = tree.getroot()
    settings = dict(PROFILES.get(args.profile, {}))
    for item in args.set:
        key, sep, value = item.partition("=")
        if not sep or not key:
            parser.error(f"bad --set {item!r}")
        settings[key] = value

    changes = apply_profile(root, settings)
    if not changes:
        print("settings already match; nothing to do")
        return 0
    for change in changes:
        print(change)
    if args.dry_run:
        print(f"dry run: {len(changes)} changes, nothing written")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(path.name + f".bak-{stamp}")
    shutil.copy2(path, backup)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"backup  {backup}")
    print(f"wrote   {path} ({len(changes)} changes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
