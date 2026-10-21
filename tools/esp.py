"""Roland/Toshiba ESP2 (TC170C140-class) DSP: decoder, disassembler and a cycle simulator.

The SP-808 has one such chip: core 0 = "DSP0" (voices/mixer, window 0xC00000), core 1 = "DSP1" (effects, window
0xC01000, the only core with external delay RAM). Instruction semantics follow The Usual Suspects' public ESP
reverse-engineering (gearmulator, GPL); this file is an independent Python implementation of those facts.

Word (28 bits, as the DSP sees it):  EEEEE PPPPP MMMMMMMM SS CCCCCCCC
  E  bits 27-23  ERAM slot (core 1 only): 0x10 write, 0x08 read @imm, 0x18 read @var; then 4 words of 5-bit imm
  P  bits 22-18  opcode (listed as op = (w >> 16) & 0x7C)
  M  bits 17-10  IRAM/GRAM address, relative to a pointer that decrements once per sample
  S  bits 9-8    shift after the multiply: 0->7 1->6 2->5 3->3
  C  bits 7-0    signed 8-bit coefficient (op 0x30: selects a 24-bit mulcoeff register instead)
Every cycle: acc(A|B) (= or +=) (mulInputA_24 * coef) >> shift.  Accumulator reads see the value from 3 cycles ago.
In the OS image a word is stored as 3 bytes C, [M low 6 | S], [E low 1 | P | M high 2]; the loader writes them to the
host port as bytes 0..2 of a 32-bit long (byte 3 = E bits 27-24, only reachable through the 'ERAM' host write mode).
"""
import sys

SHIFTS = (7, 6, 5, 3)
CONST_MEM = {1: 0x10, 2: 0x400, 3: 0x10000, 4: 0x400000}


def rom_to_dsp(w24):
    """3-byte ROM word (coef byte first) -> DSP view."""
    return ((w24 & 0xFF) << 16) | (w24 & 0xFF00) | (w24 >> 16)


def dsp_to_rom(w):
    return ((w & 0xFF) << 16) | (w & 0xFF00) | ((w >> 16) & 0xFF)


def se(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def fields(w):
    return (w >> 16) & 0x7C, (w >> 10) & 0xFF, (w >> 8) & 3, w & 0xFF, (w >> 23) & 0x1F


def encode(op, mem=0, shift=7, coef=0, eram=0):
    """Build a DSP-view word. shift is the real shift (7/6/5/3) or for GRAM ops the raw 2-bit field."""
    sh = shift if shift < 4 else SHIFTS.index(shift)
    return (eram << 23) | ((op & 0x7C) << 16) | ((mem & 0xFF) << 10) | (sh << 8) | (coef & 0xFF)


def disasm_word(w, pc=0, core=1):
    op, mem, sh, coef, ectl = fields(w)
    if w & 0x7FFFFF == 0: return 'nop' + ('' if not ectl else '                 ; eram %02X' % ectl)
    shift = SHIFTS[sh]
    src = ('0x%X' % CONST_MEM[mem]) if mem in CONST_MEM else 'i[%02X]' % mem
    c = '%d' % se(coef, 8)
    acc, clr, pre, macsrc = 'A', False, '', src
    if op in (0x00, 0x04, 0x10, 0x14): acc, clr = ('B' if op & 0x10 else 'A'), bool(op & 4)
    elif op in (0x08, 0x0C, 0x18, 0x1C):
        acc, clr = ('B' if op & 0x10 else 'A'), True
        pre = 'i[%02X]=sat(%s); ' % (mem, 'B' if op & 4 else 'A'); macsrc = 'sat(%s)' % ('B' if op & 4 else 'A')
    elif op in (0x20, 0x24):
        acc, clr, shift, macsrc = ('B' if sh & 2 else 'A'), op == 0x24, (6 if sh & 1 else 7), 'g[%02X]' % mem
    elif op == 0x30:
        acc, clr = ('B' if coef & 2 else 'A'), not (coef & 1)
        if coef & 4: pre = 'i[%02X]=sat(%s); ' % (mem, acc); macsrc = 'sat(%s)' % acc
        k = coef >> 5
        c = {6: 'eramvar.frac', 7: 'mc5'}.get(k, 'mc%d' % k)
        if coef & 8: c = '-' + c
        if coef & 16: c = '(1-%s)' % c
        if (coef & 0x1C) == 0x1C: c += '?weird'
    elif op == 0x34:
        if 0xA0 <= mem < 0xB0: return 'mc%d = sat(%s)' % ((mem >> 1) & 7, 'B' if mem & 1 else 'A')
        if mem >= 0xC0:
            acc, clr, p = ('B' if mem & 0x20 else 'A'), bool(mem & 0x10), mem & 0xF
            if p <= 3: return '%s %03X (%s)' % (('JZ', 'JMI', 'JPL', 'JMP')[p], coef, acc)
            if p == 4: return 'INT'
            if p == 6: macsrc, c = 'prev>>7', 'lo7(%s)' % c
            elif p == 7: return 'eramvar = %s' % acc
            elif p == 0xA: return 'hostreg = sat(%s)' % acc
            elif p == 0xB: return 'eramwr = sat(%s)' % acc
            elif p >= 0xC: pre = 'i[%02X]=eramrd; ' % (mem | 0xF0); macsrc = 'eramrd'
            else: return '?34 mem %02X' % mem
        else: return '?34 mem %02X' % mem
    elif op in (0x38, 0x3C): return 'g[%02X] = sat(%s)' % (mem, 'B' if op & 4 else 'A')
    elif op in (0x40, 0x44): pre = 'i[%02X]=raw(A); ' % mem; macsrc = 'raw(A)'; clr = op == 0x44
    elif op in (0x48, 0x4C): pre = 'i[%02X]=rect(A); ' % mem; macsrc = 'rect(A)'; clr = op == 0x4C
    elif op == 0x50: pre = 'CMP: '; clr = True
    elif op in (0x58, 0x5C):
        acc = 'B' if op & 4 else 'A'; pre = 'i[%02X]=sat(%s); ' % (mem, acc); macsrc = 'sat(%s)' % acc
    elif op in (0x60, 0x64, 0x70, 0x74): macsrc = '~%s' % src; clr = bool(op & 4)
    elif op in (0x68, 0x6C): pre = 'i[%02X]=sat(A); ' % mem; macsrc = 'negflip(A)'; clr = bool(op & 4)
    elif op in (0x78, 0x7C): pre = 'i[%02X]=sat(A); ' % mem; macsrc = 'abs(A)'; clr = bool(op & 4)
    else: return '?op %02X' % op
    s = '%s%s %s %s * %s >> %d' % (pre, acc, '=' if clr else '+=', macsrc, c, shift)
    if ectl: s += '    ; eram %02X' % ectl
    return s


def disasm(words, core=1, out=sys.stdout, start=0, names=None):
    """words = DSP-view words. Annotates ERAM transactions like the hardware: start, 4 imm words, commit at +10."""
    pend = None
    for i, w in enumerate(words):
        pc = start + i
        op, mem, sh, coef, ectl = fields(w)
        note = ''
        if pend is None and ectl & 0x18:
            pend = [pc, ectl, 0]; note = ' <ERAM %s start>' % ({0x10: 'WRITE', 0x08: 'READ', 0x18: 'READvar'}.get(ectl, '%02X' % ectl))
        elif pend is not None and 0 < pc - pend[0] <= 4:
            pend[2] += ectl << (5 * (pc - pend[0] - 1))
            if pc - pend[0] == 4:
                note = ' <ERAM %s imm=%d(0x%X) commit@%03X>' % ({0x10: 'WRITE', 0x08: 'READ', 0x18: 'READvar'}.get(pend[1], '?'), pend[2], pend[2], pend[0] + 10)
                pend = None
        nm = (' ' + names.get(pc, '')) if names and pc in names else ''
        out.write('%03X: %07X  %s%s%s\n' % (pc, w, disasm_word(w, pc, core), note, nm))


class Acc:
    def __init__(self): self.v = 0; self.hist = [0, 0, 0]; self.head = 0
    def set(self, x): self.v = se(x, 30)
    def add(self, x): self.v = se(self.v + x, 30)
    def sat24(self): return max(-0x800000, min(0x7FFFFF, self.hist[self.head]))
    def raw24(self): return se(self.hist[self.head], 24)
    def rawfull(self): return self.hist[self.head]
    def push(self): self.hist[self.head] = self.v; self.head = (self.head + 1) % 3


class Core:
    """One ESP core. eram: shared ERAM object or None. gram: shared 256-list."""
    def __init__(self, prog, gram, eram=None, mulc=None, name='core'):
        self.prog = list(prog) + [0] * (768 - len(prog)); self.gram = gram; self.eram = eram; self.name = name
        self.iram = [0] * 256; self.pos = 0; self.A = Acc(); self.B = Acc()
        self.mulc = mulc if mulc is not None else [0] * 8
        self.lastA = 0; self.lastB = 0; self.last30 = False; self.skip = 0; self.jump = None; self.hostreg = 0
        self.trace = None

    def ri(self, m): return self.iram[(m + self.pos) & 0xFF]
    def wi(self, m, v): self.iram[(m + self.pos) & 0xFF] = v
    def rg(self, m): return self.gram[(m + self.pos) & 0xFF]
    def wg(self, m, v): self.gram[(m + self.pos) & 0xFF] = v

    def run_sample(self):
        for pc in range(768):
            if self.eram is not None: self.eram.tick(fields(self.prog[pc])[4], pc)
            self.step(pc)
        self.pos = (self.pos - 1) & 0xFF

    def step(self, pc):
        if self.jump and pc == self.jump[0]: pass        # jumps unsupported in straight-line programs here
        w = self.prog[pc]
        if w & 0x7FFFFF == 0:
            self.skip >>= 1; self.A.push(); self.B.push(); return
        op, mem, sh, coef, ectl = fields(w)
        shift = SHIFTS[sh]
        ia = CONST_MEM[mem] if mem in CONST_MEM else self.ri(mem)
        ib = se(coef, 8); acc = False; clr = False; setcond = False
        A, B = self.A, self.B
        if op == 0x00: pass
        elif op == 0x04: clr = True
        elif op == 0x08: ia = A.sat24(); self.wi(mem, ia); clr = True
        elif op == 0x0C: ia = B.sat24(); self.wi(mem, ia); clr = True
        elif op == 0x10: acc = True
        elif op == 0x14: acc = clr = True
        elif op == 0x18: acc = clr = True; ia = A.sat24(); self.wi(mem, ia)
        elif op == 0x1C: acc = clr = True; ia = B.sat24(); self.wi(mem, ia)
        elif op in (0x20, 0x24): acc = bool(sh & 2); clr = op == 0x24; shift = 6 if sh & 1 else 7; ia = self.rg(mem)
        elif op == 0x30:
            acc = bool(coef & 2); clr = not (coef & 1); weird = (coef & 0x1C) == 0x1C
            if coef & 4:
                ia = (B if acc else A).sat24()
                if weird: ia = 0x7FFFFF if ia >= 0 else -0x800000
                self.wi(mem, ia)
            k = coef >> 5
            ib = self.mulc[k]
            if k == 6: ib = ((self.eram.var if self.eram else 0) << 11) & 0x7FFFFF
            if k == 7: ib = self.mulc[5]
            if coef & 8 and not weird: ib = -ib
            if coef & 16 and not weird: ib = (~ib & 0x7FFFFF) if ib >= 0 else ~(ib & 0x7FFFFF)
            self.lastB = ib; ib >>= 16
        elif op == 0x34:
            if 0xA0 <= mem < 0xB0: self.mulc[(mem >> 1) & 7] = (B if mem & 1 else A).sat24()
            elif mem >= 0xC0:
                acc = bool(mem & 0x20); clr = bool(mem & 0x10); ac = B if acc else A; p = mem & 0xF
                if p <= 3: raise RuntimeError('jump at %03X' % pc)
                elif p == 6:
                    ia = self.lastA >> 7
                    if self.last30: ib = (self.lastB >> 9) & 0x7F
                elif p == 7: self.eram.var = ac.rawfull()
                elif p == 0xA: self.hostreg = ac.sat24()
                elif p == 0xB: self.eram.wlatch = ac.sat24()
                elif p >= 0xC: ia = self.eram.rlatch; self.wi(mem | 0xF0, ia)
        elif op == 0x38: ia = A.sat24(); self.wg(mem, ia)
        elif op == 0x3C: ia = B.sat24(); self.wg(mem, ia)
        elif op in (0x40, 0x44): ia = A.raw24(); self.wi(mem, ia); clr = op == 0x44
        elif op in (0x48, 0x4C): ia = max(0, A.sat24()); self.wi(mem, ia); clr = op == 0x4C
        elif op == 0x50: clr = True; setcond = True
        elif op == 0x58: ia = A.sat24(); self.wi(mem, ia)
        elif op == 0x5C: acc = True; ia = B.sat24(); self.wi(mem, ia)
        elif op in (0x60, 0x64, 0x70, 0x74): ia = ~ia & 0x7FFFFF; clr = bool(op & 4)
        elif op in (0x68, 0x6C):
            ia = A.sat24(); self.wi(mem, ia); ia = (~ia if ia >= 0 else ia) & 0x7FFFFF; clr = bool(op & 4)
        elif op in (0x78, 0x7C):
            ia = A.sat24(); self.wi(mem, ia); ia = (~ia if ia < 0 else ia) & 0x7FFFFF; clr = bool(op & 4)
        else: raise RuntimeError('op %02X at %03X' % (op, pc))
        if self.skip & 1: ia = 0
        st = B if acc else A
        if clr: st.set(0)
        st.add((se(ia, 24) * ib) >> shift)
        self.skip >>= 1
        if setcond: self.skip |= 0x3C0 if st.v < 0 else 0x30
        self.lastA = ia; self.last30 = op == 0x30
        if self.trace: self.trace(self, pc, w)
        A.push(); B.push()


class Eram:
    """External delay RAM (16-bit compressed words). pos decrements once per sample; taps are pos + offset."""
    COMMIT = 10

    def __init__(self, lg2size=18):
        self.size = 1 << lg2size; self.mask = self.size - 1; self.mem = [0] * self.size
        self.pos = 0; self.var = 0; self.wlatch = 0; self.rlatch = 0; self.hiflag = 0
        self.act_next = False; self.act_cur = False; self.mode_next = 0; self.mode_cur = 0
        self.start = 0; self.imm = 0; self.commit_pc = 0; self.addr = 0; self.wnext = 0
        self.log = None

    def tick_sample(self): self.pos = (self.pos - 1) & 0x7FFFF

    def tick(self, ectl, pc):
        stage = pc - self.start
        if not self.act_next and ectl & 0x18:
            self.act_next = True; self.mode_next = ectl; self.start = pc; self.imm = 0; stage = 0
        elif self.act_next and 0 < stage <= 4:
            self.imm += ectl << ((stage - 1) * 5)
        if self.act_cur and pc == self.commit_pc:
            if self.mode_cur == 0x10: self.mem[self.addr & self.mask] = crunch(self.wnext)
            else: self.rlatch = se(self.mem[self.addr & self.mask], 24)
            if self.log is not None: self.log.append((pc, self.mode_cur, self.addr & self.mask, self.wnext if self.mode_cur == 0x10 else self.rlatch))
            self.act_cur = False
        if self.act_next and stage == 5:
            self.act_cur = True; self.mode_cur = self.mode_next; self.commit_pc = self.start + self.COMMIT
            self.act_next = False; self.wnext = self.wlatch
            self.addr = self.pos + self.imm
            if self.mode_next == 0x18:
                self.addr = self.pos + (self.var >> 12) + ((self.imm >> 1) & 1)
                self.hiflag = self.imm & 0x100
            if self.hiflag: self.addr += 0x40000 if self.pos <= 0x4000 else 0xC0000


def crunch(x):
    """ESP ERAM 16-bit block-float compression of a 24-bit value (keeps 11-15 significant bits)."""
    b = ((x >> 1) & 0x400000) * 3
    if ((x << 1) & 0xC00000) != b: return x & ~0x3FF
    if ((x << 3) & 0xC00000) != b: return x & ~0xFF
    if ((x << 5) & 0xC00000) != b: return x & ~0x3F
    return x & ~0xF


if __name__ == '__main__':
    import json
    P = json.load(open(sys.argv[1]))
    for name in sys.argv[2:]:
        ws = [rom_to_dsp(w) for w in P[name]['words']]
        print('; === %s (%d words)' % (name, len(ws)))
        disasm(ws, start=0x3C if name.startswith('fx') else 0)
