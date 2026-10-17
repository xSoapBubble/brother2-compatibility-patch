"""Build only: avoid falsely grounding an already rising airborne character.

Exact installed parent includes the confirmed zoom fix. No game file is written.
The helper uses only integer instructions; x87/SSE state is untouched.
"""

import hashlib,json,pathlib,struct

from patch_zplayer_mouse_queue import Asm

from zsol_mouse_payload import _pe

PARENT='9587270e2dc9819ca83089e91eea01fcc412907e730d97361c34025679aa7cfd'

def build(parent):
    assert hashlib.sha256(parent).hexdigest()==PARENT
    b=bytearray(parent);off,_=_pe(b)
    u16=lambda p:struct.unpack_from('<H',b,p)[0];u32=lambda p:struct.unpack_from('<I',b,p)[0]
    pe=u32(60);opt=pe+24;st=opt+u16(pe+20)
    h=next(st+40*i for i in range(u16(pe+6))if b[st+40*i:st+40*i+8]==b'.reacode')
    vs,va,sz,raw=struct.unpack_from('<IIII',b,h+8);assert u32(h+36)==0x60000020
    assert (vs,va,sz)==(0x66b,0xbe000,0x1000)
    start=(vs+15)&~15;a=Asm(va+start)
    a.label('ground_band_guard');a.emit('9c60')
    a.emit('83b90401000000');a.branch('0f84','native_ground')
    # Positive finite vertical velocity: IEEE positive finite bits are (0,7f800000).
    a.emit('8b8114010000 85c0');a.branch('0f8e','native_ground')
    a.emit('3d0000807f');a.branch('0f83','native_ground')
    # Current frame floor[ESP+58] shifts by PUSHFD+PUSHAD=24h to[ESP+7c].
    a.emit('8b81a8000000 8b54247c 8bd8 81e3ffffff7f 81fb0000807f')
    a.branch('0f83','native_ground')
    a.emit('8bfa 81e7ffffff7f 81ff0000807f');a.branch('0f83','native_ground')
    # Treat +0/-0 as equal before the monotonic IEEE integer-key transform.
    a.emit('0bdf');a.branch('0f84','native_ground')
    a.emit('8bd8 c1fb1f 81cb00000080 33c3')
    a.emit('8bda c1fb1f 81cb00000080 33d3 3bc2')
    a.branch('0f86','native_ground') # y<=floor: preserve native penetration fix.
    a.label('retain_rising');a.emit('619d');a.branch('e9',0x31d30)
    a.label('native_ground');a.emit('619d 39a904010000');a.branch('e9',0x31d02)
    payload=bytes(a.finish());assert start+len(payload)<=sz
    assert not any(b[raw+start:raw+start+len(payload)])
    rva=0x31cfc;p=off(rva);old=bytes.fromhex('39a904010000');assert b[p:p+6]==old
    new=b'\xe9'+struct.pack('<i',a.rva-rva-5)+b'\x90';b[p:p+6]=new
    rp=off(u32(opt+96+5*8));end=rp+u32(opt+100+5*8);overlap=[]
    while rp<end:
        page,block=struct.unpack_from('<II',b,rp);assert block>=8
        for ep in range(rp+8,rp+block,2):
            e=u16(ep);target=page+(e&0xfff)
            if e>>12==3 and target<rva+6 and target+4>rva:overlap.append(hex(target))
        rp+=block
    assert not overlap
    b[raw+start:raw+start+len(payload)]=payload;struct.pack_into('<I',b,h+8,start+len(payload))
    allowed=[(p,p+6),(h+8,h+12),(raw+start,raw+start+len(payload))]
    changes=[i for i,(x,y)in enumerate(zip(parent,b))if x!=y]
    assert len(parent)==len(b)and all(any(s<=i<e for s,e in allowed)for i in changes)
    report=dict(parent_sha256=PARENT,candidate_sha256=hashlib.sha256(b).hexdigest(),status='build-only; native QA pending; not installed',
        hook=dict(rva=hex(rva),file_offset=p,original=old.hex(),replacement=new.hex()),
        labels={k:hex(v)for k,v in a.labels.items()},payload_rva=hex(a.rva),payload_size=len(payload),payload_hex=payload.hex(),
        original_continuations={'retain_rising':'0x31d30','native_ground':'0x31d02'},
        predicate='airborne104!=0 && finite velocity114>0 && finite y>a finite floor; signed zeros equal',
        abi='inline JMP; ECX=character, EBP=0, ESP=generate frame; floor[ESP+58]. All GPR preserved. Bypass preserves CPU flags; fallback replays original CMP to set native branch flags. No x87/SSE instructions, calls, imports or data.',
        code_permissions='RX',new_data=False,removed_relocations=[],new_relocations=[],changed_file_offsets=changes,
        prior_repairs_preserved=True,no_installed_files_changed=True)
    return bytes(b),report
