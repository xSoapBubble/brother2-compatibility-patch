"""Build only: move the original render held-key replay to GameStepper pre-lock."""

import pathlib,hashlib,json,struct

from zsol_mouse_payload import Asm,_pe

PARENT='3bd1de74050e65ebe09bdf8568052425fda035b2619f7dce826f1344cf0597b2'

def build(parent):
 assert hashlib.sha256(parent).hexdigest()==PARENT
 b=bytearray(parent);off,imports=_pe(b)
 pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;st=opt+struct.unpack_from('<H',b,pe+20)[0]
 hdr=next(st+40*i for i in range(struct.unpack_from('<H',b,pe+6)[0]) if b[st+40*i:st+40*i+8]==b'.reamfix')
 vs,va,sz,raw=struct.unpack_from('<IIII',b,hdr+8);start=(vs+15)&~15;a=Asm(va+start)
 # Save the exact original pre-lock GPR/EFLAGS. No gate extends to the mutex.
 a.label('prestep_replay');a.emit('9c60');a.branch('e8',0x4e3e0);a.emit('85c0');a.branch('0f84','finish')
 a.emit('83ec10 648b0d00000000 890c24');a.address(0x4e4a9);a.emit('89442404');a.address(0x4f004)
 a.emit('89442408 c744240c01000000 64892500000000 8bfc')
 a.branch('e8',0x24d0);a.emit('85c0');a.branch('0f84','normal_leave');a.emit('8bc8');a.branch('e8',0x2ab0)
 a.label('normal_leave');a.emit('c7470c00000000 8b0f 64890d00000000 83c410');a.branch('e8',0x4e417)
 a.label('finish');a.emit('619d 8b4614 6aff 50');a.branch('e9',0xd79a)
 code=a.finish();assert start+len(code)<=sz and not any(b[raw+vs:raw+start+len(code)])
 changes=[]
 for rva,old,new,label in [(0xd794,bytes.fromhex('8b46146aff50'),b'\xe9'+struct.pack('<i',a.labels['prestep_replay']-0xd799)+b'\x90','prestep_replay'),(0x7de5,bytes.fromhex('e8c6acffff'),b'\x90'*5,'remove_render_replay')]:
  p=off(rva);assert b[p:p+len(old)]==old
  b[p:p+len(old)]=new;changes.append({'rva':hex(rva),'original':old.hex(),'patched':new.hex(),'label':label})
 b[raw+start:raw+start+len(code)]=code;struct.pack_into('<I',b,hdr+8,start+len(code))
 m={'parent_sha256':PARENT,'candidate_sha256':hashlib.sha256(b).hexdigest(),'status':'build-only; native QA pending; not installed','payload_rva':hex(a.rva),'payload_size':len(code),'payload_hex':code.hex(),'labels':{k:hex(v) for k,v in a.labels.items()},'changes':changes,'existing_helpers':{'try_enter':'0x4e3e0','leave':'0x4e417','unwind_handler':'0x4e4a9','generation':'0x4f000','inflight':'0x4f004','InterpretMouse_Get':'0x24d0','traceKeys':'0x2ab0'},'relocations_unchanged':True,'contract':'Inline at native Stepper d794 before reading mutex handle/pushing wait args. ESI=Stepper; EBX=StepGame,EBP=ReleaseMutex,EDI=WaitForSingleObject retained. Save all GPR/EFLAGS, enter existing lifetime gate, install same unwind registration (counter at+8/entered+12), resolve current Interpreter only after Begin, run original native256-byte traceKeys→existing guarded keyDown→nativeRoot route, End before all mutex/Time/Scene activity. Replay MOV EAX,[ESI+14]/PUSH−1/PUSHEAX; resume d79a nativeCALL EDI. Loading drops replay immediately without WaitingReady. Remove exactly original renderCALL7de5; surrounding Get calls/nativeScene unlock remain.','limits':['Held-key repeat rate follows modelling steps instead of rendered frames; direct native input polling is unchanged. Rates under heavy load and keyboard rotation/speed commands require ordinary validation.','No direct movement writes, custom binding/filter cache, new DLL/import/export, or FOV/fatigue/timestep/cap change.','Lifecycle generation prevents failed/stale admission but is not a general serialization lock between simultaneous valid input callbacks.','The new callback thread is GameStepper; inspected original input already dispatches GUI keys outside renderer, but arbitrary external script synchronous self-waits are not exhaustively proven absent.','Expected first model-frame delta-dependent actions see the last published delta, as original render replay did; this is not a new dt integration design.']}
 return b,m
