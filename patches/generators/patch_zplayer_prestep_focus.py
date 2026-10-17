"""Build only v2: pre-step held replay requires real foreground and native admission."""

import pathlib,struct,hashlib,json

from zsol_mouse_payload import Asm,_pe

PARENT='7bce2b84564a5b57bc1d0ebd382ddb39f461fc45069afb74940deb3208668da9'

def build(parent):
 assert hashlib.sha256(parent).hexdigest()==PARENT
 b=bytearray(parent);off,imports=_pe(b)
 pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;st=opt+struct.unpack_from('<H',b,pe+20)[0]
 def section(name):return next(st+40*i for i in range(struct.unpack_from('<H',b,pe+6)[0]) if b[st+40*i:st+40*i+8].rstrip(b'\0')==name)
 hdr=section(b'.reamfix');vs,va,sz,raw=struct.unpack_from('<IIII',b,hdr+8)
 gh=section(b'.reagate');gvs,gva,gsz,graw=struct.unpack_from('<IIII',b,gh+8);assert gvs==0x48 and gva==0x4f000
 assert b[graw+0x48:graw+0x4c]==bytes(4)
 start=(vs+15)&~15;a=Asm(va+start);fix=[]
 def address_label(label):
  a.emit('e8 00000000 58 05');p=len(a.b);a.dword(0);fix.append((p,label,a.rva+p-2))
 a.label('prestep_replay');a.emit('9c60');a.branch('e8',0x4e3e0);a.emit('85c0');a.branch('0f84','finish')
 a.emit('83ec10 648b0d00000000 890c24');a.address(0x4e4a9);a.emit('89442404');a.address(0x4f004)
 a.emit('89442408 c744240c01000000 64892500000000 8bfc')
 a.branch('e8','focus_admitted');a.emit('85c0');a.branch('0f84','normal_leave')
 a.branch('e8',0x24d0);a.emit('85c0');a.branch('0f84','normal_leave');a.emit('8bc8');a.branch('e8',0x2ab0)
 a.label('normal_leave');a.emit('c7470c00000000 8b0f 64890d00000000 83c410');a.branch('e8',0x4e417)
 a.label('finish');a.emit('619d 8b4614 6aff 50');a.branch('e9',0xd79a)
 # Called only inside outer PUSHAD/SEH. EDI is the exception registration pointer
 # and MUST survive. EBX=Game, ESI=cache, EBP=module temporary; Win32 APIs preserve.
 a.label('focus_admitted');a.address(0x43078);a.emit('8b18 85db');a.branch('0f84','focus_reject')
 a.emit('837b7c00');a.branch('0f84','focus_reject');a.address(0x4f048);a.emit('8bf0 8b06 85c0')
 a.branch('0f85','foreground_getter_ready')
 address_label('user32_name');a.emit('50');a.iat(imports['GetModuleHandleA']);a.emit('85c0');a.branch('0f84','focus_reject');a.emit('8be8')
 address_label('foreground_export');a.emit('50 55');a.iat(imports['GetProcAddress']);a.emit('85c0');a.branch('0f84','focus_reject');a.emit('8906')
 a.label('foreground_getter_ready');a.emit('ffd0 3b437c');a.branch('0f85','focus_reject')
 for field in [0xa4,0xb0]:
  a.emit('8b83');a.dword(field);a.emit('85c0');a.branch('0f84','focus_reject');a.emit('6a00 50');a.iat(imports['WaitForSingleObject']);a.emit('85c0');a.branch('0f85','focus_reject')
 a.emit('b801000000 c3');a.label('focus_reject');a.emit('31c0 c3')
 a.label('user32_name');a.b.extend(b'user32.dll\0');a.label('foreground_export');a.b.extend(b'GetForegroundWindow\0')
 code=bytearray(a.finish())
 for p,label,origin in fix:struct.pack_into('<i',code,p,a.labels[label]-origin)
 assert start+len(code)<=sz and not any(b[raw+vs:raw+start+len(code)])
 old=bytes.fromhex('e9a711040090');assert b[off(0xd794):off(0xd794)+6]==old
 patch=b'\xe9'+struct.pack('<i',a.labels['prestep_replay']-0xd799)+b'\x90';b[off(0xd794):off(0xd794)+6]=patch
 assert b[off(0x7de5):off(0x7de5)+5]==b'\x90'*5
 b[raw+start:raw+start+len(code)]=code;struct.pack_into('<I',b,hdr+8,start+len(code));struct.pack_into('<I',b,gh+8,0x4c)
 m={'parent_sha256':PARENT,'candidate_sha256':hashlib.sha256(b).hexdigest(),'status':'build-only; native QA pending; not installed','payload_rva':hex(a.rva),'payload_size':len(code),'payload_hex':code.hex(),'labels':{k:hex(v) for k,v in a.labels.items()},'changes':[{'rva':'0xd794','original':old.hex(),'patched':patch.hex(),'label':'prestep_replay'}],'data':{'rva':'0x4f048','bytes':4,'initial':0,'semantics':'cached GetForegroundWindow pointer only; never stores HWND/Game/UI pointer'},'imports':{k:hex(imports[k]) for k in ['GetModuleHandleA','GetProcAddress','WaitForSingleObject']},'preserved':['Old7bce payload and removed rendercall7de5','All previous mouse/cursor/WM_MOVE/Alt/lifecycle/pacing fixes','Reagate0..47 including deferred-move40/44','Entire import/export/relocation directory and file size'],'contract':'Outer existing lifetime Begin + native SEH registration precede focus checks. Require nonNULL Game at43078 and HWND+7c, real process-global GetForegroundWindow equality, both existing manual-reset events Game+a4 and+b0 WaitForSingleObject(handle,0)==WAIT_OBJECT_0. Any NULL/resolvefail/foreground mismatch/eventtimeout/failure skips via normalLeave. Never wait for Ready/focus; leave all inflight ownership before original native mutex wait. EDI registration pointer preserved by focus helper. Whole native traceKeys is unchanged and runs only after admission.','helper_abi':{'focus_admitted':'RET0 EAX0/1; mayclobberEAX/ECX/EDX/EBX/ESI/EBP/EFLAGS, preservesEDI/ESP/x87/SSE. Called only inside outerPUSHAD; EBX holds Game, ESI cachepointer, EBP resolver modulehandle.'},'limits':['Exact foreground HWND equality follows requested policy. DDrawCompat fullscreen alias behavior still needs ordinary confirmation.','Zero-time focus check is a snapshot: focus can change just after admission; this does not serialize Win32 activation with the whole pass.','Existing polling input producer is unchanged; this only guards the migrated pre-step replay.','Old132-byte7bce payload remains preserved but unreachable from d794; rollback artifact names/proof remain unchanged.']}
 return b,m
