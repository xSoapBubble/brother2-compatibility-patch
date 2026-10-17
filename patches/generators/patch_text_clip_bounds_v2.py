"""Scale only IDrawText blit bounds; preserve logical getBox/placement sizes."""

import pathlib,hashlib,struct,json

from zsol_mouse_payload import Asm,_pe

LOGICAL_PARENT='818b7d0cebd65b016b59745a276a0a1f08b9d01dc023528804087a006bdb8d08'

INSTALLED_V1='666d342c528405d84133f8f544b2450abf68a9931dfa8a3e0f5ecb6c724d9ab4'

SITES=[('source_width',0x2feb3,0x2fecc,'dd4618d9c1ded9dfe0f6c4017505ddd8dd4618dc25005a0410',0x18,0x38,True,False),
       ('source_height',0x2fee2,0x2fefb,'dd4620d9c1ded9dfe0f6c4017505ddd8dd4620dc25005a0410',0x20,0x40,True,False),
       ('dest_width',0x2ff56,0x2ff67,'dd4618d8d9dfe0f6c4017405ddd8dd4618',0x18,0x38,False,False),
       ('dest_height',0x2ff70,0x2ff85,'dd4620d8d98944242cdfe0f6c4017405ddd8dd4620',0x20,0x40,False,True)]

def build(parent):
    assert hashlib.sha256(parent).hexdigest()==LOGICAL_PARENT
    b=bytearray(parent);off,_=_pe(b);pe=struct.unpack_from('<I',b,60)[0];opt=pe+24
    st=opt+struct.unpack_from('<H',b,pe+20)[0]
    hdr=next(st+40*i for i in range(struct.unpack_from('<H',b,pe+6)[0]) if b[st+40*i:st+40*i+8].rstrip(b'\0')==b'.reacam')
    vs,va,size,raw=struct.unpack_from('<IIII',b,hdr+8);start=(vs+15)&~15
    a=Asm(va+start);changes=[]
    for name,site,end,old,field,scale,source,store_width in SITES:
        a.label(name)
        a.emit('dd46'+bytes([field]).hex()+' dc4e'+bytes([scale]).hex())
        a.emit('d9c1 ded9' if source else 'd8d9')
        if store_width:a.emit('8944242c')
        a.emit('dfe0 f6c401')
        a.branch('0f85' if source else '0f84',name+'_selected')
        a.emit('ddd8 dd46'+bytes([field]).hex()+' dc4e'+bytes([scale]).hex())
        a.label(name+'_selected')
        if source:a.emit('d9e8 dee9') # native min(...)-1, using FLD1/FSUBP
        a.branch('e9',end)
        old=bytes.fromhex(old);assert len(old)==end-site and b[off(site):off(end)]==old
        patch=(b'\xe9'+struct.pack('<i',a.labels[name]-site-5)).ljust(len(old),b'\x90')
        b[off(site):off(end)]=patch
        changes.append(dict(name=name,rva=hex(site),end=hex(end),original=old.hex(),patched=patch.hex()))
    payload=a.finish();assert start+len(payload)<=size and not any(b[raw+vs:raw+start+len(payload)])
    b[raw+start:raw+start+len(payload)]=payload;struct.pack_into('<I',b,hdr+8,start+len(payload))
    # Original source bounds subtract the double constant1. Verify FLD1 matches.
    assert struct.unpack_from('<d',b,off(0x45a00))[0]==1.0
    # Two absolute references in replaced FSUB instructions are now gone.
    rr,rs=struct.unpack_from('<II',b,opt+96+5*8);p=off(rr);removed=[]
    while p<off(rr)+rs:
        page,n=struct.unpack_from('<II',b,p);assert n>=8
        for q in range(p+8,p+n,2):
            ent=struct.unpack_from('<H',b,q)[0]
            if ent>>12==3 and page+(ent&4095) in (0x2fec8,0x2fef7):
                removed.append(hex(page+(ent&4095)));struct.pack_into('<H',b,q,0)
        p+=n
    assert sorted(removed)==['0x2fec8','0x2fef7']
    # v1 loads in IDrawText::draw are original, so public getBox is unchanged.
    assert b[off(0x2f61f):off(0x2f625)]==bytes.fromhex('db86b8000000')
    assert b[off(0x2f633):off(0x2f639)]==bytes.fromhex('db86bc000000')
    return b,dict(logical_parent_sha256=LOGICAL_PARENT,installed_parent_sha256=INSTALLED_V1,candidate_sha256=hashlib.sha256(b).hexdigest(),payload_rva=hex(a.rva),payload_size=len(payload),payload_hex=payload.hex(),labels={k:hex(v) for k,v in a.labels.items()},changes=changes,removed_relocations=removed,status='candidate; native bounds/placement checks pending',contract='RecountRects compares physical available source/dest bounds against logical layout multiplied by scale. Neither logical layout nor position is written. Native min branches, source minus1, dest-height saved width and __ftol continuations preserved; x87 stack unchanged.')
