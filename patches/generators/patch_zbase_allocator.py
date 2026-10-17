"""Route allocations through the existing native heap rather than the old pool."""
import hashlib

ORIGINAL = '22c32a6e5c15c392ea63ee7d9bc19591138143b0daa6a3cea8a6d0638dd559e9'

def build(original):
    assert hashlib.sha256(original).hexdigest() == ORIGINAL
    offset = 232062  # RVA 0x38a7e, JBE into the legacy small-block pool.
    assert original[offset:offset + 2] == bytes.fromhex('761a')
    result = bytearray(original)
    result[offset:offset + 2] = bytes.fromhex('9090')
    return result, {'rva': '0x38a7e', 'reason': 'Use the existing native malloc path'}
