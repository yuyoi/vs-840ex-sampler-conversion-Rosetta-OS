"""Rosetta OS 0.05 for the VS-840EX = 0.04 (Rosetta boot screen) + CF-friendly drive check.

"Setup ERROR / -32746" (0x8016): after an IDE soft reset, 0x126DF4 accepts an ATA drive only with
sector count 1, sector 1, cylinder 0 and status == 0x50 (DRDY + DSC) on both status registers. The caller
(0x126FEC) already retries this for 20 s, so a CF that fails it is not slow but answers differently
(DSC is obsolete, many CF cards report 0x40; some don't keep the 1/1 signature).
0.05 relaxes the ATA branch only (the Zip/ATAPI 14 EB branch is unchanged):
  - sector count / sector number no longer checked     (2x `sub.w e1,e1` -> nop nop)
  - status: (s & 0xC0) == 0x40 = ready + not busy        (and #0xFD / cmp #0x50 -> and #0xC0 / cmp #0x40, x2)
Cylinder low/high must still be 0 (that's what says "ATA").

usage: python -I tools/build_v005.py   -> work/v005/
"""
import os, shutil, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_smf import build
from decode_upd import decode
from build_v001 import flash_sum, SUM_AT
import build_v004

ROOT = build_v004.ROOT
BASE = 0x110000


def main():
    img = bytearray(open(os.path.join(ROOT, 'vs840ex_v205_os.bin'), 'rb').read())
    assert struct.unpack('>I', img[SUM_AT:SUM_AT + 4])[0] == flash_sum(img), 'stock sum'
    bits, _ = build_v004.splash_bits()
    S = build_v004.SPLASH - BASE
    patches = [
        (0x624, b'VS-840 Ver 2.05', b'ROSETTA OS 0.05'),
        (S, bytes(img[S:S + len(bits)]), bits),
        (0x126E32 - BASE, bytes.fromhex('1999'), bytes.fromhex('0000')),          # nsect != 1: no fail
        (0x126E3A - BASE, bytes.fromhex('1999'), bytes.fromhex('0000')),          # sect != 1: no fail
        (0x126E56 - BASE, bytes.fromhex('796000fd79200050'), bytes.fromhex('796000c079200040')),   # alt status
        (0x126E6C - BASE, bytes.fromhex('796000fd79200050'), bytes.fromhex('796000c079200040')),   # status
    ]
    for off, old, new in patches:
        assert len(old) == len(new) and img[off:off + len(old)] == old, hex(off)
        img[off:off + len(new)] = new
    img[SUM_AT:SUM_AT + 4] = struct.pack('>I', flash_sum(img))
    out = os.path.join(ROOT, 'work', 'v005')
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'os.bin'), 'wb').write(img)
    shutil.copyfile(os.path.join(out, 'os.bin'), os.path.join(out, '$SYSPRO2.VS1'))
    build(os.path.join(ROOT, 'upd', 'x_VS840EXv205'), bytes(img), out, 'rosetta')
    back, _, _ = decode(out)
    assert back[0x10000:0x100000] == img, 'decode mismatch'
    print('ok: flash sum %08X' % flash_sum(img))


if __name__ == '__main__':
    main()
