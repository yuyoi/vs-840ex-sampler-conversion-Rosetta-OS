"""Rosetta UI library for the VS-840EX LCD (H8S code emitted into an h8asm.Asm), HR-GP5 v0.2 look.

Screen = 136 x 32 dots in the shadow buffer 0x403200: strip g (x 8g..8g+7) = 0x22 bytes, dot row y at byte 2+y,
MSB = left. Font = the ROM's 5x7 ASCII font at 0xA36 (8 bytes per char, glyph in bits 7..3), 6 px advance.

Routines (all keep er4-er6; params in RAM words at RX/RY/RW/RH and byte RM):
  pix   r4 = x, r5 = y, r3h = mode (0 set, 1 xor)
  rect  RX, RY, RW, RH, RM                     filled rectangle, set or xor
  text  RX, RY, er6 = string                   OR glyphs at any pixel position; RX advances by 6 per char
  bold  RX, RY, er6                            text twice, 1 px apart

Layout (folder tab, adapted to 32 px): tab y 0-7 (bold white title from x 4), status right, rule y 7,
rows at y 8/16/24 (text at y), selection bar xor (row 1: y 8-15, rows 2/3: y-1..y+7), frame line x 0,
scroll bar x 130/135 + thumb.
"""
LCD, STRIDE, STRIPS = 0x403200, 0x22, 17
FONT = 0xA36


def emit(a, ram):
    RX, RY, RW, RH, RM = ram, ram + 2, ram + 4, ram + 6, ram + 8

    # ---- pix: r4 x, r5 y, r3h mode; clobbers r0-r2 ----
    a.label('pix')
    a.cmp_w_imm(STRIPS * 8, 4); a.bcc('px_out')                      # clip: x >= 136 or y >= 32 -> nothing
    a.cmp_w_imm(32, 5); a.bcc('px_out')
    a.mov_w_rr(4, 0); a.shlr_w(0); a.shlr_w(0); a.shlr_w(0)          # r0 = strip
    a.mov_b_imm(STRIDE, 'r1l'); a.mulxu_b('r1l', 0)                   # r0 = strip * 0x22
    a.extu_l(0); a.add_l_imm(LCD + 2, 0)
    a.mov_w_rr(5, 1); a.extu_l(1); a.add_l_rr(1, 0)                   # er0 = byte address
    a.mov_b_rr('r4l', 'r1l'); a.and_b_imm(7, 'r1l'); a.mov_b_imm(0x80, 'r1h')
    a.label('px_sh')
    a.cmp_b_imm(0, 'r1l'); a.beq('px_go')
    a.shlr_b('r1h'); a.add_b_imm(0xFF, 'r1l'); a.bra('px_sh')
    a.label('px_go')
    a.mov_b_ld(0, 'r2l')
    a.cmp_b_imm(0, 'r3h'); a.bne('px_x')
    a.or_b_rr('r1h', 'r2l'); a.bra('px_st')
    a.label('px_x')
    a.xor_b_rr('r1h', 'r2l')
    a.label('px_st')
    a.mov_b_st('r2l', 0)
    a.label('px_out')
    a.rts()

    # ---- rect: RX RY RW RH RM ----
    a.label('rect')
    a.push_l(4); a.push_l(5); a.push_l(6)
    a.mov_w_from_abs(RY, 5); a.mov_w_from_abs(RH, 14)                 # r5 = y, e6 = rows
    a.label('rc_y')
    a.mov_w_from_abs(RX, 4); a.mov_w_from_abs(RW, 6)                  # r4 = x, r6 = cols
    a.label('rc_x')
    a.mov_b_from_abs(RM, 'r3h'); a.bsr('pix')
    a.add_w_imm(1, 4); a.dec_w1(6); a.bne('rc_x')
    a.add_w_imm(1, 5); a.dec_w1(14); a.bne('rc_y')
    a.pop_l(6); a.pop_l(5); a.pop_l(4)
    a.rts()

    # ---- text: RX RY, er6 string (OR) ----
    a.label('text')
    a.push_l(4); a.push_l(5); a.push_l(6)
    a.label('tx_ch')
    a.mov_b_ldinc(6, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq16('tx_done')
    a.mov_w_from_abs(RX, 1); a.cmp_w_imm(STRIPS * 8 - 5, 1); a.bcc16('tx_done')      # clip: glyph must fit in x
    a.mov_w_from_abs(RY, 1); a.cmp_w_imm(32 - 7 + 1, 1); a.bcc16('tx_done')          # and in y (7 rows)
    a.extu_w(0); a.extu_l(0); a.shl32(0, 3); a.add_l_imm(FONT, 0); a.mov_l_rr(0, 1)   # er1 = glyph
    a.mov_w_from_abs(RX, 0); a.mov_b_rr('r0l', 'r3l'); a.and_b_imm(7, 'r3l')         # r3l = shift
    a.shlr_w(0); a.shlr_w(0); a.shlr_w(0)
    a.mov_b_rr('r0l', 'r5h')                                                          # r5h = strip
    a.mov_b_imm(STRIDE, 'r2l'); a.mulxu_b('r2l', 0); a.extu_l(0); a.add_l_imm(LCD + 2, 0)
    a.mov_w_from_abs(RY, 2); a.extu_l(2); a.add_l_rr(0, 2)                            # er2 = dest
    a.mov_w_imm(7, 11)                                                                # e3 = rows
    a.label('tx_row')
    a.mov_b_ldinc(1, 'r0h'); a.mov_b_imm(0, 'r0l')
    a.mov_b_rr('r3l', 'r3h')
    a.label('tx_sh')
    a.cmp_b_imm(0, 'r3h'); a.beq('tx_put')
    a.shlr_w(0); a.add_b_imm(0xFF, 'r3h'); a.bra('tx_sh')
    a.label('tx_put')
    a.mov_b_ld(2, 'r4l'); a.or_b_rr('r0h', 'r4l'); a.mov_b_st('r4l', 2)
    a.cmp_b_imm(0, 'r0l'); a.beq('tx_nx')
    a.cmp_b_imm(STRIPS - 1, 'r5h'); a.bcc('tx_nx')                                   # no strip right of 16
    a.mov_b_ld_disp(STRIDE, 2, 'r4l'); a.or_b_rr('r0l', 'r4l'); a.mov_b_st_disp('r4l', STRIDE, 2)
    a.label('tx_nx')
    a.adds1(2); a.dec_w1(11); a.bne('tx_row')
    a.mov_w_from_abs(RX, 0); a.add_w_imm(6, 0); a.mov_w_to_abs(0, RX)
    a.bra16('tx_ch')
    a.label('tx_done')
    a.pop_l(6); a.pop_l(5); a.pop_l(4)
    a.rts()

    # ---- bold: text at RX and RX+1 ----
    a.label('bold')
    a.mov_w_from_abs(RX, 0); a.push_w(0); a.push_l(6)
    a.bsr16('text')
    a.pop_l(6); a.pop_w(0); a.add_w_imm(1, 0); a.mov_w_to_abs(0, RX)
    a.bsr16('text')
    a.rts()
    return RX, RY, RW, RH, RM


def set_rect(a, regs, x, y, w, h, mode):
    RX, RY, RW, RH, RM = regs
    a.mov_w_imm(x, 0); a.mov_w_to_abs(0, RX); a.mov_w_imm(y, 0); a.mov_w_to_abs(0, RY)
    a.mov_w_imm(w, 0); a.mov_w_to_abs(0, RW); a.mov_w_imm(h, 0); a.mov_w_to_abs(0, RH)
    a.mov_b_imm(mode, 'r0l'); a.mov_b_to_abs('r0l', RM)
    a.bsr16('rect')


def put_text(a, regs, x, y, label, bold=False):
    RX, RY = regs[0], regs[1]
    a.mov_w_imm(x, 0); a.mov_w_to_abs(0, RX); a.mov_w_imm(y, 0); a.mov_w_to_abs(0, RY)
    a.mov_l_imm(label, 6); a.bsr16('bold' if bold else 'text')
