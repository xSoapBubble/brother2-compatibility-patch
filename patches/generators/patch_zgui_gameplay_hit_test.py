"""Build-only policy: bypass interface hit testing while controlling the player.

Only IRootInterMouseHandler's virtual input entries change. SceneMaster and
original UI handlers remain intact. Replaces the previous move-only fix.
"""

import hashlib,json,pathlib,struct

from patch_zplayer_mouse_queue import align

from patch_zplayer_frame_pacing import FrameAsm

from zsol_mouse_payload import _pe

ORIGINAL='7da9f915435cd571cca2b9f603b8e8a8e49c5e3dd083d7e936f82d912bf02991'

def build(original):
    assert hashlib.sha256(original).hexdigest()==ORIGINAL
    b=bytearray(original);off,imports=_pe(b)
    u16=lambda p:struct.unpack_from('<H',b,p)[0];u32=lambda p:struct.unpack_from('<I',b,p)[0]
    pe=u32(60);opt=pe+24;st=opt+u16(pe+20);n=u16(pe+6);base=u32(opt+28)
    sections=[struct.unpack_from('<IIII',b,st+40*i+8) for i in range(n)]
    hdr=st+40*n;assert hdr+40<=min(s[3] for s in sections) and not any(b[hdr:hdr+40])
    va=align(max(s[1]+max(s[0],s[2]) for s in sections),u32(opt+32));raw=align(len(b),u32(opt+36))
    a=FrameAsm(va)
    events=[('hit',0x14,0x17680,4,1),('move',0x3c,0x19ea0,8,0),('left_down',0x40,0x1a010,4,0),
        ('left_up',0x44,0x19fd0,4,0),('right_down',0x48,0x1a030,4,0),('right_up',0x4c,0x19ff0,4,0)]
    for name,slot,target,args,result in events:
        a.label(name);a.branch('e8','check_gameplay');a.emit('84c0');a.branch('0f84',name+'_original')
        a.emit('b0'+format(result,'02x')+' c2'+struct.pack('<H',args).hex())
        a.label(name+'_original');a.branch('e9',target)
    a.label('check_gameplay');a.emit('9c60 8b594c 85db');a.branch('0f84','not_gameplay')
    a.address(0x74658);a.emit('3918');a.branch('0f85','not_gameplay')
    a.emit('80bbb200000000');a.branch('0f85','not_gameplay')
    a.emit('80bba400000001');a.branch('0f85','not_gameplay')
    a.address('player_name');a.emit('50');a.iat(imports['GetModuleHandleA'])
    a.emit('85c0');a.branch('0f84','not_gameplay')
    a.emit('80b817ec030001');a.branch('0f85','not_gameplay')
    a.address('sol_name');a.emit('50');a.iat(imports['GetModuleHandleA'])
    a.emit('85c0');a.branch('0f84','not_gameplay');a.emit('8bf8')
    a.emit('80bfdeb50a0000');a.branch('0f85','not_gameplay')
    a.emit('80bf88b40a0000');a.branch('0f85','not_gameplay')
    a.emit('81c700f00300 8b5360 8b4b68 85d2');a.branch('0f84','not_gameplay')
    a.emit('85c9');a.branch('0f84','not_gameplay')
    a.emit('81f980000000');a.branch('0f87','not_gameplay')
    a.label('find_master');a.emit('8b02 85c0');a.branch('0f84','next')
    a.emit('8b00 39783c');a.branch('0f84','skip_interface')
    a.label('next');a.emit('83c204 49');a.branch('0f85','find_master');a.branch('e9','not_gameplay')
    # A false hit alone leaves stale this+48. Use the original generic miss
    # cleanup to send mouse_leave, release its reference and clear it properly.
    # Call its cleanup tail with a dummy point (unused by this path).
    a.label('skip_interface');a.emit('8b4c2418 6a00');a.branch('e8','cleanup')
    a.emit('619d b001 c3')
    a.label('not_gameplay');a.emit('619d 32c0 c3')
    a.label('cleanup');a.emit('53 56 8bf1 57 33ff');a.branch('e9',0x29020)
    a.label('player_name');a.b.extend(b'ZPlayer.dll\0');a.label('sol_name');a.b.extend(b'ZSOL.dll\0')
    payload=a.finish();entries=[]
    for name,slot,target,args,result in events:
        entry=0x45a9c+slot;p=off(entry);assert u32(p)==base+target
        struct.pack_into('<I',b,p,base+a.labels[name]);entries.append(hex(entry))
    reloc=[];rp=off(u32(opt+96+5*8));end=rp+u32(opt+100+5*8)
    while rp<end:
        page,size=struct.unpack_from('<II',b,rp);assert size>=8
        for ep in range(rp+8,rp+size,2):
            e=u16(ep)
            if e>>12==3 and hex(page+(e&0xfff)) in entries:reloc.append(hex(page+(e&0xfff)))
        rp+=size
    assert sorted(reloc)==sorted(entries) # retain all HIGHLOWs for the vtable pointers
    rawsize=align(len(payload),u32(opt+36));b.extend(b'\0'*(raw-len(b)));b.extend(payload);b.extend(b'\0'*(rawsize-len(payload)))
    struct.pack_into('<8sIIIIIIHHI',b,hdr,b'.reacam',len(payload),va,rawsize,raw,0,0,0,0,0x60000020)
    struct.pack_into('<H',b,pe+6,n+1);struct.pack_into('<I',b,opt+56,align(va+len(payload),u32(opt+32)))
    struct.pack_into('<I',b,opt+4,u32(opt+4)+rawsize);struct.pack_into('<I',b,opt+64,0)
    return b,{'original_sha256':ORIGINAL,'patched_sha256':hashlib.sha256(b).hexdigest(),
        'vtable_entries':entries,'labels':{k:hex(v) for k,v in a.labels.items()},
        'retained_relocation':reloc,'payload_hex':payload.hex(),'payload_bytes':len(payload),
        'status':'candidate; replaces move-only fallback; full root/click/mode native tests required'}
