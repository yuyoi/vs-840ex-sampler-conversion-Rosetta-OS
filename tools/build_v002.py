"""Rosetta OS 0.02 for the VS-840EX = 0.01 + a ROM dump to disk. Data only, no new code.

Roland's developer combo "SYSTEM FILE Wr?" (hold PLAY + REC + TR1 at power-on, combo 0x4180, item 4)
calls the file writer 0x12AFAA(name, addr, len) from 0x114C80 with ($SYSPRO2.VS1, 0x110000, 0xF0000).
0.02 changes its three arguments and the prompt:
  addr 0x110000 -> 0x000000, len 0xF0000 -> 0x100000   (CPU ROM / CS0, 1 MB; len must be a 64 KB multiple)
  name $SYSPRO2.VS1 -> ROMDUMP.VS1 (new string in free flash at 0x1FF000), so it is never seen as an update file
  prompt "SYSTEM FILE Wr?" -> "ROM DUMP to CF?"

Key bits at power-on (from the scan at 0x11AAD8 + key-name table 0x1F6F2E):
  b0 MONITOR b1 SOLO b2 INPUT b3 EQ b4 EFXL b5 AUXL b6 RIGHT b7 REC
  b8 TR1 b9 TR2 b10 TR3 b11 TR4 b12 MODE b13 ENTER b14 PLAY b15 PAN

usage: python -I tools/build_v002.py   -> work/v002/rosetta-1..8.mid + os.bin + $SYSPRO2.VS1
"""
import os, shutil, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_smf import build
from decode_upd import decode
from build_v001 import flash_sum, SUM_AT

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x110000
NAME_AT = 0x1FF000

# (image offset, original bytes, new bytes)
PATCHES = [
    (0x624, b'VS-840 Ver 2.05', b'ROSETTA OS 0.02'),
    (0x4C8E, struct.pack('>I', 0x0F0000), struct.pack('>I', 0x100000)),     # len
    (0x4C98, struct.pack('>I', 0x110000), struct.pack('>I', 0x000000)),     # addr
    (0x4CA2, struct.pack('>I', 0x1AB182), struct.pack('>I', NAME_AT)),      # name -> ROMDUMP.VS1
    (NAME_AT - BASE, b'\xff' * 12, b'ROMDUMP VS1\0'),
    (0x1A8B5A - BASE, b'SYSTEM FILE Wr?', b'ROM DUMP to CF?'),
]


def main():
    img = bytearray(open(os.path.join(ROOT, 'vs840ex_v205_os.bin'), 'rb').read())
    assert struct.unpack('>I', img[SUM_AT:SUM_AT + 4])[0] == flash_sum(img), 'stock sum'
    for off, old, new in PATCHES:
        assert len(old) == len(new) and img[off:off + len(old)] == old, hex(off)
        img[off:off + len(new)] = new
    img[SUM_AT:SUM_AT + 4] = struct.pack('>I', flash_sum(img))
    out = os.path.join(ROOT, 'work', 'v002')
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'os.bin'), 'wb').write(img)
    shutil.copyfile(os.path.join(out, 'os.bin'), os.path.join(out, '$SYSPRO2.VS1'))
    names = build(os.path.join(ROOT, 'upd', 'x_VS840EXv205'), bytes(img), out, 'rosetta')
    back, chunks, ctrl = decode(out)
    assert back[0x10000:0x100000] == img, 'decode mismatch'
    print('ok:', len(names), 'SMFs, flash sum 0x%08X (test mode shows %08X)' % (flash_sum(img), flash_sum(img)))


if __name__ == '__main__':
    main()
