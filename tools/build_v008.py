"""Rosetta OS 0.08 for the VS-840EX = 0.07 + SOUND TEST: the first sound from our own DSP code.

Home (folder tab): SOUND TEST, SAMPLER, SYNTH, FX, STOCK VS. Pages entered from home have no tab bar (4 rows).
SOUND TEST: TONE 440 HZ / INPUT THRU / TONE + THRU / OFF. ENTER switches live, the active row shows ON,
EXIT (or OFF) puts Roland's own DSP words back. The DSP block (vsdsp.py, simulated) sits after the stock core-0
mixer at word 0x2C0 and writes every output candidate, so whatever is plugged in (master, phones) should sound.

Generic list page (data in flash, 24 bytes): .b tab, .b count, .w thumb_h, .l items, .l cur_addr, .l top_addr,
.l on_addr (0 = none; row r shows ON when @on == r + 1), .l thumb_table. Item = .l label, .l right text, .w right x,
.w pad. list_run(er5 = page) -> r0 = chosen row, 0xFF = EXIT.

usage: python -I tools/build_v008.py [--test]   -> work/v008/ (+ emulator run with a write guard)
"""
import os, shutil, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h8asm import Asm
import rui, vsdsp
from make_smf import build
from decode_upd import decode
from build_v001 import flash_sum, SUM_AT
import build_v004, build_v007

ROOT = build_v004.ROOT
BASE = 0x110000
CODE = 0x1F9000
VERSION = b'ROSETTA OS 0.08'

ROM_CLR, ROM_DELAY, GETEV = 0x268A, 0x4C4E, 0x11D3F8
DSP_WORD, DSP_LATCH, LATCH_SHADOW = 0x5A3A, 0x4DCA, 0x5B5801
CORE0_IMAGE = 0x5B3FFA
LCD, STRIDE, STRIPS = rui.LCD, rui.STRIDE, rui.STRIPS
K_UP, K_DOWN, K_ENTER, K_EXIT = 0x1F, 0x21, 0x23, 0x24

RAM = 0xFFEC00                           # on-chip RAM 0xFFEC00-0xFFFBFF, bottom of the stack area
HCUR, HTOP, SCUR, STOP_, SMODE, SAVED = RAM, RAM + 1, RAM + 2, RAM + 3, RAM + 4, RAM + 5
T_Y0, T_N, T_IDX = RAM + 6, RAM + 8, RAM + 9          # draw temps
EV = RAM + 0x10
UIRAM = RAM + 0x30                                    # rui params (10 bytes)
SAVE = RAM + 0x40                                     # LCD backup, 0x242 bytes
DSPSAVE = RAM + 0x290                                 # stock words at TEST_AT, 32 x 4 bytes
RAM_END = DSPSAVE + vsdsp.TEST_LEN * 4
LCD_LEN = 0x242

HOOK_AT, HOOK_WAS = build_v007.HOOK_AT, build_v007.HOOK_WAS
STATUS = 'VS-840EX'
TAB_W = 4 + 6 * 10 + 1 + 4
HOME = ['SOUND TEST', 'SAMPLER', 'SYNTH', 'FX', 'STOCK VS']
SOUND = ['TONE 440 HZ', 'INPUT THRU', 'TONE + THRU', 'OFF']
SOUND_MODES = ['TONE', 'THRU', 'BOTH']


def thumb(count, rows, area):
    """scroll thumb (height, y offsets per TOP) for a list of count items, rows visible, area px tall"""
    if count <= rows: return 0, [0]
    th = max(4, area * rows // count)
    return th, [(area - th) * t // (count - rows) for t in range(count - rows + 1)]


def assemble():
    a = Asm(CODE)
    regs = None

    # ---------------- hook (replaces the once-per-boot jsr 0x12ED24) ----------------
    a.label('hook')
    a.jsr(0x12ED24)
    for r in range(7): a.push_l(r)
    a.bsr16('anim')
    a.bsr16('home')
    for r in reversed(range(7)): a.pop_l(r)
    a.rts()

    # ---------------- boot animation (same as 0.07) ----------------
    a.label('anim')
    a.push_l(4); a.push_l(5); a.push_l(6)
    a.jsr(ROM_CLR)
    a.mov_l_imm('anim_data', 6)
    a.label('an_fr')
    a.mov_b_ldinc(6, 'r5l'); a.cmp_b_imm(0, 'r5l'); a.beq16('an_end')
    a.mov_b_ldinc(6, 'r4h'); a.mov_b_ldinc(6, 'r4l')
    a.label('an_run')
    a.cmp_w_imm(0, 4); a.beq16('an_wait')
    a.mov_b_ldinc(6, 'r0l'); a.extu_w(0); a.extu_l(0)
    a.mov_b_imm(STRIDE, 'r1l'); a.mulxu_b('r1l', 0); a.extu_l(0)
    a.mov_b_ldinc(6, 'r1l'); a.extu_w(1); a.extu_l(1); a.add_l_rr(1, 0)
    a.add_l_imm(LCD + 2, 0)
    a.mov_b_ldinc(6, 'r3l')
    a.label('an_cp')
    a.mov_b_ldinc(6, 'r1l'); a.mov_b_st('r1l', 0); a.adds1(0)
    a.add_b_imm(0xFF, 'r3l'); a.bne('an_cp')
    a.dec_w1(4); a.bra16('an_run')
    a.label('an_wait')
    a.mov_w_imm(build_v007.ANIM_TICK, 0); a.jsr(ROM_DELAY)
    a.mov_l_imm(EV, 0); a.push_l(0); a.jsr(GETEV); a.adds4(7)
    a.mov_w_from_abs(EV, 0); a.cmp_w_imm(1, 0); a.beq16('an_end')
    a.add_b_imm(0xFF, 'r5l'); a.bne16('an_wait')
    a.bra16('an_fr')
    a.label('an_end')
    a.pop_l(6); a.pop_l(5); a.pop_l(4)
    a.rts()

    # ---------------- home ----------------
    a.label('home')
    a.mov_l_imm(LCD, 1); a.mov_l_imm(SAVE, 2); a.bsr16('copy_lcd')
    a.mov_b_imm(0, 'r0l')
    for v in (HCUR, HTOP, SCUR, STOP_, SMODE, SAVED): a.mov_b_to_abs('r0l', v)
    a.label('h_loop')
    a.mov_l_imm('pg_home', 5); a.bsr16('list_run')
    a.cmp_b_imm(0, 'r0l'); a.beq16('h_sound')
    a.cmp_b_imm(4, 'r0l'); a.beq16('h_stock')
    a.cmp_b_imm(0xFF, 'r0l'); a.beq16('h_loop')                  # EXIT on home: stay
    a.extu_w(0); a.extu_l(0); a.mov_l_rr(0, 1); a.add_l_rr(1, 1); a.add_l_rr(1, 0); a.shll_l2(0)   # r * 12
    a.mov_l_imm('it_home', 1); a.add_l_rr(0, 1); a.mov_l_ind(1, 6)                                  # label
    a.bsr16('soon'); a.mov_w_imm(900, 0); a.jsr(ROM_DELAY)
    a.bra16('h_loop')
    a.label('h_sound')
    a.bsr16('sound'); a.bra16('h_loop')
    a.label('h_stock')
    a.bsr16('dsp_off')
    a.mov_l_imm(SAVE, 1); a.mov_l_imm(LCD, 2); a.bsr16('copy_lcd')
    a.rts()

    # ---------------- SOUND TEST ----------------
    a.label('sound')
    a.label('s_loop')
    a.mov_l_imm('pg_sound', 5); a.bsr16('list_run')
    a.cmp_b_imm(0xFF, 'r0l'); a.beq16('s_exit')
    a.cmp_b_imm(3, 'r0l'); a.beq16('s_off')
    a.push_w(0); a.bsr16('dsp_save')
    a.pop_w(0); a.mov_b_rr('r0l', 'r1l'); a.add_b_imm(1, 'r1l'); a.mov_b_to_abs('r1l', SMODE)
    a.extu_w(0); a.extu_l(0); a.shll_l2(0)
    a.mov_l_imm('blocks', 1); a.add_l_rr(0, 1); a.mov_l_ind(1, 6)                # er6 = block bytes
    a.bsr16('dsp_load'); a.bra16('s_loop')
    a.label('s_off')
    a.bsr16('dsp_off'); a.bra16('s_loop')
    a.label('s_exit')
    a.bsr16('dsp_off')
    a.rts()

    # dsp_save: first time only, copy the stock words at TEST_AT from the core-0 RAM image
    a.label('dsp_save')
    a.mov_b_from_abs(SAVED, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.bne16('ds_done')
    a.mov_l_imm(CORE0_IMAGE + vsdsp.TEST_AT * 4, 1); a.mov_l_imm(DSPSAVE, 2); a.mov_w_imm(vsdsp.TEST_LEN * 4, 3)
    a.label('ds_cp')
    a.mov_b_ldinc(1, 'r0l'); a.mov_b_st('r0l', 2); a.adds1(2); a.dec_w1(3); a.bne('ds_cp')
    a.mov_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', SAVED)
    a.label('ds_done')
    a.rts()

    # dsp_off: put the saved stock words back (if we changed anything)
    a.label('dsp_off')
    a.mov_b_from_abs(SAVED, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq16('do_done')
    a.mov_l_imm(DSPSAVE, 6); a.bsr16('dsp_load')
    a.label('do_done')
    a.mov_b_imm(0, 'r0l'); a.mov_b_to_abs('r0l', SMODE)
    a.rts()

    # dsp_load: er6 -> TEST_LEN 4-byte words, written to core 0 at TEST_AT (raw mode), two passes
    a.label('dsp_load')
    a.push_l(4); a.push_l(5); a.push_l(6)
    a.mov_b_from_abs(LATCH_SHADOW, 'r0l'); a.and_b_imm(0xFE, 'r0l'); a.mov_b_to_abs('r0l', LATCH_SHADOW)
    a.mov_w_imm(3, 0); a.jsr(DSP_LATCH)                        # latch bit 0 = 0: raw word writes
    a.mov_w_imm(2, 13)                                          # e5 = passes
    a.label('dl_pass')
    a.mov_l_ld_disp(0, 7, 6)                                    # er6 = block (saved on the stack)
    a.mov_w_imm(vsdsp.TEST_AT * 4, 4); a.mov_w_imm(vsdsp.TEST_LEN, 5)
    a.label('dl_w')
    a.mov_w_rr(4, 0); a.mov_l_rr(6, 1); a.jsr(DSP_WORD)
    a.add_w_imm(4, 4); a.adds4(6); a.dec_w1(5); a.bne('dl_w')
    a.dec_w1(13); a.bne('dl_pass')
    a.pop_l(6); a.pop_l(5); a.pop_l(4)
    a.rts()

    # copy_lcd: er1 src -> er2 dst, LCD_LEN bytes
    a.label('copy_lcd')
    a.mov_w_imm(LCD_LEN, 3)
    a.label('cl_lp')
    a.mov_b_ldinc(1, 'r0l'); a.mov_b_st('r0l', 2); a.adds1(2); a.dec_w1(3); a.bne('cl_lp')
    a.rts()

    # ---------------- UI ----------------
    regs = rui.emit(a, UIRAM)
    RX, RY, RW, RH, RM = regs

    a.label('chrome')                                   # home only: tab, status, rule
    rui.put_text(a, regs, 4, 0, 's_title', bold=True)
    rui.set_rect(a, regs, 0, 0, TAB_W, 8, 1)
    rui.put_text(a, regs, 135 - 6 * len(STATUS), 0, 's_status')
    rui.set_rect(a, regs, TAB_W, 7, 136 - TAB_W, 1, 0)
    a.rts()

    a.label('soon')                                     # er6 = name; page without tab bar
    a.push_l(6); a.jsr(ROM_CLR); a.pop_l(6)
    a.mov_w_imm(4, 0); a.mov_w_to_abs(0, RX); a.mov_w_to_abs(0, RY); a.bsr16('bold')
    rui.put_text(a, regs, 4, 18, 's_soon')
    a.rts()

    def rect_xywh(x, y_reg_or_val, w, h_val, mode):
        a.mov_w_imm(x, 0); a.mov_w_to_abs(0, RX)
        if isinstance(y_reg_or_val, int): a.mov_w_imm(y_reg_or_val, 0); a.mov_w_to_abs(0, RY)
        else: a.mov_w_to_abs(y_reg_or_val, RY)
        a.mov_w_imm(w, 0); a.mov_w_to_abs(0, RW)
        if isinstance(h_val, int): a.mov_w_imm(h_val, 0); a.mov_w_to_abs(0, RH)
        else: a.mov_w_to_abs(h_val, RH)
        a.mov_b_imm(mode, 'r0l'); a.mov_b_to_abs('r0l', RM); a.bsr16('rect')

    # draw_list(er5 = page)
    a.label('draw_list')
    a.push_l(4); a.push_l(6)
    # rows / y0 / window: tab -> 3 rows from y 8, else 4 rows from y 0
    a.mov_b_ld(5, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq('dl_notab')
    a.mov_w_imm(8, 0); a.mov_w_to_abs(0, T_Y0); a.mov_b_imm(3, 'r0l'); a.mov_b_to_abs('r0l', T_N); a.bra('dl_clamp')
    a.label('dl_notab')
    a.mov_w_imm(0, 0); a.mov_w_to_abs(0, T_Y0); a.mov_b_imm(4, 'r0l'); a.mov_b_to_abs('r0l', T_N)
    a.label('dl_clamp')                                 # keep CUR inside [TOP, TOP + N - 1]
    a.mov_l_ld_disp(8, 5, 0); a.mov_b_ld(0, 'r1l')      # r1l = CUR
    a.mov_l_ld_disp(12, 5, 2); a.mov_b_ld(2, 'r1h')     # r1h = TOP, er2 = &TOP
    a.cmp_b_rr('r1h', 'r1l'); a.bcc('dl_c1')
    a.mov_b_st('r1l', 2); a.bra('dl_c2')                # CUR < TOP: TOP = CUR
    a.label('dl_c1')
    a.mov_b_rr('r1l', 'r0l'); a.sub_b_rr('r1h', 'r0l')  # r0l = CUR - TOP
    a.mov_b_from_abs(T_N, 'r0h'); a.add_b_imm(0xFF, 'r0h')
    a.cmp_b_rr('r0h', 'r0l'); a.bls('dl_c2')            # CUR - TOP <= N - 1
    a.mov_b_rr('r1l', 'r0l'); a.sub_b_rr('r0h', 'r0l'); a.mov_b_st('r0l', 2)
    a.label('dl_c2')
    a.push_l(5); a.jsr(ROM_CLR); a.pop_l(5)
    a.mov_b_ld(5, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq('dl_nochrome')
    a.push_l(5); a.bsr16('chrome'); a.pop_l(5)
    a.label('dl_nochrome')
    # frame line x 0 and scroll frame x 130/135 over the rows area
    a.mov_w_from_abs(T_Y0, 4); a.mov_w_imm(32, 0); a.sub_w_rr(4, 0); a.mov_w_rr(0, 14)   # e6 = area height
    rect_xywh(0, 4, 1, 14, 0); rect_xywh(130, 4, 1, 14, 0); rect_xywh(135, 4, 1, 14, 0)
    # rows: T_IDX = TOP, y = Y0
    a.mov_l_ld_disp(12, 5, 0); a.mov_b_ld(0, 'r0l'); a.mov_b_to_abs('r0l', T_IDX)
    a.mov_b_from_abs(T_N, 'r6l')                        # r6l = rows left
    a.label('dl_row')
    a.mov_b_from_abs(T_IDX, 'r0l'); a.mov_b_ld_disp(1, 5, 'r0h')     # r0h = count
    a.cmp_b_rr('r0h', 'r0l'); a.bcc16('dl_rows_done')
    a.extu_w(0); a.mov_b_imm(0, 'r0h'); a.extu_l(0)
    a.mov_l_rr(0, 1); a.add_l_rr(1, 1); a.add_l_rr(1, 0); a.shll_l2(0)              # er0 = idx * 12
    a.mov_l_ld_disp(4, 5, 1); a.add_l_rr(0, 1); a.push_l(1)                          # item ptr
    a.mov_l_ind(1, 6); a.mov_w_imm(4, 0); a.mov_w_to_abs(0, RX); a.mov_w_to_abs(4, RY)
    a.push_l(6); a.bsr16('text'); a.pop_l(6)
    a.pop_l(1)
    # right text: ON when @on == idx + 1, else the item's
    a.mov_l_ld_disp(16, 5, 0); a.cmp_l_imm(0, 0); a.beq('dl_right')
    a.mov_b_ld(0, 'r0l'); a.mov_b_from_abs(T_IDX, 'r0h'); a.add_b_imm(1, 'r0h')
    a.cmp_b_rr('r0h', 'r0l'); a.bne('dl_right')
    a.mov_l_imm('s_on', 6); a.mov_w_imm(128 - 6 * 2, 0); a.bra('dl_put')
    a.label('dl_right')
    a.mov_l_ld_disp(4, 1, 6); a.mov_w_disp(8, 1, 0)
    a.label('dl_put')
    a.mov_w_to_abs(0, RX); a.mov_w_to_abs(4, RY)
    a.push_l(6); a.bsr16('text'); a.pop_l(6)
    a.mov_b_from_abs(T_IDX, 'r0l'); a.add_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', T_IDX)
    a.add_w_imm(8, 4); a.add_b_imm(0xFF, 'r6l'); a.bne16('dl_row')
    a.label('dl_rows_done')
    # thumb (if the page has one): x 132, w 2, y = Y0 + table[TOP], h = thumb_h
    a.mov_w_disp(2, 5, 0); a.cmp_w_imm(0, 0); a.beq16('dl_bar')
    a.mov_w_to_abs(0, RH)
    a.mov_l_ld_disp(12, 5, 0); a.mov_b_ld(0, 'r0l'); a.extu_w(0); a.extu_l(0)
    a.mov_l_ld_disp(20, 5, 1); a.add_l_rr(0, 1); a.mov_b_ld(1, 'r0l'); a.extu_w(0)
    a.mov_w_from_abs(T_Y0, 1); a.add_w_rr(1, 0); a.mov_w_to_abs(0, RY)
    a.mov_w_imm(132, 0); a.mov_w_to_abs(0, RX); a.mov_w_imm(2, 0); a.mov_w_to_abs(0, RW)
    a.mov_b_imm(0, 'r0l'); a.mov_b_to_abs('r0l', RM); a.bsr16('rect')
    # selection bar: k = CUR - TOP; y = Y0 + 8k (k > 0: one px higher, 9 tall)
    a.label('dl_bar')
    a.mov_l_ld_disp(8, 5, 0); a.mov_b_ld(0, 'r0l')
    a.mov_l_ld_disp(12, 5, 1); a.mov_b_ld(1, 'r0h'); a.sub_b_rr('r0h', 'r0l')      # r0l = k
    a.mov_b_rr('r0l', 'r1l'); a.extu_w(1); a.shll_w(1); a.shll_w(1); a.shll_w(1)     # r1 = 8k
    a.mov_w_from_abs(T_Y0, 0); a.add_w_rr(0, 1)                                     # r1 = Y0 + 8k
    a.mov_w_imm(8, 4)                                                               # r4 = h
    a.cmp_w_imm(0, 1); a.beq('dl_bar_go')
    a.mov_w_from_abs(T_Y0, 0); a.cmp_w_rr(1, 0); a.beq('dl_bar_go')                 # first row: no lift
    a.add_w_imm(0xFFFF, 1); a.mov_w_imm(9, 4)
    a.label('dl_bar_go')
    rect_xywh(1, 1, 129, 4, 1)
    a.pop_l(6); a.pop_l(4)
    a.rts()

    # list_run(er5 = page) -> r0l = row or 0xFF (EXIT)
    a.label('list_run')
    a.push_l(5); a.bsr16('draw_list'); a.pop_l(5)
    a.label('lr_ev')
    a.push_l(5); a.mov_l_imm(EV, 0); a.push_l(0); a.jsr(GETEV); a.adds4(7); a.pop_l(5)
    a.mov_w_from_abs(EV, 0)
    a.cmp_w_imm(1, 0); a.beq('lr_key')
    a.cmp_w_imm(2, 0); a.beq16('lr_dial')
    a.bra('lr_ev')
    a.label('lr_key')
    a.mov_w_from_abs(EV + 2, 0); a.cmp_w_imm(1, 0); a.bne('lr_ev')
    a.mov_w_from_abs(EV + 4, 0)
    a.cmp_w_imm(K_UP, 0); a.beq16('lr_up')
    a.cmp_w_imm(K_DOWN, 0); a.beq16('lr_down')
    a.cmp_w_imm(K_ENTER, 0); a.beq16('lr_enter')
    a.cmp_w_imm(K_EXIT, 0); a.beq16('lr_exit')
    a.bra('lr_ev')
    a.label('lr_dial')
    a.mov_w_from_abs(EV + 2, 0); a.cmp_w_imm(0, 0)
    a.beq('lr_ev'); a.bmi16('lr_up'); a.bra16('lr_down')
    a.label('lr_up')
    a.mov_l_ld_disp(8, 5, 1); a.mov_b_ld(1, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq16('lr_ev')
    a.add_b_imm(0xFF, 'r0l'); a.mov_b_st('r0l', 1); a.bra16('list_run')
    a.label('lr_down')
    a.mov_l_ld_disp(8, 5, 1); a.mov_b_ld(1, 'r0l'); a.mov_b_ld_disp(1, 5, 'r0h'); a.add_b_imm(0xFF, 'r0h')
    a.cmp_b_rr('r0h', 'r0l'); a.bcc16('lr_ev')
    a.add_b_imm(1, 'r0l'); a.mov_b_st('r0l', 1); a.bra16('list_run')
    a.label('lr_enter')
    a.mov_l_ld_disp(8, 5, 1); a.mov_b_ld(1, 'r0l'); a.rts()
    a.label('lr_exit')
    a.mov_b_imm(0xFF, 'r0l'); a.rts()

    # ---------------- data ----------------
    a.label('s_title'); a.string('ROSETTA OS')
    a.label('s_status'); a.string(STATUS)
    a.label('s_soon'); a.string('COMING SOON')
    a.label('s_on'); a.string('ON')
    a.label('s_more'); a.string('>')
    a.label('s_none'); a.string('')
    for i, s in enumerate(HOME): a.label('h%d' % i); a.string(s)
    for i, s in enumerate(SOUND): a.label('so%d' % i); a.string(s)
    th_h, th_y = thumb(len(HOME), 3, 24)
    a.label('th_home'); a.raw(bytes(th_y))
    th_s, th_sy = thumb(len(SOUND), 4, 32)
    a.label('th_sound'); a.raw(bytes(th_sy))
    a.align2()
    # DSP blocks (4-byte words), one per sound mode
    for m in SOUND_MODES:
        a.label('blk_' + m); a.raw(vsdsp.to_bytes(vsdsp.block(*vsdsp.MODES[m])))
    a.label('blocks')
    for m in SOUND_MODES: a.dc_l('blk_' + m)
    # items: label, right, right x, pad
    a.label('it_home')
    for i in range(len(HOME)):
        a.dc_l('h%d' % i); a.dc_l('s_more' if i < 4 else 's_none'); a.raw(struct.pack('>HH', 123, 0))
    a.label('it_sound')
    for i in range(len(SOUND)):
        a.dc_l('so%d' % i); a.dc_l('s_none'); a.raw(struct.pack('>HH', 123, 0))
    a.label('pg_home')
    a.raw(bytes([1, len(HOME)]) + struct.pack('>H', th_h)); a.dc_l('it_home')
    a.dc_l(HCUR); a.dc_l(HTOP); a.dc_l(0); a.dc_l('th_home')
    a.label('pg_sound')
    a.raw(bytes([0, len(SOUND)]) + struct.pack('>H', th_s)); a.dc_l('it_sound')
    a.dc_l(SCUR); a.dc_l(STOP_); a.dc_l(SMODE); a.dc_l('th_sound')
    a.label('anim_data'); a.raw(build_v007.anim_pack())
    code = a.assemble()
    return code, a.labels


def build_image():
    img = bytearray(open(os.path.join(ROOT, 'vs840ex_v205_os.bin'), 'rb').read())
    assert struct.unpack('>I', img[SUM_AT:SUM_AT + 4])[0] == flash_sum(img), 'stock sum'
    code, labels = assemble()
    assert CODE + len(code) < 0x1FFF00
    for p in ('pg_home', 'pg_sound', 'it_home', 'it_sound', 'blocks', 'blk_TONE'): assert labels[p] % 2 == 0, p
    bits, _ = build_v004.splash_bits()
    S = build_v004.SPLASH - BASE
    hook = bytes([0x5E]) + labels['hook'].to_bytes(3, 'big')
    patches = [
        (0x624, b'VS-840 Ver 2.05', VERSION),
        (S, bytes(img[S:S + len(bits)]), bits),
        (HOOK_AT - BASE, HOOK_WAS, hook),
        (CODE - BASE, bytes([0xFF]) * len(code), code),
    ]
    for off, old, new in patches:
        assert len(old) == len(new) and img[off:off + len(old)] == old, hex(off)
        img[off:off + len(new)] = new
    img[SUM_AT:SUM_AT + 4] = struct.pack('>I', flash_sum(img))
    return img, code, labels


def test(img, labels, code_len):
    """whole hook in the emulator: animation, home, SOUND TEST (TONE, THRU, OFF, EXIT), STOCK VS.
    Checks: write guard, DSP words in the core-0 image after each step, screens for the preview."""
    from vsemu import VSEmu
    e = VSEmu(bytes(img))
    e.stubs[ROM_DELAY] = lambda e: None
    e.stubs[0x12ED24] = lambda e: None
    # a recognisable stock pattern at TEST_AT in the core-0 image, to check OFF restores it
    for i in range(vsdsp.TEST_LEN * 4): e.wb(CORE0_IMAGE + vsdsp.TEST_AT * 4 + i, (i * 7 + 3) & 0xFF)
    stock = bytes(e.rb(CORE0_IMAGE + vsdsp.TEST_AT * 4 + i) for i in range(vsdsp.TEST_LEN * 4))
    q, wi, ri = 0x5B7A34, 0x5B8034, 0x5B8035
    SP0 = 0xFFF600
    bad = []; ow, orb = e.wb, e.rb
    def wb(a, v):
        a &= 0xFFFFFF
        if CODE <= e.pc < CODE + code_len and not (LCD <= a < LCD + LCD_LEN or RAM <= a < RAM_END
                                                    or e.er[7] - 64 <= a < SP0 or a == LATCH_SHADOW):
            bad.append((e.pc, a))
        ow(a, v)
    e.wb = wb
    K = lambda c: ('key', c)
    script = [K(K_ENTER),                    # home row 0 = SOUND TEST
              K(K_ENTER),                    # TONE
              ('chk', 'TONE'),
              K(K_DOWN), K(K_ENTER),         # THRU
              ('chk', 'THRU'),
              ('dial', 1), ('dial', 1), K(K_ENTER),   # OFF
              ('chk', 'STOCK'),
              K(K_UP), K(K_ENTER), ('chk', 'BOTH'),  # OFF -> UP = TONE + THRU
              K(K_EXIT), ('chk', 'STOCK'),           # back home, stock words back
              K(K_DOWN), K(K_ENTER),                 # SAMPLER -> coming soon
              ('dial', 1), ('dial', 1), ('dial', 1), K(K_ENTER)]   # STOCK VS -> return
    def post(kind, v):
        w = orb(wi); o = q + w * 12
        words = (1, 1, v, 0) if kind == 'key' else (2, v & 0xFFFF, 0, 0)
        for k, x in enumerate(words): ow(o + 2 * k, x >> 8); ow(o + 2 * k + 1, x & 0xFF)
        ow(wi, (w + 1) & 0x7F)
    def image():
        return bytes(orb(CORE0_IMAGE + vsdsp.TEST_AT * 4 + i) for i in range(vsdsp.TEST_LEN * 4))
    want = {m: vsdsp.to_bytes(vsdsp.block(*vsdsp.MODES[m])) for m in vsdsp.MODES}
    want['STOCK'] = stock
    e.er[7] = SP0 - 0x40; e.push32(0xDEAD00); e.pc = labels['hook']
    waits = {labels['lr_ev']}; shots = []; i = 0; checks = []
    while e.pc != 0xDEAD00:
        if e.pc in waits and orb(wi) == orb(ri):
            while i < len(script) and script[i][0] == 'chk':
                m = script[i][1]; checks.append((m, image() == want[m])); i += 1
            shots.append((str(script[i - 1]) if i else 'start', e.screen()))
            if i < len(script): post(*script[i]); i += 1
        e.step()
        if e.steps > 30_000_000: raise RuntimeError('stuck at %06X' % e.pc)
        e.steps += 1
    print('DSP image checks:', checks)
    print('guard violations: %d %s' % (len(bad), ['%06X->%06X' % x for x in bad[:5]]))
    assert not bad and all(ok for _, ok in checks)
    return shots


def main():
    img, code, labels = build_image()
    out = os.path.join(ROOT, 'work', 'v008')
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'os.bin'), 'wb').write(img)
    shutil.copyfile(os.path.join(out, 'os.bin'), os.path.join(out, '$SYSPRO2.VS1'))
    build(os.path.join(ROOT, 'upd', 'x_VS840EXv205'), bytes(img), out, 'rosetta')
    back, _, _ = decode(out)
    assert back[0x10000:0x100000] == img, 'decode mismatch'
    print('ok: code %d bytes at %06X, flash sum %08X' % (len(code), CODE, flash_sum(img)))
    if '--test' in sys.argv: return test(img, labels, len(code))


if __name__ == '__main__':
    main()
