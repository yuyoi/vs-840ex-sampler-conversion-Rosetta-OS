"""Tiny H8S assembler: just the instructions our patches use, with labels.

Usage (from a build script):
    a = Asm(0x16B000)
    a.label('top'); a.mov_w_imm(0x1f, 0); a.jsr(0x13FC0E); a.beq('top'); a.rts()
    code = a.assemble()        # bytes, all label fixups resolved
Every build should round-trip the result through h8sdis to eyeball it.
"""
import struct

R8 = {'r0h': 0, 'r1h': 1, 'r2h': 2, 'r3h': 3, 'r4h': 4, 'r5h': 5, 'r6h': 6, 'r7h': 7,
      'r0l': 8, 'r1l': 9, 'r2l': 10, 'r3l': 11, 'r4l': 12, 'r5l': 13, 'r6l': 14, 'r7l': 15}
COND = {'bra': 0, 'brn': 1, 'bhi': 2, 'bls': 3, 'bcc': 4, 'bcs': 5, 'bne': 6, 'beq': 7,
        'bvc': 8, 'bvs': 9, 'bpl': 10, 'bmi': 11, 'bge': 12, 'blt': 13, 'bgt': 14, 'ble': 15}


class Asm:
    def __init__(self, base):
        self.base = base
        self.items = []          # (kind, payload)
        self.labels = {}

    # --- plumbing ---
    def _b(self, *bs): self.items.append(('b', bytes(bs)))
    def raw(self, data): self.items.append(('b', bytes(data)))
    def label(self, name):
        if not hasattr(self, '_names'): self._names = set()
        assert name not in self._names, 'duplicate label %s' % name
        self._names.add(name); self.items.append(('L', name))
    # --- data ---
    def string(self, s): self.raw(s.encode('ascii') + b'\0')
    def dc_l(self, v):                                  # 32-bit data word: a number or a label's address
        if isinstance(v, str): self.items.append(('abs32', v))
        else: self.raw(struct.pack('>I', v & 0xFFFFFFFF))
    def align2(self): self.items.append(('A', 2))     # pad to an even address, decided at layout (v1.95: the
                                                     # old length guess missed jsr/jmp abs24 -> odd tables on the H8S)

    # --- instructions ---
    def push_l(self, n): self._b(0x01, 0x00, 0x6D, 0xF0 | n)
    def pop_l(self, n): self._b(0x01, 0x00, 0x6D, 0x70 | n)
    def rts(self): self._b(0x54, 0x70)
    def nop(self): self._b(0x00, 0x00)
    def mov_w_rr(self, src, dst): self._b(0x0D, (src << 4) | dst)       # r0-r7 / e0-e7 as 0-15
    def mov_b_rr(self, src, dst): self._b(0x0C, (R8[src] << 4) | R8[dst])
    def mov_b_imm(self, imm, reg): self._b(0xF0 | R8[reg], imm & 0xFF)
    def cmp_b_imm(self, imm, reg): self._b(0xA0 | R8[reg], imm & 0xFF)
    def mov_w_imm(self, imm, n): self._b(0x79, 0x00 | n, (imm >> 8) & 0xFF, imm & 0xFF)
    def cmp_w_imm(self, imm, n): self._b(0x79, 0x20 | n, (imm >> 8) & 0xFF, imm & 0xFF)
    def mov_w_to_abs(self, n, addr): self._b(0x6B, 0xA0 | n, *struct.pack('>I', addr & 0xFFFFFF))
    def mov_w_from_abs(self, addr, n): self._b(0x6B, 0x20 | n, *struct.pack('>I', addr & 0xFFFFFF))
    def mov_b_to_abs(self, reg, addr): self._b(0x6A, 0xA0 | R8[reg], *struct.pack('>I', addr & 0xFFFFFF))
    def mov_b_from_abs(self, addr, reg): self._b(0x6A, 0x20 | R8[reg], *struct.pack('>I', addr & 0xFFFFFF))
    def mov_l_imm(self, imm, n):
        if isinstance(imm, str): self._b(0x7A, 0x00 | n); self.items.append(('abs32', imm))
        else: self._b(0x7A, 0x00 | n, *struct.pack('>I', imm & 0xFFFFFFFF))
    def btst_imm(self, bit, reg): self._b(0x73, (bit << 4) | R8[reg])
    def bclr_abs(self, bit, addr): self._b(0x6A, 0x38, *struct.pack('>I', addr & 0xFFFFFF), 0x72, bit << 4)  # bclr #b,@aa:32
    def bset_abs(self, bit, addr): self._b(0x6A, 0x38, *struct.pack('>I', addr & 0xFFFFFF), 0x70, bit << 4)  # bset #b,@aa:32
    def add_b_imm(self, imm, reg): self._b(0x80 | R8[reg], imm & 0xFF)
    def and_w_imm(self, imm, n): self._b(0x79, 0x60 | n, (imm >> 8) & 0xFF, imm & 0xFF)
    def cmp_b_rr(self, src, dst): self._b(0x1C, (R8[src] << 4) | R8[dst])
    def mov_l_from_abs(self, addr, n): self._b(0x01, 0x00, 0x6B, 0x20 | n, *struct.pack('>I', addr & 0xFFFFFF))
    def mov_l_to_abs(self, n, addr): self._b(0x01, 0x00, 0x6B, 0xA0 | n, *struct.pack('>I', addr & 0xFFFFFF))
    def cmp_l_imm(self, imm, n): self._b(0x7A, 0x20 | n, *struct.pack('>I', imm & 0xFFFFFFFF))
    def bsr(self, lbl): self.items.append(('br8', (None, lbl)))      # 8-bit bsr (0x55)
    def bsr16(self, lbl): self.items.append(('br16', (None, lbl)))   # 16-bit bsr (5C 00)
    def mov_l_ind(self, src, dst): self._b(0x01, 0x00, 0x69, (src << 4) | dst)        # mov.l @ers,erd
    def mov_l_rr(self, src, dst): self._b(0x0F, 0x80 | (src << 4) | dst)               # mov.l ers,erd
    def mov_w_disp(self, disp, src, dst): self._b(0x6F, (src << 4) | dst, (disp >> 8) & 0xFF, disp & 0xFF)  # mov.w @(d16,ers),rd
    def sub_l(self, src, dst): self._b(0x1A, 0x80 | (src << 4) | dst)                  # sub.l ers,erd
    def add_l_imm(self, imm, n): self._b(0x7A, 0x10 | n, *struct.pack('>I', imm & 0xFFFFFFFF))
    def sub_l_imm(self, imm, n): self._b(0x7A, 0x30 | n, *struct.pack('>I', imm & 0xFFFFFFFF))
    def adds4(self, n): self._b(0x0B, 0x90 | n)                                         # adds #4,ern (n=7: sp)
    def dec_w1(self, n): self._b(0x1B, 0x50 | n)                                        # dec.w #1,rn
    def jsr_ind(self, n): self._b(0x5D, n << 4)                                         # jsr @ern
    def jsr(self, addr):
        if isinstance(addr, str): self._b(0x5E); self.items.append(('abs24', addr))
        else: self._b(0x5E, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF)
    # --- byte ALU, shifts, indirect access (graphics engine) ---
    def add_b_rr(self, src, dst): self._b(0x08, (R8[src] << 4) | R8[dst])
    def sub_b_rr(self, src, dst): self._b(0x18, (R8[src] << 4) | R8[dst])
    def and_b_imm(self, imm, reg): self._b(0xE0 | R8[reg], imm & 0xFF)
    def or_b_imm(self, imm, reg): self._b(0xC0 | R8[reg], imm & 0xFF)
    def xor_b_imm(self, imm, reg): self._b(0xD0 | R8[reg], imm & 0xFF)
    def and_b_rr(self, src, dst): self._b(0x16, (R8[src] << 4) | R8[dst])
    def or_b_rr(self, src, dst): self._b(0x14, (R8[src] << 4) | R8[dst])
    def xor_b_rr(self, src, dst): self._b(0x15, (R8[src] << 4) | R8[dst])
    def not_b(self, reg): self._b(0x17, R8[reg])
    def inc_b(self, reg): self._b(0x0A, R8[reg])
    def dec_b(self, reg): self._b(0x1A, R8[reg])
    def shll_b(self, reg): self._b(0x10, R8[reg])
    def shlr_b(self, reg): self._b(0x11, R8[reg])
    def shlr_w(self, n): self._b(0x11, 0x10 | n)
    def shll_l(self, n): self._b(0x10, 0x30 | n)
    def shll_l2(self, n): self._b(0x10, 0x70 | n)                                       # shll.l #2,ern
    def extu_w(self, n): self._b(0x17, 0x50 | n)
    def exts_w(self, n): self._b(0x17, 0xD0 | n)                                        # exts.w rn
    def shll_w(self, n): self._b(0x10, 0x10 | n)                                        # shll.w rn
    def add_w_imm(self, imm, n): self._b(0x79, 0x10 | n, (imm >> 8) & 0xFF, imm & 0xFF)  # add.w #imm,rn
    def extu_l(self, n): self._b(0x17, 0x70 | n)
    def mulxu_b(self, src, n): self._b(0x50, (R8[src] << 4) | n)                       # rn(16) = rn.l * src
    def add_l_rr(self, src, dst): self._b(0x0A, 0x80 | (src << 4) | dst)
    def adds1(self, n): self._b(0x0B, n)                                                # adds #1,ern
    def mov_b_ld(self, ptr, reg): self._b(0x68, (ptr << 4) | R8[reg])                   # mov.b @erp,rd
    def mov_b_st(self, reg, ptr): self._b(0x68, 0x80 | (ptr << 4) | R8[reg])            # mov.b rs,@erp
    def mov_b_ldinc(self, ptr, reg): self._b(0x6C, (ptr << 4) | R8[reg])                # mov.b @erp+,rd
    def mov_b_ld_disp(self, disp, ptr, reg): self._b(0x6E, (ptr << 4) | R8[reg], (disp >> 8) & 0xFF, disp & 0xFF)
    def mov_b_st_disp(self, reg, disp, ptr): self._b(0x6E, 0x80 | (ptr << 4) | R8[reg], (disp >> 8) & 0xFF, disp & 0xFF)
    def mov_l_st(self, src, ptr): self._b(0x01, 0x00, 0x69, 0x80 | (ptr << 4) | src)    # mov.l ers,@erp
    def mov_l_ld_disp(self, disp, ptr, dst): self._b(0x01, 0x00, 0x6F, (ptr << 4) | dst, (disp >> 8) & 0xFF, disp & 0xFF)
    def mov_l_st_disp(self, src, disp, ptr): self._b(0x01, 0x00, 0x6F, 0x80 | (ptr << 4) | src, (disp >> 8) & 0xFF, disp & 0xFF)
    def shlr_l(self, n): self._b(0x11, 0x30 | n)
    def shlr_l2(self, n): self._b(0x11, 0x70 | n)                                       # shlr.l #2,ern
    def shl32(self, n, count):                                                          # ern <<= count
        for _ in range(count // 2): self.shll_l2(n)
        if count & 1: self.shll_l(n)
    def shr32(self, n, count):                                                          # ern >>= count (logical)
        for _ in range(count // 2): self.shlr_l2(n)
        if count & 1: self.shlr_l(n)
    def btst_abs(self, bit, addr): self._b(0x6A, 0x30, *struct.pack('>I', addr & 0xFFFFFF), 0x73, bit << 4)  # btst #b,@aa:32 (as stock 0x13FC12)
    def divxu_b(self, src, n): self._b(0x51, (R8[src] << 4) | n)                       # rn / src: rnl = quot, rnh = rem
    def mulxu_w(self, src, n): self._b(0x52, (src << 4) | n)                           # ern = rn * src (16 x 16)
    def divxu_w(self, src, n): self._b(0x53, (src << 4) | n)                           # ern / src: rn = quot, en = rem
    def subs1(self, n): self._b(0x1B, n)                                                # subs #1,ern
    def add_w_rr(self, src, dst): self._b(0x09, (src << 4) | dst)
    def and_w_rr(self, src, dst): self._b(0x66, (src << 4) | dst)                      # and.w rs,rd
    def or_w_rr(self, src, dst): self._b(0x64, (src << 4) | dst)                       # or.w rs,rd
    def xor_w_rr(self, src, dst): self._b(0x65, (src << 4) | dst)                      # xor.w rs,rd
    def push_w(self, n): self._b(0x6D, 0xF0 | n)                                        # mov.w rn,@-sp
    def pop_w(self, n): self._b(0x6D, 0x70 | n)                                         # mov.w @sp+,rn
    def sub_w_rr(self, src, dst): self._b(0x19, (src << 4) | dst)
    def cmp_w_rr(self, src, dst): self._b(0x1D, (src << 4) | dst)                     # flags of dst - src
    def cmp_l_rr(self, src, dst): self._b(0x1F, 0x80 | (src << 4) | dst)
    def mov_w_ld(self, ptr, n): self._b(0x69, (ptr << 4) | n)                          # mov.w @erp,rn
    def mov_w_st(self, n, ptr): self._b(0x69, 0x80 | (ptr << 4) | n)                   # mov.w rn,@erp
    def jmp(self, addr):
        if isinstance(addr, str): self._b(0x5A); self.items.append(('abs24', addr))
        else: self._b(0x5A, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF)

    def __getattr__(self, name):
        # bne('lbl') = 8-bit branch, bne16('lbl') = 16-bit branch
        if name in COND:
            return lambda lbl: self.items.append(('br8', (COND[name], lbl)))
        if name.endswith('16') and name[:-2] in COND:
            return lambda lbl: self.items.append(('br16', (COND[name[:-2]], lbl)))
        raise AttributeError(name)

    def assemble(self):
        pc = self.base
        for k, p in self.items:              # pass 1: addresses
            if k == 'L': self.labels[p] = pc
            elif k == 'b': pc += len(p)
            elif k == 'br8': pc += 2
            elif k in ('br16', 'abs32'): pc += 4
            elif k == 'abs24': pc += 3
            elif k == 'A': pc += pc & 1
        out = bytearray(); pc = self.base
        for k, p in self.items:              # pass 2: emit
            if k == 'b': out += p; pc += len(p)
            elif k == 'br8':
                c, lbl = p; d = self.labels[lbl] - (pc + 2)
                assert -128 <= d <= 127, 'branch to %s out of range' % lbl
                out += bytes((0x55 if c is None else 0x40 | c, d & 0xFF)); pc += 2
            elif k == 'br16':
                c, lbl = p; d = self.labels[lbl] - (pc + 4)
                if not -32768 <= d <= 32767 and c in (None, 0):  # bsr / bra out of reach: jsr / jmp @aa:24, same 4 bytes
                    out += bytes((0x5E if c is None else 0x5A,)) + self.labels[lbl].to_bytes(3, 'big'); pc += 4
                    continue
                assert -32768 <= d <= 32767, 'branch16 to %s out of range (%d)' % (lbl, d)
                out += (bytes((0x5C, 0x00)) if c is None else bytes((0x58, c << 4))) + struct.pack('>h', d); pc += 4
            elif k == 'abs32':
                out += struct.pack('>I', self.labels[p]); pc += 4
            elif k == 'abs24':
                out += self.labels[p].to_bytes(3, 'big'); pc += 3
            elif k == 'A' and pc & 1: out += b'\0'; pc += 1
        return bytes(out)
