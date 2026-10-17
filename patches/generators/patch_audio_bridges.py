"""Build-only native GUI/Geometry adapters for portable per-game audio gain."""

import pathlib,struct,hashlib,json

from zsol_mouse_payload import Asm,_pe

PARENTS={'ZGUI':'122b9cdf799474b9458e3123c257711d3ebb0347f438ad33c1b03dff4d1560b5','ZGeometry':'70edbaaf4daab32c22f691c620f6d33114f3aba7b626b4c68fad5561968ed8b6'}

align=lambda x,n:(x+n-1)&~(n-1)

def prepare(parent):
    b=bytearray(parent);off,imports=_pe(b);pe=struct.unpack_from('<I',b,60)[0];opt=pe+24
    n=struct.unpack_from('<H',b,pe+6)[0];st=opt+struct.unpack_from('<H',b,pe+20)[0]
    sa,fa=struct.unpack_from('<II',b,opt+32)
    sections=[struct.unpack_from('<IIII',b,st+40*i+8) for i in range(n)]
    assert st+40*(n+2)<=min(s[3] for s in sections) and not any(b[st+40*n:st+40*(n+2)])
    code=align(max(va+max(vs,sz) for vs,va,sz,raw in sections),sa);data=code+0x1000
    return b,off,imports,(pe,opt,n,st,sa,fa,code,data)

def resolver(a,im,data,names):
    a.label('resolve');a.emit('53 56 57 8bda');a.address(data);a.emit('8d3c98 8b07 85c0');a.branch('0f85','resolve_done')
    a.address(a.labels['dll_name']);a.emit('50');a.iat(im['GetModuleHandleA']);a.emit('85c0');a.branch('0f85','resolve_module')
    a.address(a.labels['dll_name']);a.emit('50');a.iat(im['LoadLibraryA'])
    a.label('resolve_module');a.emit('85c0');a.branch('0f84','resolve_done');a.emit('8bf0')
    a.address(a.labels['names']);a.emit('8b1498');a.address(0);a.emit('03d0 52 56');a.iat(im['GetProcAddress']);a.emit('8907')
    a.label('resolve_done');a.emit('5f 5e 5b c3')

def build(name,parent,test=False):
    assert hashlib.sha256(parent).hexdigest()==PARENTS[name]
    b,off,im,ctx=prepare(parent);pe,opt,n,st,sa,fa,code,data=ctx;a=Asm(code)
    names=['REA_SetVolume','REA_GetVolume'] if name=='ZGUI' else ['REA_TrackSound','REA_RemoveSound','REA_RegisterMusic','REA_UnregisterMusic']
    changes=[];remove=set()
    def patch(rva,old,new,reason):
        old=bytes.fromhex(old) if isinstance(old,str) else old;assert b[off(rva):off(rva)+len(old)]==old,(name,hex(rva))
        assert len(new)<=len(old);new=new.ljust(len(old),b'\x90');b[off(rva):off(rva)+len(old)]=new
        changes.append(dict(rva=hex(rva),original=old.hex(),patched=new.hex(),reason=reason))
    def hook(rva,old,label,reason):
        patch(rva,old,b'\xe9'+struct.pack('<i',a.labels[label]-rva-5),reason)
    def resolve(index):a.emit('ba');a.dword(index);a.branch('e8','resolve')
    def counted(offset):a.address(data+offset);a.emit('f0ff00')
    if name=='ZGUI':
        for kind,setter,getter in [(0,0x20ea0,0x20ef0),(1,0x20f90,0x20fb0),(2,0x20fd0,0x20ff0)]:
            label='set_'+str(kind);a.label(label);a.emit('56 57 8b74240c');counted(0x40+4*kind);resolve(0);a.emit('8bf8 85ff');a.branch('0f84',label+'_done')
            a.emit('8b06 85c0');a.branch('0f84',label+'_done');a.emit('83780401');a.branch('0f84',label+'_float');a.emit('83780400');a.branch('0f85',label+'_done')
            a.emit('db4008');a.branch('e9',label+'_value');a.label(label+'_float');a.emit('d94008');a.label(label+'_value')
            a.emit('83ec04 d91c24 6a'+bytes([kind]).hex()+' ffd7 83c408');a.label(label+'_done');a.emit('5f 5e c20400')
            hook(setter,'8b44240450',label,'per-game normalized gain setter')
            label='get_'+str(kind);a.label(label);a.emit('56 57 8b74240c');counted(0x20+4*kind);resolve(1);a.emit('8bf8 85ff');a.branch('0f84',label+'_fallback')
            a.emit('6a'+bytes([kind]).hex()+' ffd7 83c404');a.branch('e9',label+'_store')
            a.label(label+'_fallback');a.address(0);a.emit('d980');a.dword(0) # patched constant RVA below
            a.label(label+'_store');a.emit('83ec04 d91c24 8bce');a.iat(im['?dispose@_Variable@Nestor@@IAEXXZ'])
            a.emit('6a01 8bce');a.iat(im['?create@_Variable@Nestor@@QAEXW4VariableTypes@2@@Z'])
            a.emit('8b06 8b1424 895008 83c404 5f 5e c20400')
            hook(getter,'8b44240450',label,'typed native Base Variable result; independent persisted gain')
        patch(0x207a4,'c744241404000000',b'\x83\xc4\x04\xe9'+struct.pack('<i',0x2091c-0x207a4-8),'pop preceding pending log-string argument; retain CDMusic initialization; helper validates/loads three volumes')
        for site,target in [(0x20a5e,0x20ea0),(0x20a69,0x20f90),(0x20a74,0x20fd0)]:
            old=b'\xe8'+struct.pack('<i',target-site-5);patch(site,old,bytes.fromhex('83c4049090'),'remove obsolete system-volume restoration, preserve argument stack pop')
    else:
        # 2D returns no control flags in the original. 3D already returns
        # 0x20090 (including CTRLVOLUME). Cache prototypes retain these flags.
        patch(0x48790,'33c0c3909090',bytes.fromhex('b880000000c3'),'enable DSBCAPS_CTRLVOLUME on actual 2D cache prototypes and duplicates')
        for label,field,setter,getter in [('set_sound',0x34,0x48660,0x48640),('set_sound_3d',0x60,0x48d90,0x48d70)]:
            disp=bytes([field]).hex()
            a.label(label);a.emit('56 8bf1 8b442408 8946'+disp);resolve(0);a.emit('85c0');a.branch('0f84',label+'_legacy')
            a.emit('ff76'+disp+' ff7610 56 ffd0 83c40c');a.branch('e9',label+'_done')
            a.label(label+'_legacy');a.emit('8b4610 85c0');a.branch('0f84',label+'_done');a.emit('8b10 ff76'+disp+' 50 ff523c')
            a.label(label+'_done');a.emit('5e c20400')
            hook(setter,'568bf18b4610',label,'retain authored dB and apply category gain to actual '+('3D' if field==0x60 else '2D')+' DS buffer')
            patch(getter,'568bf18b4610',bytes.fromhex('8b41'+disp+'c3'),'return authored volume, avoiding attenuation compounded by copies/queries')
        a.label('remove_sound');a.emit('60 51');resolve(1);a.emit('85c0');a.branch('0f84','remove_sound_skip');a.emit('ffd0');a.label('remove_sound_skip');a.emit('83c404 61 6aff');a.address(0x60f35);a.emit('50');a.branch('e9',0x47f77)
        hook(0x47f70,'6aff68350f0610','remove_sound','unregister retained buffer before original owner destruction')
        remove.add(0x47f73)
        a.label('register_music');a.emit('60');a.address(0xa6e98);a.emit('ff30');resolve(2);a.emit('85c0');a.branch('0f84','register_music_skip');a.emit('ffd0');a.label('register_music_skip');a.emit('83c404 61 5f5e5d5b81c468010000');a.branch('e9',0x4a028)
        hook(0x4a01e,'5f5e5d5b81c468010000','register_music','apply persisted master/music gain after DirectMusic performance initialization')
        a.label('unregister_music');a.emit('60 ff7128');resolve(3);a.emit('85c0');a.branch('0f84','unregister_music_skip');a.emit('ffd0');a.label('unregister_music_skip');a.emit('83c404 61 8b442404 56');a.branch('e9',0x4a035)
        hook(0x4a030,'8b44240456','unregister_music','release helper reference before native performance CloseDown/Release')
    # Fixed-size name area keeps test and production code byte identical.
    a.label('dll_name');a.b.extend((b'rea_audio_test.dll\0' if test else b'rea_audio.dll\0').ljust(32,b'\0'))
    a.label('names');tablepos=len(a.b);a.b.extend(b'\0'*(4*len(names)))
    for symbol in names:a.label(symbol);a.b.extend(symbol.encode()+b'\0')
    a.label('half');a.b.extend(struct.pack('<f',0.5))
    resolver(a,im,data,names)
    payload=bytearray(a.finish())
    for i,symbol in enumerate(names):struct.pack_into('<I',payload,tablepos+4*i,a.labels[symbol])
    # Fallback loads are PIC base+constant-rva, never absolute process pointers.
    if name=='ZGUI':
        pattern=bytes.fromhex('d98000000000');pos=0
        for kind in range(3):
            pos=payload.index(pattern,pos);struct.pack_into('<I',payload,pos+2,a.labels['half']);pos+=6
    assert len(payload)<=0x1000
    rr,rs=struct.unpack_from('<II',b,opt+96+5*8);q=off(rr);removed=[]
    while q<off(rr)+rs:
        page,size=struct.unpack_from('<II',b,q);assert size>=8
        for p in range(q+8,q+size,2):
            ent=struct.unpack_from('<H',b,p)[0]
            if ent>>12==3 and page+(ent&4095) in remove:removed.append(hex(page+(ent&4095)));struct.pack_into('<H',b,p,0)
        q+=size
    assert len(removed)==len(remove)
    for i,(sname,va,content,flags) in enumerate([(b'.reaauC',code,payload,0x60000020),(b'.reaauD',data,bytes(0x100),0xc0000040)]):
        raw=align(len(b),fa);b.extend(bytes(raw-len(b)));rawsize=align(len(content),fa);b.extend(content);b.extend(bytes(rawsize-len(content)))
        struct.pack_into('<8sIIIIIIHHI',b,st+40*(n+i),sname,len(content),va,rawsize,raw,0,0,0,0,flags)
    struct.pack_into('<H',b,pe+6,n+2);struct.pack_into('<I',b,opt+56,align(data+0x100,sa))
    return b,dict(name=name,parent_sha256=PARENTS[name],candidate_sha256=hashlib.sha256(b).hexdigest(),test_helper=test,helper_dll='rea_audio_test.dll' if test else 'rea_audio.dll',code_rva=hex(code),data_rva=hex(data),payload_hex=payload.hex(),payload_size=len(payload),labels={k:hex(v) for k,v in a.labels.items()},changes=changes,removed_relocations=removed,status='built; native bridge probes pending')
