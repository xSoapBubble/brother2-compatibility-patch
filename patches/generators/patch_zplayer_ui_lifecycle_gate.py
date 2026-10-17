"""Build only: serialize input callback lifetime with whole view lifecycle.

No installed game file is written. On-disk initial odd generation means Loading.
Queue publication/last_event bookkeeping remains in its existing consumer.
"""

import hashlib,json,pathlib,struct

from patch_zplayer_frame_pacing import FrameAsm

from zsol_mouse_payload import _pe

PARENT='ffe7b091cec946ce909bc56643e9924c84399dca44383002e79cc046941574ff'

def build(parent):
    assert hashlib.sha256(parent).hexdigest()==PARENT
    b=bytearray(parent);off,imports=_pe(b)
    u16=lambda p:struct.unpack_from('<H',b,p)[0]
    u32=lambda p:struct.unpack_from('<I',b,p)[0]
    pe=u32(60);opt=pe+24;st=opt+u16(pe+20);n=u16(pe+6)
    sections=[(st+40*i,*struct.unpack_from('<IIII',b,st+40*i+8)) for i in range(n)]
    hdr,vs,va,sz,raw=sections[-1]
    assert b[hdr:hdr+8]==b'.reamfix' and va==0x4e000 and sz==0x1000
    start=(vs+15)&~15;rw=(va+max(vs,sz)+0xfff)&~0xfff
    assert rw==0x4f000 and st+(n+1)*40<=0x1000
    newhdr=st+n*40;assert not any(b[newhdr:newhdr+40])
    a=FrameAsm(va+start)
    fields={'generation':0,'inflight':4,'accepted':8,'dropped':12,
        'normal_exits':16,'unwind_exits':20,'transitions':24,'publications':28,'drain_polls':32}
    # EAX points to RW; EDX samples generation. No OS calls or nonvolatiles.
    a.label('try_enter');a.address(rw);a.emit('8b10 f6c201');a.branch('0f85','reject')
    a.emit('f0ff4004 3b10');a.branch('0f85','reject_counted')
    a.emit('f0ff4008 b801000000 c3')
    a.label('reject_counted');a.emit('f0ff4804')
    a.label('reject');a.emit('f0ff400c 33c0 c3')
    a.label('leave');a.address(rw);a.emit('f0ff4804 f0ff4010 c3')
    # No gate lock held during callbacks/scene work. Poll only on view thread.
    a.label('mark_loading');a.emit('56');a.address(rw);a.emit('8bf0 f0830e01 f0ff4618')
    a.label('drain');a.emit('837e0400');a.branch('0f84','drained')
    a.emit('f0ff4620 6a01');a.iat(imports['Sleep']);a.branch('e9','drain')
    a.label('drained');a.emit('5e c3')
    a.label('publish_ready');a.address(rw);a.emit('f60001');a.branch('0f84','published')
    a.emit('f0ff00 f0ff401c');a.label('published');a.emit('c3')
    # Existing native TRef reset helper8450 clears pointer then releases correct
    # virtual RefCounter base. Safe only after callbacks drain, before UI cleanup.
    # Do NOT free/reset518: consumer owns post-analize bookkeeping outside gate.
    a.label('clear_drag');a.address(0x42f04);a.emit('8b00 85c0');a.branch('0f84','drag_done')
    a.emit('c6802005000000 8d883c050000');a.branch('e8',0x8450)
    a.label('drag_done');a.emit('c3')
    # SEH handler cdecl(EXCEPTION_RECORD*,frame,CONTEXT*,dispatcher)->ContinueSearch.
    # Registration fields: prev0, handler4, counterPtr8, enteredFlag12.
    # First-chance search leaves count intact. Unwind clears flag exactly once.
    a.label('unwind_handler');a.emit('8b442404 f7400406000000');a.branch('0f84','continue_search')
    a.emit('8b542408 33c0 87420c 85c0');a.branch('0f84','continue_search')
    a.emit('8b4a08 f0ff09');a.address(rw+fields['unwind_exits']);a.emit('f0ff00')
    a.label('continue_search');a.emit('b801000000 c3')

    guards=[('analize',0x2b20,'64a100000000',4,False),
        ('mouse_enter',0x2800,'568bf1578b8e1c050000',4,True),
        ('mouse_leave',0x28d0,'568bf18a8620050000',4,True),
        ('hover',0x2ae0,'568bf18b8618050000',0,False),
        ('key_down',0x2fe0,'8b811c050000',4,False),
        ('key_up',0x3010,'8b811c050000',4,False)]
    for name,target,prolog,args,reset_inside in guards:
        a.label('guard_'+name);a.emit('55 8bec 53 56 57 8bf1');a.branch('e8','try_enter')
        a.emit('85c0');a.branch('0f84','drop_'+name)
        # Install one frame below the callee's own EH frame.
        a.emit('83ec10 648b0d00000000 890c24');a.address('unwind_handler');a.emit('89442404')
        a.address(rw+fields['inflight']);a.emit('89442408 c744240c01000000 64892500000000 8bfc')
        if args:a.emit('ff7508')
        a.emit('8bce');a.branch('e8','original_'+name)
        a.emit('c7470c00000000 8b0f 64890d00000000 83c410 50');a.branch('e8','leave');a.emit('58')
        a.branch('e9','finish_'+name)
        a.label('drop_'+name)
        if reset_inside:a.emit('c6862005000000')
        a.label('finish_'+name);a.emit('5f 5e 5b 8be5 5d')
        a.emit('c20400' if args else 'c3')
        a.label('original_'+name);a.emit(prolog);a.branch('e9',target+len(bytes.fromhex(prolog)))

    # Hook whole virtual overrides in GameView::run, not only MainGameView base.
    a.label('before_run');a.emit('9c60');a.branch('e8','mark_loading');a.branch('e8','clear_drag');a.emit('619d')
    a.emit('ff520c c6461d00 9c60');a.branch('e8','publish_ready');a.emit('619d c3')
    a.label('after_run');a.emit('9c60');a.branch('e8','mark_loading');a.branch('e8','clear_drag');a.emit('619d 8b06 8bce ff5010 c3')
    payload=a.finish();assert start+len(payload)<=sz,(start,len(payload),sz)
    changes=[]
    def hook(rva,expected,label):
        old=bytes.fromhex(expected);p=off(rva);assert b[p:p+len(old)]==old,(hex(rva),b[p:p+len(old)].hex())
        new=b'\xe9'+struct.pack('<i',a.labels[label]-(rva+5))+b'\x90'*(len(old)-5)
        b[p:p+len(old)]=new;changes.append({'rva':hex(rva),'original':old.hex(),'replacement':new.hex(),'label':label,'kind':'entry-jump'})
    for name,target,prolog,args,reset in guards:hook(target,prolog,'guard_'+name)
    # These are inline call-site wrappers and must RETURN to their original run.
    for target,expected,label in [(0x10b65,'ff520cc6461d00','before_run'),(0x10be1,'8b068bceff5010','after_run')]:
        old=bytes.fromhex(expected);p=off(target);assert b[p:p+len(old)]==old
        new=b'\xe8'+struct.pack('<i',a.labels[label]-(target+5))+b'\x90'*(len(old)-5)
        b[p:p+len(old)]=new;changes.append({'rva':hex(target),'original':old.hex(),'replacement':new.hex(),'label':label,'kind':'inline-call'})
    # All displaced prologs are position-independent. Prove no live HIGHLOW
    # operands intersect the replaced instruction spans.
    reloc=[];p=off(u32(opt+96+5*8));end=p+u32(opt+100+5*8)
    while p<end:
        page,size=struct.unpack_from('<II',b,p);assert size>=8
        for ep in range(p+8,p+size,2):
            e=u16(ep)
            if e>>12==3:reloc.append(page+(e&0xfff))
        p+=size
    assert not [r for r in reloc for c in changes if int(c['rva'],16)<=r<int(c['rva'],16)+len(bytes.fromhex(c['original']))]
    b[raw+start:raw+start+len(payload)]=payload
    struct.pack_into('<I',b,hdr+8,start+len(payload))
    rwraw=(len(b)+0xfff)&~0xfff;b.extend(b'\0'*(rwraw-len(b)));b.extend(b'\0'*0x1000)
    struct.pack_into('<I',b,rwraw,1)
    struct.pack_into('<8sIIIIIIHHI',b,newhdr,b'.reagate',0x40,rw,0x1000,rwraw,0,0,0,0,0xc0000040)
    struct.pack_into('<H',b,pe+6,n+1);struct.pack_into('<I',b,opt+56,rw+0x1000)
    struct.pack_into('<I',b,opt+8,u32(opt+8)+0x1000);struct.pack_into('<I',b,opt+64,0)
    # No existing payload bytes or old frame pacing call sites may change.
    for rva,size in [(0x4e000,vs),(0x10b9a,5),(0x10bb6,5),(0x2840,5),(0x2891,6),(0x978c,5)]:
        p=off(rva);assert b[p:p+size]==parent[p:p+size],hex(rva)
    return b,{'parent_sha256':PARENT,'candidate_sha256':hashlib.sha256(b).hexdigest(),
        'status':'build-only; native preferred/relocated/SEH/interleaving tests pending; not installed',
        'labels':{k:hex(v)for k,v in a.labels.items()},'changes':changes,
        'gate_rw':{'rva':hex(rw),'raw':hex(rwraw),'virtual_bytes':0x40,'raw_bytes':0x1000,'initial_generation':1,'fields':{k:hex(rw+v)for k,v in fields.items()}},
        'payload':{'rva':hex(va+start),'bytes':len(payload),'section_virtual_bytes':start+len(payload)},
        'imports':{k:hex(imports[k])for k in ['Sleep','GetCurrentThreadId']},
        'relocations_unchanged':True,'set_handler_scope':'Only native callers:10680→2f40;10680 called before_run6ee8/after_run7777. No other app Z*.dll imports found.',
        'helper_abi':{'try_enter':'cdecl void->EAX bool; EAX/EDX volatile; no count on false','leave':'cdecl void->void; normal counted exit','mark_loading':'cdecl void->void; odd generation and poll-drain; call only lifecycle thread outside callbacks','publish_ready':'cdecl void->void; increment odd generation to even after full init returns normally','clear_drag':'cdecl void->void; no518 write; native8450 release/reset53c after drain','unwind_handler':'cdecl(record*,frame*,context*,dispatcher*)->1; decrement entered frame once on flags&6','before_run':'inline wrapper expectsESI=view,ECX=view,EDX=vtable; invokesfullvirtual+c then publishes','after_run':'inline wrapper expectsESI=view; drain then invokesfullvirtual+10','guards':'native thiscall ECX=InterpretMouse; analize/enter/leave/key take1arg RET4; hoverRET0'},
        'limits':['Only inspected native GameView::run lifecycle path; synchronous lifecycle reentry from an already counted callback is unsupported and would self-wait.','Generation rejects Begin spanning a transition; it does not timestamp already queued packets.','last_event518 remains owned by existing consumer; direct Leave during Loading only clears inside520.','All guard wrappers preserve entered count on search and release it during SEH unwind or normal return.']}
