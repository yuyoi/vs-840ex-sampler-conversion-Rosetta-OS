"""Rosetta MIDI remote for the VS-840EX (H8S code emitted into an h8asm.Asm).

MIDI IN: ROM SCI0 RX interrupt 0x7478 fills a 512-byte ring at 0x400000 (write 0xFFF9AE, read 0xFFF9AC);
ROM 0x7258 pops one byte (r0 = byte, 0xFFFF = empty; clobbers er0-er2).
MIDI OUT: ROM 0x7316(r0 = queue 0-3, r1l = byte) waits for room, queues, starts the TX interrupt (clobbers er0-er2).
Events: Roland's queue, posted with OS 0x11D44E (12-byte event on the caller's stack: w type, w a, w b, w c).

Protocol (PC -> VS, all numbers in SysEx are sent as 4-bit nibbles, high nibble first):
  Note On ch 16 (9F nn vv, vv > 0)   key press, nn = key code (key-name table 0x1F6F2E)
  CC 1 on ch 16 (BF 01 vv)           dial, delta = vv - 64
  F0 7D 56 01 F7                     ping   -> F0 7D 56 41 <15 bytes version> F7
  F0 7D 56 02 a*6 n*2 F7             read n (<= 64) bytes at a -> F0 7D 56 42 <2n nibbles> F7
  F0 7D 56 03 a*6 (d*2)... F7        write bytes at a          -> F0 7D 56 43 F7
  F0 7D 56 04 c i*3 w*8 F7           DSP word: core c, index i, 4 bytes (ROM order + E) -> F0 7D 56 44 F7
  F0 7D 56 05 k*2 F7                 key press code k (any code) -> F0 7D 56 45 F7
midi_poll() is called from the menu's event wait: it drains the ring and acts on complete messages.
"""
GETB, PUTB, POSTEV = 0x7258, 0x7316, 0x11D44E
DSP_WORD, DSP_LATCH, LATCH_SHADOW = 0x5A3A, 0x4DCA, 0x5B5801
SX_MAX = 0x90


def emit(a, ram, version):
    STATUS, NEED, NDATA, D0, D1, SXON = ram, ram + 1, ram + 2, ram + 3, ram + 4, ram + 5
    SXLEN, SCR, BUF = ram + 6, ram + 8, ram + 0x10
    end = BUF + SX_MAX

    def st_w_sp(reg, disp):                      # mov.w rN,@(disp,sp)
        a.raw(bytes([0x6F, 0x80 | (7 << 4) | reg, (disp >> 8) & 0xFF, disp & 0xFF]))

    # ---- post_key(r0 = code) / post_dial(r0 = delta): Roland event onto the queue ----
    a.label('post_key')
    a.mov_w_rr(0, 3); a.mov_w_imm(1, 1); a.mov_w_imm(1, 2); a.bra('pe_go')
    a.label('post_dial')
    a.mov_w_rr(0, 2); a.mov_w_imm(2, 1); a.mov_w_imm(0, 3)
    a.label('pe_go')                              # r1 = type, r2 = a, r3 = b
    a.sub_l_imm(12, 7)
    st_w_sp(1, 0); st_w_sp(2, 2); st_w_sp(3, 4); a.mov_w_imm(0, 0); st_w_sp(0, 6)
    a.jsr(POSTEV)
    a.add_l_imm(12, 7)
    a.rts()

    # ---- tx(r1l = byte) ----
    a.label('tx')
    a.mov_w_imm(0, 0); a.jsr(PUTB); a.rts()

    def tx_imm(v):
        a.mov_b_imm(v, 'r1l'); a.bsr16('tx')

    def tx_head(cmd):
        for v in (0xF0, 0x7D, 0x56, cmd): tx_imm(v)

    # ---- getn(r4 = buffer offset, r5l = nibbles) -> er0 ----
    a.label('getn')
    a.sub_l(0, 0)
    a.mov_l_imm(BUF, 1); a.mov_w_rr(4, 2); a.extu_l(2); a.add_l_rr(2, 1)
    a.label('gn_lp')
    a.shl32(0, 4)
    a.mov_b_ldinc(1, 'r2l'); a.and_b_imm(0x0F, 'r2l'); a.or_b_rr('r2l', 'r0l')
    a.add_b_imm(0xFF, 'r5l'); a.bne('gn_lp')
    a.rts()

    def getn(off, n, reg_off=None):
        if reg_off is None: a.mov_w_imm(off, 4)
        a.mov_b_imm(n, 'r5l'); a.bsr16('getn')

    # ---- tx_hex(r6l = byte): two nibbles ----
    a.label('tx_hex')
    a.mov_b_rr('r6l', 'r1l'); a.shlr_b('r1l'); a.shlr_b('r1l'); a.shlr_b('r1l'); a.shlr_b('r1l'); a.bsr16('tx')
    a.mov_b_rr('r6l', 'r1l'); a.and_b_imm(0x0F, 'r1l'); a.bsr16('tx')
    a.rts()

    # ---- midi_poll ----
    a.label('midi_poll')
    a.push_l(4); a.push_l(5); a.push_l(6)
    a.label('mp_next')
    a.jsr(GETB)
    a.cmp_w_imm(0xFFFF, 0); a.beq16('mp_done')
    a.mov_b_rr('r0l', 'r6l')
    a.cmp_b_imm(0xF0, 'r6l'); a.bne('mp_1')
    a.mov_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', SXON); a.mov_w_imm(0, 0); a.mov_w_to_abs(0, SXLEN)
    a.bra16('mp_next')
    a.label('mp_1')
    a.cmp_b_imm(0xF7, 'r6l'); a.bne('mp_2')
    a.mov_b_from_abs(SXON, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq16('mp_next')
    a.mov_b_imm(0, 'r0l'); a.mov_b_to_abs('r0l', SXON)
    a.bsr16('sx_exec'); a.bra16('mp_next')
    a.label('mp_2')
    a.cmp_b_imm(0xF8, 'r6l'); a.bcc16('mp_next')                  # real time: ignore
    a.mov_b_from_abs(SXON, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq('mp_3')
    a.btst_imm(7, 'r6l'); a.beq('mp_sxd')
    a.mov_b_imm(0, 'r0l'); a.mov_b_to_abs('r0l', SXON); a.bra('mp_3')   # status inside SysEx: abort it
    a.label('mp_sxd')
    a.mov_w_from_abs(SXLEN, 0); a.cmp_w_imm(SX_MAX, 0); a.bcc16('mp_next')
    a.mov_l_imm(BUF, 1); a.extu_l(0); a.add_l_rr(0, 1); a.mov_b_st('r6l', 1)
    a.mov_w_from_abs(SXLEN, 0); a.add_w_imm(1, 0); a.mov_w_to_abs(0, SXLEN)
    a.bra16('mp_next')
    a.label('mp_3')
    a.btst_imm(7, 'r6l'); a.beq('mp_data')
    a.mov_b_imm(0, 'r0l'); a.mov_b_to_abs('r0l', NDATA)
    a.cmp_b_imm(0xF0, 'r6l'); a.bcs('mp_st')
    a.mov_b_imm(0, 'r6l')                                          # system common: ignore its data
    a.label('mp_st')
    a.mov_b_to_abs('r6l', STATUS)
    a.mov_b_rr('r6l', 'r0l'); a.and_b_imm(0xE0, 'r0l'); a.mov_b_imm(2, 'r0h')
    a.cmp_b_imm(0xC0, 'r0l'); a.bne('mp_st2'); a.mov_b_imm(1, 'r0h')
    a.label('mp_st2')
    a.mov_b_to_abs('r0h', NEED); a.bra16('mp_next')
    a.label('mp_data')
    a.mov_b_from_abs(STATUS, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq16('mp_next')
    a.mov_b_from_abs(NDATA, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne('mp_d1')
    a.mov_b_to_abs('r6l', D0); a.mov_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', NDATA)
    a.mov_b_from_abs(NEED, 'r0l'); a.cmp_b_imm(1, 'r0l'); a.bne16('mp_next')
    a.mov_b_imm(0, 'r0l'); a.mov_b_to_abs('r0l', NDATA); a.bra16('mp_next')   # 1-byte messages: ignored
    a.label('mp_d1')
    a.mov_b_to_abs('r6l', D1); a.mov_b_imm(0, 'r0l'); a.mov_b_to_abs('r0l', NDATA)
    a.mov_b_from_abs(STATUS, 'r0l')
    a.cmp_b_imm(0x9F, 'r0l'); a.bne('mp_cc')
    a.mov_b_from_abs(D1, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq16('mp_next')       # note off as velocity 0
    a.mov_b_from_abs(D0, 'r0l'); a.extu_w(0); a.bsr16('post_key'); a.bra16('mp_next')
    a.label('mp_cc')
    a.cmp_b_imm(0xBF, 'r0l'); a.bne16('mp_next')
    a.mov_b_from_abs(D0, 'r0l'); a.cmp_b_imm(1, 'r0l'); a.bne16('mp_next')
    a.mov_b_from_abs(D1, 'r0l'); a.extu_w(0); a.add_w_imm(0xFFC0, 0)               # delta = v - 64
    a.cmp_w_imm(0, 0); a.beq16('mp_next')
    a.bsr16('post_dial'); a.bra16('mp_next')
    a.label('mp_done')
    a.pop_l(6); a.pop_l(5); a.pop_l(4)
    a.rts()

    # ---- sx_exec: BUF = 7D 56 cmd args ----
    a.label('sx_exec')
    a.mov_b_from_abs(BUF, 'r0l'); a.cmp_b_imm(0x7D, 'r0l'); a.bne16('sx_ret')
    a.mov_b_from_abs(BUF + 1, 'r0l'); a.cmp_b_imm(0x56, 'r0l'); a.bne16('sx_ret')
    a.mov_b_from_abs(BUF + 2, 'r0l')
    a.cmp_b_imm(1, 'r0l'); a.beq16('sx_ping')
    a.cmp_b_imm(2, 'r0l'); a.beq16('sx_read')
    a.cmp_b_imm(3, 'r0l'); a.beq16('sx_write')
    a.cmp_b_imm(4, 'r0l'); a.beq16('sx_dsp')
    a.cmp_b_imm(5, 'r0l'); a.beq16('sx_key')
    a.label('sx_ret')
    a.rts()
    # ping
    a.label('sx_ping')
    tx_head(0x41)
    a.mov_l_imm('mr_ver', 6)
    a.label('sp_lp')
    a.mov_b_ldinc(6, 'r1l'); a.cmp_b_imm(0, 'r1l'); a.beq('sp_end')
    a.push_l(6); a.bsr16('tx'); a.pop_l(6); a.bra('sp_lp')
    a.label('sp_end')
    tx_imm(0xF7); a.rts()
    # read: addr 6 nibbles at 3, count 2 nibbles at 9
    a.label('sx_read')
    getn(3, 6); a.push_l(0)
    getn(9, 2); a.mov_w_rr(0, 13)                                      # e5 = count
    a.cmp_w_imm(65, 13); a.bcs('sr_ok'); a.mov_w_imm(64, 13)
    a.label('sr_ok')
    tx_head(0x42)
    a.pop_l(4)                                                         # er4 = address
    a.cmp_w_imm(0, 13); a.beq('sr_end')
    a.label('sr_lp')
    a.mov_b_ld(4, 'r6l'); a.push_l(4); a.bsr16('tx_hex'); a.pop_l(4)
    a.adds1(4); a.dec_w1(13); a.bne('sr_lp')
    a.label('sr_end')
    tx_imm(0xF7); a.rts()
    # write: addr at 3, data pairs from 9
    a.label('sx_write')
    getn(3, 6); a.mov_l_rr(0, 6)                                       # er6 = address
    a.mov_w_from_abs(SXLEN, 0); a.add_w_imm(0xFFF7, 0); a.shlr_w(0); a.mov_w_rr(0, 13)   # e5 = (len - 9) / 2
    a.mov_w_imm(9, 4)
    a.cmp_w_imm(0, 13); a.beq('sw_end')
    a.label('sw_lp')
    a.mov_b_imm(2, 'r5l'); a.push_w(4); a.bsr16('getn'); a.pop_w(4)
    a.mov_b_st('r0l', 6); a.adds1(6); a.add_w_imm(2, 4); a.dec_w1(13); a.bne('sw_lp')
    a.label('sw_end')
    tx_head(0x43); tx_imm(0xF7); a.rts()
    # DSP word: core at 3 (1 nibble), index at 4 (3 nibbles), bytes at 7, 9, 11, 13
    a.label('sx_dsp')
    for k in range(4):
        getn(7 + 2 * k, 2); a.mov_b_to_abs('r0l', SCR + k)
    a.mov_b_from_abs(LATCH_SHADOW, 'r0l'); a.and_b_imm(0xFE, 'r0l'); a.mov_b_to_abs('r0l', LATCH_SHADOW)
    a.mov_w_imm(3, 0); a.jsr(DSP_LATCH)
    getn(4, 3); a.shll_w(0); a.shll_w(0); a.push_w(0)                   # index * 4
    getn(3, 1); a.mov_b_rr('r0l', 'r1l'); a.pop_w(0)
    a.cmp_b_imm(0, 'r1l'); a.beq('sd_c0')
    a.raw(bytes([0x79, 0x40, 0x10, 0x00]))                              # or.w #0x1000,r0 (core 1)
    a.label('sd_c0')
    a.mov_l_imm(SCR, 1); a.jsr(DSP_WORD)
    tx_head(0x44); tx_imm(0xF7); a.rts()
    # key
    a.label('sx_key')
    getn(3, 2); a.extu_w(0); a.bsr16('post_key')
    tx_head(0x45); tx_imm(0xF7); a.rts()

    a.label('mr_ver'); a.string(version.decode('ascii'))
    return end
