"""Build the compatibility patch from source on Windows. No game is required.

Use --game to additionally regenerate and verify all five engine DLLs from
your original installation. Build output never installs or launches the game.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import zipfile

from dependencies import locked_tools
from engine import apply_delta, delta, regenerate, sha

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.0'
ZIP_TIME = (2026, 10, 17, 0, 0, 0)
RELEASE_FILES = ['BrotherPatch.exe', 'README-RU.txt', 'DDrawCompat-LICENSE.txt',
    'LICENSE', 'THIRD-PARTY-NOTICES.txt', 'LLVM-LICENSE.txt', 'MinGW-LICENSE.txt', 'Zig-LICENSE.txt']

def stable_zip(path, members):
    """Stored ZIP avoids differing zlib versions changing a signed payload hash."""
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as z:
        for name, data in sorted(members.items()):
            entry = zipfile.ZipInfo(name, ZIP_TIME)
            entry.create_system = 3; entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_STORED
            z.writestr(entry, data)

def execute(args, env=None):
    subprocess.run([str(a) for a in args], cwd=ROOT, env=env, check=True)

def normalize_native_pe(path):
    """Normalize metadata on our freshly linked, unsigned DLLs only."""
    b = bytearray(path.read_bytes()); pe = struct.unpack_from('<I', b, 60)[0]
    if b[:2] != b'MZ' or b[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', b, pe+4)[0] != 0x14c:
        raise ValueError('Expected our x86 PE output')
    opt = pe+24; sections = opt+struct.unpack_from('<H', b, pe+20)[0]
    def offset(rva):
        for i in range(struct.unpack_from('<H', b, pe+6)[0]):
            vs, va, size, raw = struct.unpack_from('<IIII', b, sections+40*i+8)
            if va <= rva < va+size: return raw+rva-va
        raise ValueError('Invalid PE directory')
    struct.pack_into('<I', b, pe+8, 0)
    struct.pack_into('<I', b, opt+64, 0)
    exports = struct.unpack_from('<I', b, opt+96)[0]
    if exports: struct.pack_into('<I', b, offset(exports)+4, 0)
    debug, size = struct.unpack_from('<II', b, opt+96+6*8)
    if debug:
        for at in range(offset(debug), offset(debug)+size, 28): struct.pack_into('<I', b, at+4, 0)
    path.write_bytes(b)

def compile_csharp(compiler, sources, output, references=(), resource=None):
    framework = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework/v4.0.30319'
    args = [compiler, '/nologo', '/noconfig', '/nostdlib+', '/target:winexe',
            '/platform:x86', '/optimize+', '/deterministic+', '/debug-', '/langversion:5',
            '/pathmap:' + str(ROOT) + '=/_/brother2-compatibility-patch', '/out:' + str(output)]
    for name in ['mscorlib', 'System', 'System.Core'] + list(references):
        ref = framework / (name + '.dll')
        if not ref.is_file(): raise RuntimeError('Missing .NET Framework reference: ' + str(ref))
        args.append('/reference:' + str(ref))
    if resource: args.append('/resource:' + str(resource) + ',BrotherPatch.Payload')
    args.extend(sources)
    execute(args)

def native_components(zig, output, cache, include_tests):
    version = subprocess.check_output([str(zig), 'version'], text=True).strip()
    if version != '0.15.2': raise RuntimeError('Unexpected Zig version: ' + version)
    env = os.environ.copy()
    env.update(ZIG_GLOBAL_CACHE_DIR=str(cache / 'zig-global'),
               ZIG_LOCAL_CACHE_DIR=str(output / 'zig-cache'), ZIG_LIB_DIR=str(zig.parent / 'lib'))
    objects = output / 'objects'; objects.mkdir(exist_ok=True)
    common = ['-target', 'x86-windows-gnu', '-O2', '-g0', '-mstackrealign', '-Wall', '-Wextra',
        '-Wno-unused-command-line-argument', '-fno-sanitize=undefined',
        '-ffile-prefix-map=' + str(ROOT) + '=/_/brother2-compatibility-patch']
    sources = ['rea_audio_settings.c', 'rea_audio_engine.c', 'rea_audio_music.c',
               'rea_audio_recovery.c', 'rea_audio_device_proxy.cpp']
    for testing in ([False, True] if include_tests else [False]):
        compiled = []; flags = common + (['-DREA_AUDIO_TEST'] if testing else [])
        for name in sources:
            cpp = name.endswith('.cpp'); obj = objects / (name + ('.test' if testing else '') + '.o')
            args = [zig, 'c++' if cpp else 'cc'] + flags
            if cpp: args += ['-std=c++11', '-fno-exceptions', '-fno-rtti']
            execute(args + ['-c', 'src/runtime/' + name, '-o', obj], env)
            compiled.append(obj)
        target = output / ('rea_audio_test.dll' if testing else 'rea_audio.dll')
        execute([zig, 'c++'] + flags + ['-fno-exceptions', '-fno-rtti', '-shared', '-s'] + compiled + ['-o', target, '-ladvapi32', '-lole32', '-lwinmm'], env)
        normalize_native_pe(target)
    execute([zig, 'cc', '-target', 'x86-windows-gnu', '-O2', '-g0', '-fno-stack-protector',
        '-fno-builtin', '-nostdlib', '-isystem', zig.parent / 'lib/libc/include/any-windows-any',
        '-Wl,--subsystem,windows', '-Wl,--entry,DllMain@12',
        '-s', '-shared', 'src/diagnostics/BrotherCrashHook.c', 'src/diagnostics/BrotherCrashHook.def',
        '-o', output / 'BrotherCrashHook.dll', '-lkernel32'], env)
    normalize_native_pe(output / 'BrotherCrashHook.dll')

def prepare_payload(output, components, wrapper):
    engine = json.loads((ROOT / 'patches/engine-manifest.json').read_text())
    compatibility = json.loads((ROOT / 'patches/compatibility.json').read_text())
    known = json.loads((ROOT / 'patches/known-components.json').read_text())
    upgrades = json.loads((ROOT / 'patches/upgrades.json').read_text())
    blobs = {}; entries = []
    for e in engine['files']:
        path = 'Bin/' + e['name']; blob = 'engine/' + e['name'] + '.b2patch'
        patch = (ROOT / e['patch']).read_bytes()
        if sha(patch) != e['patch_sha256']: raise ValueError('Engine delta changed: ' + path)
        blobs[blob] = patch
        entry = dict(Path=path, Mode='delta', Blob=blob, BaseSha256=e['original_sha256'],
            BaseSize=e['original_size'], Sha256=e['patched_sha256'], Size=e['patched_size'])
        for u in upgrades:
            if u['path'] != path: continue
            data = (ROOT / u['patch']).read_bytes()
            if sha(data) != u['patch_sha256']: raise ValueError('Upgrade delta changed: ' + path)
            name = 'upgrades/' + Path(u['patch']).name; blobs[name] = data
            entry.setdefault('Updates', []).append(dict(Sha256=u['sha256'], Size=u['size'], Blob=name))
        entries.append(entry)
    copies = {
        'Bin/rea_audio.dll': components / 'rea_audio.dll',
        'Bin/BrotherDiagnostics.exe': components / 'BrotherDiagnostics.exe',
        'Bin/BrotherCrashHook.dll': components / 'BrotherCrashHook.dll',
        'Bin/ddraw.dll': wrapper,
        'Bin/DDrawCompat.ini': ROOT / 'resources/DDrawCompat.ini',
        'Start-Brother.cmd': ROOT / 'resources/Start-Brother.cmd',
        'Capture-Diagnostics.cmd': ROOT / 'resources/Capture-Diagnostics.cmd',
        'DIAGNOSTICS-RU.txt': ROOT / 'resources/DIAGNOSTICS-RU.txt',
        'PATCH-README-RU.txt': ROOT / 'resources/README-RU.txt',
        'DDrawCompat-LICENSE.txt': ROOT / 'third_party/ddrawcompat/LICENSE.txt',
        'LICENSE-PATCH.txt': ROOT / 'LICENSE',
        'THIRD-PARTY-NOTICES.txt': ROOT / 'THIRD-PARTY-NOTICES.txt',
        'LLVM-LICENSE.txt': ROOT / 'third_party/toolchain/LLVM-LICENSE.txt',
        'MinGW-LICENSE.txt': ROOT / 'third_party/toolchain/MinGW-LICENSE.txt',
        'Zig-LICENSE.txt': ROOT / 'third_party/toolchain/Zig-LICENSE.txt',
    }
    for path, source in sorted(copies.items()):
        data = source.read_bytes(); name = 'components/' + path
        blobs[name] = data
        entry = dict(Path=path, Mode='copy', Blob=name, BaseSha256=None, BaseSize=0,
                     Sha256=sha(data), Size=len(data))
        versions = [v for v in known.get(path, []) if v['Sha256'] != entry['Sha256']]
        if versions: entry['KnownVersions'] = versions
        entries.append(entry)
    manifest = dict(Id='brother-compatibility', Version=VERSION, Files=entries,
        Requires=compatibility['requires'], Directories=compatibility['directories'])
    blobs['manifest.json'] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    stable_zip(output / 'payload.zip', blobs)
    (output / 'package-manifest.json').write_bytes(blobs['manifest.json'])
    return manifest

def build(output, cache, game=None, include_tests=False):
    if os.name != 'nt': raise RuntimeError('Native source builds require Windows x64')
    output = Path(output).resolve(); cache = Path(cache).resolve()
    if output == ROOT or output in ROOT.parents:
        raise ValueError('Choose a dedicated build subdirectory')
    if (output/'brother.exe').exists() or (output/'Bin/brother.exe').exists():
        raise ValueError('Build output must not be an installed game')
    if ROOT in output.parents and output != ROOT/'build' and ROOT/'build' not in output.parents:
        raise ValueError('Inside this project use the build/ directory')
    output.mkdir(parents=True, exist_ok=True)
    if game: regenerate(game, output / 'engine')
    tools = locked_tools(cache)
    lock = json.loads((ROOT / 'tools/dependencies.lock.json').read_text())
    if sha(tools['ddrawcompat'].read_bytes()) != lock['ddrawcompat']['dll_sha256']:
        raise ValueError('DDrawCompat DLL does not match the official release')
    components = output / 'components'; components.mkdir(exist_ok=True)
    native_components(tools['zig'], components, cache, include_tests)
    compile_csharp(tools['roslyn'], ['src/diagnostics/BrotherDiagnostics.cs'],
        components / 'BrotherDiagnostics.exe', ['System.Management', 'System.IO.Compression', 'System.IO.Compression.FileSystem'])
    prepare_payload(output, components, tools['ddrawcompat'])
    identity = output / 'BuildIdentity.cs'
    identity.write_text('static class BuildIdentity { public const string Version="' + VERSION +
        '"; public const string PayloadSha256="' + sha((output / 'payload.zip').read_bytes()) + '"; }\n')
    dist = output / 'dist'; dist.mkdir(exist_ok=True)
    compile_csharp(tools['roslyn'], ['src/installer/BrotherPatch.cs', identity], dist / 'BrotherPatch.exe',
        ['System.Windows.Forms', 'System.Drawing', 'System.Web.Extensions', 'System.IO.Compression'], output / 'payload.zip')
    for src, name in [('resources/README-RU.txt', 'README-RU.txt'),
                      ('third_party/ddrawcompat/LICENSE.txt', 'DDrawCompat-LICENSE.txt'),
                      ('LICENSE', 'LICENSE'), ('THIRD-PARTY-NOTICES.txt', 'THIRD-PARTY-NOTICES.txt')]:
        shutil.copyfile(ROOT / src, dist / name)
    for name in ['LLVM-LICENSE.txt', 'MinGW-LICENSE.txt', 'Zig-LICENSE.txt']:
        shutil.copyfile(ROOT / 'third_party/toolchain' / name, dist / name)
    release_members = {name:(dist/name).read_bytes() for name in RELEASE_FILES}
    archive = dist / ('Brother-Compatibility-Patch-' + VERSION + '.zip')
    stable_zip(archive, release_members)
    sums = '\n'.join(sha(p.read_bytes()) + '  ' + p.name for p in [dist / 'BrotherPatch.exe', archive]) + '\n'
    (dist / 'SHA256SUMS.txt').write_text(sums, encoding='ascii', newline='\n')
    inputs = {}
    for directory in ['src', 'patches', 'resources', 'third_party', 'tools']:
        for p in sorted((ROOT / directory).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:
                inputs[p.relative_to(ROOT).as_posix()] = sha(p.read_bytes())
    for name in ['LICENSE','THIRD-PARTY-NOTICES.txt','.gitattributes']:
        inputs[name] = sha((ROOT/name).read_bytes())
    info = dict(version=VERSION, toolchain_versions={k:v['version'] for k,v in lock.items()},
        input_sha256=inputs, installer_sha256=sha((dist/'BrotherPatch.exe').read_bytes()),
        archive_sha256=sha(archive.read_bytes()), payload_sha256=sha((output/'payload.zip').read_bytes()),
        components={name:sha((components/name).read_bytes()) for name in ['rea_audio.dll','BrotherCrashHook.dll','BrotherDiagnostics.exe']},
        deterministic_zip='fixed timestamps, order, attributes and ZIP_STORED', engine_regenerated=bool(game))
    (output / 'build-info.json').write_text(json.dumps(info, sort_keys=True, indent=2) + '\n')
    print('Built', archive)
    print('SHA256', info['archive_sha256'])
    return info

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=ROOT/'build')
    p.add_argument('--tools-dir', type=Path, default=ROOT/'.tools')
    p.add_argument('--game', type=Path)
    p.add_argument('--test-components', action='store_true')
    a = p.parse_args()
    build(a.output, a.tools_dir, a.game, a.test_components)
