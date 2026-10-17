"""Build a narrow missing-save-preview draw guard; retain the background."""

import hashlib, json, pathlib, struct

from zsol_mouse_payload import Asm, _pe

PARENT = '05e59243138ca5e4d513abe54b56f5a56343f6f7f8054ff2bb766b4d41d61086'

def build(parent):
    assert hashlib.sha256(parent).hexdigest() == PARENT
    b = bytearray(parent)
    off, imports = _pe(b)
    assert imports['?exists@GFile@@QBE_NXZ'] == 0x6f77c
    pe = struct.unpack_from('<I', b, 60)[0]
    st = pe + 24 + struct.unpack_from('<H', b, pe + 20)[0]
    hdr = next(st+40*i for i in range(struct.unpack_from('<H', b, pe+6)[0])
               if b[st+40*i:st+40*i+8] == b'.reacode')
    vs, va, size, raw = struct.unpack_from('<IIII', b, hdr+8)
    start = (vs+15) & ~15
    a = Asm(va+start)
    a.label('guard')
    a.emit('60 8b45ec 85c0')  # pushad; redirected GFile string, EBP-14
    a.branch('0f84', 'normal')
    a.emit('8bd0')
    a.label('scan')
    a.emit('8a08 84c9')
    a.branch('0f84', 'basename')
    a.emit('80f95c')
    a.branch('0f84', 'separator')
    a.emit('80f92f')
    a.branch('0f85', 'advance')
    a.label('separator')
    a.emit('8d5001')
    a.label('advance')
    a.emit('40')
    a.branch('e9', 'scan')
    a.label('basename')
    a.emit('2bc2 83f80a')
    a.branch('0f85', 'normal')
    a.emit('8b02 0d20202020 3d6c6f6164')
    a.branch('0f85', 'normal')
    a.emit('807a045f')
    a.branch('0f85', 'normal')
    a.emit('8a4205 2c31 3c05')
    a.branch('0f87', 'normal')
    a.emit('8b4206 0d20202020 3d2e626d70')
    a.branch('0f85', 'normal')
    a.emit('8d4dec')
    a.iat(0x6f77c)  # native redirected GFile::exists
    a.emit('84c0 61')
    a.branch('0f84', 'missing')
    a.branch('e9', 'replay')
    a.label('normal')
    a.emit('61')
    a.label('replay')
    a.emit('8b55ec 8b4e3c')
    a.branch('e9', 0x369a2)
    a.label('missing')
    # Image never initialized/drawn. Keep dirty flag so a newly created real
    # preview can load normally; use native GString and interface cleanup.
    a.emit('8d4dec')
    a.iat(0x6f83c)
    a.emit('c645fc02')
    a.branch('e9', 0x36d16)
    payload = a.finish()
    assert start+len(payload) <= size
    assert not any(b[raw+vs:raw+start+len(payload)])
    rva = 0x3699c
    original = bytes.fromhex('8b55ec8b4e3c')
    assert b[off(rva):off(rva)+6] == original
    patch = b'\xe9'+struct.pack('<i', a.rva-rva-5)+b'\x90'
    b[off(rva):off(rva)+6] = patch
    b[raw+start:raw+start+len(payload)] = payload
    struct.pack_into('<I', b, hdr+8, start+len(payload))
    m = dict(parent_sha256=PARENT, candidate_sha256=hashlib.sha256(b).hexdigest(),
             payload_rva=hex(a.rva), payload_size=len(payload), payload_hex=payload.hex(),
             labels={k:hex(v) for k,v in a.labels.items()},
             changes=[dict(rva=hex(rva), original=original.hex(), patched=patch.hex())],
             removed_relocations=[], status='built; isolated native validation pending',
             behavior='After native path redirection, only absent load_[1-6].bmp skips image initialization and blit; native cleanup retains menu background. Existing previews and other images retain native code.',
             limitation='Missing preview existence is checked while visible each frame; no file-error exceptions or changed caching state. Real previews remain reloadable after saving.')
    return b, m
