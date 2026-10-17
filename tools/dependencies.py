"""Fetch only pinned public build tools, verifying every downloaded archive."""
import hashlib
import json
import os
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def locked_tools(cache):
    cache = Path(cache).resolve(); cache.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / 'tools/dependencies.lock.json').read_text())
    result = {}
    for name, e in lock.items():
        archive = cache / e['archive']
        if not archive.exists() or digest(archive) != e['sha256']:
            temporary = archive.with_suffix(archive.suffix + '.downloading')
            try:
                request = urllib.request.Request(e['url'], headers={'User-Agent': 'BrotherCompatibilityPatch-source-build'})
                with urllib.request.urlopen(request, timeout=120) as response, temporary.open('wb') as output:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block: break
                        output.write(block)
                if digest(temporary) != e['sha256']: raise ValueError('Dependency checksum mismatch: ' + name)
                os.replace(temporary, archive)
            finally:
                if temporary.exists(): temporary.unlink()
        directory = cache / name
        stamp = directory / '.verified-archive-sha256'
        if not stamp.exists() or stamp.read_text() != e['sha256']:
            directory.mkdir(exist_ok=True)
            with zipfile.ZipFile(archive) as z:
                for info in z.infolist():
                    target = (directory / info.filename).resolve()
                    if directory not in target.parents: raise ValueError('Unsafe dependency archive path')
                    if info.is_dir(): target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(z.read(info))
            stamp.write_text(e['sha256'])
        result[name] = directory / e['entry']
        if not result[name].is_file(): raise ValueError('Missing dependency entry point: ' + name)
    return result
