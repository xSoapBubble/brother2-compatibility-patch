"""Test source/installer without game data; --game and --audio are opt-in."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from build import ROOT, VERSION, stable_zip, compile_csharp
from dependencies import locked_tools
from engine import delta, sha, regenerate, original_bin
from verify_release import verify

def snapshot(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}

def run_cli(exe, command, folder, expected=0):
    r=subprocess.run([str(exe),command,str(folder)],capture_output=True,timeout=30)
    if r.returncode!=expected:
        raise AssertionError((command,r.returncode,r.stdout.decode('utf-8-sig'),r.stderr.decode('utf-8-sig')))
    return json.loads(r.stdout.decode('utf-8-sig')) if expected==0 else r.stderr.decode('utf-8-sig')

def synthetic_installer(work, compiler):
    old=b'original synthetic engine data';new=b'corrected synthetic engine data'
    component=b'new synthetic component';legacy=b'previous synthetic component'
    anchor=b'synthetic executable anchor; never executed'
    payload=work/'synthetic.zip';identity=work/'BuildIdentity.cs';exe=work/'SyntheticInstaller.exe'
    manifest=dict(Id='brother-compatibility',Version=VERSION,Directories=['Maps','Sounds','Textures'],
        Requires=[dict(Path='Bin/brother.exe',Sha256=sha(anchor),Size=len(anchor))],Files=[
            dict(Path='Bin/Engine.dll',Mode='delta',Blob='engine.patch',BaseSha256=sha(old),BaseSize=len(old),Sha256=sha(new),Size=len(new)),
            dict(Path='Bin/Component.dll',Mode='copy',Blob='component',Sha256=sha(component),Size=len(component),
                 KnownVersions=[dict(Sha256=sha(legacy),Size=len(legacy))])])
    stable_zip(payload,{'manifest.json':json.dumps(manifest).encode(),'engine.patch':delta(old,new),'component':component})
    identity.write_text('static class BuildIdentity { public const string Version="1.0"; public const string PayloadSha256="'+sha(payload.read_bytes())+'"; }')
    compile_csharp(compiler,['src/installer/BrotherPatch.cs',identity],exe,
        ['System.Windows.Forms','System.Drawing','System.Web.Extensions','System.IO.Compression'],payload)
    def fixture(name,previous=False):
        root=work/name;(root/'Bin').mkdir(parents=True)
        (root/'Bin/brother.exe').write_bytes(anchor);(root/'Bin/Engine.dll').write_bytes(old)
        (root/'Bin/personal.sav').write_bytes(b'personal save sentinel')
        if previous:(root/'Bin/Component.dll').write_bytes(legacy)
        for d in ['Maps','Sounds','Textures']:
            (root/d).mkdir();(root/d/'sentinel.txt').write_bytes(b'own synthetic resource')
        return root
    clean=fixture('Синтетическая игра с пробелами');before=snapshot(clean)
    assert run_cli(exe,'--check',clean)['Status']=='compatible' and snapshot(clean)==before
    assert run_cli(exe,'--install',clean)['Changed']==2
    assert (clean/'Bin/Engine.dll').read_bytes()==new and (clean/'Bin/Component.dll').read_bytes()==component
    assert (clean/'Bin/personal.sav').read_bytes()==b'personal save sentinel'
    assert run_cli(exe,'--verify',clean/'Bin')['Status']=='verified'
    after=snapshot(clean);assert run_cli(exe,'--install',clean)['Changed']==0 and snapshot(clean)==after
    previous=fixture('Known previous component',True)
    assert run_cli(exe,'--install',previous)['Changed']==2
    reject=fixture('Unknown component');(reject/'Bin/Component.dll').write_bytes(b'foreign component')
    before=snapshot(reject);run_cli(exe,'--install',reject,2);assert snapshot(reject)==before
    bad=fixture('Modified engine');(bad/'Bin/Engine.dll').write_bytes(b'foreign engine')
    before=snapshot(bad);run_cli(exe,'--install',bad,2);assert snapshot(bad)==before
    wrong=fixture('Modified executable');(wrong/'Bin/brother.exe').write_bytes(b'foreign executable')
    before=snapshot(wrong);run_cli(exe,'--install',wrong,2);assert snapshot(wrong)==before
    locked=fixture('Transaction rollback',True);before=snapshot(locked)
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    k.CreateFileW.restype=ctypes.c_void_p;k.CloseHandle.argtypes=[ctypes.c_void_p]
    h=k.CreateFileW(str(locked/'Bin/Component.dll'),0x80000000,1,None,3,0,None)
    if h in (None,ctypes.c_void_p(-1).value):raise OSError(ctypes.get_last_error())
    try:run_cli(exe,'--install',locked,1)
    finally:k.CloseHandle(h)
    assert snapshot(locked)==before and not list(locked.glob('.BrotherPatch*'))
    tampered=work/'tampered.zip';tampered.write_bytes(payload.read_bytes()+b'changed')
    broken=work/'TamperedInstaller.exe'
    compile_csharp(compiler,['src/installer/BrotherPatch.cs',identity],broken,
        ['System.Windows.Forms','System.Drawing','System.Web.Extensions','System.IO.Compression'],tampered)
    before=snapshot(wrong);run_cli(broken,'--install',wrong,1);assert snapshot(wrong)==before
    harness=work/'InstallerHarness.exe'
    compile_csharp(compiler,['tests/InstallerHarness.cs'],harness,['System.Windows.Forms','System.Drawing'])
    r=subprocess.run([str(harness),str(exe),str(work/'ui-preview.png'),str(work/'Isolated desktop'),str(clean)],timeout=30,capture_output=True)
    if r.returncode:
        raise AssertionError(('InstallerHarness',r.returncode,r.stdout.decode('utf-8',errors='replace'),r.stderr.decode('utf-8',errors='replace')))
    return dict(status='passed',source='same installer source, synthetic payload only',cases=11,
                ui_preview=str((work/'ui-preview.png').resolve()))

def audio_tests(work, compiler, output):
    helper=output/'components/rea_audio_test.dll'
    if not helper.exists():raise RuntimeError('Run build.py --test-components first')
    for name,args in [('AudioDeviceProxyProbe',[str(helper),'routes']),
                      ('DirectMusicProxyInitProbe',['proxy',str(helper),'10'])]:
        exe=work/(name+'.exe')
        compile_csharp(compiler,['tests/native/'+name+'.cs'],exe)
        r=subprocess.run([str(exe)]+args,capture_output=True,timeout=45)
        (work/(name+'.txt')).write_bytes(r.stdout+r.stderr)
        if r.returncode:raise AssertionError((name,r.returncode,r.stdout,r.stderr))
    return dict(status='passed',scope='own native processes; synthetic route fingerprints; verified zero PCM at -10000 only')

def diagnostic_component_test(work,compiler,output):
    exe=work/'CrashHookNoMonitorProbe.exe'
    compile_csharp(compiler,['tests/native/CrashHookNoMonitorProbe.cs'],exe)
    r=subprocess.run([str(exe),str(output/'components/BrotherCrashHook.dll')],capture_output=True,timeout=15)
    (work/'crash-hook-no-monitor.txt').write_bytes(r.stdout+r.stderr)
    if r.returncode:raise AssertionError(('CrashHookNoMonitorProbe',r.returncode,r.stdout,r.stderr))
    return dict(status='passed',scope='Own process; version/export ABI and harmless initialization/unload without a diagnostics monitor')

def licensed_test(work, output, game, compiler):
    source=original_bin(game).parent
    regenerate(source,work/'regenerated-engine')
    copy=work/'Licensed original game copy';shutil.copytree(source,copy)
    exe=output/'dist/BrotherPatch.exe'
    before=snapshot(copy);assert run_cli(exe,'--check',copy)['Status']=='compatible' and snapshot(copy)==before
    run_cli(exe,'--install',copy);assert run_cli(exe,'--verify',copy)['Status']=='verified'
    after=snapshot(copy);assert run_cli(exe,'--install',copy)['Changed']==0 and snapshot(copy)==after
    manifest=json.loads((output/'package-manifest.json').read_text())
    for e in manifest['Files']:assert sha((copy/e['Path']).read_bytes())==e['Sha256']
    changed={e['Path'] for e in manifest['Files']}
    assert all(after[n]==b for n,b in before.items() if n not in changed)
    exe=work/'ClockOriginProbe.exe';compile_csharp(compiler,['tests/native/ClockOriginProbe.cs'],exe)
    for mode in [[],['relocated']]:
        r=subprocess.run([str(exe),str(copy/'Bin/ZBase.dll'),'candidate']+mode,capture_output=True,timeout=30)
        (work/('clock-'+('relocated'if mode else'preferred')+'.txt')).write_bytes(r.stdout+r.stderr)
        if r.returncode:raise AssertionError(('ClockOriginProbe',r.returncode,r.stdout,r.stderr))
    return dict(status='passed',original_input_read_only=True,game_started=False)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'build')
    p.add_argument('--tools-dir',type=Path,default=ROOT/'.tools')
    p.add_argument('--game',type=Path)
    p.add_argument('--audio',action='store_true')
    a=p.parse_args();output=a.output.resolve();cache=a.tools_dir.resolve()
    subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=ROOT,check=True)
    tools=locked_tools(cache)
    work=output/'checks'/uuid.uuid4().hex;work.mkdir(parents=True)
    report={'source_tests':'passed','release':verify(output),'synthetic_installer':synthetic_installer(work,tools['roslyn'])}
    report['diagnostic_component']=diagnostic_component_test(work,tools['roslyn'],output)
    if a.game:report['licensed_game']=licensed_test(work,output,a.game,tools['roslyn'])
    if a.audio:report['audio']=audio_tests(work,tools['roslyn'],output)
    (output/'check-results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
