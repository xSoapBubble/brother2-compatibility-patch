"""Build-only RGB screenshot decoder repair; never writes installed binaries."""

import hashlib,json,pathlib,struct

from zsol_mouse_payload import Asm,_pe

PARENT='a27623c262f48e2fa71a095e5be89d7d77fb240e4e54c274186df0b891737adb'

align=lambda x,n:(x+n-1)&~(n-1)

def build(parent):
    assert hashlib.sha256(parent).hexdigest()==PARENT
    b=bytearray(parent);off,imports=_pe(b)
    u16=lambda p:struct.unpack_from('<H',b,p)[0]
    u32=lambda p:struct.unpack_from('<I',b,p)[0]
    pe=u32(60);opt=pe+24;st=opt+u16(pe+20);n=u16(pe+6)
    secs=[struct.unpack_from('<IIII',b,st+40*i+8) for i in range(n)]
    hdr=st+40*n
    assert hdr+40<=min(s[3] for s in secs) and not any(b[hdr:hdr+40])
    code=align(max(va+max(vs,rs) for vs,va,rs,rp in secs),u32(opt+32))
    a=Asm(code);changes=[]
    a.label('decode_pixel');a.emit('9c60')
    # PUSHFD/PUSHAD add24h. Native locals: Surface44h, Color14h;
    # saved input EAX=sourceX, EDX=sourceRow. No calls or x87 operations.
    a.emit('8b6c2468 8b44241c 8b542414 8b8d00010000 83f910')
    a.branch('0f84','load16');a.emit('83f920');a.branch('0f84','load32')
    a.emit('83f918');a.branch('0f84','load24');a.emit('33db');a.branch('e9','loaded')
    a.label('load16');a.emit('0fb71c42');a.branch('e9','loaded')
    a.label('load32');a.emit('8b1c82');a.branch('e9','loaded')
    a.label('load24');a.emit('8d0c40 03d1 0fb71a 0fb64202 c1e010 0bd8')
    a.label('loaded')
    for channel,mask,dest in [('blue',0x10c,0x38),('green',0x108,0x39),('red',0x104,0x3a)]:
        a.emit('8b8d');a.dword(mask);a.emit('33c0 85c9');a.branch('0f84',channel+'_store')
        a.emit('8bc3 23c1 0fbdc9 41 83e908');a.branch('0f88',channel+'_left')
        a.emit('d3e8');a.branch('e9',channel+'_store')
        a.label(channel+'_left');a.emit('f7d9 d3e0')
        a.label(channel+'_store');a.emit('884424'+bytes([dest]).hex())
    a.emit('619d 8b8c24f4000000');a.branch('e9',0x2c43d)
    site=0x2c400;old=bytes.fromhex('668b04428a542440')
    assert b[off(site):off(site)+len(old)]==old
    new=(b'\xe9'+struct.pack('<i',a.labels['decode_pixel']-site-5)).ljust(len(old),b'\x90')
    b[off(site):off(site)+len(old)]=new
    changes.append(dict(rva=hex(site),original=old.hex(),patched=new.hex(),helper='decode_pixel'))
    payload=a.finish();assert len(payload)<0x1000
    # Original hooks contain only EBX-relative offsets, never image addresses.
    rr,rs=u32(opt+96+40),u32(opt+100+40);p=off(rr)
    while p<off(rr)+rs:
        page,sz=struct.unpack_from('<II',b,p);assert sz>=8
        for ep in range(p+8,p+sz,2):
            ent=u16(ep)
            if ent>>12:assert not any(int(c['rva'],16)<=page+(ent&4095)<int(c['rva'],16)+len(bytes.fromhex(c['original'])) for c in changes)
        p+=sz
    raw=align(len(b),u32(opt+36));rawsize=align(len(payload),u32(opt+36))
    b.extend(bytes(raw-len(b)));b.extend(payload);b.extend(bytes(rawsize-len(payload)))
    struct.pack_into('<8sIIIIIIHHI',b,hdr,b'.reaprev',len(payload),code,rawsize,raw,0,0,0,0,0x60000020)
    struct.pack_into('<H',b,pe+6,n+1)
    struct.pack_into('<I',b,opt+56,align(code+len(payload),u32(opt+32)))
    struct.pack_into('<I',b,opt+4,u32(opt+4)+rawsize);struct.pack_into('<I',b,opt+64,0)
    return b,dict(parent_sha256=PARENT,candidate_sha256=hashlib.sha256(b).hexdigest(),
        scope='Only MakePixelmap pixel load/conversion: RGB16/24/32 actual BPP/full masks; cached shifts ignored; sampling/pitch/output unchanged',
        changes=changes,labels={k:hex(v) for k,v in a.labels.items()},payload_hex=payload.hex(),
        section=dict(rva=hex(code),raw=raw,bytes=len(payload)),removed_relocations=[],
        status='build-only candidate; native fixture and fullscreen manual validation required')
