"""Version-checked Brother ZSOL compatibility repairs; original preserved.

Glass: unlock the old vertex buffer before IndexedPrimitive::init destroys it,
and clear the original SEH cleanup state so it cannot unlock it a second time.
Mouse payload is built in zsol_mouse_payload.py, with separate RX/RW sections.
"""

import hashlib, importlib, json, pathlib, shutil, struct, sys

from patch_zplayer_mouse_queue import Asm, align

EXPECTED='7bc117fa33f29c414785c352c6bb1e824e25eadc7239f41ed01c12968be8f075'

def sha(b): return hashlib.sha256(b).hexdigest()

def build(original, mouse=True, mouse_gain=0.5):
    b=bytearray(original)
    u16=lambda p:struct.unpack_from('<H',b,p)[0]
    u32=lambda p:struct.unpack_from('<I',b,p)[0]
    pe=u32(0x3c);coff=pe+4;opt=coff+20;n=u16(coff+2);st=opt+u16(coff+16)
    assert u16(coff)==0x14c and u16(opt)==0x10b
    sections=[]
    for i in range(n):
        p=st+40*i;sections.append((u32(p+12),u32(p+8),u32(p+20),u32(p+16)))
    def off(rva):
        for va,vs,raw,sz in sections:
            if va<=rva<va+sz:return raw+rva-va
        raise ValueError(hex(rva))
    fa=u32(opt+36);sa=u32(opt+32)
    codeva=align(max(va+max(vs,sz) for va,vs,raw,sz in sections),sa)
    datava=codeva+0x1000
    a=Asm(codeva)
    helpers={}
    for name,vb,seh in [('glass_start',0xa0,0x1bc),('glass_break_face',0xdc,0xfc)]:
        helpers[name]=a.rva+len(a.b);a.label(name)
        a.emit('9c 60 8b8424');a.dword(vb)  # original stack +64 after save
        a.emit('8b10 50 ff5210')           # old VB->Unlock(old VB)
        a.emit('c68424');a.dword(seh);a.emit('00')
        a.emit('61 9d');a.address(0x6f928);a.emit('ff20') # tailcall original init
    payload=bytearray(a.finish());data=b'';mouse_info=None
    hooks=[];removed_wanted={0x52feb,0x5283b}
    def hook(rva,original_hex,patched):
        pos=off(rva);exp=bytes.fromhex(original_hex)
        assert b[pos:pos+len(exp)]==exp,(hex(rva),b[pos:pos+len(exp)].hex())
        assert len(patched)==len(exp)
        b[pos:pos+len(exp)]=patched
        hooks.append({'rva':hex(rva),'offset':pos,'original':exp.hex(),'patched':patched.hex()})
    for rva,name in [(0x52fe9,'glass_start'),(0x52839,'glass_break_face')]:
        hook(rva,'ff15 28f90610',b'\xe8'+struct.pack('<i',helpers[name]-(rva+5))+b'\x90')
    for rva in [0x53051,0x52858]:
        hook(rva,'50 8b08 ff5110',b'\x90'*6)
    if mouse:
        motion=importlib.import_module('zsol_mouse_payload')
        # API finalized in the motion module; it returns PIC code and exact hooks.
        result=motion.build_mouse(codeva+len(payload),datava,original,gain=mouse_gain)
        payload.extend(result['code']);data=result['data'];mouse_info=result['metadata']
        for h in result['hooks']:hook(h['rva'],h['original'],h['patched'])
        removed_wanted.update(result.get('remove_relocations',[]))
    assert len(payload)<=0x1000,'Code would overlap data section'
    removed=[];p=off(u32(opt+96+5*8));end=p+u32(opt+100+5*8)
    while p<end:
        page,block=struct.unpack_from('<II',b,p)
        if block<8:raise ValueError('Invalid relocation block')
        for ep in range(p+8,p+block,2):
            e=u16(ep);rva=page+(e&0xfff)
            if e>>12==3 and rva in removed_wanted:
                struct.pack_into('<H',b,ep,0);removed.append(rva)
        p+=block
    assert set(removed)==removed_wanted,(removed,removed_wanted)
    add_sections=[(b'.reacode',codeva,payload,0x60000020)]
    if data:add_sections.append((b'.readata',datava,data,0xc0000040))
    assert st+40*(n+len(add_sections))<=min(s[2] for s in sections)
    assert not any(b[st+40*n:st+40*(n+len(add_sections))])
    section_info=[]
    for i,(name,va,contents,flags) in enumerate(add_sections):
        raw=align(len(b),fa);size=align(len(contents),fa)
        b.extend(b'\0'*(raw-len(b)));b.extend(contents);b.extend(b'\0'*(size-len(contents)))
        struct.pack_into('<8sIIIIIIHHI',b,st+40*(n+i),name,len(contents),va,size,raw,0,0,0,0,flags)
        section_info.append({'name':name.decode(),'rva':hex(va),'offset':raw,'length':len(contents)})
        if flags&0x20:struct.pack_into('<I',b,opt+4,u32(opt+4)+size)
        else:struct.pack_into('<I',b,opt+8,u32(opt+8)+size)
    struct.pack_into('<H',b,coff+2,n+len(add_sections))
    struct.pack_into('<I',b,opt+56,align(add_sections[-1][1]+len(add_sections[-1][2]),sa))
    struct.pack_into('<I',b,opt+64,0)
    manifest={'original_sha256':sha(original),'patched_sha256':sha(b),'hooks':hooks,
        'helpers':{k:hex(v) for k,v in helpers.items()},'sections':section_info,
        'removed_relocations':[hex(v) for v in removed],'mouse':mouse_info}
    return b,manifest
