"""Minimal H8S/2600 disassembler (big-endian, advanced mode, 24-bit addresses).

Covers the common integer / move / branch / bit instructions. Anything unknown
is emitted as .word so a linear sweep keeps going.

usage: python -I h8sdis.py image.bin BASE START END     (hex numbers)
"""
import sys

R8 = ['r0h', 'r1h', 'r2h', 'r3h', 'r4h', 'r5h', 'r6h', 'r7h',
      'r0l', 'r1l', 'r2l', 'r3l', 'r4l', 'r5l', 'r6l', 'r7l']
R16 = ['r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7',
       'e0', 'e1', 'e2', 'e3', 'e4', 'e5', 'e6', 'e7']
def ER(n): return 'er%d' % (n & 7) if (n & 7) != 7 else 'sp'
COND = ['bra', 'brn', 'bhi', 'bls', 'bcc', 'bcs', 'bne', 'beq',
        'bvc', 'bvs', 'bpl', 'bmi', 'bge', 'blt', 'bgt', 'ble']
ALU79 = ['mov', 'add', 'cmp', 'sub', 'or', 'xor', 'and']
IMM8 = {0x8: 'add.b', 0x9: 'addx', 0xA: 'cmp.b', 0xB: 'subx', 0xC: 'or.b',
        0xD: 'xor.b', 0xE: 'and.b', 0xF: 'mov.b'}
RR = {0x08: 'add.b', 0x09: 'add.w', 0x0C: 'mov.b', 0x0D: 'mov.w', 0x0E: 'addx',
      0x14: 'or.b', 0x15: 'xor.b', 0x16: 'and.b', 0x18: 'sub.b', 0x19: 'sub.w',
      0x1C: 'cmp.b', 0x1D: 'cmp.w', 0x1E: 'subx', 0x64: 'or.w', 0x65: 'xor.w',
      0x66: 'and.w'}
BITR = {0x60: 'bset', 0x61: 'bnot', 0x62: 'bclr', 0x63: 'btst'}
BITI = {0x70: 'bset', 0x71: 'bnot', 0x72: 'bclr', 0x73: 'btst',
        0x74: ('bor', 'bior'), 0x75: ('bxor', 'bixor'), 0x76: ('band', 'biand'),
        0x77: ('bld', 'bild'), 0x67: ('bst', 'bist')}
SHIFT = {0x10: ('shll', 'shal'), 0x11: ('shlr', 'shar'),
         0x12: ('rotxl', 'rotl'), 0x13: ('rotxr', 'rotr')}
SZ = {0: ('.b', R8), 1: ('.w', R16), 3: ('.l', None)}

def s8(v): return v - 0x100 if v & 0x80 else v
def s16(v): return v - 0x10000 if v & 0x8000 else v
def s24(v): return v - 0x1000000 if v & 0x800000 else v

def dis(b, i, base):
    """returns (length, text, target_or_None)"""
    pc = base + i
    g = lambda k: b[i + k]
    w = lambda k: (b[i + k] << 8) | b[i + k + 1]
    a24 = lambda k: (b[i + k] << 16) | (b[i + k + 1] << 8) | b[i + k + 2]
    l32 = lambda k: (w(k) << 16) | w(k + 2)
    op, x = g(0), g(1)
    hi, lo = x >> 4, x & 15
    try:
        if op == 0 and x == 0: return 2, 'nop', None
        if op in RR:
            if op in (0x09, 0x0D, 0x19, 0x1D, 0x64, 0x65, 0x66):
                return 2, '%s %s,%s' % (RR[op], R16[hi], R16[lo]), None
            return 2, '%s %s,%s' % (RR[op], R8[hi], R8[lo]), None
        if op in (0x0A, 0x1A, 0x0F, 0x1F):
            if hi & 8:
                n = {0x0A: 'add.l', 0x1A: 'sub.l', 0x0F: 'mov.l', 0x1F: 'cmp.l'}[op]
                return 2, '%s %s,%s' % (n, ER(hi), ER(lo)), None
            if hi == 0:
                n = {0x0A: 'inc.b', 0x1A: 'dec.b', 0x0F: 'daa', 0x1F: 'das'}[op]
                return 2, '%s %s' % (n, R8[lo]), None
        if op in (0x0B, 0x1B):
            t = {0: ('adds', 'subs', '#1'), 8: ('adds', 'subs', '#2'), 9: ('adds', 'subs', '#4'),
                 5: ('inc.w', 'dec.w', '#1'), 0xD: ('inc.w', 'dec.w', '#2'),
                 7: ('inc.l', 'dec.l', '#1'), 0xF: ('inc.l', 'dec.l', '#2')}[hi]
            n = t[0] if op == 0x0B else t[1]
            reg = R16[lo] if 'w' in n else ER(lo)
            return 2, '%s %s,%s' % (n, t[2], reg), None
        if op in SHIFT:
            n = SHIFT[op][1 if hi & 8 else 0]
            sz = hi & 3; two = ',#2' if hi & 4 else ''
            suf, rr = SZ[sz]
            reg = rr[lo] if rr else ER(lo)
            return 2, '%s%s%s %s' % (n, suf, two and ' #2', reg) if two else '%s%s %s' % (n, suf, reg), None
        if op == 0x17:
            t = {0: 'not.b', 1: 'not.w', 3: 'not.l', 5: 'extu.w', 7: 'extu.l',
                 8: 'neg.b', 9: 'neg.w', 0xB: 'neg.l', 0xD: 'exts.w', 0xF: 'exts.l'}[hi]
            reg = R8[lo] if t.endswith('.b') else (R16[lo] if t.endswith('.w') else ER(lo))
            return 2, '%s %s' % (t, reg), None
        if op == 0x02: return 2, 'stc ccr,%s' % R8[lo], None
        if op == 0x03: return 2, 'ldc %s,ccr' % R8[lo], None
        if op in (0x04, 0x05, 0x06, 0x07):
            return 2, '%s #0x%02x,ccr' % (['orc', 'xorc', 'andc', 'ldc'][op - 4], x), None
        if 0x20 <= op <= 0x2F: return 2, 'mov.b @0x%06x:8,%s' % (0xFFFF00 | x, R8[op & 15]), None
        if 0x30 <= op <= 0x3F: return 2, 'mov.b %s,@0x%06x:8' % (R8[op & 15], 0xFFFF00 | x), None
        if 0x40 <= op <= 0x4F:
            t = pc + 2 + s8(x); return 2, '%s 0x%06x' % (COND[op & 15], t), t
        if op == 0x50: return 2, 'mulxu.b %s,%s' % (R8[hi], R16[lo]), None
        if op == 0x51: return 2, 'divxu.b %s,%s' % (R8[hi], R16[lo]), None
        if op == 0x52: return 2, 'mulxu.w %s,%s' % (R16[hi], ER(lo)), None
        if op == 0x53: return 2, 'divxu.w %s,%s' % (R16[hi], ER(lo)), None
        if op == 0x54 and x == 0x70: return 2, 'rts', None
        if op == 0x56 and x == 0x70: return 2, 'rte', None
        if op == 0x55: t = pc + 2 + s8(x); return 2, 'bsr 0x%06x' % t, t
        if op == 0x57: return 2, 'trapa #%d' % (hi & 3), None
        if op == 0x58 and lo == 0:
            t = pc + 4 + s16(w(2)); return 4, '%s 0x%06x' % (COND[hi], t), t
        if op == 0x5C and x == 0:
            t = pc + 4 + s16(w(2)); return 4, 'bsr 0x%06x' % t, t
        if op == 0x59: return 2, 'jmp @%s' % ER(hi), None
        if op == 0x5D: return 2, 'jsr @%s' % ER(hi), None
        if op == 0x5A: t = a24(1); return 4, 'jmp 0x%06x' % t, t
        if op == 0x5E: t = a24(1); return 4, 'jsr 0x%06x' % t, t
        if op == 0x5B: return 2, 'jmp @@0x%02x' % x, None
        if op == 0x5F: return 2, 'jsr @@0x%02x' % x, None
        if op in BITR: return 2, '%s %s,%s' % (BITR[op], R8[hi], R8[lo]), None
        if op in BITI:
            n = BITI[op]
            if isinstance(n, tuple): n = n[1 if hi & 8 else 0]
            return 2, '%s #%d,%s' % (n, hi & 7, R8[lo]), None
        if op in (0x68, 0x69, 0x6C, 0x6D):
            sz = '.b' if op in (0x68, 0x6C) else '.w'
            rr = R8 if sz == '.b' else R16
            st = hi & 8; e = ER(hi)
            if op in (0x68, 0x69):
                return 2, ('mov%s %s,@%s' % (sz, rr[lo], e)) if st else ('mov%s @%s,%s' % (sz, e, rr[lo])), None
            if op == 0x6D and (hi & 7) == 7:
                return 2, ('push.w %s' % R16[lo]) if st else ('pop.w %s' % R16[lo]), None
            return 2, ('mov%s %s,@-%s' % (sz, rr[lo], e)) if st else ('mov%s @%s+,%s' % (sz, e, rr[lo])), None
        if op in (0x6E, 0x6F):
            sz = '.b' if op == 0x6E else '.w'; rr = R8 if sz == '.b' else R16
            d = s16(w(2)); e = ER(hi)
            return 4, ('mov%s %s,@(%d,%s)' % (sz, rr[lo], d, e)) if hi & 8 else ('mov%s @(%d,%s),%s' % (sz, d, e, rr[lo])), None
        if op == 0x6A and x in (0x10, 0x18, 0x30, 0x38):
            # bit ops on absolute address: 6A 10/18 aaaa op x / 6A 30/38 aaaaaaaa op x
            if x in (0x10, 0x18): a = w(2); a = a | 0xFF0000 if a & 0x8000 else a; k = 4
            else: a = l32(2) & 0xFFFFFF; k = 6
            o2, x2 = g(k), g(k + 1); ea = '@0x%06x' % a
            if o2 in BITR: return k + 2, '%s %s,%s' % (BITR[o2], R8[x2 >> 4], ea), None
            if o2 in BITI:
                n = BITI[o2]
                if isinstance(n, tuple): n = n[1 if x2 & 0x80 else 0]
                return k + 2, '%s #%d,%s' % (n, (x2 >> 4) & 7, ea), None
            return k + 2, '.bitop %02x%02x %s' % (o2, x2, ea), None
        if op in (0x6A, 0x6B):
            sz = '.b' if op == 0x6A else '.w'; rr = R8 if sz == '.b' else R16
            if hi in (0, 8):
                a = w(2); a = a | 0xFF0000 if a & 0x8000 else a
                return 4, ('mov%s %s,@0x%06x:16' % (sz, rr[lo], a)) if hi == 8 else ('mov%s @0x%06x:16,%s' % (sz, a, rr[lo])), None
            if hi in (2, 0xA):
                a = l32(2) & 0xFFFFFF
                return 6, ('mov%s %s,@0x%06x' % (sz, rr[lo], a)) if hi == 0xA else ('mov%s @0x%06x,%s' % (sz, a, rr[lo])), None
        if op == 0x78 and lo == 0 and g(2) in (0x6A, 0x6B):
            sz = '.b' if g(2) == 0x6A else '.w'; rr = R8 if sz == '.b' else R16
            h3 = g(3) >> 4; r = g(3) & 15; d = s24(l32(4) & 0xFFFFFF)
            return 8, ('mov%s %s,@(%d,%s)' % (sz, rr[r], d, ER(hi))) if h3 & 8 else ('mov%s @(%d,%s),%s' % (sz, d, ER(hi), rr[r])), None
        if op == 0x79 and hi < 7:
            return 4, '%s.w #0x%04x,%s' % (ALU79[hi], w(2), R16[lo]), None
        if op == 0x7A and hi < 7:
            v = l32(2); return 6, '%s.l #0x%08x,%s' % (ALU79[hi], v, ER(lo)), v
        if op == 0x7B and x in (0x5C, 0xD4): return 4, 'eepmov.%s' % ('b' if x == 0x5C else 'w'), None
        if op in (0x7C, 0x7D, 0x7E, 0x7F):
            ea = ('@%s' % ER(hi)) if op in (0x7C, 0x7D) else ('@0x%06x:8' % (0xFFFF00 | x))
            o2, x2 = g(2), g(3)
            if o2 in BITR: return 4, '%s %s,%s' % (BITR[o2], R8[x2 >> 4], ea), None
            if o2 in BITI:
                n = BITI[o2]
                if isinstance(n, tuple): n = n[1 if x2 & 0x80 else 0]
                return 4, '%s #%d,%s' % (n, (x2 >> 4) & 7, ea), None
            return 4, '.bitop %02x%02x %s' % (o2, x2, ea), None
        if op >= 0x80:
            return 2, '%s #0x%02x,%s' % (IMM8[op >> 4], x, R8[op & 15]), None
        if op == 0x01:
            if x == 0x00:
                o2, y = g(2), g(3); yh, yl = y >> 4, y & 15
                if o2 == 0x69:
                    return 4, ('mov.l %s,@%s' % (ER(yl), ER(yh))) if yh & 8 else ('mov.l @%s,%s' % (ER(yh), ER(yl))), None
                if o2 == 0x6D:
                    if (yh & 7) == 7: return 4, ('push.l %s' % ER(yl)) if yh & 8 else ('pop.l %s' % ER(yl)), None
                    return 4, ('mov.l %s,@-%s' % (ER(yl), ER(yh))) if yh & 8 else ('mov.l @%s+,%s' % (ER(yh), ER(yl))), None
                if o2 == 0x6F:
                    d = s16(w(4))
                    return 6, ('mov.l %s,@(%d,%s)' % (ER(yl), d, ER(yh))) if yh & 8 else ('mov.l @(%d,%s),%s' % (d, ER(yh), ER(yl))), None
                if o2 == 0x6B:
                    if yh in (0, 8):
                        a = w(4); a = a | 0xFF0000 if a & 0x8000 else a
                        return 6, ('mov.l %s,@0x%06x:16' % (ER(yl), a)) if yh == 8 else ('mov.l @0x%06x:16,%s' % (a, ER(yl))), None
                    if yh in (2, 0xA):
                        a = l32(4) & 0xFFFFFF
                        return 8, ('mov.l %s,@0x%06x' % (ER(yl), a)) if yh == 0xA else ('mov.l @0x%06x,%s' % (a, ER(yl))), None
                if o2 == 0x78 and g(4) == 0x6B:
                    h5 = g(5) >> 4; r = g(5) & 15; d = s24(l32(6) & 0xFFFFFF)
                    return 10, ('mov.l %s,@(%d,%s)' % (ER(r), d, ER(yh))) if h5 & 8 else ('mov.l @(%d,%s),%s' % (d, ER(yh), ER(r))), None
            if x in (0x10, 0x20, 0x30) and g(2) == 0x6D:
                n = (x >> 4) + 1; y = g(3)
                if y & 0x80: return 4, 'stm.l er%d-er%d,@-sp' % (y & 7, (y & 7) + n - 1), None
                return 4, 'ldm.l @sp+,er%d-er%d' % ((y & 7) - n + 1, y & 7), None
            if x == 0x80: return 2, 'sleep', None
            if x == 0xC0 and g(2) in (0x50, 0x52):
                y = g(3)
                if g(2) == 0x50: return 4, 'mulxs.b %s,%s' % (R8[y >> 4], R16[y & 15]), None
                return 4, 'mulxs.w %s,%s' % (R16[y >> 4], ER(y & 15)), None
            if x == 0xD0 and g(2) in (0x51, 0x53):
                y = g(3)
                if g(2) == 0x51: return 4, 'divxs.b %s,%s' % (R8[y >> 4], R16[y & 15]), None
                return 4, 'divxs.w %s,%s' % (R16[y >> 4], ER(y & 15)), None
            if x == 0xF0 and g(2) in (0x64, 0x65, 0x66):
                y = g(3); n = {0x64: 'or.l', 0x65: 'xor.l', 0x66: 'and.l'}[g(2)]
                return 4, '%s %s,%s' % (n, ER(y >> 4), ER(y & 15)), None
    except (IndexError, KeyError):
        pass
    return 2, '.word 0x%04x' % w(0), None


def listing(b, base, start, end, labels=None):
    i = start - base
    out = []
    while base + i < end:
        n, t, tgt = dis(b, i, base)
        raw = b[i:i + n].hex()
        lab = (labels or {}).get(base + i)
        if lab: out.append('%s:' % lab)
        out.append('%06x: %-20s %s' % (base + i, raw, t))
        i += n
    return out


if __name__ == '__main__':
    path, base, start, end = sys.argv[1], *(int(v, 16) for v in sys.argv[2:5])
    data = open(path, 'rb').read()
    print('\n'.join(listing(data, base, start, end)))
