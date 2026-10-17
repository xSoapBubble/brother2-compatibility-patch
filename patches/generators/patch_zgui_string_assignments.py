"""Build-only: three GUI string assignments use the existing Base asCHARPTR.

Input is the installed click-constructor build. Both old and new buffers must
use Base's CRT, so replace the complete inline assignment, including old free.
"""

import pathlib,hashlib,struct,json

from zsol_mouse_payload import _pe

PARENT='99e825e0d2cfccb9303399aa26488f98b5c945ba30b411be2ac994c861d501e1'

SITES=[('SelectSceneMaster.getValue',0x9834,0x988c,0x9845,False),
       ('GUIOptions.getTime',0x20c24,0x20c80,0x20c39,True),
       ('IDrawText.getValue',0x2e14a,0x2e1a6,0x2e15f,True)]

def build(parent):
    assert hashlib.sha256(parent).hexdigest()==PARENT
    b=bytearray(parent);off,imports=_pe(b);pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;base=struct.unpack_from('<I',b,opt+28)[0]
    iat=imports['?asCHARPTR@VariableRef@Nestor@@QAEXPBD@Z'];assert iat==0x447a4
    rr,rs=struct.unpack_from('<II',b,opt+96+5*8);q=off(rr);limit=q+rs;rel=[]
    while q<limit:
        page,size=struct.unpack_from('<II',b,q);assert size>=8
        for p in range(q+8,q+size,2):
            e=struct.unpack_from('<H',b,p)[0]
            if e>>12==3:rel.append(page+(e&4095))
        q+=size
    entries=[]
    for name,start,end,call,seh in SITES:
        assert b[off(call):off(call)+6]==b'\xff\x15'+struct.pack('<I',base+imports['?create@_Variable@Nestor@@QAEXW4VariableTypes@2@@Z'])
        assert [r for r in rel if start<=r<end]==[call+2]
        before=bytes(b[off(start):off(end)])
        prefix=(bytes.fromhex('c744241c00000000') if seh else b'')+bytes.fromhex('53 8bce')
        patch=prefix.ljust(call-start,b'\x90')+b'\xff\x15'+struct.pack('<I',base+iat)
        patch=patch.ljust(end-start,b'\x90');assert len(patch)==end-start
        b[off(start):off(end)]=patch
        entries.append({'name':name,'range':[hex(start),hex(end)],'retained_highlow':hex(call+2),'before_hex':before.hex(),'after_hex':patch.hex()})
    return b,{'parent_sha256':PARENT,'patched_sha256':hashlib.sha256(b).hexdigest(),'sites':entries,'assignment_iat':hex(iat),'status':'candidate; native full getter/repeated assignment tests required'}
