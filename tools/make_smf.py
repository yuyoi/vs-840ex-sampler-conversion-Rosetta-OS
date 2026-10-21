"""Image -> 8 update SMFs for the VS-840 / VS-840EX, using Roland's own SMFs as the template.

Every message, delta time and file boundary is kept; only the 196-byte payloads of the data
messages (addr 00 00 01 PP), the version string messages (addr 01 03 00 00) and the end
message (addr 01 01 00 00) change, each with its Roland checksum recomputed.

End message body = 4 zero nibbles + (~sum(image)) & 0x7F, image = flash 0x100000-0x1EFFFF
(0xF0000 bytes, SMF pages 01-0F). Verified on 1.05 (0x0D) and EX 2.05 (0x78).

usage: python -I tools/make_smf.py <template folder> <image.bin> <out folder> [prefix]
Round trip check: make_smf on the decoded stock image must reproduce Roland's files byte for byte.
"""
import glob, os, sys

SIZE = 0xF0000
VER_OFF = 0x624          # "VS-840 Ver 2.05\0\0Mar 21 2001\013:04:39" inside the image


def vlq(b, i):
    v = 0
    while True:
        c = b[i]; i += 1; v = (v << 7) | (c & 0x7F)
        if c < 0x80: return v, i


def pack7(data):
    out = bytearray()
    for g in range(0, len(data), 7):
        grp = data[g:g + 7]; top = 0
        for k, x in enumerate(grp):
            out.append(x & 0x7F)
            if x & 0x80: top |= 0x40 >> k
        out.append(top)
    return out


def ver_text(img):
    """Image header 0x624: name\0 (\0) date\0 time\0 -> SMF form 'name\0 date time\0'."""
    f = [x for x in bytes(img[VER_OFF:VER_OFF + 0x30]).split(b'\0') if x]
    return f[0] + b'\0 ' + f[1] + b' ' + f[2] + b'\0'


def rewrite(m, img, page0):
    """m = sysex body without F0 (ends with ck F7). Returns the new body, same length."""
    if m[:5] != b'\x41\x00\x00\x0C\x12': return m
    m = bytearray(m); addr = bytes(m[5:9]); body = m[9:-2]
    if addr[:3] == b'\x00\x00\x01':
        off = (body[0] << 12) | (body[1] << 8) | (body[2] << 4) | body[3]
        at = (addr[3] - page0) * 0x10000 + off
        n = (len(body) - 4) // 8 * 7
        chunk = bytearray(img[at:at + n]) if at < SIZE else bytearray()
        old = m[13:-2]
        if len(chunk) < n:                       # tail past the image: keep Roland's bytes
            from decode_upd import unpack7
            chunk += unpack7(old)[len(chunk):n]
        m[13:-2] = pack7(chunk)
    elif addr == b'\x01\x03\x00\x00':           # "VS-840 Ver 2.05\0 Mar 21 2001 13:04:39\0" from the image header
        k = len(body) - 4
        m[13:-2] = ver_text(img).ljust(k, b'\0')[:k]
        assert all(x < 0x80 for x in m[13:-2])
    elif addr == b'\x01\x01\x00\x00':
        m[-3] = (~sum(img)) & 0x7F
    m[-2] = (-sum(m[5:-2])) & 0x7F
    return bytes(m)


def build(tdir, img, odir, prefix=None):
    assert len(img) == SIZE, hex(len(img))
    files = sorted(glob.glob(os.path.join(tdir, '*.mid')), key=lambda p: int(p.rsplit('-', 1)[1].split('.')[0]))
    os.makedirs(odir, exist_ok=True); out = []
    for f in files:
        b = bytearray(open(f, 'rb').read()); i = 0
        while True:
            i = b.find(b'\xF0', i)
            if i < 0: break
            n, j = vlq(b, i + 1)
            b[j:j + n] = rewrite(bytes(b[j:j + n]), img, 1)
            i = j + n
        name = os.path.basename(f) if not prefix else '%s-%s' % (prefix, f.rsplit('-', 1)[1])
        open(os.path.join(odir, name), 'wb').write(b); out.append(name)
    return out


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    img = open(sys.argv[2], 'rb').read()
    print(build(sys.argv[1], img, sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None))
    print('image sum7 = 0x%02X' % ((~sum(img)) & 0x7F))
