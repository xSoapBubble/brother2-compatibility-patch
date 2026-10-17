"""Build only: deterministic pending DXIExplosion save and legacy negative recovery."""

import hashlib,json,pathlib,struct

from zsol_mouse_payload import Asm,_pe

PARENT='aa596af0328ed1ae148a13083a239a436be4cfc66d232e2261f7a747058ebb52'

def build(parent):
 assert hashlib.sha256(parent).hexdigest()==PARENT
 b=bytearray(parent);off,_=_pe(b)
 u16=lambda p:struct.unpack_from('<H',b,p)[0];u32=lambda p:struct.unpack_from('<I',b,p)[0]
 pe=u32(60);opt=pe+24;st=opt+u16(pe+20)
 hdr=next(st+40*i for i in range(u16(pe+6)) if b[st+40*i:st+40*i+8]==b'.reacode')
 vs,va,sz,raw=struct.unpack_from('<IIII',b,hdr+8);assert u32(hdr+36)==0x60000020
 start=(vs+15)&~15;a=Asm(va+start)
 a.label('ctor_initialize');a.emit('895e34 895e48 895e4c 895e50 895e54 895e58 895e38 895e3c');a.branch('e9',0x51016)
 a.label('write_marker');a.emit('837ed000');a.branch('0f84','write_started')
 a.emit('6a00 8bcf');a.iat(0x6f7b0);a.branch('e9',0x5121b)
 a.label('write_started');a.emit('6a01 8bcf');a.iat(0x6f7b0);a.branch('e9',0x511a0)
 a.label('read_allocate');a.emit('837ed000');a.branch('0f84','read_original')
 a.emit('837d0000');a.branch('0f8f','read_original')
 a.emit('c7450000000000 c746f800000000');a.branch('e9',0x512f7)
 a.label('read_original');a.emit('8b5d00 8d145b');a.branch('e9',0x512a4)
 code=a.finish();assert start+len(code)<=sz and not any(b[raw+vs:raw+start+len(code)])
 changes=[]
 for rva,old,label in [(0x51010,'895e38895e3c','ctor_initialize'),(0x51196,'6a018bcfff15b0f70610','write_marker'),(0x5129e,'8b5d008d145b','read_allocate')]:
  old=bytes.fromhex(old);p=off(rva);assert b[p:p+len(old)]==old,(hex(rva),b[p:p+len(old)].hex())
  new=b'\xe9'+struct.pack('<i',a.labels[label]-rva-5)+b'\x90'*(len(old)-5);b[p:p+len(old)]=new
  changes.append(dict(rva=hex(rva),original=old.hex(),patched=new.hex(),label=label))
 rr,rs=struct.unpack_from('<II',b,opt+96+5*8);p=off(rr);removed=[]
 while p<off(rr)+rs:
  page,size=struct.unpack_from('<II',b,p);assert size>=8
  for q in range(p+8,p+size,2):
   ent=u16(q)
   if ent>>12==3 and page+(ent&4095)==0x5119c:struct.pack_into('<H',b,q,0);removed.append('0x5119c')
  p+=size
 assert removed==['0x5119c']
 b[raw+start:raw+start+len(code)]=code;struct.pack_into('<I',b,hdr+8,start+len(code))
 return b,dict(parent_sha256=PARENT,candidate_sha256=hashlib.sha256(b).hexdigest(),status='build-only; native tests pending; not installed',payload_rva=hex(a.rva),payload_size=len(code),payload_hex=code.hex(),labels={k:hex(v) for k,v in a.labels.items()},changes=changes,removed_relocations=removed,contract={'ctor':'ESI=whole; EBX=0; zero34/48/4c/50/54/58 and replay38/3c stores','writer':'ESI=whole+60, EDI=opstream; after native basewrite; pending emits marker0 then native epilogue; started replaymarker1 and remaining original writer','reader':'ESI=whole+60, EBP=whole+34; all36scalar bytes consumed; pending and signedcount<=0 canonicalize count0/bufferNULL; positive pending and started unchanged'},limits=['No generic count clamp; positive legacy pending count follows original path and consumes its original raw rows.','Active fragment serialization and reload are unchanged.','Writer marker0 is already understood by original reader.'])
