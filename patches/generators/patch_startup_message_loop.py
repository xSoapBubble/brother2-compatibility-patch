"""Remove redundant WaitMessage before blocking GetMessage; preserve other fixes."""

import hashlib,json,pathlib,struct

EXPECTED='3386e0a28fb4e5ecb6bb74bf70a8c7435ec3010eb3831d0142e06aa89585ae69'

RVA=0xe58d

OLD=bytes.fromhex('ff152c92021085c074f6')

def build(original):
    assert hashlib.sha256(original).hexdigest()==EXPECTED
    b=bytearray(original);pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;st=opt+struct.unpack_from('<H',b,pe+20)[0]
    sections=[struct.unpack_from('<IIII',b,st+40*i+8)for i in range(struct.unpack_from('<H',b,pe+6)[0])]
    offset=next(raw+RVA-va for vs,va,size,raw in sections if va<=RVA<va+size)
    assert b[offset:offset+len(OLD)]==OLD
    # Skip the entire redundant call/test/retry; retain its HIGHLOW relocation
    # in unreachable bytes so ASLR cannot corrupt executed padding.
    b[offset:offset+2]=bytes.fromhex('eb08')
    differences=[i for i,(x,y)in enumerate(zip(original,b))if x!=y]
    assert differences==[offset,offset+1]
    return bytes(b),dict(before_sha256=EXPECTED,after_sha256=hashlib.sha256(b).hexdigest(),rva=hex(RVA),file_offset=offset,old=OLD.hex(),new=bytes(b[offset:offset+len(OLD)]).hex(),changed_bytes=len(differences),same_size=len(original)==len(b),description='Short jump skips redundant WaitMessage/test/retry; preserve relocation data, blocking GetMessage, WM_QUIT, dispatch, focus, capture, lifecycle and frame pacing')
