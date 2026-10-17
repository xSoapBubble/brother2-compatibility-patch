"""Build-only, version-checked 60 Hz render-loop trial on top of cursor v3.

QPC and Sleep run outside GameView::render_step and therefore outside the
Time/Scene callback locks. All timing state is on this render thread's stack.
No game speed, geometry, depth readback, input or save format changes.
"""

import hashlib,json,pathlib,struct

from patch_zplayer_mouse_queue import Asm

V3='3ad2dbe42c51df84ac21281b14f4fba91813e1621202cb785f7ce04885421904'

class FrameAsm(Asm):
    def address(self,rva):
        if not isinstance(rva,str):return super().address(rva)
        self.emit('e8 00000000 58 05')
        position=len(self.b);self.dword(0)
        self.fix.append((position,('address',rva,self.rva+position-2)))
    def finish(self):
        normal=[]
        for position,dest in self.fix:
            if isinstance(dest,tuple):
                _,name,return_address=dest
                struct.pack_into('<I',self.b,position,(self.labels[name]-return_address)&0xffffffff)
            else:normal.append((position,dest))
        self.fix=normal
        return super().finish()

def build(parent, fps=60):
    assert isinstance(fps,int) and 30<=fps<=165
    b=bytearray(parent)
    assert hashlib.sha256(b).hexdigest()==V3
    u16=lambda p:struct.unpack_from('<H',b,p)[0]
    u32=lambda p:struct.unpack_from('<I',b,p)[0]
    pe=u32(60);opt=pe+24;st=opt+u16(pe+20)
    sections=[(st+40*i,*struct.unpack_from('<IIII',b,st+40*i+8)) for i in range(u16(pe+6))]
    def off(rva):return next(raw+rva-va for _,vs,va,sz,raw in sections if va<=rva<va+sz)
    hdr,vs,va,sz,raw=sections[-1]
    assert b[hdr:hdr+8]==b'.reamfix' and u32(hdr+36)==0x60000020
    start=(vs+15)&~15
    a=FrameAsm(va+start)
    a.label('frame_pacer')
    a.emit('53 56 57 83ec18 8bf1') # EBX/ESI/EDI, 3 LARGE_INTEGER locals
    a.address('kernel_name');a.emit('50');a.iat(0x29138) # GetModuleHandleA
    a.emit('85c0');a.branch('0f84','render_unpaced');a.emit('8bd8')
    a.address('qpc_name');a.emit('50 53');a.iat(0x29134) # GetProcAddress
    a.emit('85c0');a.branch('0f84','render_unpaced');a.emit('8bf8')
    a.address('qpf_name');a.emit('50 53');a.iat(0x29134)
    a.emit('85c0');a.branch('0f84','render_unpaced')
    a.emit('8d542408 52 ffd0 85c0');a.branch('0f84','render_unpaced')
    # Unsigned 64-bit frequency / fps, guarded against DIV overflow.
    a.emit('8b442408 8b54240c b9');a.dword(fps)
    a.emit('3bd1');a.branch('0f83','render_unpaced')
    a.emit('f7f1 85c0');a.branch('0f84','render_unpaced');a.emit('8bd8')
    a.emit('8d0424 50 ffd7 85c0');a.branch('0f84','render_unpaced')
    a.emit('8bce');a.branch('e8',0x10ab0)
    # Bounded fallback if an unusual QPC implementation stops advancing.
    a.emit('c7442408 20000000')
    a.label('wait_frame')
    a.emit('807e1e00');a.branch('0f84','done')
    a.emit('8d442410 50 ffd7 85c0');a.branch('0f84','done')
    a.emit('8b442410 8b542414 2b0424 1b542404');a.branch('0f82','done')
    a.emit('85d2');a.branch('0f85','done')
    a.emit('3bc3');a.branch('0f83','done')
    a.emit('ff4c2408');a.branch('0f88','done')
    a.emit('6a01');a.iat(0x290a4) # Sleep(1), only after render_step returns
    a.branch('e9','wait_frame')
    a.label('render_unpaced');a.emit('8bce');a.branch('e8',0x10ab0)
    a.label('done');a.emit('83c418 5f5e5b c3')
    # Asm.address supports numeric RVAs; resolve forward string labels here.
    a.label('kernel_name');a.b.extend(b'kernel32.dll\0')
    a.label('qpc_name');a.b.extend(b'QueryPerformanceCounter\0')
    a.label('qpf_name');a.b.extend(b'QueryPerformanceFrequency\0')
    payload=a.finish()
    assert start+len(payload)<=sz
    b[raw+start:raw+start+len(payload)]=payload
    struct.pack_into('<I',b,hdr+8,start+len(payload))
    hooks=[]
    for rva in (0x10b9a,0x10bb6):
        p=off(rva);old=b[p:p+5]
        assert old==b'\xe8'+struct.pack('<i',0x10ab0-rva-5)
        change=b'\xe8'+struct.pack('<i',a.labels['frame_pacer']-rva-5)
        b[p:p+5]=change
        hooks.append({'rva':hex(rva),'file_offset':p,'original':old.hex(),'patched':change.hex()})
    manifest={'previous_sha256':V3,'patched_sha256':hashlib.sha256(b).hexdigest(),
        'fps':fps,'hooks':hooks,'labels':{k:hex(v) for k,v in a.labels.items()},
        'payload_rva':hex(a.rva),'payload_hex':payload.hex(),
        'runtime_imports':{'GetModuleHandleA':'0x29138','GetProcAddress':'0x29134','Sleep':'0x290a4'},
        'status':'candidate only; requires isolated validation, restart and measured A/B'}
    return b,manifest
