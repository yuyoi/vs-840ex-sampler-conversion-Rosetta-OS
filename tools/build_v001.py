"""Rosetta OS 0.01 for the VS-840EX = stock 2.05 with a new version string. Data only, no code change.

Visible in test mode (hold MONITOR SEL + SOLO at power-on), whose screen prints the version string
(0x182EB0 / 0x113F10) and checks the flash sum ("Bad FLASH!!" on mismatch).

Image facts (see CONTEXT.md):
  image runs at 0x110000 (SMF page 01), size 0xF0000
  flash sum at 0x1FFF00 (u32 BE) = sum of bytes 0x110000..0x1FFEFF minus the 31 bytes at 0x11064A
  SMF end message = (~sum(image)) & 0x7F, recomputed by make_smf

usage: python -I tools/build_v001.py   -> work/v001/rosetta-1..8.mid + work/v001/os.bin
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_smf import build
from decode_upd import decode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x110000
SUM_AT, ID_AT, ID_LEN = 0xEFF00, 0x64A, 31

# (image offset, original bytes, new bytes)
PATCHES = [
    (0x624, b'VS-840 Ver 2.05', b'ROSETTA OS 0.01'),
]


def flash_sum(img):
    return (sum(img[:SUM_AT]) - sum(img[ID_AT:ID_AT + ID_LEN])) & 0xFFFFFFFF


def main():
    img = bytearray(open(os.path.join(ROOT, 'vs840ex_v205_os.bin'), 'rb').read())
    assert struct.unpack('>I', img[SUM_AT:SUM_AT + 4])[0] == flash_sum(img), 'stock sum'
    for off, old, new in PATCHES:
        assert len(old) == len(new) and img[off:off + len(old)] == old, hex(off)
        img[off:off + len(new)] = new
    img[SUM_AT:SUM_AT + 4] = struct.pack('>I', flash_sum(img))
    out = os.path.join(ROOT, 'work', 'v001')
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'os.bin'), 'wb').write(img)
    names = build(os.path.join(ROOT, 'upd', 'x_VS840EXv205'), bytes(img), out, 'rosetta')
    # read it back the way the unit will
    back, chunks, ctrl = decode(out)
    assert back[0x10000:0x100000] == img, 'decode mismatch'
    assert all(c.split()[1][8:].startswith(b'ROSETTA OS 0.01'.hex()) for c in ctrl if c.startswith('0103'))
    print('ok:', names, 'flash sum 0x%08X, end sum 0x%02X' % (flash_sum(img), (~sum(img)) & 0x7F))


if __name__ == '__main__':
    main()
