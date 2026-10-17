"""Build-only mouse displacement repair for the original Brother ZSOL.dll.

No file mutation or PE assembly is performed here. The caller must place code in
RX memory, data in RW memory, apply hooks, and remove the listed old relocations.
"""

import hashlib

import struct

EXPECTED_SHA256 = '7bc117fa33f29c414785c352c6bb1e824e25eadc7239f41ed01c12968be8f075'

MASTER_RVA = 0xaab20

LOCK_RVA = 0xab4f0

class Asm:
    def __init__(self, rva):
        self.rva, self.b, self.labels, self.fix = rva, bytearray(), {}, []

    def emit(self, value):
        self.b.extend(bytes.fromhex(value))

    def dword(self, value):
        self.b.extend(struct.pack('<I', value & 0xffffffff))

    def label(self, name):
        self.labels[name] = self.rva + len(self.b)

    def branch(self, opcode, destination):
        self.emit(opcode)
        self.fix.append((len(self.b), destination))
        self.dword(0)

    def address(self, rva):
        # call-next pushes moduleBase + instructionRva + 5, pop into EAX.
        self.emit('e8 00000000 58 05')
        self.dword(rva - (self.rva + len(self.b) - 2))

    def iat(self, rva):
        self.address(rva)
        self.emit('ff10')

    def finish(self):
        for position, destination in self.fix:
            target = self.labels[destination] if isinstance(destination, str) else destination
            struct.pack_into('<i', self.b, position, target - (self.rva + position + 4))
        return bytes(self.b)

def _pe(original):
    u16 = lambda offset: struct.unpack_from('<H', original, offset)[0]
    u32 = lambda offset: struct.unpack_from('<I', original, offset)[0]
    pe = u32(0x3c)
    coff, optional = pe + 4, pe + 24
    assert u16(coff) == 0x14c and u16(optional) == 0x10b
    section_table = optional + u16(coff + 16)
    sections = []
    for i in range(u16(coff + 2)):
        p = section_table + 40 * i
        sections.append((u32(p + 12), u32(p + 20), u32(p + 16)))

    def offset(rva):
        for va, raw, size in sections:
            if va <= rva < va + size:
                return raw + rva - va
        raise ValueError(f'RVA has no file backing: {rva:#x}')

    def cstr(p):
        return original[p:original.index(0, p)].decode('ascii')

    imports = {}
    p = offset(u32(optional + 104))
    while any(original[p:p + 20]):
        oft, _, _, _, ft = struct.unpack_from('<IIIII', original, p)
        q = offset(oft or ft)
        i = 0
        while (value := u32(q + i * 4)):
            if not value & 0x80000000:
                imports[cstr(offset(value) + 2)] = ft + i * 4
            i += 1
        p += 20
    return offset, imports

def build_mouse(code_rva, data_rva, original, gain=0.5):
    """Return code/data/hooks/relocation-removal/metadata; never write files.

    Data: owner DWORD; pending X/Y doubles; reference frameDT float (1/60).
    The existing statically initialized INnCMaster critical section protects
    owner and both pending axes. Keyboard/script Turn stays untouched.
    """
    if hashlib.sha256(original).hexdigest() != EXPECTED_SHA256:
        raise ValueError('Unsupported ZSOL.dll version')
    if data_rva % 4:
        raise ValueError('Mouse data must have at least DWORD alignment')
    if not 0.05 <= gain <= 4.0:
        raise ValueError('Mouse gain must be within 0.05..4.0')
    offset, imports = _pe(original)
    enter, leave = imports['EnterCriticalSection'], imports['LeaveCriticalSection']
    hooks = []
    a = Asm(code_rva)

    a.label('mouse_producer')
    # Hook is a jump in the function tail, before its original x87 writes.
    # pushfd+pushad saves 36 bytes: original arg [ESP+24] becomes [ESP+48].
    a.emit('9c 60 8b742448')              # preserve state; ESI=relative GPoint
    a.address(MASTER_RVA)
    a.emit('8b00 8bb8 60010000')          # EDI = master->character
    a.address(data_rva)
    a.emit('8bd8')                       # EBX = private mouse state
    a.address(LOCK_RVA)
    a.emit('50')
    a.iat(enter)
    a.emit('393b')                       # cmp [EBX],EDI
    a.branch('0f84', 'producer_owner_ok')
    a.emit('893b 31c0 894304 894308 89430c 894310')
    a.label('producer_owner_ok')
    a.emit('db06 dc4304 dd5b04')          # pendingX += (double)relative.x
    a.emit('db4604 d9e0 dc430c dd5b0c')  # pendingY -= (double)relative.y
    a.address(LOCK_RVA)
    a.emit('50')
    a.iat(leave)
    a.emit('61 9d 32c0 83c41c c20800')   # original return: false, pop locals, ret8

    a.label('mouse_consumer')
    # Original consumer has already copied and cleared character Turn. EBP
    # points to camera's two doubles. Original char/dt: [ESP+14]/[ESP+18].
    a.emit('9c 60 8b7c2438 8bf5')       # EDI=character; ESI=camera Turn
    a.address(data_rva)
    a.emit('8bd8')
    a.address(LOCK_RVA)
    a.emit('50')
    a.iat(enter)
    a.emit('393b')
    a.branch('0f84', 'consumer_owner_ok')
    a.emit('893b')
    a.branch('e9', 'consumer_clear')     # never carry counts across characters
    a.label('consumer_owner_ok')
    # Positive finite normal dt only. This also rejects all negative bit patterns.
    a.emit('8b44243c 3d00008000')
    a.branch('0f82', 'consumer_clear')
    a.emit('3d0000807f')
    a.branch('0f83', 'consumer_clear')
    # Existing camera code multiplies by 0.2*dt (and zoom). Cancel dt only for
    # mouse displacement, preserving legacy single-sample gain at 60 Hz.
    a.emit('d94314 d874243c')             # ST0 = referenceDT / actualDT
    a.emit('dd4304 d8c9 dc06 dd1e')       # cameraX += pendingX * ratio
    a.emit('dd430c dec9 dc4608 dd5e08')  # cameraY += pendingY * ratio; x87 balanced
    a.label('consumer_clear')
    a.emit('31c0 894304 894308 89430c 894310')
    a.address(LOCK_RVA)
    a.emit('50')
    a.iat(leave)
    a.emit('61 9d')
    a.emit('8b442414 8d9030010000')       # replay displaced original instructions
    a.branch('e9', 0x31141)
    code = a.finish()

    def hook(rva, expected, label):
        expected = bytes.fromhex(expected)
        actual = original[offset(rva):offset(rva) + len(expected)]
        if actual != expected:
            raise ValueError(f'Unexpected hook bytes at {rva:#x}: {actual.hex()}')
        patched = b'\xe9' + struct.pack('<i', a.labels[label] - (rva + 5))
        patched += b'\x90' * (len(expected) - len(patched))
        hooks.append({'rva': rva, 'original': expected.hex(), 'patched': patched})

    hook(0x3f035, '8b4424248b0d20ab0a10', 'mouse_producer')
    hook(0x31137, '8b4424148d9030010000', 'mouse_consumer')
    return {
        'code': code,
        'data': struct.pack('<Iddf', 0, 0.0, 0.0, gain / 60.0),
        'hooks': hooks,
        'remove_relocations': [0x3f03b],
        'metadata': {
            'version': 1,
            'original_sha256': EXPECTED_SHA256,
            'labels': {key: hex(value) for key, value in a.labels.items()},
            'code_rva': hex(code_rva), 'code_size': len(code),
            'data_rva': hex(data_rva), 'data_size': 24,
            'data_layout': {'owner': 0, 'pending_x': 4, 'pending_y': 12, 'reference_dt': 20},
            'reference_fps': 60, 'gain_multiplier': gain,
            'imports': {'enter': hex(enter), 'leave': hex(leave)},
            'critical_section_rva': hex(LOCK_RVA),
            'semantics': 'Locked raw relative-count accumulation; consume once per camera frame; normalize mouse-only gain to 60 Hz; keep keyboard Turn semantics.',
            'verification_required': 'Native producer/consumer probe at preferred and relocated base, then live game input/level transition check.',
        },
    }
