"""Build-only clamp for the original reject-whole-step pitch bounds.

Preserves the confirmed glass/mouse build. Out-of-range steps reach the
original +/-80 degree limit and pass the shortened delta to original Rot.
"""

import hashlib,json,pathlib,struct


from zsol_mouse_payload import Asm,_pe

PARENT='2664200790245d337138681b15ede1d998befec53c67d46863fb2d276fb9a6b9'

def build(parent):
    b=bytearray(parent)
    assert hashlib.sha256(b).hexdigest()==PARENT
    off,_=_pe(b);u16=lambda p:struct.unpack_from('<H',b,p)[0];u32=lambda p:struct.unpack_from('<I',b,p)[0]
    pe=u32(60);opt=pe+24;st=opt+u16(pe+20)
    hdr=next(st+40*i for i in range(u16(pe+6)) if b[st+40*i:st+40*i+8]==b'.reacode')
    vs,va,sz,raw=struct.unpack_from('<IIII',b,hdr+8)
    start=(vs+15)&~15;a=Asm(va+start)
    for name in ('upper','lower'):
        a.label(name);a.emit('9c60') # locals +40/+44 now at +64/+68
        if name=='lower':
            # The original lower JZ is only two bytes. Replace its preceding
            # FLD and reproduce the complete lower test here instead.
            a.address(0x72180);a.emit('d900 d9e0 d85c2468 dfe0 f6c401')
            a.branch('0f85','lower_normal')
        a.emit('8b876c010000 250000807f 3d0000807f')
        a.branch('0f84',name+'_skip') # finite current pitch required
        a.address(0x72180);a.emit('d900') # original +80deg float constant
        if name=='lower':a.emit('d9e0')
        a.emit('d9876c010000 d8d9 dfe0 f6c404') # compare current vs bound, pop current
        a.branch('0f85',name+'_pop_skip')
        if name=='upper':
            a.emit('f6c401');a.branch('0f84',name+'_pop_skip') # current >= +bound
        else:
            a.emit('f6c441');a.branch('0f85',name+'_pop_skip') # current <= -bound
        # ST0=bound. Store clamped absolute pitch and actual rotation delta.
        a.emit('d9542468 d8a76c010000 d95c2464 619d')
        a.branch('e9',0x3168a) # unchanged matrix rotation and pitch update
        a.label(name+'_pop_skip');a.emit('ddd8')
        a.label(name+'_skip');a.emit('619d');a.branch('e9',0x316fe)
        if name=='lower':
            a.label('lower_normal');a.emit('619d');a.branch('e9',0x3168a)
    payload=a.finish();assert start+len(payload)<=sz
    b[raw+start:raw+start+len(payload)]=payload;struct.pack_into('<I',b,hdr+8,start+len(payload))
    hooks=[]
    for rva,name in ((0x31671,'upper'),(0x31677,'lower')):
        p=off(rva)
        expected=(b'\x0f\x84'+struct.pack('<i',0x316fe-rva-6)) if name=='upper' else bytes.fromhex('d90580210710')
        assert b[p:p+6]==expected
        change=(b'\x0f\x84'+struct.pack('<i',a.labels[name]-rva-6)) if name=='upper' else (b'\xe9'+struct.pack('<i',a.labels[name]-rva-5)+b'\x90')
        b[p:p+6]=change;hooks.append({'rva':hex(rva),'offset':p,'original':expected.hex(),'patched':change.hex()})
    removed=[];p=off(u32(opt+96+5*8));end=p+u32(opt+100+5*8)
    while p<end:
        page,block=struct.unpack_from('<II',b,p);assert block>=8
        for ep in range(p+8,p+block,2):
            entry=u16(ep)
            if entry>>12==3 and page+(entry&0xfff)==0x31679:
                struct.pack_into('<H',b,ep,0);removed.append('0x31679')
        p+=block
    assert removed==['0x31679']
    manifest={'parent_sha256':PARENT,'patched_sha256':hashlib.sha256(b).hexdigest(),
        'hooks':hooks,'labels':{k:hex(v) for k,v in a.labels.items()},
        'payload_rva':hex(a.rva),'payload_hex':payload.hex(),'removed_relocations':removed,
        'status':'candidate only; isolated bounds/ABI/ASLR probe and gameplay validation required'}
    return b,manifest
