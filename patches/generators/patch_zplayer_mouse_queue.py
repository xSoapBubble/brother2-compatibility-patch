"""Version-checked x86 PIC repair for Brother's unsynchronized mouse queue.

Uses the queue's existing Win32 CRITICAL_SECTION. Consumer callbacks run outside
the queue lock. Auto-reset SetEvent replaces producer PulseEvent. A 50 ms wait
also tolerates the unmodified constructor/shutdown PulseEvent calls.
"""

import hashlib, json, pathlib, shutil, struct, sys

EXPECTED = '01ba058e5de06818e8146f1a20da2d0a462087a424fd1cdc35faf868e08e2e3e'

def sha(b): return hashlib.sha256(b).hexdigest()

def align(n, a): return (n + a - 1) // a * a

class Asm:
    def __init__(self, rva): self.rva=rva; self.b=bytearray(); self.labels={}; self.fix=[]
    def emit(self, h): self.b.extend(bytes.fromhex(h))
    def dword(self, n): self.b.extend(struct.pack('<I', n & 0xffffffff))
    def label(self, name): self.labels[name]=self.rva+len(self.b)
    def branch(self, op, dest):
        self.emit(op); self.fix.append((len(self.b),dest)); self.dword(0)
    def address(self, rva):
        # EAX := current module base + rva, without absolute relocations.
        self.emit('e8 00000000 58 05')
        self.dword(rva - (self.rva + len(self.b) - 2))
    def iat(self, rva): self.address(rva); self.emit('ff10')
    def finish(self):
        for p,dest in self.fix:
            dst=self.labels[dest] if isinstance(dest,str) else dest
            struct.pack_into('<i',self.b,p,dst-(self.rva+p+4))
        return self.b

def build(original, coalesce=True, cursor_reacquire=True):
    b=bytearray(original)
    u16=lambda p:struct.unpack_from('<H',b,p)[0]
    u32=lambda p:struct.unpack_from('<I',b,p)[0]
    pe=u32(0x3c); coff=pe+4; opt=coff+20; n=u16(coff+2)
    assert u16(opt)==0x10b and u16(coff)==0x14c
    st=opt+u16(coff+16); sections=[]
    for i in range(n):
        p=st+40*i
        sections.append((u32(p+12),u32(p+8),u32(p+20),u32(p+16)))
    def off(rva):
        for va,vs,raw,sz in sections:
            if va<=rva<va+sz: return raw+rva-va
        raise ValueError(hex(rva))
    def cstr(p): return b[p:b.index(0,p)].decode('ascii')
    imports={}; p=off(u32(opt+104))
    while any(b[p:p+20]):
        oft,_,_,name,ft=struct.unpack_from('<IIIII',b,p)
        q=off(oft or ft); i=0
        while (v:=u32(q+4*i)):
            if not v&0x80000000: imports[cstr(off(v)+2)]=ft+4*i
            i+=1
        p+=20
    enter=imports['EnterCriticalSection']; leave=imports['LeaveCriticalSection']
    setevent=imports['SetEvent']; wait=imports['WaitForSingleObject']
    free=imports['?gmempool_free@@YAXAAPAVGMemoryPoolHandleRep@@PAX@Z']
    assert free==0x2943c
    fa=u32(opt+36); sa=u32(opt+32)
    newva=align(max(va+max(vs,sz) for va,vs,raw,sz in sections),sa)
    raw=align(len(b),fa)
    header=st+40*n
    assert header+40<=min(s[2] for s in sections)
    assert not any(b[header:header+40])
    a=Asm(newva)
    a.label('producer_entry')
    # Preserve all incoming state, lock queue+8, replay displaced instructions.
    a.emit('9c 60 8b81 14050000 83c008 50'); a.iat(enter)
    a.emit('61 9d 53 6a18 8bd9'); a.branch('e9',0x2845)
    a.label('producer_signal')
    # Original ECX still points at queue. Stack has return, event handle.
    a.emit('9c 60 8d4108 50'); a.iat(leave)
    a.emit('ff7424 28'); a.iat(setevent)
    a.emit('61 9d c20400')
    a.label('consumer')
    a.emit('53 56 57 8bf9')  # preserve EBX/ESI/EDI; EDI=this
    a.label('wait')
    a.emit('8b9f 14050000 6a32 ff7324'); a.iat(wait)
    a.label('pop')
    a.emit('80bf 10050000 00'); a.branch('0f85','exit')
    a.emit('8b9f 14050000 8d4308 50'); a.iat(enter)
    a.emit('8b33 85f6'); a.branch('0f84','empty')
    a.emit('8b4614 8903 c74614 00000000 85c0'); a.branch('0f85','nonempty')
    a.emit('c74304 00000000')
    a.label('nonempty')
    a.emit('8d4308 50'); a.iat(leave)
    a.emit('56 8bcf'); a.branch('e8',0x2b20)
    a.emit('ffb7 18050000'); a.address(0x42f00); a.emit('50'); a.iat(free)
    a.emit('83c408 89b7 18050000'); a.branch('e9','pop')
    a.label('empty')
    a.emit('8d4308 50'); a.iat(leave); a.branch('e9','wait')
    a.label('exit'); a.emit('5f 5e 5b c3')
    if coalesce:
        a.label('coalesce_publish')
        # Entry lock is still held; restore original saved EBX, then keep all
        # registers/flags while publishing or merging the newly allocated node.
        a.emit('8b8b14050000 5b 9c60 8bf0 8bf9 85f6')
        a.branch('0f84','publish_signal')
        a.emit('c6461200 8b5704 85d2') # node padding marker starts protected
        a.branch('0f84','publish_empty')
        a.emit('66837e1000');a.branch('0f85','publish_append')
        a.emit('66837a1000');a.branch('0f85','publish_append')
        # Both states released: new node is a pure move. A release edge itself
        # is never merged, because its predecessor had a pressed button (or was
        # empty). Padding +12 is unused by the original MouseEvent structure.
        a.emit('c64612a5 807a12a5');a.branch('0f85','publish_append')
        a.emit('8b06 8902 8b4604 894204 8b4608 014208 8b460c 01420c')
        a.emit('56');a.address(0x42f00);a.emit('50');a.iat(free);a.emit('83c408')
        a.branch('e9','publish_signal')
        a.label('publish_append');a.emit('897214');a.branch('e9','publish_tail')
        a.label('publish_empty');a.emit('8937')
        a.label('publish_tail');a.emit('897704')
        a.label('publish_signal')
        a.emit('8d4708 50');a.iat(leave)
        a.emit('ff7724');a.iat(setevent)
        a.emit('619d c21000')
    if cursor_reacquire:
        a.label('reacquire_cursor')
        # The original acquire saved the OS position BEFORE waiting for focus.
        # Captured movement rejects any new position outside the client rect,
        # so an outside starting point can remain outside indefinitely. Refresh
        # the rectangle and normalize the virtual point after acquire returns.
        # Do not move the desktop pointer or alter non-captured mouse behavior.
        a.emit('9c60 807e3c00');a.branch('0f84','reacquire_done')
        a.address(0x3ec17);a.emit('803800');a.branch('0f84','reacquire_done')
        a.emit('8bce');a.branch('e8',0x99d0)
        a.emit('8b86a0000000 8b96a8000000 3bd0');a.branch('0f8e','reacquire_done')
        a.emit('8b8ea4000000 8bbeac000000 3bf9');a.branch('0f8e','reacquire_done')
        # Normalize each outside axis to its midpoint; valid coordinates remain.
        a.emit('8b9eb0000000 3bd8');a.branch('0f8c','reacquire_x')
        a.emit('3bda');a.branch('0f8c','reacquire_y_check')
        a.label('reacquire_x')
        a.emit('2bd0 d1fa 03d0 8996b0000000')
        a.label('reacquire_y_check')
        a.emit('8b9eb4000000 3bd9');a.branch('0f8c','reacquire_y')
        a.emit('3bdf');a.branch('0f8c','reacquire_done')
        a.label('reacquire_y')
        a.emit('2bf9 d1ff 03f9 89beb4000000')
        a.label('reacquire_done')
        a.emit('619d 5e83c408c3')
    payload=a.finish()
    patches=[]
    def hook(rva, expected, dest, call=False):
        pos=off(rva); exp=bytes.fromhex(expected)
        assert b[pos:pos+len(exp)]==exp, (hex(rva),b[pos:pos+len(exp)].hex())
        change=bytes([0xe8 if call else 0xe9])+struct.pack('<i',a.labels[dest]-(rva+5))
        change+=b'\x90'*(len(exp)-5)
        b[pos:pos+len(exp)]=change
        patches.append({'rva':hex(rva),'file_offset':pos,'original':exp.hex(),'patched':change.hex(),'destination':dest})
    hook(0x2840,'53 6a18 8bd9','producer_entry')
    hook(0x28a9,'ff15 8c900210','producer_signal',True)
    hook(0x28bb,'ff15 8c900210','producer_signal',True)
    hook(0x2a40,'53 55 8b2d 3c940210','consumer')
    if coalesce:hook(0x2891,'8b8b14050000','coalesce_publish')
    if cursor_reacquire:hook(0x978c,'5e83c408c3','reacquire_cursor')
    # Original absolute IAT operands carried HIGHLOW relocations. They overlap
    # the new rel32 hooks and must become ABSOLUTE padding, or ASLR corrupts them.
    removed=[]; reloc=u32(opt+96+5*8); relocsize=u32(opt+100+5*8)
    p=off(reloc); end=p+relocsize
    wanted={0x28ab,0x28bd,0x2a44}
    while p<end:
        page,block=struct.unpack_from('<II',b,p)
        if block<8: raise ValueError('Invalid relocation block')
        for ep in range(p+8,p+block,2):
            entry=u16(ep); rva=page+(entry&0xfff)
            if (entry>>12)==3 and rva in wanted:
                struct.pack_into('<H',b,ep,0);removed.append(hex(rva))
        p+=block
    assert set(int(x,16) for x in removed)==wanted, removed
    b.extend(b'\0'*(raw-len(b)))
    b.extend(payload); b.extend(b'\0'*(align(len(payload),fa)-len(payload)))
    struct.pack_into('<8sIIIIIIHHI',b,header,b'.reamfix',len(payload),newva,align(len(payload),fa),raw,0,0,0,0,0x60000020)
    struct.pack_into('<H',b,coff+2,n+1)
    struct.pack_into('<I',b,opt+56,align(newva+len(payload),sa))
    struct.pack_into('<I',b,opt+4,u32(opt+4)+align(len(payload),fa))
    struct.pack_into('<I',b,opt+64,0) # optional image checksum (ordinary user DLL)
    manifest={'original_sha256':sha(original),'patched_sha256':sha(b),'hooks':patches,
        'move_coalescing':coalesce,
        'captured_cursor_reacquire':cursor_reacquire,
        'section':{'rva':hex(newva),'offset':raw,'bytes':len(payload),'hex':payload.hex()},
        'labels':{k:hex(v) for k,v in a.labels.items()},
        'removed_hook_relocations':removed,
        'imports':{k:hex(v) for k,v in [('enter',enter),('leave',leave),('setevent',setevent),('wait',wait),('free',free)]}}
    return b,manifest
