"""Rosetta OS 0.06 for the VS-840EX = 0.05 + the VS boots into the Rosetta home menu.

Hook: the stock main loop head 0x11B588 (`mov.w @er5,r0 / cmp.w #3,r0`, 6 bytes) becomes `jsr hook / nop`.
That is after the update-file check (0x11B3DA), so a disk update stays reachable whatever our code does.
hook: once per power-on (magic word in on-chip RAM 0xFFDC00, which nothing else touches) it runs home(),
then redoes the two replaced instructions and returns (rts keeps the flags for the following bne).

home(): saves the LCD shadow buffer (whatever the stock boot drew), draws its own screen, reads Roland's event
queue (0x11D3F8: type 1 = key {state, code}, type 2 = dial {delta}), and on RECORDER restores the buffer and
returns into the stock loop. Other entries say COMING SOON for now.

Screen: HR-GP5 v0.2 folder-tab look (rui.py): black tab with the bold title, status right, rule, 3 rows,
inverted selection, scroll bar. Text = the ROM 5x7 font drawn at pixel positions.

usage: python -I tools/build_v006.py [--test]   -> work/v006/ (+ emulator screens with --test)
"""
import os, shutil, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h8asm import Asm
import rui
from make_smf import build
from decode_upd import decode
from build_v001 import flash_sum, SUM_AT
import build_v004

ROOT = build_v004.ROOT
BASE = 0x110000
CODE = 0x1F9000                         # free flash after the OS data (0x1F80AA-0x1FFEFF is all FF)
VERSION = b'ROSETTA OS 0.06'
CF_FIX = '--no-cf-fix' not in sys.argv     # 0.06b: without the 0.05 drive-check patch (it hung the boot on hw)
if not CF_FIX: VERSION = b'ROSETTA OS 0.6b'

# ROM / OS routines
ROM_CLR, ROM_PRINT, ROM_DELAY = 0x268A, 0x2E36, 0x4C4E
GETEV = 0x11D3F8
LCD, STRIDE, STRIPS = 0x403200, 0x22, 17
# our RAM (on-chip, unused by ROM and OS)
RAM = 0xFFDC00
MAGIC, CUR, TOP, EV, SAVE = RAM, RAM + 4, RAM + 5, RAM + 0x10, RAM + 0x40
MAGIC_V = 0x52535441                    # 'RSTA'
LCD_LEN = 0x242
# keys (code numbering = key-name table 0x1F6F2E)
K_UP, K_DOWN, K_ENTER = 0x1F, 0x21, 0x23

STATUS = 'VS-840EX'
TAB_W = 4 + 6 * 10 + 1 + 4             # bold 'ROSETTA OS' + margins
THUMB_H = 12
ITEMS = ['RECORDER', 'LOOPER', 'FX LAB', 'SAMPLER', 'SYNTH', 'SYSTEM']
HOOK_AT = 0x11B588


def assemble():
    a = Asm(CODE)
    # ---------------- hook (called from the stock main loop head) ----------------
    a.label('hook')
    for r in range(7): a.push_l(r)
    a.mov_l_from_abs(MAGIC, 0)
    a.cmp_l_imm(MAGIC_V, 0)
    a.beq16('h_done')
    a.mov_l_imm(MAGIC_V, 0)
    a.mov_l_to_abs(0, MAGIC)
    a.bsr16('home')
    a.label('h_done')
    for r in reversed(range(7)): a.pop_l(r)
    a.mov_w_ld(5, 0)                        # replaced: mov.w @er5,r0
    a.cmp_w_imm(3, 0)                       # replaced: cmp.w #3,r0 (rts keeps CCR)
    a.rts()

    # ---------------- home ----------------
    a.label('home')
    a.mov_l_imm(LCD, 1); a.mov_l_imm(SAVE, 2); a.bsr16('copy_lcd')
    a.mov_b_imm(0, 'r0l'); a.mov_b_to_abs('r0l', CUR); a.mov_b_to_abs('r0l', TOP)
    a.bsr16('draw')
    a.label('loop')
    a.mov_l_imm(EV, 0); a.push_l(0); a.jsr(GETEV); a.adds4(7)
    a.mov_w_from_abs(EV, 0)
    a.cmp_w_imm(1, 0); a.beq16('k_key')
    a.cmp_w_imm(2, 0); a.beq16('k_dial')
    a.bra16('loop')
    a.label('k_key')
    a.mov_w_from_abs(EV + 2, 0); a.cmp_w_imm(1, 0); a.bne16('loop')     # presses only
    a.mov_w_from_abs(EV + 4, 0)
    a.cmp_w_imm(K_UP, 0); a.beq16('up')
    a.cmp_w_imm(K_DOWN, 0); a.beq16('down')
    a.cmp_w_imm(K_ENTER, 0); a.beq16('enter')
    a.bra16('loop')
    a.label('k_dial')
    a.mov_w_from_abs(EV + 2, 0); a.cmp_w_imm(0, 0)
    a.beq16('loop'); a.bmi16('up'); a.bra16('down')
    a.label('up')
    a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq16('loop')
    a.add_b_imm(0xFF, 'r0l'); a.mov_b_to_abs('r0l', CUR); a.bsr16('draw'); a.bra16('loop')
    a.label('down')
    a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(len(ITEMS) - 1, 'r0l'); a.beq16('loop')
    a.add_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', CUR); a.bsr16('draw'); a.bra16('loop')
    a.label('enter')
    a.mov_b_from_abs(CUR, 'r0l'); a.cmp_b_imm(0, 'r0l'); a.beq16('recorder')
    a.bsr16('soon')
    a.mov_w_imm(900, 0); a.jsr(ROM_DELAY)
    a.bsr16('draw'); a.bra16('loop')
    a.label('recorder')
    a.mov_l_imm(SAVE, 1); a.mov_l_imm(LCD, 2); a.bsr16('copy_lcd')
    a.rts()

    # copy_lcd: er1 src -> er2 dst, LCD_LEN bytes (r3 counter)
    a.label('copy_lcd')
    a.mov_w_imm(LCD_LEN, 3)
    a.label('cl_lp')
    a.mov_b_ldinc(1, 'r0l'); a.mov_b_st('r0l', 2); a.adds1(2); a.dec_w1(3); a.bne('cl_lp')
    a.rts()

    # ---- screen pieces (HR-GP5 v0.2 folder-tab look, see rui.py) ----
    regs = rui.emit(a, RAM + 0x30)
    a.label('chrome')                                   # tab title, status, rule, frame, scroll frame
    rui.put_text(a, regs, 4, 0, 's_title', bold=True)
    rui.set_rect(a, regs, 0, 0, TAB_W, 8, 1)
    rui.put_text(a, regs, 135 - 6 * len(STATUS), 0, 's_status')
    rui.set_rect(a, regs, TAB_W, 7, 136 - TAB_W, 1, 0)
    rui.set_rect(a, regs, 0, 8, 1, 24, 0)
    rui.set_rect(a, regs, 130, 8, 1, 24, 0)
    rui.set_rect(a, regs, 135, 8, 1, 24, 0)
    a.rts()

    # draw: clear, chrome, 3 rows from TOP, scroll thumb, selection bar on CUR
    a.label('draw')
    a.push_l(4); a.push_l(5); a.push_l(6)
    a.mov_b_from_abs(CUR, 'r0l'); a.mov_b_from_abs(TOP, 'r0h')
    a.cmp_b_rr('r0h', 'r0l'); a.bcc('dr_t1')                 # CUR >= TOP: ok
    a.mov_b_to_abs('r0l', TOP); a.bra('dr_t2')
    a.label('dr_t1')
    a.mov_b_rr('r0l', 'r1l'); a.sub_b_rr('r0h', 'r1l')         # r1l = CUR - TOP
    a.cmp_b_imm(2, 'r1l'); a.bls('dr_t2')
    a.add_b_imm(0xFE, 'r0l'); a.mov_b_to_abs('r0l', TOP)
    a.label('dr_t2')
    a.jsr(ROM_CLR); a.bsr16('chrome')
    a.mov_b_from_abs(TOP, 'r5l'); a.mov_w_imm(8, 4)            # r5l = index, r4 = y
    a.label('dr_row')
    a.cmp_b_imm(len(ITEMS), 'r5l'); a.bcc16('dr_done')
    a.mov_b_rr('r5l', 'r0l'); a.extu_w(0); a.extu_l(0); a.shll_l2(0)
    a.mov_l_imm('items', 1); a.add_l_rr(0, 1); a.mov_l_ind(1, 6)            # er6 = items[index]
    a.mov_w_imm(4, 0); a.mov_w_to_abs(0, regs[0]); a.mov_w_to_abs(4, regs[1]); a.bsr16('text')
    a.mov_w_imm(123, 0); a.mov_w_to_abs(0, regs[0]); a.mov_w_to_abs(4, regs[1])
    a.mov_l_imm('s_more', 6); a.bsr16('text')
    a.add_b_imm(1, 'r5l'); a.add_w_imm(8, 4); a.cmp_w_imm(32, 4); a.bne16('dr_row')
    a.label('dr_done')
    # thumb: y from the table by TOP, 12 px tall
    a.mov_b_from_abs(TOP, 'r0l'); a.extu_w(0); a.extu_l(0)
    a.mov_l_imm('thumb', 1); a.add_l_rr(0, 1); a.mov_b_ld(1, 'r0l'); a.extu_w(0)
    a.mov_w_to_abs(0, regs[1]); a.mov_w_imm(132, 0); a.mov_w_to_abs(0, regs[0])
    a.mov_w_imm(2, 0); a.mov_w_to_abs(0, regs[2]); a.mov_w_imm(THUMB_H, 0); a.mov_w_to_abs(0, regs[3])
    a.mov_b_imm(0, 'r0l'); a.mov_b_to_abs('r0l', regs[4]); a.bsr16('rect')
    # selection bar (xor): k = CUR - TOP -> y/h from the bar table
    a.mov_b_from_abs(CUR, 'r0l'); a.mov_b_from_abs(TOP, 'r0h'); a.sub_b_rr('r0h', 'r0l')
    a.extu_w(0); a.extu_l(0); a.shll_l(0)
    a.mov_l_imm('bars', 1); a.add_l_rr(0, 1)
    a.mov_b_ld(1, 'r0l'); a.extu_w(0); a.mov_w_to_abs(0, regs[1])
    a.mov_b_ld_disp(1, 1, 'r0l'); a.extu_w(0); a.mov_w_to_abs(0, regs[3])
    a.mov_w_imm(1, 0); a.mov_w_to_abs(0, regs[0]); a.mov_w_imm(129, 0); a.mov_w_to_abs(0, regs[2])
    a.mov_b_imm(1, 'r0l'); a.mov_b_to_abs('r0l', regs[4]); a.bsr16('rect')
    a.pop_l(6); a.pop_l(5); a.pop_l(4)
    a.rts()

    # coming soon page
    a.label('soon')
    a.push_l(4); a.push_l(5); a.push_l(6)
    a.jsr(ROM_CLR)                                      # pages have no tab bar: the whole 32 px is content
    a.mov_b_from_abs(CUR, 'r0l'); a.extu_w(0); a.extu_l(0); a.shll_l2(0)
    a.mov_l_imm('items', 1); a.add_l_rr(0, 1); a.mov_l_ind(1, 6)    # er6 = name of the entered item
    a.mov_w_imm(4, 0); a.mov_w_to_abs(0, regs[0]); a.mov_w_imm(4, 0); a.mov_w_to_abs(0, regs[1])
    a.bsr16('bold')
    rui.put_text(a, regs, 4, 18, 's_soon')
    a.pop_l(6); a.pop_l(5); a.pop_l(4)
    a.rts()

    # data
    a.label('s_title'); a.string('ROSETTA OS')
    a.label('s_status'); a.string(STATUS)
    a.label('s_more'); a.string('>')
    a.label('s_soon'); a.string('COMING SOON')
    for i, s in enumerate(ITEMS): a.label('it%d' % i); a.string(s)
    a.label('thumb'); a.raw(bytes(8 + 4 * k for k in range(len(ITEMS) - 2)))
    a.label('bars'); a.raw(bytes([8, 8, 15, 9, 23, 9]))
    a.align2()
    a.label('items')
    for i in range(len(ITEMS)): a.dc_l('it%d' % i)
    code = a.assemble()
    return code, a.labels


def build_image():
    img = bytearray(open(os.path.join(ROOT, 'vs840ex_v205_os.bin'), 'rb').read())
    assert struct.unpack('>I', img[SUM_AT:SUM_AT + 4])[0] == flash_sum(img), 'stock sum'
    import build_v005
    code, labels = assemble()
    assert CODE + len(code) < 0x1FFF00
    bits, _ = build_v004.splash_bits()
    S = build_v004.SPLASH - BASE
    hook = bytes([0x5E]) + labels['hook'].to_bytes(3, 'big') + b'\0\0'
    patches = [
        (0x624, b'VS-840 Ver 2.05', VERSION),
        (S, bytes(img[S:S + len(bits)]), bits),
    ] + ([
        (0x126E32 - BASE, bytes.fromhex('1999'), bytes.fromhex('0000')),
        (0x126E3A - BASE, bytes.fromhex('1999'), bytes.fromhex('0000')),
        (0x126E56 - BASE, bytes.fromhex('796000fd79200050'), bytes.fromhex('796000c079200040')),
        (0x126E6C - BASE, bytes.fromhex('796000fd79200050'), bytes.fromhex('796000c079200040')),
    ] if CF_FIX else []) + [
        (HOOK_AT - BASE, bytes.fromhex('695079200003'), hook),
        (CODE - BASE, b'\xff' * len(code), code),
    ]
    for off, old, new in patches:
        assert len(old) == len(new) and img[off:off + len(old)] == old, hex(off)
        img[off:off + len(new)] = new
    img[SUM_AT:SUM_AT + 4] = struct.pack('>I', flash_sum(img))
    return img, code, labels


def test(img, labels):
    """run home() in the emulator with real events in Roland's queue; print the screens"""
    from vsemu import VSEmu
    e = VSEmu(bytes(img))
    e.stubs[ROM_DELAY] = lambda e: None
    q, wi, ri = 0x5B7A34, 0x5B8034, 0x5B8035
    script = [('key', K_DOWN), ('key', K_DOWN), ('dial', 1), ('dial', 1), ('dial', 1), ('dial', -1),
              ('key', K_ENTER), ('key', K_UP), ('key', K_UP), ('key', K_UP), ('key', K_UP), ('key', K_ENTER)]
    def post(kind, v):
        w = e.rb(wi); o = q + w * 12
        words = (1, 1, v, 0) if kind == 'key' else (2, v & 0xFFFF, 0, 0)
        for k, x in enumerate(words): e.ww(o + 2 * k, x)
        e.wb(wi, (w + 1) & 0x7F)
    e.er[7] = 0x43F000; e.push32(0xDEAD00); e.pc = labels['home']
    loop = labels['loop']; shots = []; i = 0
    while e.pc != 0xDEAD00:
        if e.pc == loop and e.rb(wi) == e.rb(ri):
            shots.append(('after ' + (str(script[i - 1]) if i else 'start'), e.screen()))
            if i < len(script): post(*script[i]); i += 1
        e.step()
        if e.steps > 5_000_000: raise RuntimeError('stuck at %06X' % e.pc)
        e.steps += 1
    shots.append(('returned (RECORDER)', e.screen()))
    for name, s in shots:
        print('---', name)
        for row in s: print(row)
    return shots


def main():
    img, code, labels = build_image()
    out = os.path.join(ROOT, 'work', 'v006' if CF_FIX else 'v006b')
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'os.bin'), 'wb').write(img)
    open(os.path.join(out, 'rosetta.bin'), 'wb').write(code)
    shutil.copyfile(os.path.join(out, 'os.bin'), os.path.join(out, '$SYSPRO2.VS1'))
    build(os.path.join(ROOT, 'upd', 'x_VS840EXv205'), bytes(img), out, 'rosetta')
    back, _, _ = decode(out)
    assert back[0x10000:0x100000] == img, 'decode mismatch'
    print('ok: code %d bytes at %06X, hook %06X, flash sum %08X' % (len(code), CODE, labels['hook'], flash_sum(img)))
    if '--test' in sys.argv: test(img, labels)


if __name__ == '__main__':
    main()
