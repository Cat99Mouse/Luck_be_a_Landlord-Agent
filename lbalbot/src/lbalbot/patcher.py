"""Patch Luck be a Landlord's Godot PCK with the LBALBot bridge."""

from __future__ import annotations

import shutil
from pathlib import Path

from .pck import GodotPck

MAIN_SCENE = "res://Main.tscn"
BRIDGE_BEGIN = "# LBALBOT_BRIDGE_BEGIN"
BRIDGE_END = "# LBALBOT_BRIDGE_END"


def _resource_text(name: str) -> str:
    return (Path(__file__).parent / name).read_text(encoding="utf-8")


def _escape_for_tscn_script(source: str) -> str:
    """Escape text for insertion inside a Godot text scene quoted string."""
    return source.replace("\\", "\\\\").replace('"', '\\"').rstrip() + "\n\n"


def patch_main_scene(scene: str, bridge_source: str | None = None) -> str:
    """Inject the bridge into the first script resource in Main.tscn."""
    bridge = _escape_for_tscn_script(bridge_source or _resource_text("bridge.gd"))

    if BRIDGE_BEGIN in scene:
        start = scene.index(BRIDGE_BEGIN)
        end = scene.index(BRIDGE_END, start) + len(BRIDGE_END)
        while end < len(scene) and scene[end] in "\r\n":
            end += 1
        return scene[:start] + bridge + scene[end:]

    init_marker = "\nfunc _init():"
    ready_marker = "\nfunc _ready():"
    process_marker = "\nfunc _process(delta):"

    if init_marker not in scene:
        raise ValueError("Could not find main func _init() in Main.tscn")
    if ready_marker not in scene:
        raise ValueError("Could not find main func _ready() in Main.tscn")
    if process_marker not in scene:
        raise ValueError("Could not find main func _process(delta) in Main.tscn")

    scene = scene.replace(init_marker, "\n" + bridge + init_marker, 1)
    scene = scene.replace(
        ready_marker,
        ready_marker + "\n\tlbalbot_setup()",
        1,
    )
    scene = scene.replace(
        process_marker,
        process_marker + "\n\tlbalbot_poll()",
        1,
    )
    return scene


def patch_pck(
    pck_path: str | Path,
    output_path: str | Path | None = None,
    backup: bool = True,
) -> Path:
    """Patch a Luck be a Landlord PCK in place or to an output path."""
    source = Path(pck_path)
    target = Path(output_path) if output_path else source
    pck = GodotPck.read(source)
    if pck.godot_version[:2] != (3, 4):
        raise ValueError(f"Unexpected Godot version: {pck.godot_version}")

    original = pck.get_text(MAIN_SCENE)
    patched = patch_main_scene(original)
    if patched == original:
        return target

    pck.replace_text(MAIN_SCENE, patched)
    if target == source and backup:
        backup_path = source.with_suffix(source.suffix + ".bak")
        if not backup_path.exists():
            shutil.copy2(source, backup_path)
    pck.write(target)
    return target
