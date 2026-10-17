"""Build only: retain original optic toggle edge across missing action pulses while held."""

import hashlib,json,pathlib,struct

from zsol_mouse_payload import Asm,_pe

PARENT='a23d4904087cdd60771f9a2c849f5c9cb984b36eb009318eed52264a34c08728'

def build(parent):
 assert hashlib.sha256(parent).hexdigest()==PARENT
 b=bytearray(parent);off,imports=_pe(b)
 u16=lambda p:struct.unpack_from('<H',b,p)[0]
 u32=lambda p:struct.unpack_from('<I',b,p)[0]
 pe=u32(60);opt=pe+24;st=opt+u16(pe+20)
 def section(name):
  h=next(st+40*i for i in range(u16(pe+6)) if b[st+40*i:st+40*i+8].rstrip(b'\0')==name)
  return h,struct.unpack_from('<IIII',b,h+8)
 ch,(cvs,cva,csz,craw)=section(b'.reacode');dh,(dvs,dva,dsz,draw)=section(b'.readata')
 assert u32(ch+36)==0x60000020 and u32(dh+36)==0xc0000040
 start=(cvs+15)&~15;ds=(dvs+15)&~15;data=dva+ds
 a=Asm(cva+start)
 def addrlabel(label):
  a.emit('e8 00000000 58 05');p=len(a.b);a.dword(0);label_fixes.append((p,label,a.rva+p-2))
 label_fixes=[]
 # Neither thunk changes the native CMP AL,1 flags nor any original GPR.
 for label,resume in [('rifle_previous',0x20ca5),('binokl_previous',0x21a25)]:
  a.label(label);a.emit('9c 60');a.branch('e8','update_previous');a.emit('61 9d 885d5d');a.branch('e9',resume)
 a.label('read_success')
 a.emit('9c 60 8b6c2434')  # saved native read-this [oldESP+10]
 a.branch('e8','configure_keys');a.emit('61 9d 8b4c246c 5f 5e');a.branch('e9',0x3df46)

 # EBP=item, CL=current accepted action pulse. All calls are inside PUSHAD.
 a.label('update_previous');a.emit('84c9');a.branch('0f85','store_original_pulse')
 a.emit('807d5e01');a.branch('0f85','store_original_pulse')
 a.branch('e8','is_configured_key_held');a.emit('88455e c3')
 a.label('store_original_pulse');a.emit('884d5e c3')

 # EBP=original Master::read secondary-this. Called after native registry override.
 # Layout from exact original assembly: binding pointers[-98], count[-94].
 a.label('configure_keys');a.address(data);a.emit('8bf0 c7460400000000 8d7e08 31c0 b910000000 f3ab')
 # resolve("Zooming") uses hidden 4-byte NameLinkID output; no retained object.
 a.emit('83ec04');a.address(0xa62d4);a.emit('50 8d442404 50')
 a.iat(imports['?Get@NameLink@Nestor@@SAPAV12@XZ']);a.emit('8bc8')
 a.iat(imports['?resolve@NameLink@Nestor@@QAE?AVNameLinkID@2@PBD@Z'])
 a.emit('8b10 83c404 8bbd68ffffff 8b8d6cffffff 85c9')
 a.branch('0f8e','configuration_ready')
 a.label('binding_loop');a.emit('8b1f 395304');a.branch('0f85','next_binding')
 a.emit('8b03 a900100000');a.branch('0f84','next_binding')
 a.emit('25ff010000 0fab4608')  # atomicity not needed: loading/read callback owns publication
 a.label('next_binding');a.emit('83c704 49');a.branch('0f85','binding_loop')
 a.label('configuration_ready');a.emit('c7460401000000 c3')

 # Returns AL=0/1. Clobbers volatile and EBX/ESI/EDI; preserves EBP and x87/SSE.
 a.label('is_configured_key_held');a.address(data);a.emit('8bf0 837e0401')
 a.branch('0f85','not_held');a.emit('8b06 85c0');a.branch('0f85','getter_ready')
 addrlabel('player_name');a.emit('50');a.iat(imports['GetModuleHandleA']);a.emit('85c0')
 a.branch('0f84','not_held');a.emit('8bd8');addrlabel('get_export_name');a.emit('50 53')
 a.iat(imports['GetProcAddress']);a.emit('85c0');a.branch('0f84','not_held');a.emit('8906')
 a.label('getter_ready');a.emit('ffd0 85c0');a.branch('0f84','not_held');a.emit('8bf8 31c9')
 a.label('scan_loop');a.emit('8b848f10010000 3dff010000');a.branch('0f87','next_scan')
 a.emit('0fa34608');a.branch('0f83','next_scan')
 a.emit('f6440f1080');a.branch('0f85','held')
 a.label('next_scan');a.emit('41 81f900010000');a.branch('0f82','scan_loop')
 a.label('not_held');a.emit('31c0 c3')
 a.label('held');a.emit('b801000000 c3')
 a.label('player_name');a.b.extend(b'ZPlayer.dll\0')
 a.label('get_export_name');a.b.extend(b'?Get@InterpretMouse@Nestor@@SAPAV12@XZ\0')
 code=bytearray(a.finish())
 for p,label,origin in label_fixes:struct.pack_into('<i',code,p,a.labels[label]-origin)
 assert start+len(code)<=csz and ds+72<=dsz
 assert not any(b[craw+cvs:craw+start+len(code)]) and not any(b[draw+dvs:draw+ds+72])
 changes=[]
 for rva,old,label in [(0x20c9f,'884d5e885d5d','rifle_previous'),(0x21a1f,'884d5e885d5d','binokl_previous'),(0x3df40,'8b4c246c5f5e','read_success')]:
  old=bytes.fromhex(old);p=off(rva);assert b[p:p+len(old)]==old,(hex(rva),b[p:p+len(old)].hex())
  patch=b'\xe9'+struct.pack('<i',a.labels[label]-rva-5)+b'\x90'*(len(old)-5)
  b[p:p+len(old)]=patch;changes.append({'rva':hex(rva),'original':old.hex(),'patched':patch.hex(),'label':label})
 b[craw+start:craw+start+len(code)]=code;struct.pack_into('<I',b,ch+8,start+len(code))
 b[draw+ds:draw+ds+72]=bytes(72);struct.pack_into('<I',b,dh+8,ds+72)
 m={'parent_sha256':PARENT,'candidate_sha256':hashlib.sha256(b).hexdigest(),'status':'build-only; not installed; review/native QA pending','payload_rva':hex(a.rva),'payload_size':len(code),'payload_hex':code.hex(),'data_rva':hex(data),'data_size':72,'data_layout':{'cached_Get_function':0,'configuration_ready':4,'configured_logical_key_bitset_512':8},'labels':{k:hex(v) for k,v in a.labels.items()},'changes':changes,'removed_relocations':[],'imports':{k:hex(imports[k]) for k in ['GetModuleHandleA','GetProcAddress','?Get@NameLink@Nestor@@SAPAV12@XZ','?resolve@NameLink@Nestor@@QAE?AVNameLinkID@2@PBD@Z']},'contracts':{'rifle_previous/binokl_previous':'Native entry EBP=item,CL=[item+5d],AL=[item+5c],BL=0; preserve every GPR/EFLAGS (original CMP AL,1) and x87/SSE; update5e from CL except keep1 forCL0/old5e1/held actual configured key. Replay5d=BL then exact original branch.','read_success':'Native read epilogue, [ESP+10]=original secondary Master read-this. Preserve GPR/EFLAGS, resolve existing NameLinkID Zooming, copy actual down packed keys only from bindings[this-98]/count[this-94], then replay MOVECX,[ESP+6c]/POPedI/POPesI and resume3df46. Configready0 before lookup and1 after complete copy.','configure_keys':'Private helper EBP=original read-this; caller PUSHAD; clobbers EAX/ECX/EDX/EBX/ESI/EDI/EFLAGS; EBP preserved; RET0, x87/SSE untouched. NameLink Get cdeclRET0, resolve thiscallRET8 with hidden output.','is_configured_key_held':'Private helper returns EAX0/1, clobbers all except EBP; RET0, no x87/SSE. Cached existing Player InterpretMouse::Get cdeclRET0, NULL handled; exact current engine map+110 maps scan to configured logical codes; heldbyte+10 bit80. Unknown/missing config/resolution/map =>0 native fallback.','update_previous':'Private helper EBP=item,CL=pulse, modifiesonly[item+5e] plus helper scratch/registers (outerPUSHAD restores); never changes58/5c/60/64/5d.'},'limits':['Process-only snapshot preserves original sampling boundary; a complete release/repress between process samples is not newly guaranteed.','No hardcoded Z, GetAsyncKeyState, timestamp debounce, or synthesized action pulse.','Configuration is refreshed on each successful native Master read after registry overrides; no GUI record or Master pointer retained. Active-binding mutation without a native Master read needs a separately proven refresh boundary.','If native Master read throws before successful epilogue, this hook is not reached; existing view lifecycle must prevent processing the failed view. If our lookup throws after starting, configurationready remains0.','Only the original keyboard Zooming path has maintained held-state support. Non-keyboard pulses with no matching keyboard hold follow original pulse behavior.','No installed Bin/process modifications; all parent bytes preserved except3hooksites, section VirtualSize fields, newRXpayload/RWzero range.']}
 return b,m
