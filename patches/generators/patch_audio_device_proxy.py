"""Build-only: route the native DirectSound factory through a stable proxy.

Parent is the last complete pre-recovery Geometry, so v1 listener-only hooks
are superseded. Existing volume/destructor/music bridges remain byte identical.
"""

import pathlib,struct,hashlib,json

from patch_audio_bridges import prepare,resolver

from zsol_mouse_payload import Asm

PARENT='56dc7222e0267ab6aa7c4e9e170ba7f6249d6a7bd04213026b18136540de1237'

align=lambda x,n:(x+n-1)&~(n-1)

def build(parent,test=False):
    assert hashlib.sha256(parent).hexdigest()==PARENT
    b,off,im,ctx=prepare(parent);pe,opt,n,st,sa,fa,code,data=ctx
    a=Asm(code);a.label('create_direct_sound')
    # Original stdcall frame: return, GUID*, output**, outer*. Resolve a cdecl
    # helper without consuming those arguments; callee-save all native regs.
    a.emit('53 56 57 8d742410 31d2');a.branch('e8','resolve')
    a.emit('85c0');a.branch('0f84','native_factory')
    a.emit('ff7608 ff7604 ff36 ffd0 83c40c');a.branch('e9','done')
    a.label('native_factory');a.emit('ff7608 ff7604 ff36');a.branch('e8',0x4c200)
    a.label('done');a.emit('5f5e5b c20c00')
    a.label('dll_name');a.b.extend((b'rea_audio_test.dll\0'if test else b'rea_audio.dll\0').ljust(32,b'\0'))
    a.label('names');table=len(a.b);a.b.extend(bytes(4));a.label('REA_DirectSoundCreate');a.b.extend(b'REA_DirectSoundCreate\0')
    resolver(a,im,data,['REA_DirectSoundCreate'])
    payload=bytearray(a.finish());struct.pack_into('<I',payload,table,a.labels['REA_DirectSoundCreate'])
    assert len(payload)<=sa
    site=0x49750;pos=off(site);old=b'\xe8'+struct.pack('<i',0x4c200-site-5);assert b[pos:pos+5]==old
    new=b'\xe8'+struct.pack('<i',a.labels['create_direct_sound']-site-5);b[pos:pos+5]=new
    for i,(name,va,content,flags)in enumerate([(b'.readvC',code,payload,0x60000020),(b'.readvD',data,bytes(16),0xc0000040)]):
        raw=align(len(b),fa);b.extend(bytes(raw-len(b)));size=align(len(content),fa);b.extend(content);b.extend(bytes(size-len(content)))
        struct.pack_into('<8sIIIIIIHHI',b,st+40*(n+i),name,len(content),va,size,raw,0,0,0,0,flags)
    struct.pack_into('<H',b,pe+6,n+2);struct.pack_into('<I',b,opt+56,align(data+16,sa));struct.pack_into('<I',b,opt+64,0)
    return bytes(b),dict(parent_sha256=PARENT,candidate_sha256=hashlib.sha256(b).hexdigest(),test_helper=test,code_rva=hex(code),data_rva=hex(data),payload_size=len(payload),labels={k:hex(v)for k,v in a.labels.items()},changes=[dict(rva=hex(site),original=old.hex(),patched=new.hex(),reason='stable DirectSound/device/buffer COM proxy factory')],removed_relocations=[],scope='factory hook only; native listener/sound playback paths and prior audio gain fixes retained',status='candidate; full proxy component/native validation pending')
