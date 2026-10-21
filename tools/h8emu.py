"""Small H8S emulator for testing our own code on the PC (the instructions h8asm emits, not the whole CPU).

Stock OS routines are not emulated: every jsr/jmp to an address in `stubs` runs a Python function instead
(stub(emu) -> None, then the emulator returns to the caller). Unknown targets outside our code raise.

    emu = Emu(image_bytes)                 # OS image at 0x100000 (our build's .bin)
    emu.stubs[0x14D8AA] = lambda e: e.set16(0, 1)
    emu.call(0x16B272)                     # runs until that routine returns
"""
import struct

FLASH, RAM_LO, RAM_HI = 0x100000, 0x400000, 0x800000      # RAM incl. sample RAM (size on the unit unknown)
ONCHIP = 0xFFF000                                         # on-chip RAM / registers (plain memory here)


class Emu:
    def __init__(self, image):
        self.flash = bytearray(image)
        self.odd = set()                                     # odd word/long accesses (pc, address)
        self.ram = bytearray(RAM_HI - RAM_LO)
        self.onchip = bytearray(0x1000)
        self.hw = bytearray(0x3000)                          # DSP host port window 0xC00000-0xC02FFF (plain memory)
        self.hwrd = bytearray(8)                             # what reads of 0xC00000-7 return (status, readback regs)
        self.boot = None                                     # optional boot ROM image mapped at 0x000000 (1 MB)
        self.er = [0] * 8
        self.N = self.Z = self.V = self.C = 0
        self.I = self.H = 0
        self.pc = 0
        self.stubs = {}
        self.steps = 0
        self.on_step = None                                  # f(emu) after every instruction (e.g. a clock)
        self.code_lo, self.code_hi = 0x16B000, 0x1C0000     # where we really execute (others need a stub)

    # ---------- memory ----------
    def rb(self, a):
        a &= 0xFFFFFF
        if FLASH <= a < FLASH + len(self.flash): return self.flash[a - FLASH]
        if RAM_LO <= a < RAM_HI: return self.ram[a - RAM_LO]
        if a < FLASH and self.boot is not None: return self.boot[a]
        if a >= ONCHIP: return self.onchip[a - ONCHIP]
        if 0xC00000 <= a < 0xC00008: return self.hwrd[a - 0xC00000]      # DSP readback / status registers
        if 0xC00000 <= a < 0xC03000: return self.hw[a - 0xC00000]
        raise RuntimeError('read %06X at pc %06X' % (a, self.pc))
    def wb(self, a, v):
        a &= 0xFFFFFF
        if RAM_LO <= a < RAM_HI: self.ram[a - RAM_LO] = v & 0xFF; return
        if a >= ONCHIP: self.onchip[a - ONCHIP] = v & 0xFF; return
        if 0xC00000 <= a < 0xC03000: self.hw[a - 0xC00000] = v & 0xFF; return
        raise RuntimeError('write %06X at pc %06X' % (a, self.pc))
    # The H8S ignores address bit 0 on word / long accesses (no address error): model that, and log each odd one
    # (pc, address) in self.odd, because the real unit reads the wrong bytes there (v1.94 tables bug).
    def rw(self, a):
        if a & 1: self.odd.add((self.pc, a & 0xFFFFFF)); a &= ~1
        return (self.rb(a) << 8) | self.rb(a + 1)
    def ww(self, a, v):
        if a & 1: self.odd.add((self.pc, a & 0xFFFFFF)); a &= ~1
        self.wb(a, v >> 8); self.wb(a + 1, v)
    def rl(self, a): return (self.rw(a) << 16) | self.rw(a + 2)
    def wl(self, a, v): self.ww(a, v >> 16); self.ww(a + 2, v & 0xFFFF)

    # ---------- registers ----------
    def g8(self, i):
        return (self.er[i] >> 8) & 0xFF if i < 8 else self.er[i - 8] & 0xFF
    def s8(self, i, v):
        v &= 0xFF
        if i < 8: self.er[i] = (self.er[i] & 0xFFFF00FF) | (v << 8)
        else: self.er[i - 8] = (self.er[i - 8] & 0xFFFFFF00) | v
    def g16(self, i):
        return self.er[i] & 0xFFFF if i < 8 else (self.er[i - 8] >> 16) & 0xFFFF
    def s16(self, i, v):
        v &= 0xFFFF
        if i < 8: self.er[i] = (self.er[i] & 0xFFFF0000) | v
        else: self.er[i - 8] = (self.er[i - 8] & 0xFFFF) | (v << 16)
    def set16(self, i, v): self.s16(i, v)
    def g32(self, i): return self.er[i] & 0xFFFFFFFF
    def s32(self, i, v): self.er[i] = v & 0xFFFFFFFF

    # ---------- flags ----------
    def nz(self, v, bits):
        self.N = (v >> (bits - 1)) & 1; self.Z = int((v & ((1 << bits) - 1)) == 0)
    def logic(self, v, bits): self.nz(v, bits); self.V = 0
    def add(self, a, b, bits):
        m = (1 << bits) - 1; r = (a + b) & m
        self.C = int(a + b > m); self.nz(r, bits)
        self.V = int(((a ^ r) & (b ^ r)) >> (bits - 1) & 1); return r
    def sub(self, a, b, bits):                              # a - b
        m = (1 << bits) - 1; r = (a - b) & m
        self.C = int(b > a); self.nz(r, bits)
        self.V = int(((a ^ b) & (a ^ r)) >> (bits - 1) & 1); return r
    def cond(self, c):
        N, Z, V, C = self.N, self.Z, self.V, self.C
        return [True, False, not (C or Z), bool(C or Z), not C, bool(C), not Z, bool(Z), not V, bool(V),
                not N, bool(N), not (N ^ V), bool(N ^ V), not (Z or (N ^ V)), bool(Z or (N ^ V))][c]

    # ---------- stack ----------
    def push32(self, v): self.er[7] = (self.er[7] - 4) & 0xFFFFFFFF; self.wl(self.er[7], v)
    def pop32(self):
        v = self.rl(self.er[7]); self.er[7] = (self.er[7] + 4) & 0xFFFFFFFF; return v

    # ---------- run ----------
    def call(self, addr, sp=0x43F000, limit=2_000_000):
        self.er[7] = sp
        self.push32(0xDEAD00)
        self.pc = addr
        while self.pc != 0xDEAD00:
            self.step()
            self.steps += 1
            if self.on_step: self.on_step(self)
            if self.steps > limit: raise RuntimeError('step limit at %06X' % self.pc)

    def goto_sub(self, target, ret):
        if target in self.stubs:
            self.stubs[target](self); self.pc = ret
        elif self.code_lo <= target < self.code_hi:
            self.push32(ret); self.pc = target
        else:
            raise RuntimeError('call to %06X (no stub) from %06X' % (target, self.pc))

    # ---------- full H8S/2600 decoder ----------
    def ccr(self):
        return (self.I << 7) | (self.H << 5) | (self.N << 3) | (self.Z << 2) | (self.V << 1) | self.C
    def set_ccr(self, v):
        self.I, self.H, self.N, self.Z, self.V, self.C = (v >> 7) & 1, (v >> 5) & 1, (v >> 3) & 1, (v >> 2) & 1, (v >> 1) & 1, v & 1

    def getr(self, kind, r): return {8: self.g8, 16: self.g16, 32: self.g32}[kind](r if kind != 32 else r & 7)
    def setr(self, kind, r, v): {8: self.s8, 16: self.s16, 32: self.s32}[kind](r if kind != 32 else r & 7, v)

    def shiftop(self, b0, b1):
        hi, lo = b1 >> 4, b1 & 15
        kind = {0: 8, 1: 16, 3: 32}[hi & 3]; cnt = 2 if hi & 4 else 1; alt = bool(hi & 8)
        v = self.getr(kind, lo); m = (1 << kind) - 1; msb = 1 << (kind - 1); V = 0
        for _ in range(cnt):
            if b0 == 0x10:                                        # shll / shal
                self.C = (v >> (kind - 1)) & 1; nv = (v << 1) & m
                if alt and ((nv ^ v) & msb): V = 1
                v = nv
            elif b0 == 0x11:                                      # shlr / shar
                self.C = v & 1; v = (v >> 1) | ((v & msb) if alt else 0)
            elif b0 == 0x12:                                      # rotxl / rotl
                top = (v >> (kind - 1)) & 1; v = ((v << 1) & m) | (top if alt else self.C); self.C = top
            else:                                                 # rotxr / rotr
                bot = v & 1; v = (v >> 1) | ((bot if alt else self.C) << (kind - 1)); self.C = bot
        self.setr(kind, lo, v); self.nz(v, kind); self.V = V

    def bitop(self, op, arg, rd_fn, wr_fn):
        """op = second-word opcode byte, arg = its operand byte; rd_fn()/wr_fn(v) access the byte."""
        v = rd_fn(); b = (arg >> 4) & 7; inv = bool(arg & 0x80)
        if op in (0x60, 0x61, 0x62, 0x63): b = self.g8((arg >> 4) & 15) & 7      # register-selected bit
        bit = (v >> b) & 1
        if op in (0x70, 0x60): wr_fn(v | (1 << b))
        elif op in (0x71, 0x61): wr_fn(v ^ (1 << b))
        elif op in (0x72, 0x62): wr_fn(v & ~(1 << b))
        elif op in (0x73, 0x63): self.Z = int(not bit)
        elif op == 0x67: wr_fn((v & ~(1 << b)) | ((self.C ^ int(inv)) << b))
        elif op == 0x74: self.C |= bit ^ int(inv)
        elif op == 0x75: self.C ^= bit ^ int(inv)
        elif op == 0x76: self.C &= bit ^ int(inv)
        elif op == 0x77: self.C = bit ^ int(inv)
        else: raise RuntimeError('bitop %02X' % op)

    def step(self):
        pc = self.pc
        b0, b1 = self.rb(pc), self.rb(pc + 1)
        hi, lo = b1 >> 4, b1 & 15
        def imm32(o): return self.rl(pc + o)
        def abs32(o): return self.rl(pc + o) & 0xFFFFFF
        def d16(o): return struct.unpack('>h', self.flash_bytes(pc + o, 2))[0]
        def d8(v): return struct.unpack('b', bytes([v]))[0]
        if pc in self.stubs:                                 # jmp into a stub: run it, return to the caller
            self.stubs[pc](self); self.pc = self.pop32(); return
        # ---- 01 xx: long forms ----
        if b0 == 0x01:
            b2, b3 = self.rb(pc + 2), self.rb(pc + 3)
            if b1 == 0x00:
                if b2 == 0x6D:
                    s, d = (b3 >> 4) & 7, b3 & 7
                    if b3 & 0x80: self.s32(s, self.g32(s) - 4); v = self.g32(d); self.wl(self.g32(s), v)
                    else: v = self.rl(self.g32(s)); self.s32(s, self.g32(s) + 4); self.s32(d, v)
                    self.logic(v, 32); self.pc = pc + 4; return
                if b2 == 0x69:
                    s, d = (b3 >> 4) & 7, b3 & 7
                    if b3 & 0x80: self.wl(self.g32(s), self.g32(d)); v = self.g32(d)
                    else: v = self.rl(self.g32(s)); self.s32(d, v)
                    self.logic(v, 32); self.pc = pc + 4; return
                if b2 == 0x6F:                                 # mov.l @(d16,ers)
                    p = (b3 >> 4) & 7; a = (self.g32(p) + d16(4)) & 0xFFFFFF
                    if b3 & 0x80: v = self.g32(b3 & 7); self.wl(a, v)
                    else: v = self.rl(a); self.s32(b3 & 7, v)
                    self.logic(v, 32); self.pc = pc + 6; return
                if b2 == 0x6B:
                    if b3 & 0x20: a = abs32(4); n = 8
                    else: a = struct.unpack('>h', self.flash_bytes(pc + 4, 2))[0] & 0xFFFFFF; n = 6
                    if b3 & 0x80: v = self.g32(b3 & 7); self.wl(a, v)
                    else: v = self.rl(a); self.s32(b3 & 7, v)
                    self.logic(v, 32); self.pc = pc + n; return
                if b2 == 0x78:                                 # mov.l @(d32,ers)
                    p = (b3 >> 4) & 7; b5 = self.rb(pc + 5); a = (self.g32(p) + imm32(6)) & 0xFFFFFF
                    if b5 & 0x80: v = self.g32(b5 & 7); self.wl(a, v)
                    else: v = self.rl(a); self.s32(b5 & 7, v)
                    self.logic(v, 32); self.pc = pc + 10; return
                raise RuntimeError('01 00 %02X at %06X' % (b2, pc))
            if b1 in (0x10, 0x20, 0x30):                       # stm/ldm
                n = (b1 >> 4) + 1
                if b3 & 0xF0 == 0xF0:
                    first = b3 & 7
                    for r in range(first, first + n): self.push32(self.g32(r))
                else:
                    last = b3 & 7
                    for r in range(last, last - n, -1): self.s32(r, self.pop32())
                self.pc = pc + 4; return
            if b1 == 0xC0 and b2 == 0x50:                      # mulxs.b
                d = b3 & 15; v = (d8(self.g8((b3 >> 4) & 15)) * d8(self.g16(d) & 0xFF)) & 0xFFFF
                self.s16(d, v); self.nz(v, 16); self.pc = pc + 4; return
            if b1 == 0xC0 and b2 == 0x52:                      # mulxs.w
                d = b3 & 7; a_ = struct.unpack('>h', struct.pack('>H', self.g16((b3 >> 4) & 15)))[0]
                b_ = struct.unpack('>h', struct.pack('>H', self.g32(d) & 0xFFFF))[0]
                v = (a_ * b_) & 0xFFFFFFFF; self.s32(d, v); self.nz(v, 32); self.pc = pc + 4; return
            if b1 == 0xD0 and b2 == 0x51:                      # divxs.b
                d = b3 & 15; dv = d8(self.g8((b3 >> 4) & 15)); n = struct.unpack('>h', struct.pack('>H', self.g16(d)))[0]
                q = int(n / dv) if dv else 0; r = n - q * dv if dv else n
                self.s16(d, ((r & 0xFF) << 8) | (q & 0xFF)); self.Z = int(dv == 0); self.N = int(q < 0); self.pc = pc + 4; return
            if b1 == 0xD0 and b2 == 0x53:                      # divxs.w
                d = b3 & 7; dv = struct.unpack('>h', struct.pack('>H', self.g16((b3 >> 4) & 15)))[0]
                n = struct.unpack('>i', struct.pack('>I', self.g32(d)))[0]
                q = int(n / dv) if dv else 0; r = n - q * dv if dv else n
                self.s32(d, ((r & 0xFFFF) << 16) | (q & 0xFFFF)); self.Z = int(dv == 0); self.N = int(q < 0); self.pc = pc + 4; return
            if b1 == 0xF0 and b2 in (0x64, 0x65, 0x66):        # or/xor/and.l ers,erd
                s, d = (b3 >> 4) & 7, b3 & 7; a_, b_ = self.g32(d), self.g32(s)
                v = {0x64: a_ | b_, 0x65: a_ ^ b_, 0x66: a_ & b_}[b2]
                self.s32(d, v); self.logic(v, 32); self.pc = pc + 4; return
            if b1 == 0x40:                                     # ldc/stc @mem forms: treat as nop-ish loads
                if b2 == 0x69: self.pc = pc + 4; return
                if b2 == 0x6F: self.pc = pc + 6; return
                if b2 == 0x6D: self.pc = pc + 4; return
                if b2 == 0x6B: self.pc = pc + (8 if b3 & 0x20 else 6); return
            if b1 == 0x80: self.pc = pc + 2; return          # sleep
            raise RuntimeError('01 %02X at %06X' % (b1, pc))
        # ---- control flow ----
        if b0 == 0x54 and b1 == 0x70: self.pc = self.pop32(); return
        if b0 == 0x56 and b1 == 0x70: self.set_ccr(self.rb(self.er[7])); self.pc = self.pop32() & 0xFFFFFF; return
        if b0 == 0x5E: self.goto_sub(((b1 << 16) | self.rw(pc + 2)), pc + 4); return
        if b0 == 0x5A:
            t = (b1 << 16) | self.rw(pc + 2)
            if t in self.stubs: self.stubs[t](self); self.pc = self.pop32()
            elif self.code_lo <= t < self.code_hi: self.pc = t
            else: raise RuntimeError('jmp %06X' % t)
            return
        if b0 == 0x59:
            t = self.g32(hi & 7) & 0xFFFFFF
            if t in self.stubs: self.stubs[t](self); self.pc = self.pop32()
            else: self.pc = t
            return
        if b0 == 0x5D: self.goto_sub(self.g32(hi & 7) & 0xFFFFFF, pc + 2); return
        if b0 == 0x5B: self.pc = self.rl(b1) & 0xFFFFFF; return
        if b0 == 0x5F: self.goto_sub(self.rl(b1) & 0xFFFFFF, pc + 2); return
        if b0 == 0x55: self.push32(pc + 2); self.pc = (pc + 2 + d8(b1)) & 0xFFFFFF; return
        if b0 == 0x5C and b1 == 0x00: self.push32(pc + 4); self.pc = (pc + 4 + d16(2)) & 0xFFFFFF; return
        if 0x40 <= b0 <= 0x4F:
            self.pc = pc + 2
            if self.cond(b0 & 15): self.pc = (pc + 2 + d8(b1)) & 0xFFFFFF
            return
        if b0 == 0x58 and lo == 0:
            self.pc = pc + 4
            if self.cond(hi): self.pc = (pc + 4 + d16(2)) & 0xFFFFFF
            return
        if b0 == 0x57: raise RuntimeError('trapa at %06X' % pc)
        # ---- CCR ----
        if b0 == 0x02 and hi == 0: self.s8(lo, self.ccr()); self.pc = pc + 2; return
        if b0 == 0x03 and hi == 0: self.set_ccr(self.g8(lo)); self.pc = pc + 2; return
        if b0 == 0x04: self.set_ccr(self.ccr() | b1); self.pc = pc + 2; return
        if b0 == 0x05: self.set_ccr(self.ccr() ^ b1); self.pc = pc + 2; return
        if b0 == 0x06: self.set_ccr(self.ccr() & b1); self.pc = pc + 2; return
        if b0 == 0x07: self.set_ccr(b1); self.pc = pc + 2; return
        # ---- moves ----
        if b0 == 0x0C: v = self.g8(hi); self.s8(lo, v); self.logic(v, 8); self.pc = pc + 2; return
        if b0 == 0x0D: v = self.g16(hi); self.s16(lo, v); self.logic(v, 16); self.pc = pc + 2; return
        if b0 == 0x0F and b1 & 0x80:
            v = self.g32((b1 >> 4) & 7); self.s32(b1 & 7, v); self.logic(v, 32); self.pc = pc + 2; return
        if b0 & 0xF0 == 0xF0: self.s8(b0 & 15, b1); self.logic(b1, 8); self.pc = pc + 2; return
        if 0x20 <= b0 <= 0x2F: v = self.rb(0xFFFF00 | b1); self.s8(b0 & 15, v); self.logic(v, 8); self.pc = pc + 2; return
        if 0x30 <= b0 <= 0x3F: v = self.g8(b0 & 15); self.wb(0xFFFF00 | b1, v); self.logic(v, 8); self.pc = pc + 2; return
        if b0 == 0x79:
            v = self.rw(pc + 2); n = lo
            if hi == 0: self.s16(n, v); self.logic(v, 16)
            elif hi == 1: self.s16(n, self.add(self.g16(n), v, 16))
            elif hi == 2: self.sub(self.g16(n), v, 16)
            elif hi == 3: self.s16(n, self.sub(self.g16(n), v, 16))
            elif hi in (4, 5, 6):
                r = {4: self.g16(n) | v, 5: self.g16(n) ^ v, 6: self.g16(n) & v}[hi]; self.s16(n, r); self.logic(r, 16)
            else: raise RuntimeError('79 %X' % hi)
            self.pc = pc + 4; return
        if b0 == 0x7A:
            v = imm32(2); n = lo & 7
            if hi == 0: self.s32(n, v); self.logic(v, 32)
            elif hi == 1: self.s32(n, self.add(self.g32(n), v, 32))
            elif hi == 2: self.sub(self.g32(n), v, 32)
            elif hi == 3: self.s32(n, self.sub(self.g32(n), v, 32))
            elif hi in (4, 5, 6):
                r = {4: self.g32(n) | v, 5: self.g32(n) ^ v, 6: self.g32(n) & v}[hi]; self.s32(n, r); self.logic(r, 32)
            else: raise RuntimeError('7A %X' % hi)
            self.pc = pc + 6; return
        if b0 == 0x78:                                       # mov.b/w @(d32,ers)
            p = (b1 >> 4) & 7; b2, b3 = self.rb(pc + 2), self.rb(pc + 3); a = (self.g32(p) + imm32(4)) & 0xFFFFFF
            if b2 == 0x6A:
                if b3 & 0x80: v = self.g8(b3 & 15); self.wb(a, v)
                else: v = self.rb(a); self.s8(b3 & 15, v)
                self.logic(v, 8)
            elif b2 == 0x6B:
                if b3 & 0x80: v = self.g16(b3 & 15); self.ww(a, v)
                else: v = self.rw(a); self.s16(b3 & 15, v)
                self.logic(v, 16)
            else: raise RuntimeError('78 %02X' % b2)
            self.pc = pc + 8; return
        if b0 == 0x6A:
            if b1 in (0x10, 0x18, 0x30, 0x38):                 # bit ops @aa:16 / @aa:32
                if b1 & 0x20: a = abs32(2); o = 6
                else: a = struct.unpack('>h', self.flash_bytes(pc + 2, 2))[0] & 0xFFFFFF; o = 4
                op, arg = self.rb(pc + o), self.rb(pc + o + 1)
                self.bitop(op, arg, lambda: self.rb(a), lambda v: self.wb(a, v)); self.pc = pc + o + 2; return
            if b1 & 0x20: a = abs32(2); n = 6
            else: a = struct.unpack('>h', self.flash_bytes(pc + 2, 2))[0] & 0xFFFFFF; n = 4
            if b1 & 0x80: v = self.g8(lo); self.wb(a, v)
            else: v = self.rb(a); self.s8(lo, v)
            self.logic(v, 8); self.pc = pc + n; return
        if b0 == 0x6B:
            if b1 & 0x20: a = abs32(2); n = 6
            else: a = struct.unpack('>h', self.flash_bytes(pc + 2, 2))[0] & 0xFFFFFF; n = 4
            if b1 & 0x80: v = self.g16(lo); self.ww(a, v)
            else: v = self.rw(a); self.s16(lo, v)
            self.logic(v, 16); self.pc = pc + n; return
        if b0 == 0x68:
            p = (b1 >> 4) & 7
            if b1 & 0x80: v = self.g8(lo); self.wb(self.g32(p), v)
            else: v = self.rb(self.g32(p)); self.s8(lo, v)
            self.logic(v, 8); self.pc = pc + 2; return
        if b0 == 0x69:
            p = (b1 >> 4) & 7
            if b1 & 0x80: v = self.g16(lo); self.ww(self.g32(p), v)
            else: v = self.rw(self.g32(p)); self.s16(lo, v)
            self.logic(v, 16); self.pc = pc + 2; return
        if b0 == 0x6C:
            p = (b1 >> 4) & 7
            if b1 & 0x80: self.s32(p, self.g32(p) - 1); v = self.g8(lo); self.wb(self.g32(p), v)
            else: v = self.rb(self.g32(p)); self.s8(lo, v); self.s32(p, self.g32(p) + 1)
            self.logic(v, 8); self.pc = pc + 2; return
        if b0 == 0x6D:                                     # mov.w @er+ / @-er (incl. push.w / pop.w)
            p = (b1 >> 4) & 7
            if b1 & 0x80: self.s32(p, self.g32(p) - 2); v = self.g16(lo); self.ww(self.g32(p), v)
            else: v = self.rw(self.g32(p)); self.s16(lo, v); self.s32(p, self.g32(p) + 2)
            self.logic(v, 16); self.pc = pc + 2; return
        if b0 in (0x6E, 0x6F):
            p = (b1 >> 4) & 7; a = (self.g32(p) + d16(2)) & 0xFFFFFF
            if b0 == 0x6E:
                if b1 & 0x80: v = self.g8(lo); self.wb(a, v)
                else: v = self.rb(a); self.s8(lo, v)
                self.logic(v, 8)
            else:
                if b1 & 0x80: v = self.g16(lo); self.ww(a, v)
                else: v = self.rw(a); self.s16(lo, v)
                self.logic(v, 16)
            self.pc = pc + 4; return
        # ---- ALU ----
        if b0 & 0xF0 == 0xA0: self.sub(self.g8(b0 & 15), b1, 8); self.pc = pc + 2; return
        if b0 & 0xF0 == 0x80: self.s8(b0 & 15, self.add(self.g8(b0 & 15), b1, 8)); self.pc = pc + 2; return
        if b0 & 0xF0 == 0x90 or b0 == 0x0E:                  # addx #imm / addx rs,rd
            r = b0 & 15 if b0 != 0x0E else lo; s = b1 if b0 != 0x0E else self.g8(hi)
            a_ = self.g8(r); c = self.C; res = a_ + s + c; v = res & 0xFF
            self.C = int(res > 0xFF); self.N = v >> 7; self.V = int(((a_ ^ v) & (s ^ v)) >> 7 & 1)
            if v: self.Z = 0
            self.s8(r, v); self.pc = pc + 2; return
        if b0 & 0xF0 == 0xB0 or b0 == 0x1E:                  # subx #imm / subx rs,rd
            r = b0 & 15 if b0 != 0x1E else lo; s = b1 if b0 != 0x1E else self.g8(hi)
            a_ = self.g8(r); c = self.C; res = a_ - s - c; v = res & 0xFF
            self.C = int(res < 0); self.N = v >> 7; self.V = int(((a_ ^ s) & (a_ ^ v)) >> 7 & 1)
            if v: self.Z = 0
            self.s8(r, v); self.pc = pc + 2; return
        if b0 & 0xF0 in (0xC0, 0xD0, 0xE0):
            r = b0 & 15; v = self.g8(r)
            v = {0xC0: v | b1, 0xD0: v ^ b1, 0xE0: v & b1}[b0 & 0xF0]
            self.s8(r, v); self.logic(v, 8); self.pc = pc + 2; return
        if b0 == 0x1C: self.sub(self.g8(lo), self.g8(hi), 8); self.pc = pc + 2; return
        if b0 == 0x1D: self.sub(self.g16(lo), self.g16(hi), 16); self.pc = pc + 2; return
        if b0 == 0x08: self.s8(lo, self.add(self.g8(lo), self.g8(hi), 8)); self.pc = pc + 2; return
        if b0 == 0x09: self.s16(lo, self.add(self.g16(lo), self.g16(hi), 16)); self.pc = pc + 2; return
        if b0 == 0x18: self.s8(lo, self.sub(self.g8(lo), self.g8(hi), 8)); self.pc = pc + 2; return
        if b0 == 0x19: self.s16(lo, self.sub(self.g16(lo), self.g16(hi), 16)); self.pc = pc + 2; return
        if b0 in (0x14, 0x15, 0x16):
            a_, b_ = self.g8(lo), self.g8(hi)
            v = {0x14: a_ | b_, 0x15: a_ ^ b_, 0x16: a_ & b_}[b0]
            self.s8(lo, v); self.logic(v, 8); self.pc = pc + 2; return
        if b0 in (0x64, 0x65, 0x66):
            a_, b_ = self.g16(lo), self.g16(hi)
            v = {0x64: a_ | b_, 0x65: a_ ^ b_, 0x66: a_ & b_}[b0]
            self.s16(lo, v); self.logic(v, 16); self.pc = pc + 2; return
        if b0 == 0x17:
            kind = {0: 8, 1: 16, 3: 32}.get(hi & 3, 32)
            if hi in (0, 1, 3): v = ~self.getr(kind, lo) & ((1 << kind) - 1); self.setr(kind, lo, v); self.logic(v, kind)
            elif hi == 5: v = self.g16(lo) & 0xFF; self.s16(lo, v); self.logic(v, 16)
            elif hi == 7: v = self.g32(lo & 7) & 0xFFFF; self.s32(lo & 7, v); self.logic(v, 32)
            elif hi == 0xD: v = self.g16(lo) & 0xFF; v = v - 0x100 if v & 0x80 else v; self.s16(lo, v & 0xFFFF); self.logic(v & 0xFFFF, 16)
            elif hi == 0xF: v = self.g32(lo & 7) & 0xFFFF; v = v - 0x10000 if v & 0x8000 else v; self.s32(lo & 7, v & 0xFFFFFFFF); self.logic(v & 0xFFFFFFFF, 32)
            elif hi in (8, 9, 0xB): v = self.sub(0, self.getr(kind, lo), kind); self.setr(kind, lo, v)
            else: raise RuntimeError('17 %X' % hi)
            self.pc = pc + 2; return
        if b0 == 0x0A:
            if b1 & 0x80: self.s32(b1 & 7, self.add(self.g32(lo & 7), self.g32((b1 >> 4) & 7), 32))
            elif hi == 0: c = self.C; self.s8(lo, self.add(self.g8(lo), 1, 8)); self.C = c
            else: raise RuntimeError('0A %02X' % b1)
            self.pc = pc + 2; return
        if b0 == 0x1A:
            if b1 & 0x80: self.s32(b1 & 7, self.sub(self.g32(lo & 7), self.g32((b1 >> 4) & 7), 32))
            elif hi == 0: c = self.C; self.s8(lo, self.sub(self.g8(lo), 1, 8)); self.C = c
            else: raise RuntimeError('1A %02X' % b1)
            self.pc = pc + 2; return
        if b0 in (0x0B, 0x1B):
            sign = 1 if b0 == 0x0B else -1
            n = {0: 1, 8: 2, 9: 4}.get(hi)
            if n is not None: self.s32(lo & 7, self.g32(lo & 7) + sign * n)
            elif hi in (5, 0xD):
                c = self.C; k = 1 if hi == 5 else 2
                self.s16(lo, self.add(self.g16(lo), k, 16) if sign > 0 else self.sub(self.g16(lo), k, 16)); self.C = c
            elif hi in (7, 0xF):
                c = self.C; k = 1 if hi == 7 else 2
                self.s32(lo & 7, self.add(self.g32(lo & 7), k, 32) if sign > 0 else self.sub(self.g32(lo & 7), k, 32)); self.C = c
            else: raise RuntimeError('%02X %02X' % (b0, b1))
            self.pc = pc + 2; return
        if b0 in (0x10, 0x11, 0x12, 0x13): self.shiftop(b0, b1); self.pc = pc + 2; return
        if b0 == 0x50: self.s16(lo, (self.g16(lo) & 0xFF) * self.g8(hi)); self.pc = pc + 2; return
        if b0 == 0x51:                                     # divxu.b rs, rd: rdl = quot, rdh = rem
            v, d = self.g16(lo), self.g8(hi)
            if d: self.s16(lo, ((v % d) << 8) | (v // d & 0xFF))
            self.Z = int(d == 0); self.N = d >> 7; self.pc = pc + 2; return
        if b0 == 0x52: self.s32(lo & 7, self.g16(lo & 7) * self.g16(hi)); self.pc = pc + 2; return
        if b0 == 0x53:                                     # divxu.w rs, erd: rd = quot, ed = rem
            v, d = self.g32(lo & 7), self.g16(hi)
            if d: self.s32(lo & 7, ((v % d) << 16) | (v // d & 0xFFFF))
            self.Z = int(d == 0); self.N = d >> 15; self.pc = pc + 2; return
        if b0 == 0x1F and b1 & 0x80: self.sub(self.g32(lo & 7), self.g32((b1 >> 4) & 7), 32); self.pc = pc + 2; return
        # ---- bit ops ----
        if b0 in (0x60, 0x61, 0x62, 0x63) or 0x70 <= b0 <= 0x77:
            r = lo
            self.bitop(b0, b1, lambda: self.g8(r), lambda v: self.s8(r, v)); self.pc = pc + 2; return
        if b0 == 0x67:
            r = lo; self.bitop(0x67, b1, lambda: self.g8(r), lambda v: self.s8(r, v)); self.pc = pc + 2; return
        if b0 in (0x7C, 0x7D):
            a = self.g32(hi & 7) & 0xFFFFFF; op, arg = self.rb(pc + 2), self.rb(pc + 3)
            self.bitop(op, arg, lambda: self.rb(a), lambda v: self.wb(a, v)); self.pc = pc + 4; return
        if b0 in (0x7E, 0x7F):
            a = 0xFFFF00 | b1; op, arg = self.rb(pc + 2), self.rb(pc + 3)
            self.bitop(op, arg, lambda: self.rb(a), lambda v: self.wb(a, v)); self.pc = pc + 4; return
        if b0 == 0x00 and b1 == 0x00: self.pc = pc + 2; return
        raise RuntimeError('unknown opcode %02X %02X at %06X' % (b0, b1, pc))

    def flash_bytes(self, a, n): return bytes(self.rb(a + i) for i in range(n))
