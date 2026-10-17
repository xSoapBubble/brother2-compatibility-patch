"""Build only: suppress implicit Alt/F10 menu activation in Brother's WndProc."""

import hashlib,json,pathlib,struct,sys

from patch_zplayer_mouse_queue import Asm

PARENT='c5316da9ea51f49af7f65be659f923aaa572edd06e5e68b92415a0f67fd8d37f'

def build(parent,explicit_space_only=False,suppress_all_keymenu=False):
    assert hashlib.sha256(parent).hexdigest()==PARENT
    b=bytearray(parent);u16=lambda p:struct.unpack_from('<H',b,p)[0];u32=lambda p:struct.unpack_from('<I',b,p)[0]
    pe=u32(60);opt=pe+24;st=opt+u16(pe+20)
    sections=[(st+40*i,*struct.unpack_from('<IIII',b,st+40*i+8))for i in range(u16(pe+6))]
    def off(rva):return next(raw+rva-va for hdr,vs,va,sz,raw in sections if va<=rva<va+sz)
    hdr,vs,va,sz,raw=next(s for s in sections if b[s[0]:s[0]+8]==b'.reamfix')
    assert u32(hdr+36)==0x60000020
    start=(vs+15)&~15;a=Asm(va+start)
    a.label('filter')
    a.emit('817c2408 12010000');a.branch('0f85','original') # WM_SYSCOMMAND only
    a.emit('8b44240c 25f0ff0000 3d00f10000');a.branch('0f85','original')
    if suppress_all_keymenu:
        pass
    elif explicit_space_only:
        a.emit('837c241020');a.branch('0f84','original') # explicit Alt+Space remains native
    else:
        a.emit('837c241000');a.branch('0f85','original')
    a.emit('33c0 c21000')
    a.label('original');a.address(0x43078);a.emit('8b08');a.branch('e9',0xd966)
    payload=a.finish();assert start+len(payload)<=sz
    p=off(0xd960);old=bytes(b[p:p+6]);assert old==bytes.fromhex('8b0d78300410')
    b[p:p+6]=b'\xe9'+struct.pack('<i',a.rva-(0xd960+5))+b'\x90'
    # Original MOV ECX,[Game] absolute operand is displaced. Its HIGHLOW fixup
    # must become ABSOLUTE padding; the replacement and payload are PIC.
    rp=off(u32(opt+96+5*8));end=rp+u32(opt+100+5*8);removed=[]
    while rp<end:
        page,size=struct.unpack_from('<II',b,rp);assert size>=8
        for ep in range(rp+8,rp+size,2):
            value=u16(ep)
            if value>>12==3 and page+(value&0xfff)==0xd962:
                struct.pack_into('<H',b,ep,0);removed.append(dict(file_offset=ep,old=value,new=0))
        rp+=size
    assert len(removed)==1
    assert not any(b[raw+start:raw+start+len(payload)])
    b[raw+start:raw+start+len(payload)]=payload;struct.pack_into('<I',b,hdr+8,start+len(payload))
    preserved=['Alt+Tab WM_SYSKEY/activation','Alt+F4 SC_CLOSE','Original game window-event dispatch for all other messages','All existing mouse/lifecycle/frame pacing/startup repairs']
    if not suppress_all_keymenu:preserved.append('Alt+Space SC_KEYMENU character32')
    if not explicit_space_only and not suppress_all_keymenu:preserved.append('Explicit Alt menu mnemonics')
    report=dict(before_sha256=PARENT,after_sha256=hashlib.sha256(b).hexdigest(),entry_rva=hex(0xd960),original_entry=old.hex(),replacement_entry=bytes(b[p:p+6]).hex(),payload_rva=hex(a.rva),payload_hex=payload.hex(),labels={k:hex(v)for k,v in a.labels.items()},removed_relocations=removed,code_section='RX',new_sections=False,changed_file_size=False,filter=dict(message=0x112,wparam_mask=0xfff0,command=0xf100,condition='any lparam'if suppress_all_keymenu else('lparam != 32'if explicit_space_only else'lparam == 0')),preserved=preserved)
    return bytes(b),report
