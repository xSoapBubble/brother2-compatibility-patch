"""Scale only original OnShowDialog ToolTip logical coordinates at its caller."""

import pathlib,hashlib,struct,json

from zsol_mouse_payload import Asm,_pe

PARENT='128e2081b7189f33134e736298cf3f9d1adf38534dbb688a8e98ebc61946ee3f'

def build(parent):
    assert hashlib.sha256(parent).hexdigest()==PARENT
    b=bytearray(parent);off,im=_pe(b);assert im['?setPos@InterfaceObject@Nestor@@QAEXAAVVector2D@@@Z']==0x6fbbc
    pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;st=opt+struct.unpack_from('<H',b,pe+20)[0]
    hdr=next(st+40*i for i in range(struct.unpack_from('<H',b,pe+6)[0]) if b[st+40*i:st+40*i+8]==b'.reacode')
    vs,va,size,raw=struct.unpack_from('<IIII',b,hdr+8);start=(vs+15)&~15
    a=Asm(va+start);a.label('scale_tooltip_position')
    # EAX points to the original stack Vector2D, ESI is InterfaceObject.
    # Its draw interface is the same +54 consumed by the original setPos.
    # Native virtual getScale(out Vector2D) is slot7c, thiscall RET4.
    a.emit('53 8bd8 83ec10 8d1424 8b4e54 52 8b01 ff507c')
    a.emit('dd03 dc0c24 dd1b dd4308 dc4c2408 dd5b08')
    a.emit('83c410 8bc3 5b 50 8bce');a.iat(0x6fbbc);a.branch('e9',0x3e4ec)
    payload=a.finish();assert start+len(payload)<=size and not any(b[raw+vs:raw+start+len(payload)])
    rva=0x3e4e3;old=bytes.fromhex('508bceff15bcfb0610');assert b[off(rva):off(rva)+len(old)]==old
    patch=(b'\xe9'+struct.pack('<i',a.rva-rva-5)).ljust(len(old),b'\x90');b[off(rva):off(rva)+len(old)]=patch
    b[raw+start:raw+start+len(payload)]=payload;struct.pack_into('<I',b,hdr+8,start+len(payload))
    rr,rs=struct.unpack_from('<II',b,opt+96+5*8);q=off(rr);removed=[]
    while q<off(rr)+rs:
        page,n=struct.unpack_from('<II',b,q);assert n>=8
        for p in range(q+8,q+n,2):
            ent=struct.unpack_from('<H',b,p)[0]
            if ent>>12==3 and page+(ent&4095)==0x3e4e8:
                struct.pack_into('<H',b,p,0);removed.append('0x3e4e8')
        q+=n
    assert removed==['0x3e4e8']
    return b,dict(parent_sha256=PARENT,candidate_sha256=hashlib.sha256(b).hexdigest(),payload_rva=hex(a.rva),payload_size=len(payload),payload_hex=payload.hex(),changes=[dict(rva=hex(rva),original=old.hex(),patched=patch.hex())],removed_relocations=removed,status='candidate; native getter/setter tests pending',contract='Scale original caller-local ToolTip Vector2D by the actual draw interface scale. Only callsite3e4e3 changes. Getter7c and original setPos run native; no shared logical-size or global positioning API changes. Both menu346/151 and inventory-return8/142 branches covered.')
