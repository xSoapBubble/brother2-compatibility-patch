import importlib
import json
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from engine import apply_delta, delta, sha, STEPS

class PatchFormatTests(unittest.TestCase):
    def test_round_trip_growing_shrinking_and_sparse_files(self):
        for old, new in [(b'',b''), (b'',b'abc'), (b'abc',b''), (b'abcdef',b'abXdeY'),
                         (bytes(range(256))*4,b'new'+bytes(range(256))*4+b'end'),
                         (b'A'*4096,b'A'*100+b'Z'+b'A'*3995)]:
            with self.subTest(size=(len(old),len(new))): self.assertEqual(apply_delta(old,delta(old,new)),new)

    def test_rejects_malformed_ranges_counts_and_trailing_data(self):
        header=lambda size,count:b'B2PATCH1'+struct.pack('<ii',size,count)
        samples=[b'',b'notapatch',header(-1,0),header(2,-1),header(2,100001),
                 header(2,1),header(2,1)+struct.pack('<ii',0,3)+b'abc',
                 header(2,1)+struct.pack('<ii',-1,1)+b'a',
                 header(2,1)+struct.pack('<ii',0,0),header(0,0)+b'trailing',
                 header(3,2)+struct.pack('<ii',1,2)+b'ab'+struct.pack('<ii',1,1)+b'c']
        for patch in samples:
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):apply_delta(b'abc',patch)

    def test_canonical_delta_is_stable(self):
        a=b'original'+bytes(500);b=bytearray(a);b[12:19]=b'patched'
        self.assertEqual(delta(a,b),delta(a,bytes(b)))

class SourceIntegrityTests(unittest.TestCase):
    def test_five_engine_deltas_match_manifest(self):
        m=json.loads((ROOT/'patches/engine-manifest.json').read_text())
        self.assertEqual({e['name'] for e in m['files']},set(STEPS))
        for e in m['files']:
            p=ROOT/e['patch'];self.assertEqual(sha(p.read_bytes()),e['patch_sha256'])
            self.assertEqual(p.read_bytes()[:8],b'B2PATCH1')
            self.assertEqual(struct.unpack_from('<i',p.read_bytes(),8)[0],e['patched_size'])

    def test_explicit_upgrade_deltas_are_intact(self):
        for e in json.loads((ROOT/'patches/upgrades.json').read_text()):
            self.assertEqual(sha((ROOT/e['patch']).read_bytes()),e['patch_sha256'])
            self.assertIn(Path(e['path']).name,STEPS)

    def test_all_generators_import_without_machine_specific_files(self):
        sys.path.insert(0,str(ROOT/'patches/generators'))
        names={i[0] if isinstance(i,tuple) else i for steps in STEPS.values() for i in steps}
        for name in names:self.assertTrue(callable(importlib.import_module(name).build))

    def test_component_preimages_are_hash_and_size_only(self):
        m=json.loads((ROOT/'patches/known-components.json').read_text())
        for path,versions in m.items():
            self.assertNotIn('..',Path(path).parts)
            for v in versions:
                self.assertEqual(set(v),{'Sha256','Size'})
                self.assertEqual(len(bytes.fromhex(v['Sha256'])),32)
                self.assertGreater(v['Size'],0)

    def test_public_sources_have_no_old_workspace_paths(self):
        for folder in ['src','tools','patches/generators']:
            for p in (ROOT/folder).rglob('*'):
                if p.suffix in ['.py','.c','.cpp','.h','.cs']:
                    b=p.read_bytes()
                    drive=b'E:'; old_workspace=b'Bratik'
                    self.assertNotIn(drive+b'\\'+old_workspace,b,str(p))
                    self.assertNotIn(drive+b'/'+old_workspace,b,str(p))
                    self.assertNotIn(b'C:\\Users\\',b,str(p))

if __name__=='__main__':unittest.main()
