"""Build only: preserve all installed ZSOL fixes and align doSelect string CRT ownership."""

import hashlib, json, pathlib, struct

from zsol_mouse_payload import _pe

PARENT = 'b4ba77c26c786b2e5daaceaf2f37ac2f978197dc6165a8c881dd3fc194d599c7'

START, END = 0x13b48, 0x13b97

def build(parent):
    assert hashlib.sha256(parent).hexdigest() == PARENT
    b = bytearray(parent); off, imports = _pe(b)
    # The exact parent SHA pins this original, untouched instruction range.
    old = parent[off(START):off(END)]
    assert old[:16] == bytes.fromhex('6a028d4c2414895c2414ff15bcf70610')
    iat = imports['??0_Variable@Nestor@@IAE@PBD@Z']; assert iat == 0x6f5fc
    pe = struct.unpack_from('<I', b, 60)[0]; opt = pe + 24
    base = struct.unpack_from('<I', b, opt + 28)[0]
    # Preserve argument footprint, this pointer and the original HIGHLOW operand.
    patch = bytes.fromhex('568d4c2414') + b'\x90' * 5 + b'\xff\x15' + struct.pack('<I', base + iat)
    patch = patch.ljust(END - START, b'\x90')
    reloc_rva, reloc_size = struct.unpack_from('<II', b, opt + 96 + 5 * 8)
    p = off(reloc_rva); within = []
    while p < off(reloc_rva) + reloc_size:
        page, size = struct.unpack_from('<II', b, p); assert size >= 8
        for q in range(p + 8, p + size, 2):
            entry = struct.unpack_from('<H', b, q)[0]; rva = page + (entry & 4095)
            if entry >> 12 == 3 and START <= rva < END: within.append(rva)
        p += size
    assert within == [0x13b54]
    b[off(START):off(END)] = patch
    changed = [i for i, (x, y) in enumerate(zip(parent, b)) if x != y]
    assert all(off(START) <= i < off(END) for i in changed)
    metadata = dict(parent_sha256=PARENT, patched_sha256=hashlib.sha256(b).hexdigest(),
                    rva_range=[hex(START), hex(END)], constructor_iat=hex(iat),
                    retained_highlow=hex(within[0]), changed_bytes=len(changed),
                    before_hex=old.hex(), after_hex=patch.hex(),
                    status='build-only candidate; isolated native probe required')
    return b, metadata
