"""Rosetta OS 0.03 = 0.02 with the ROM dump triggered at a plain power-on (no buttons held).

0.02 needed PLAY + REC + TR1 held at power-on: not doable with two hands and the power switch on the back,
and Roland's combo match is exact, so it failed silently (the boot fell through to "Version up ?").
0.03 changes the combo compare at 0x11AF8A from 0x4180 to 0x0000 = "no key held". Every normal boot then
asks "ROM DUMP to CF?" (YES = dump, NO = boot on). The combo check runs before the update-file check.
One-off build: 0.04 puts the compare back.

usage: python -I tools/build_v003.py   -> work/v003/ (rosetta-1..8.mid, os.bin, $SYSPRO2.VS1)
"""
import os, shutil, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_smf import build
from decode_upd import decode
from build_v001 import flash_sum, SUM_AT
import build_v002

ROOT = build_v002.ROOT
PATCHES = [p for p in build_v002.PATCHES if p[0] != 0x624] + [
    (0x624, b'VS-840 Ver 2.05', b'ROSETTA OS 0.03'),
    (0xAF8C, b'\x41\x80', b'\x00\x00'),          # cmp.w #0x4180,r6 -> cmp.w #0x0000,r6
]


def main():
    img = bytearray(open(os.path.join(ROOT, 'vs840ex_v205_os.bin'), 'rb').read())
    assert struct.unpack('>I', img[SUM_AT:SUM_AT + 4])[0] == flash_sum(img), 'stock sum'
    for off, old, new in PATCHES:
        assert len(old) == len(new) and img[off:off + len(old)] == old, hex(off)
        img[off:off + len(new)] = new
    img[SUM_AT:SUM_AT + 4] = struct.pack('>I', flash_sum(img))
    out = os.path.join(ROOT, 'work', 'v003')
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'os.bin'), 'wb').write(img)
    shutil.copyfile(os.path.join(out, 'os.bin'), os.path.join(out, '$SYSPRO2.VS1'))
    build(os.path.join(ROOT, 'upd', 'x_VS840EXv205'), bytes(img), out, 'rosetta')
    back, _, _ = decode(out)
    assert back[0x10000:0x100000] == img, 'decode mismatch'
    print('ok: flash sum %08X' % flash_sum(img))


if __name__ == '__main__':
    main()
