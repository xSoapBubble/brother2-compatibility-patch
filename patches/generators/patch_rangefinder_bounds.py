"""Give only the two original blue range readouts their measured raster width.

No position, public layout size, font, precision, resources or reticle changes.
"""

import pathlib,hashlib,struct,json

from zsol_mouse_payload import Asm,_pe

PARENT='a35a60b2d7db383aec62ec3883196cfd7335a22070790bdf1d6480b8daea5b21'

def build(parent):
    assert hashlib.sha256(parent).hexdigest()==PARENT
    b=bytearray(parent);off,_=_pe(b);p=struct.unpack_from('<I',b,60)[0];s=p+24+struct.unpack_from('<H',b,p+20)[0]
    hdr=next(s+40*i for i in range(struct.unpack_from('<H',b,p+6)[0]) if b[s+40*i:s+40*i+8].rstrip(b'\0')==b'.reacam')
    vs,va,size,raw=struct.unpack_from('<IIII',b,hdr+8);start=(vs+15)&~15
    a=Asm(va+start)
    a.label('range_width')
    # FLD/FMUL push one width, with all integer registers and CPU flags saved.
    a.emit('9c 50 dd4618 dc4e38')
    for field,value in [(0xb8,50),(0xbc,22),(0xb4,22),(0xc0,400),(0xa0,0xff0000)]:
        a.emit('81be');a.dword(field);a.dword(value);a.branch('0f85','width_done')
    a.emit('83be0801000000');a.branch('0f8e','width_done')
    a.emit('db8608010000 d8d1 dfe0 f6c401') # measured surface vs scaled layout
    a.branch('0f85','keep_layout')
    a.emit('ddd9');a.branch('e9','width_done') # FSTP ST1: measured replaces layout
    a.label('keep_layout');a.emit('ddd8')
    a.label('width_done');a.emit('58 9d c3')
    changes=[]
    for name,site,end,previous,source in [('source_width',0x2feb3,0x2fecc,0x811c0,True),('dest_width',0x2ff56,0x2ff67,0x8120c,False)]:
        a.label(name);a.branch('e8','range_width')
        a.emit('d9c1 ded9' if source else 'd8d9')
        a.emit('dfe0 f6c401');a.branch('0f85' if source else '0f84',name+'_selected')
        a.emit('ddd8');a.branch('e8','range_width')
        a.label(name+'_selected')
        if source:a.emit('d9e8 dee9')
        a.branch('e9',end)
        old=(b'\xe9'+struct.pack('<i',previous-site-5)).ljust(end-site,b'\x90')
        assert b[off(site):off(end)]==old
        new=(b'\xe9'+struct.pack('<i',a.labels[name]-site-5)).ljust(end-site,b'\x90')
        b[off(site):off(end)]=new
        changes.append(dict(rva=hex(site),old=old.hex(),new=new.hex()))
    payload=a.finish();assert start+len(payload)<=size and not any(b[raw+vs:raw+start+len(payload)])
    b[raw+start:raw+start+len(payload)]=payload;struct.pack_into('<I',b,hdr+8,start+len(payload))
    m=dict(parent_sha256=PARENT,candidate_sha256=hashlib.sha256(b).hexdigest(),payload_rva=hex(a.rva),payload_size=len(payload),labels={k:hex(v) for k,v in a.labels.items()},changes=changes,contract='For original Arial22,weight400,window50x22,blue range readouts only, use max(scaled logical width,measured text surface width) as existing source/destination min operand. Keep native rounding, source minus1 and vertical bounds. No object writes, absolute references, new relocations or precision changes.',status='candidate; validation pending')
    return b,m
