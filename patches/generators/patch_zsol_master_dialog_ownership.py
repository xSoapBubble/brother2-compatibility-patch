"""Build only: INnCMaster releases its SOL-owned POD dialog vector before GUI base dtor."""

import hashlib,json,pathlib,struct

from zsol_mouse_payload import Asm,_pe

PARENT='70fcab77ed5494f866c536f12f6e1abb2ccf251a3031384c07f1b86db4744f71'

def build(parent):
    assert hashlib.sha256(parent).hexdigest()==PARENT
    b=bytearray(parent);off,_=_pe(b)
    u16=lambda p:struct.unpack_from('<H',b,p)[0];u32=lambda p:struct.unpack_from('<I',b,p)[0]
    pe=u32(60);opt=pe+24;st=opt+u16(pe+20)
    hdr=next(st+40*i for i in range(u16(pe+6)) if b[st+40*i:st+40*i+8]==b'.reacode')
    vs,va,sz,raw=struct.unpack_from('<IIII',b,hdr+8);assert u32(hdr+36)==0x60000020
    start=(vs+15)&~15;a=Asm(va+start);a.label('master_dialog_cleanup')
    # ECX=whole+b4. Dialog vector=whole+90: count94, cap98, dataa0.
    a.emit('51 57 8b79ec c741ec00000000 c741e000000000 c741e400000000 85ff')
    a.branch('0f84','base_dtor');a.emit('57');a.branch('e8',0x61d76);a.emit('83c404')
    a.label('base_dtor');a.emit('5f 59');a.address(0x6fc90);a.emit('ff20')
    code=a.finish();assert start+len(code)<=sz and not any(b[raw+vs:raw+start+len(code)])
    b[raw+start:raw+start+len(code)]=code;struct.pack_into('<I',b,hdr+8,start+len(code))
    hook=0x3d9e4;old=bytes.fromhex('ff1590fc0610');assert b[off(hook):off(hook)+6]==old
    change=b'\xe8'+struct.pack('<i',a.rva-hook-5)+b'\x90';b[off(hook):off(hook)+6]=change
    rr,rs=struct.unpack_from('<II',b,opt+96+5*8);p=off(rr);removed=[]
    while p<off(rr)+rs:
        page,size=struct.unpack_from('<II',b,p);assert size>=8
        for q in range(p+8,p+size,2):
            ent=u16(q)
            if ent>>12==3 and page+(ent&4095)==0x3d9e6:
                struct.pack_into('<H',b,q,0);removed.append('0x3d9e6')
        p+=size
    assert removed==['0x3d9e6']
    return b,dict(parent_sha256=PARENT,patched_sha256=hashlib.sha256(b).hexdigest(),
        payload_rva=hex(a.rva),payload_hex=code.hex(),payload_size=len(code),
        hook_rva=hex(hook),hook_before=old.hex(),hook_after=change.hex(),removed_relocations=removed,
        status='build-only candidate; native complete GUI base lifecycle/ASLR tests required')
