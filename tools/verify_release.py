"""Verify source fingerprints and the exact release allowlist before upload."""
import argparse
import json
from pathlib import Path
import zipfile
from build import ROOT, RELEASE_FILES
from engine import sha

def verify(output):
    output=Path(output).resolve();info=json.loads((output/'build-info.json').read_text())
    for name,expected in info['input_sha256'].items():
        if sha((ROOT/name).read_bytes())!=expected:raise ValueError('Source changed after build: '+name)
    dist=output/'dist';archive=dist/'Brother-Compatibility-Patch-1.0.zip'
    if sha(archive.read_bytes())!=info['archive_sha256']:raise ValueError('Release ZIP hash mismatch')
    if sha((dist/'BrotherPatch.exe').read_bytes())!=info['installer_sha256']:raise ValueError('Installer hash mismatch')
    with zipfile.ZipFile(archive) as z:
        if sorted(z.namelist())!=sorted(RELEASE_FILES) or z.testzip() is not None:
            raise ValueError('Unexpected or damaged release members')
        for name in RELEASE_FILES:
            if z.read(name)!=(dist/name).read_bytes():raise ValueError('Release member mismatch: '+name)
        if z.read('README-RU.txt')!=(ROOT/'resources/README-RU.txt').read_bytes():raise ValueError('Player README changed')
    with zipfile.ZipFile(output/'payload.zip') as z:
        m=json.loads(z.read('manifest.json'));engine=[]
        for e in m['Files']:
            if e['Path'].split('/')[-1] in ['ZBase.dll','ZPlayer.dll','ZSOL.dll','ZGUI.dll','ZGeometry.dll']:
                if e['Mode']!='delta' or z.read(e['Blob'])[:8]!=b'B2PATCH1':raise ValueError('Whole game DLL in payload')
                engine.append(e['Path'])
            if 'rea_audio_test' in e['Path']:raise ValueError('Test-only DLL in payload')
        if len(engine)!=5:raise ValueError('Unexpected engine DLL count')
    return dict(status='passed',archive_sha256=info['archive_sha256'],files=len(RELEASE_FILES),source_fingerprints='match')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'build')
    a=p.parse_args();print(json.dumps(verify(a.output),indent=2))
