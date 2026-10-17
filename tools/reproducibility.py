"""Build from two separate allowlisted source copies and compare release bytes."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from build import ROOT
from engine import sha

COPY_DIRS=['src','tools','patches','resources','third_party']
COPY_FILES=['LICENSE','THIRD-PARTY-NOTICES.txt','.gitattributes']

def source_copy(destination):
    destination.mkdir(parents=True,exist_ok=True)
    for name in COPY_DIRS:
        shutil.copytree(ROOT/name,destination/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'),dirs_exist_ok=True)
    for name in COPY_FILES:shutil.copyfile(ROOT/name,destination/name)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tools-dir',type=Path,default=ROOT/'.tools')
    p.add_argument('--output',type=Path,default=ROOT/'build/reproducibility')
    a=p.parse_args();cache=a.tools_dir.resolve();output=a.output.resolve()
    if output==ROOT or output in ROOT.parents:raise ValueError('Choose a dedicated build subdirectory')
    snapshots=[];run=output/uuid.uuid4().hex
    for name in ['source-a','different source directory b']:
        source=run/name;source_copy(source)
        subprocess.run([sys.executable,str(source/'tools/build.py'),'--tools-dir',str(cache)],check=True)
        build=source/'build';members=['payload.zip','components/rea_audio.dll','components/BrotherCrashHook.dll',
            'components/BrotherDiagnostics.exe','dist/BrotherPatch.exe','dist/Brother-Compatibility-Patch-1.0.zip']
        snapshots.append({n:sha((build/n).read_bytes()) for n in members})
    if snapshots[0]!=snapshots[1]:raise AssertionError(dict(first=snapshots[0],second=snapshots[1]))
    report=dict(status='passed',scope='Two independent source roots in the same pinned Windows/toolchain environment',sha256=snapshots[0])
    (output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
