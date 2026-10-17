"""Audit the tracked allowlist before upload. Never reads credentials or logs."""
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
DIRS={'src','tools','patches','resources','third_party','tests','docs','.github'}
FILES={'README.md','CONTRIBUTING.md','LICENSE','THIRD-PARTY-NOTICES.txt','.gitignore','.gitattributes'}

def audit():
    git=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True)
    if git.returncode==0:
        names=[n for n in git.stdout.decode('utf-8').split('\0') if n]
    else:
        names=[p.relative_to(ROOT).as_posix() for folder in DIRS for p in (ROOT/folder).rglob('*')
            if p.is_file() and '__pycache__'not in p.parts]+[n for n in FILES if (ROOT/n).exists()]
    if not names:raise RuntimeError('No source files selected')
    total=0
    for name in names:
        path=Path(name)
        if path.parts[0] not in DIRS and name not in FILES:raise ValueError('Unexpected public path: '+name)
        if path.suffix.lower()in ['.exe','.dll','.pdb','.dmp','.sav','.save_db','.log','.game_db','.main_db','.zip','.7z','.nupkg']:
            raise ValueError('Binary/game/private file selected: '+name)
        data=(ROOT/path).read_bytes();total+=len(data)
        if data[:2]==b'MZ':raise ValueError('Whole PE image in source tree: '+name)
        if path.suffix=='.b2patch':
            if not data.startswith(b'B2PATCH1'):raise ValueError('Unexpected binary patch: '+name)
            continue
        # Values of credentials, rather than variable names or login examples.
        if re.search(rb'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b',data):
            raise ValueError('Credential-shaped value in '+name)
        if name!='tools/audit_public_tree.py' and path.suffix not in ['.txt']:
            drive=b'E:'; old_workspace=b'Bratik'
            if drive+b'\\'+old_workspace in data or drive+b'/'+old_workspace in data or b'C:\\Users\\' in data:
                raise ValueError('Private workspace path in '+name)
    return dict(status='passed',files=len(names),bytes=total,scope='Tracked source allowlist; no original PE/game/save/report files; credential-pattern scan')

if __name__=='__main__':print(json.dumps(audit(),indent=2))
