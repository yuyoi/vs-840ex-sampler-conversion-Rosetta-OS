"""Decode Roland's VS-840 / VS-840EX OS update SMFs (vs-840-1..8.mid, vs84ex-1..8.mid) into the flash image.

Same scheme as the SP-808 update (sp808/tools/decode_upd.py), but the model ID is 2 bytes:
  F0 41 00 00 0C 12 <a0 a1 a2 a3> <body> <ck> F7
Data messages: address 00 00 01 PP (PP = 64 KB page of the OS flash at 0x100000), body =
  4 nibbles  = 16-bit byte offset inside the page
  224 bytes  = 7-bit packed data, groups of 8 = 7 data bytes + 1 byte of their top bits -> 196 bytes
Address 01 xx xx xx messages are control (start / version string / end).

usage: python -I tools/decode_upd.py <folder with the 8 .mid files> <out.bin>
"""
import glob, os, sys


def vlq(b, i):
    v = 0
    while True:
        c = b[i]; i += 1; v = (v << 7) | (c & 0x7F)
        if c < 0x80: return v, i


def sysex(data):
    i = 0
    while True:
        i = data.find(b'\xF0', i)
        if i < 0: return
        n, j = vlq(data, i + 1)
        yield data[j:j + n]
        i = j + n


def unpack7(b):
    out = bytearray()
    for g in range(0, len(b), 8):
        grp = b[g:g + 8]; top = grp[-1]
        for k, x in enumerate(grp[:-1]):
            out.append(x | (0x80 if top & (0x40 >> k) else 0))
    return out


def decode(folder):
    img = bytearray(); chunks = 0; ctrl = []
    files = sorted(glob.glob(os.path.join(folder, '*.mid')), key=lambda p: int(p.rsplit('-', 1)[1].split('.')[0]))
    assert len(files) == 8, files
    for f in files:
        for m in sysex(open(f, 'rb').read()):
            if m[:5] != b'\x41\x00\x00\x0C\x12' or m[-1] != 0xF7: continue
            addr, body, ck = m[5:9], m[9:-2], m[-2]
            assert (sum(m[5:-2]) + ck) & 0x7F == 0, 'checksum'
            if addr[:3] != b'\x00\x00\x01':
                ctrl.append(addr.hex() + ' ' + bytes(body).hex()); continue
            off = (body[0] << 12) | (body[1] << 8) | (body[2] << 4) | body[3]
            payload = unpack7(body[4:])
            at = addr[3] * 0x10000 + off
            if len(img) < at + len(payload): img.extend(b'\xFF' * (at + len(payload) - len(img)))
            img[at:at + len(payload)] = payload; chunks += 1
    return bytes(img), chunks, ctrl


if __name__ == '__main__':
    img, chunks, ctrl = decode(sys.argv[1])
    open(sys.argv[2], 'wb').write(img)
    print('%d data messages -> %d bytes (0x%X), %d control messages' % (chunks, len(img), len(img), len(ctrl)))
    for c in ctrl[:6]: print('  ctrl', c[:100])
