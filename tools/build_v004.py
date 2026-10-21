"""Rosetta OS 0.04 for the VS-840EX = stock 2.05 + Rosetta boot screen. Data only, no code change.

Boot screen: the OS boot (0x11AA4C -> 0x113DC0) blits one full-screen 136x32 bitmap from 0x1B57EF
with ROM 0x4106 (x 0, y 0, w 136, h 32). Format: 32 rows x 17 bytes, MSB = leftmost pixel, 544 bytes.
0.04 swaps that bitmap for Roland-chan + ROSETTA, the last frame of the SP-808 Rosetta boot animation
(sp808/assets/roland_chan_frames.npz, 132x32, user's own Hex Wizard art), centred with 2 px each side.
The 0.02/0.03 ROM dump patches are gone (Roland's SYSTEM FILE Wr is stock again).

usage: python -I tools/build_v004.py   -> work/v004/ (rosetta-1..8.mid, os.bin, $SYSPRO2.VS1, splash.png)
"""
import os, shutil, struct, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_smf import build
from decode_upd import decode
from build_v001 import flash_sum, SUM_AT

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x110000
SPLASH, W, H = 0x1B57EF, 136, 32
FRAMES = os.path.join(os.path.dirname(ROOT), 'sp808', 'assets', 'roland_chan_frames.npz')


def splash_bits():
    f = np.load(FRAMES)['screens'][-1]                     # 32 x 132, nonzero = dot on
    scr = np.zeros((H, W), np.uint8)
    scr[:, 2:2 + f.shape[1]] = f != 0
    out = bytearray()
    for y in range(H):
        for xb in range(W // 8):
            v = 0
            for k in range(8):
                if scr[y, xb * 8 + k]: v |= 0x80 >> k
            out.append(v)
    return bytes(out), scr


def main():
    img = bytearray(open(os.path.join(ROOT, 'vs840ex_v205_os.bin'), 'rb').read())
    assert struct.unpack('>I', img[SUM_AT:SUM_AT + 4])[0] == flash_sum(img), 'stock sum'
    bits, scr = splash_bits()
    assert len(bits) == W * H // 8
    patches = [
        (0x624, b'VS-840 Ver 2.05', b'ROSETTA OS 0.04'),
        (SPLASH - BASE, bytes(img[SPLASH - BASE:SPLASH - BASE + len(bits)]), bits),
    ]
    for off, old, new in patches:
        assert len(old) == len(new) and img[off:off + len(old)] == old, hex(off)
        img[off:off + len(new)] = new
    img[SUM_AT:SUM_AT + 4] = struct.pack('>I', flash_sum(img))
    out = os.path.join(ROOT, 'work', 'v004')
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'os.bin'), 'wb').write(img)
    shutil.copyfile(os.path.join(out, 'os.bin'), os.path.join(out, '$SYSPRO2.VS1'))
    build(os.path.join(ROOT, 'upd', 'x_VS840EXv205'), bytes(img), out, 'rosetta')
    back, _, _ = decode(out)
    assert back[0x10000:0x100000] == img, 'decode mismatch'
    try:                                                    # preview: green LCD, 6x scale
        from PIL import Image
        s = 6
        im = Image.new('RGB', (W * s + 24, H * s + 24), (150, 200, 40))
        px = im.load()
        for y in range(H):
            for x in range(W):
                c = (20, 40, 10) if scr[y, x] else (140, 190, 35)
                for dy in range(s - 1):
                    for dx in range(s - 1):
                        px[12 + x * s + dx, 12 + y * s + dy] = c
        im.save(os.path.join(out, 'splash.png'))
    except ImportError:
        pass
    print('ok: flash sum %08X' % flash_sum(img))


if __name__ == '__main__':
    main()
