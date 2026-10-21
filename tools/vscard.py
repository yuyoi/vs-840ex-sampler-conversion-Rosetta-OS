"""VS-840 card / Zip volume tools (FAT16 with < 4085 clusters).

Windows sees fewer than 4085 clusters and treats the volume as FAT12, so it reads multi-cluster
files as "corrupt" and its own writes (System Volume Information on every mount) put FAT12
entries into the FAT16 table. Never let Windows write to a VS card: patch an image here and
write it back raw with cardwrite.py.

  python -I tools/vscard.py check <volume.img>
  python -I tools/vscard.py fix-svi <in.img> <out.img>      undo Windows' SVI damage (2026-10-21 card)
  python -I tools/vscard.py add <in.img> <out.img> <file> [NAME.EXT]
"""
import struct, sys

ROOT_ENTS = 512


class Vol:
    def __init__(self, img):
        self.b = bytearray(img)
        b = self.b
        self.bps, self.spc, self.rsv, self.nfat, self.nroot, tot16, _, self.spf = struct.unpack_from('<HBHBHHBH', b, 11)
        self.tot = tot16 or struct.unpack_from('<I', b, 32)[0]
        assert b[3:11] == b'RolandBS' and self.bps == 512, 'not a VS volume'
        self.fat0 = self.rsv * 512
        self.root0 = self.fat0 + self.nfat * self.spf * 512
        self.data0 = self.root0 + self.nroot * 32
        self.cl = self.spc * 512
        self.ncl = (self.tot * 512 - self.data0) // self.cl

    def get(self, c): return struct.unpack_from('<H', self.b, self.fat0 + c * 2)[0]

    def put(self, c, v):
        for k in range(self.nfat): struct.pack_into('<H', self.b, self.fat0 + k * self.spf * 512 + c * 2, v)

    def chain(self, c):
        out = []
        while 2 <= c < self.ncl + 2 and c not in out and len(out) <= self.ncl: out.append(c); c = self.get(c)
        return out, c

    def entries(self, off, n):
        for i in range(n):
            o = off + i * 32; e = self.b[o:o + 32]
            if e[0] == 0: return
            if e[0] == 0xE5 or e[11] == 0x0F: continue
            yield o, e[:11].decode('latin1'), e[11], struct.unpack_from('<H', e, 26)[0], struct.unpack_from('<I', e, 28)[0]

    def files(self):
        """(path, start, size) of every file, root + one level of song folders."""
        for o, nm, at, c, sz in self.entries(self.root0, self.nroot):
            if at & 0x08: continue
            if at & 0x10:
                for c2 in self.chain(c)[0][:1]:
                    for o2, nm2, at2, cc, sz2 in self.entries(self.data0 + (c2 - 2) * self.cl, self.cl // 32):
                        if nm2[0] != '.': yield nm + '/' + nm2, cc, sz2, at2
            else:
                yield nm, c, sz, at

    def check(self):
        ok = True; seen = {}
        for path, c, sz, at in self.files():
            ch, end = self.chain(c)
            need = max(1, -(-sz // self.cl))
            good = end >= 0xFFF8 and (len(ch) == need or at & 0x10)
            for k in ch:
                if k in seen: good = False; print('  cross-link', k, path, seen[k])
                seen[k] = path
            if not good: ok = False
            print('%-24s start %5d clusters %4d need %4d end %04X %s' % (path, c, len(ch), need, end, '' if good else '<-- BAD'))
        used = [c for c in range(2, self.ncl + 2) if self.get(c)]
        lost = [c for c in used if c not in seen]
        print('clusters %d used %d free %d lost %d' % (self.ncl, len(used), self.ncl - len(used), len(lost)), lost[:20])
        fats = [bytes(self.b[self.fat0 + k * self.spf * 512:self.fat0 + (k + 1) * self.spf * 512]) for k in range(self.nfat)]
        print('FAT copies equal', all(f == fats[0] for f in fats))
        return ok and not lost

    def add(self, data, name83):
        n = max(1, -(-len(data) // self.cl))
        free = [c for c in range(2, self.ncl + 2) if self.get(c) == 0]
        run = next(free[i:i + n] for i in range(len(free)) if free[i:i + n] == list(range(free[i], free[i] + n)))
        for k, c in enumerate(run): self.put(c, run[k + 1] if k + 1 < n else 0xFFFF)
        for k, c in enumerate(run):
            o = self.data0 + (c - 2) * self.cl
            chunk = data[k * self.cl:(k + 1) * self.cl]
            self.b[o:o + self.cl] = chunk + bytes(self.cl - len(chunk))
        for i in range(self.nroot):
            o = self.root0 + i * 32
            if self.b[o] in (0, 0xE5):
                e = bytearray(32); e[:11] = name83; e[11] = 0x20
                e[22:26] = b'\xf0\x55\x48\x26'                  # same time/date bytes the VS writes (1999-02-08)
                struct.pack_into('<HI', e, 26, run[0], len(data))
                self.b[o:o + 32] = e
                return run
        raise SystemExit('root directory full')


def fix_svi(v):
    """Windows' FAT12 writes for its SVI folder (cluster 54) + 2 files (98, 142) each hit 1.5 FAT16 bytes.
    Lost values solved from chain constraints (every used cluster has one predecessor, takes = 168 clusters)."""
    fixes = {40: 0x0029, 41: 0x0030, 73: 0x004F, 74: 0x0050, 106: 0x006F, 107: 0x0070}
    for c, v16 in fixes.items():
        cur = v.get(c)
        assert (c in (40, 73, 106) and cur == 0xFF00 | v16) or (c in (41, 74, 107) and cur == v16 | 0xF), (c, hex(cur))
        v.put(c, v16)
    # drop the SVI root entries (LFN x2 + SYSTEM~1); they sat in the first free slots
    for i in range(v.nroot):
        o = v.root0 + i * 32
        if v.b[o + 11] == 0x0F or v.b[o:o + 11] == b'SYSTEM~1   ':
            v.b[o:o + 32] = bytes(32)
    # compact: entries after a zeroed slot would be hidden, make sure none follow
    seen0 = False
    for i in range(v.nroot):
        o = v.root0 + i * 32
        if v.b[o] == 0: seen0 = True
        elif seen0: raise SystemExit('live root entry after a hole at %d' % i)


if __name__ == '__main__':
    cmd = sys.argv[1]
    v = Vol(open(sys.argv[2], 'rb').read())
    if cmd == 'check':
        sys.exit(0 if v.check() else 1)
    if cmd == 'fix-svi':
        fix_svi(v)
    elif cmd == 'add':
        data = open(sys.argv[4], 'rb').read()
        name = sys.argv[5] if len(sys.argv) > 5 else sys.argv[4].replace('\\', '/').rsplit('/', 1)[1]
        base, ext = name.upper().split('.')
        print('added at clusters', v.add(data, (base.ljust(8) + ext.ljust(3)).encode('ascii')))
    open(sys.argv[3], 'wb').write(v.b)
    print('check after:'); v.check()
