"""Build-only: use the imported ZBase string Variable constructor in playSound.

Preserves the installed gameplay routing patch and its relocation table.
"""

import hashlib,json,pathlib,struct

from zsol_mouse_payload import _pe

PARENT='2ce335544e93bb465031828bfe2def03969cdb7c45e9c04b8db86c6a67646d07'

START,END=0x1ced4,0x1cf28

OLD=bytes.fromhex('6a028d4c2414c644244004895c2414ff15ac4704108bfe83c9ff33c0f2aef7d151e8a1d301008b4c24148bfe83c40489410883c9ff33c0f2ae8b442410f7d12bf98bd18bf78b7808c1e902f3a58bca83e103f3a4')

def build(parent):
    assert hashlib.sha256(parent).hexdigest()==PARENT
    b=bytearray(parent);off,imports=_pe(b)
    pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;base=struct.unpack_from('<I',b,opt+28)[0]
    assert b[off(START):off(END)]==OLD and len(OLD)==END-START
    iat=imports['??0_Variable@Nestor@@IAE@PBD@Z'];assert iat==0x44794
    # PUSH ESI keeps the same 4-byte argument footprint as original PUSH 2.
    # The constructor zeros this VariableRef and allocates/copies its string
    # through the same CRT which later disposes it. Preserve original EH state4.
    prefix=bytes.fromhex('56 8d4c2414 c644244004')+b'\x90'*5
    assert len(prefix)==15
    patch=prefix+b'\xff\x15'+struct.pack('<I',base+iat)
    patch=patch.ljust(END-START,b'\x90')
    # Keep the sole HIGHLOW in this block exactly at the call operand1cee5.
    reloc_rva,reloc_size=struct.unpack_from('<II',b,opt+96+5*8)
    p=off(reloc_rva);limit=p+reloc_size;within=[]
    while p<limit:
        page,size=struct.unpack_from('<II',b,p);assert size>=8
        for q in range(p+8,p+size,2):
            entry=struct.unpack_from('<H',b,q)[0];rva=page+(entry&4095)
            if entry>>12==3 and START<=rva<END:within.append(rva)
        p+=size
    assert within==[0x1cee5]
    b[off(START):off(END)]=patch
    changed=[i for i,(x,y) in enumerate(zip(parent,b)) if x!=y]
    assert all(off(START)<=i<off(END) for i in changed)
    return b,{'parent_sha256':PARENT,'patched_sha256':hashlib.sha256(b).hexdigest(),
        'rva_range':[hex(START),hex(END)],'constructor_iat':hex(iat),
        'retained_highlow':'0x1cee5','changed_bytes':len(changed),
        'before_hex':OLD.hex(),'after_hex':patch.hex(),'status':'candidate; native allocation ownership and lifecycle checks required'}
