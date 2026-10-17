"""Build only: replace the shared absolute-float counter with a process epoch.

All public QueryCounter and internal model/render callers already converge on
Base RVA262f0. Integer subtraction precedes x87 conversion. Atomic publication
of immutable origins needs no lock, wait, callback, import or thread mutation.
"""

import hashlib, json, pathlib, struct

from patch_zplayer_mouse_queue import Asm, align

PARENT='3c524e1f254a1c4f33a30e984ffeb2ad462cb22e71d8af6fa895f74899785c07'

def sha(b): return hashlib.sha256(b).hexdigest()

def build(original):
    assert sha(original)==PARENT, 'Unexpected parent Base'
    b=bytearray(original)
    u16=lambda p:struct.unpack_from('<H',b,p)[0]
    u32=lambda p:struct.unpack_from('<I',b,p)[0]
    pe=u32(60); opt=pe+24; st=opt+u16(pe+20); n=u16(pe+6)
    assert u16(pe+4)==0x14c and u16(opt)==0x10b
    sections=[]
    for i in range(n):
        p=st+40*i; vs,va,sz,raw=struct.unpack_from('<IIII',b,p+8)
        sections.append((vs,va,sz,raw))
    def off(rva):
        return next(raw+rva-va for vs,va,sz,raw in sections if va<=rva<va+sz)
    fa=u32(opt+36); sa=u32(opt+32)
    code=align(max(va+max(vs,sz) for vs,va,sz,raw in sections),sa)
    data=code+sa
    assert st+40*(n+2)<=min(s[3] for s in sections)
    assert not any(b[st+40*n:st+40*(n+2)])
    assert original[off(0x262f0):off(0x262f0)+6]==bytes.fromhex('8a0d5c931110')
    a=Asm(code)
    a.label('relative_counter')
    a.emit('53 56 57 83ec10') # preserve all nonvolatile regs; two LARGE_INTEGERs
    a.emit('8d442408 50'); a.iat(0xac278) # QPF(&frequency)
    a.emit('85c0');a.branch('0f84','tick_counter')
    a.emit('837c240c00');a.branch('0f8c','tick_counter')
    a.branch('0f85','qpc_frequency_ok')
    a.emit('837c240800');a.branch('0f84','tick_counter')
    a.label('qpc_frequency_ok')
    a.emit('8d0424 50');a.iat(0xac27c) # QPC(&counter)
    a.emit('85c0');a.branch('0f84','tick_counter')
    # Encode origin as ticks+1, reserving all-zero as uninitialized even at QPC0.
    a.emit('8b1c24 8b4c2404 83c301 83d100')
    a.address(data);a.emit('8bf8 31c0 31d2 f00fc70f') # lock cmpxchg8b [EDI]
    a.branch('0f85','qpc_origin_ready')
    a.emit('8bc3 8bd1')
    a.label('qpc_origin_ready')
    a.emit('2bd8 1bca') # now-origin, before any floating conversion
    a.branch('0f89','qpc_nonnegative')
    # Another thread may publish a slightly later first sample; return zero.
    a.emit('31db 31c9')
    a.label('qpc_nonnegative')
    a.emit('891c24 894c2404 df2c24 df6c2408 def9')
    a.branch('e9','done')
    a.label('tick_counter')
    a.iat(0xac280) # original GetTickCount fallback, modulo DWORD subtraction
    a.emit('8bd8 b901000000')
    a.address(data+8);a.emit('8bf8 31c0 31d2 f00fc70f')
    a.branch('0f85','tick_origin_ready')
    a.emit('8bc3')
    a.label('tick_origin_ready')
    a.emit('2bd8 891c24 c744240400000000 df2c24')
    a.address(data+16);a.emit('da30') # FIDIV int32(1000)
    a.label('done')
    a.emit('83c410 5f 5e 5b c3')
    payload=a.finish()
    assert len(payload)<=sa
    code_raw=align(len(b),fa); data_raw=code_raw+align(len(payload),fa)
    data_bytes=bytes(16)+struct.pack('<I',1000)
    b.extend(bytes(code_raw-len(b)))
    b.extend(payload+bytes(align(len(payload),fa)-len(payload)))
    b.extend(data_bytes+bytes(align(len(data_bytes),fa)-len(data_bytes)))
    for i,(name,vs,va,sz,raw,flags) in enumerate([
        (b'.reatime',len(payload),code,align(len(payload),fa),code_raw,0x60000020),
        (b'.retdata',len(data_bytes),data,align(len(data_bytes),fa),data_raw,0xc0000040)]):
        struct.pack_into('<8sIIIIIIHHI',b,st+(n+i)*40,name,vs,va,sz,raw,0,0,0,0,flags)
    struct.pack_into('<H',b,pe+6,n+2)
    struct.pack_into('<I',b,opt+56,align(data+len(data_bytes),sa))
    struct.pack_into('<I',b,opt+4,u32(opt+4)+align(len(payload),fa))
    struct.pack_into('<I',b,opt+8,u32(opt+8)+align(len(data_bytes),fa))
    struct.pack_into('<I',b,opt+64,0)
    hook=off(0x262f0)
    b[hook:hook+6]=b'\xe9'+struct.pack('<i',code-0x262f0-5)+b'\x90'
    # Old absolute operand spans RVA262f2; mark its HIGHLOW relocation ABSOLUTE.
    rel_rva=u32(opt+136);rel_size=u32(opt+140);p=off(rel_rva);end=p+rel_size;removed=[]
    while p+8<=end:
        page,size=struct.unpack_from('<II',b,p)
        if not size:break
        assert size>=8 and p+size<=end
        for q in range(p+8,p+size,2):
            entry=u16(q)
            if entry>>12==3 and page+(entry&4095)==0x262f2:
                struct.pack_into('<H',b,q,entry&4095);removed.append(hex(0x262f2))
        p+=size
    assert removed==['0x262f2']
    manifest=dict(parent_sha256=PARENT,patched_sha256=sha(b),code_rva=hex(code),data_rva=hex(data),
        labels={k:hex(v) for k,v in a.labels.items()},payload_hex=payload.hex(),
        hook_rva='0x262f0',old_bytes=original[hook:hook+6].hex(),new_bytes=b[hook:hook+6].hex(),
        removed_relocations=removed,atomic='cmpxchg8b immutable QPC ticks+1 and separate DWORD fallback origin',
        scope='counter epoch only; game scale, step limits, callbacks, saves, input and render cap unchanged',
        status='candidate; native validation required')
    return bytes(b),manifest
