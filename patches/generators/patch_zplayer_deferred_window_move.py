"""Build only: remove WM_MOVE's DD->GameCS lock-order edge.

No installed game file is written. Single UI publisher / single renderer consumer.
All existing repair code and lifecycle data remain at their original addresses.
"""

import hashlib, json, pathlib, struct

from patch_zplayer_mouse_queue import Asm

from zsol_mouse_payload import _pe

PARENT = '1f3462d87715d97a09b01239d0a54578970e023ac4db139dd7824266c227bd93'

def build(parent):
    assert hashlib.sha256(parent).hexdigest() == PARENT
    b = bytearray(parent)
    off, imports = _pe(b)
    u16 = lambda p: struct.unpack_from('<H', b, p)[0]
    u32 = lambda p: struct.unpack_from('<I', b, p)[0]
    pe = u32(60); opt = pe + 24; st = opt + u16(pe + 20)
    sections = [(st+40*i, *struct.unpack_from('<IIII', b, st+40*i+8))
                for i in range(u16(pe+6))]
    rx = next(s for s in sections if b[s[0]:s[0]+8] == b'.reamfix')
    rw = next(s for s in sections if b[s[0]:s[0]+8] == b'.reagate')
    rh, rvs, rva, rsize, rraw = rx
    dh, dvs, dva, dsize, draw = rw
    assert u32(rh+36) == 0x60000020 and u32(dh+36) == 0xc0000040
    assert (rvs, rva, dvs, dva) == (0x8c9, 0x4e000, 0x40, 0x4f000)
    code_start = (rvs+15)&~15
    data_start = (dvs+3)&~3
    state_rva = dva+data_start
    assert state_rva % 4 == 0
    a = Asm(rva+code_start)

    # WM_MOVE branch entry contract: ESI=GameInitializer, EBP=packed lParam.
    # No game lock, callbacks, event or DirectDraw call on this producer path.
    a.label('publish_move')
    a.emit('9c60'); a.address(state_rva)
    a.emit('8bd5 8710 ba01000000 875004 619d')
    a.branch('e9', 0x10665)

    # Inline CALL replaces MOV [ESP+24],0 in update_view, after lock returns.
    # CALL adds 4 to the original ESP displacement. Activate existing native
    # EH cleanup before touching helper state or calling the Win32 event API.
    a.label('consume_move')
    a.emit('c744242800000000 9c60'); a.address(state_rva)
    a.emit('33d2 875004 85d2'); a.branch('0f84', 'consume_done')
    a.emit('8b10 0fbfca c1fa10 0fbfd2 898e80000000 899684000000')
    a.emit('ffb6a8000000'); a.iat(imports['PulseEvent'])
    a.label('consume_done'); a.emit('619d c3')
    payload = bytes(a.finish())
    assert code_start+len(payload) <= rsize
    assert data_start+8 <= dsize
    assert not any(b[rraw+code_start:rraw+code_start+len(payload)])
    assert not any(b[draw+data_start:draw+data_start+8])

    hooks = []
    for target, original, label, opcode in [
        (0x10356, '8dbeb8000000', 'publish_move', b'\xe9'),
        (0xfb62, 'c744242400000000', 'consume_move', b'\xe8'),
    ]:
        old = bytes.fromhex(original); p = off(target)
        assert b[p:p+len(old)] == old
        new = opcode+struct.pack('<i', a.labels[label]-(target+5))+b'\x90'*(len(old)-5)
        b[p:p+len(old)] = new
        hooks.append(dict(rva=hex(target), original=old.hex(), replacement=new.hex(),
                          label=label, file_offset=p, length=len(old)))

    # Neither displaced instruction has an absolute operand. Original unreachable
    # lock/event/unlock calls retain their relocations; new code is entirely PIC.
    rp = off(u32(opt+96+5*8)); end = rp+u32(opt+100+5*8)
    overlapping = []
    while rp < end:
        page, size = struct.unpack_from('<II', b, rp); assert size >= 8
        for ep in range(rp+8, rp+size, 2):
            e = u16(ep)
            if e >> 12 == 3:
                target = page+(e&0xfff)
                for h in hooks:
                    hr = int(h['rva'],16)
                    if target < hr+h['length'] and target+4 > hr:
                        overlapping.append(hex(target))
        rp += size
    assert not overlapping
    b[rraw+code_start:rraw+code_start+len(payload)] = payload
    struct.pack_into('<I', b, rh+8, code_start+len(payload))
    struct.pack_into('<I', b, dh+8, data_start+8)
    # Raw zero bytes already initialize the two new DWORDs; no runtime reset is
    # needed for the one GameInitializer lifetime. No new section or file bytes.
    allowed = [(h['file_offset'],h['file_offset']+h['length']) for h in hooks]
    allowed += [(rh+8,rh+12),(dh+8,dh+12),
                (rraw+code_start,rraw+code_start+len(payload))]
    changed = [i for i,(x,y) in enumerate(zip(parent,b)) if x != y]
    assert len(b) == len(parent)
    assert all(any(start <= i < end for start,end in allowed) for i in changed)
    report = dict(parent_sha256=PARENT,candidate_sha256=hashlib.sha256(b).hexdigest(),
        status='build-only; not installed; native fixture pending',
        hooks=hooks,labels={k:hex(v) for k,v in a.labels.items()},
        code_rva=hex(a.rva),code_size=len(payload),code_hex=payload.hex(),
        state_rva=hex(state_rva),fields={'packedXY':0,'pending':4},data_size=8,
        code_permissions='RX',data_permissions='RW, non-executable',
        removed_relocations=[],new_relocations=[],changed_file_offsets=changed,
        preserved_prior_code=True,existing_lifecycle_state_preserved=True,
        scene_or_activation_changes=False,
        helper_abi={
            'publish_move':'inline branch: ESI=GameInitializer, EBP=WM_MOVE packed lParam; preserves GPR/EFLAGS; tail JMP10665; no calls/locks',
            'consume_move':'inline CALL fromfb62: ESI=GameInitializer, original stack state0 at[ESP+24] becomes[ESP+28] at helper entry; replay first, preserve GPR/EFLAGS; RET after pending consume and PulseEvent under existing GameCS',
        },
        evidence=['rea-load-transition-lock-order-player-evidence.json: handleWEvent102b0 assembly/pseudo',
                  'rea-fullscreen-reactivation-player-evidence.json: update_viewfb30 pseudo',
                  'exact parentfb30..fb9e byte decoding; lock IAT297a4 CALLfb56 returnsfb5c'],
        concurrency='UI publishes aligned packedXY via XCHG then pending=1 via XCHG. Renderer clears pending via XCHG before reading packedXY. A racing newer publish may be applied again next frame, but final coordinates and pending publication are never lost. Both coordinates derive from one DWORD sample.')
    return bytes(b), report
