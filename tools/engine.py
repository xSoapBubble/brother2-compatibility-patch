"""Read-only original inputs -> authored x86 patch generators -> patched bytes.

All functions operate on bytes. The command line writes only into --output.
Never point that output into an installed game or this source tree.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'patches/generators'))
MAX_FILE = 64 * 1024 * 1024

def sha(data):
    return hashlib.sha256(data).hexdigest()

def delta(old, new):
    """Canonical B2PATCH1 format used by the source-available installer."""
    original = old[:len(new)] + bytes(max(0, len(new) - len(old)))
    spans = []; i = 0
    while i < len(new):
        if original[i] == new[i]:
            i += 1; continue
        start = i; i += 1; last = i
        while i < len(new):
            if original[i] != new[i]: last = i + 1
            if i - last >= 24: break
            i += 1
        spans.append((start, new[start:last])); i = last
    blob = bytearray(b'B2PATCH1' + struct.pack('<ii', len(new), len(spans)))
    for offset, data in spans:
        blob.extend(struct.pack('<ii', offset, len(data))); blob.extend(data)
    return bytes(blob)

def apply_delta(original, patch):
    if len(patch) < 16 or patch[:8] != b'B2PATCH1':
        raise ValueError('Invalid patch header')
    size, count = struct.unpack_from('<ii', patch, 8)
    if not 0 <= size <= MAX_FILE or not 0 <= count <= 100000:
        raise ValueError('Invalid patch limits')
    result = bytearray(original[:size] + bytes(max(0, size - len(original))))
    at = 16; end = 0
    for _ in range(count):
        if at + 8 > len(patch): raise ValueError('Truncated patch record')
        start, n = struct.unpack_from('<ii', patch, at); at += 8
        if start < end or n <= 0 or start > size or n > size - start or at + n > len(patch):
            raise ValueError('Invalid patch range')
        result[start:start+n] = patch[at:at+n]; at += n; end = start + n
    if at != len(patch): raise ValueError('Trailing patch data')
    return bytes(result)

STEPS = {
    'ZBase.dll': ['patch_zbase_allocator', 'patch_clock_origin'],
    'ZPlayer.dll': ['patch_zplayer_mouse_queue', 'patch_zplayer_frame_pacing',
        'patch_zplayer_ui_lifecycle_gate', 'patch_startup_message_loop',
        ('patch_alt_system_menu', {'suppress_all_keymenu': True}),
        'patch_zplayer_deferred_window_move', 'patch_zplayer_prestep_keys',
        'patch_zplayer_prestep_focus'],
    'ZSOL.dll': ['patch_zsol_compatibility', 'patch_zsol_pitch_limit',
        'patch_zsol_select_string', 'patch_zsol_radar_ownership',
        'patch_zsol_master_dialog_ownership', 'patch_zsol_explosion_serialization',
        'patch_empty_slot_previews', 'patch_save_tooltip_position',
        'patch_zsol_zoom_hold', 'patch_zsol_jump_ground_band'],
    'ZGUI.dll': ['patch_zgui_gameplay_hit_test', 'patch_zgui_click_string',
        'patch_zgui_string_assignments', 'patch_text_clip_bounds_v2',
        ('patch_audio_bridges', {'name': 'ZGUI'}),
        'patch_zgui_preview_decoder', 'patch_rangefinder_bounds'],
    'ZGeometry.dll': [('patch_audio_bridges', {'name': 'ZGeometry'}),
        'patch_audio_device_proxy'],
}

def generate(name, original):
    data = original; evidence = []
    for item in STEPS[name]:
        module, options = item if isinstance(item, tuple) else (item, {})
        options = dict(options); label = module
        builder = importlib.import_module(module).build
        before = sha(data)
        if 'name' in options:
            data, _ = builder(options.pop('name'), data, **options)
        else:
            data, _ = builder(data, **options)
        data = bytes(data)
        evidence.append(dict(generator=label, input_sha256=before, output_sha256=sha(data)))
    return data, evidence

def original_bin(path):
    path = Path(path).resolve()
    return path / 'Bin' if (path / 'Bin').is_dir() else path

def regenerate(game, output):
    source = original_bin(game); output = Path(output).resolve()
    if output == source or source in output.parents or output == ROOT or output in ROOT.parents:
        raise ValueError('Output must be a separate build folder, outside the game')
    if (output/'brother.exe').exists() or (output/'Bin/brother.exe').exists():
        raise ValueError('Output must not be another installed game')
    if ROOT in output.parents and output != ROOT/'build' and ROOT/'build' not in output.parents:
        raise ValueError('Inside this project use the build/ directory')
    manifest = json.loads((ROOT / 'patches/engine-manifest.json').read_text())
    # Validate every input before creating any output.
    originals = {}
    for e in manifest['files']:
        b = (source / e['name']).read_bytes()
        if len(b) != e['original_size'] or sha(b) != e['original_sha256']:
            raise ValueError('Unsupported original DLL: ' + e['name'])
        originals[e['name']] = b
    output.mkdir(parents=True, exist_ok=True); reports = []
    for e in manifest['files']:
        name = e['name']; original = originals[name]
        result, steps = generate(name, original)
        if sha(result) != e['patched_sha256']:
            raise ValueError('Generator output differs from the release: ' + name)
        patch = delta(original, result)
        if patch != (ROOT / e['patch']).read_bytes():
            raise ValueError('Generated delta differs from the reviewed delta: ' + name)
        if apply_delta(original, patch) != result:
            raise ValueError('Delta round trip failed: ' + name)
        (output / name).write_bytes(result)
        reports.append(dict(name=name, steps=steps, patched_sha256=sha(result), delta_sha256=sha(patch)))
    (output / 'engine-build.json').write_text(json.dumps(reports, indent=2) + '\n')
    return reports

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    for row in regenerate(a.game, a.output): print(row['name'], row['patched_sha256'])
