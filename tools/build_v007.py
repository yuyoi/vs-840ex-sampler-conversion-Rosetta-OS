"""Rosetta OS 0.07 for the VS-840EX = boot animation + Rosetta home menu (fixes the 0.06 hw bug).

0.06 on hw: after the boot the screen slowly filled black. Cause: its variables were at 0xFFDC00, which is not RAM
(the H8S/2655 has 4 KB on-chip RAM at 0xFFEC00-0xFFFBFF, see the ROM reset clear at 0x74A), so every width / height
read was garbage and rect() drew a huge rectangle (and pix wrote far outside the LCD buffer).
0.07:
  - RAM = 0xFFEC00 (bottom of the on-chip stack area: no OS/ROM reference, the stack is shallow while home runs).
    Only used while Rosetta runs, nothing has to survive into the stock code.
  - hook = the once-per-boot `jsr 0x12ED24` at 0x11B4CC (after the update check 0x11B3DA, after the task setup):
    hook calls 0x12ED24, then the animation, then home(). No magic word needed.
  - pix / text clip to 136 x 32, so wrong numbers can never write outside the LCD buffer again.
  - the 0.05 CF drive-check patch is dropped (it did not cure Setup ERROR on hw).
  - boot animation: the SP-808 Roland-chan / ROSETTA frames (45 frames, 112 ticks of 50 ms), run-packed (changed
    byte runs per frame), any key skips it.

usage: python -I tools/build_v007.py [--test]   -> work/v007/ (+ emulator run with a write guard)
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
VERSION = b'ROSETTA OS 0.07'

# ROM / OS routines
ROM_CLR, ROM_PRINT, ROM_DELAY = 0x268A, 0x2E36, 0x4C4E
GETEV = 0x11D3F8
LCD, STRIDE, STRIPS = 0x403200, 0x22, 17
# our RAM: bottom of the on-chip stack area (on-chip RAM = 0xFFEC00-0xFFFBFF, stack top 0xFFF600)
RAM = 0xFFEC00
CUR, TOP, EV, SAVE = RAM + 4, RAM + 5, RAM + 0x10, RAM + 0x40
RAM_END = SAVE + 0x242
ANIM_TICK = 50                          # ms per tick (SP-808 player: 50000 us)
LCD_LEN = 0x242
# keys (code numbering = key-name table 0x1F6F2E)
K_UP, K_DOWN, K_ENTER = 0x1F, 0x21, 0x23

STATUS = 'VS-840EX'
TAB_W = 4 + 6 * 10 + 1 + 4             # bold 'ROSETTA OS' + margins
THUMB_H = 12
ITEMS = ['RECORDER', 'LOOPER', 'FX LAB', 'SAMPLER', 'SYNTH', 'SYSTEM']
HOOK_AT, HOOK_WAS = 0x11B4CC, bytes.fromhex('5e12ed24')     # jsr 0x12ED24, once per boot


def assemble():
    a = Asm(CODE)
    # ---------------- hook (replaces the once-per-boot jsr 0x12ED24) ----------------
    a.label('hook')
    a.jsr(0x12ED24)
    for r in range(7): a.push_l(r)
    a.bsr16('anim')
    a.bsr16('home')
    for r in reversed(range(7)): a.pop_l(r)
    a.rts()

    # ---------------- boot animation: frames = runs of changed bytes; any key skips ----------------
    a.label('anim')
    a.push_l(4); a.push_l(5); a.push_l(6)
    a.jsr(ROM_CLR)
    a.mov_l_imm('anim_data', 6)
    a.label('an_fr')
    a.mov_b_ldinc(6, 'r5l'); a.cmp_b_imm(0, 'r5l'); a.beq16('an_end')       # ticks, 0 = end
    a.mov_b_ldinc(6, 'r4h'); a.mov_b_ldinc(6, 'r4l')                        # r4 = runs
    a.label('an_run')
    a.cmp_w_imm(0, 4); a.beq16('an_wait')
    a.mov_b_ldinc(6, 'r0l'); a.extu_w(0); a.extu_l(0)                       # strip
    a.mov_b_imm(STRIDE, 'r1l'); a.mulxu_b('r1l', 0); a.extu_l(0)
    a.mov_b_ldinc(6, 'r1l'); a.extu_w(1); a.extu_l(1); a.add_l_rr(1, 0)    # + row
    a.add_l_imm(LCD + 2, 0)                                                 # er0 = dest
    a.mov_b_ldinc(6, 'r3l')                                                 # length
    a.label('an_cp')
    a.mov_b_ldinc(6, 'r1l'); a.mov_b_st('r1l', 0); a.adds1(0)
    a.add_b_imm(0xFF, 'r3l'); a.bne('an_cp')
    a.dec_w1(4); a.bra16('an_run')
    a.label('an_wait')                                                      # r5l ticks of ANIM_TICK ms, key = skip
    a.mov_w_imm(ANIM_TICK, 0); a.jsr(ROM_DELAY)
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
    a.label('anim_data'); a.raw(anim_pack())
    code = a.assemble()
    return code, a.labels


def anim_pack():
    """SP-808 boot frames -> [ticks, runs.w, (strip, row, len, bytes...) x runs] per frame, 0 = end.
    Runs never cross a strip (rows 0-31 of one 8 px column)."""
    import numpy as np
    z = np.load(build_v004.FRAMES)
    out = bytearray(); prev = [bytes(32)] * STRIPS
    for f, tk in zip(z['screens'] != 0, z['ticks']):
        scr = np.zeros((32, 136), bool); scr[:, 2:2 + f.shape[1]] = f
        cols = [bytes(sum(0x80 >> k for k in range(8) if scr[y, g * 8 + k]) for y in range(32)) for g in range(STRIPS)]
        runs = []
        for g in range(STRIPS):
            y = 0
            while y < 32:
                if cols[g][y] != prev[g][y]:
                    s = y
                    while y < 32 and cols[g][y] != prev[g][y]: y += 1
                    runs.append((g, s, cols[g][s:y]))
                else: y += 1
        out += bytes([max(1, int(tk))]) + struct.pack('>H', len(runs))
        for g, s, d in runs: out += bytes([g, s, len(d)]) + d
        prev = cols
    return bytes(out) + b'\0'


def build_image():
    img = bytearray(open(os.path.join(ROOT, 'vs840ex_v205_os.bin'), 'rb').read())
    assert struct.unpack('>I', img[SUM_AT:SUM_AT + 4])[0] == flash_sum(img), 'stock sum'
    code, labels = assemble()
    assert CODE + len(code) < 0x1FFF00
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


def test(img, labels, code_len, quiet=False):
    """run the whole hook (animation, then home) in the emulator with real events in Roland's queue.
    Write guard: while the PC is in our code, any write outside the LCD buffer, our RAM block and the stack fails."""
    from vsemu import VSEmu
    e = VSEmu(bytes(img))
    e.stubs[ROM_DELAY] = lambda e: None
    e.stubs[0x12ED24] = lambda e: None                       # the stock call the hook replaces
    q, wi, ri = 0x5B7A34, 0x5B8034, 0x5B8035
    SP0 = 0xFFF600                                           # the real stack top
    bad = []
    orig_wb = e.wb
    def wb(a, v):
        a &= 0xFFFFFF
        if CODE <= e.pc < CODE + code_len and not (LCD <= a < LCD + 0x242 or RAM <= a < RAM_END
                                                    or e.er[7] - 64 <= a < SP0):
            bad.append((e.pc, a))
        orig_wb(a, v)
    e.wb = wb
    script = [('key', K_DOWN), ('key', K_DOWN), ('dial', 1), ('dial', 1), ('dial', 1), ('dial', -1),
              ('key', K_ENTER), ('key', K_UP), ('key', K_UP), ('key', K_UP), ('key', K_UP), ('key', K_ENTER)]
    def post(kind, v):
        w = orig_rb(wi); o = q + w * 12
        words = (1, 1, v, 0) if kind == 'key' else (2, v & 0xFFFF, 0, 0)
        for k, x in enumerate(words): orig_wb(o + 2 * k, x >> 8); orig_wb(o + 2 * k + 1, x & 0xFF)
        orig_wb(wi, (w + 1) & 0x7F)
    orig_rb = e.rb
    e.er[7] = SP0 - 0x40; e.push32(0xDEAD00); e.pc = labels['hook']
    loop, frame = labels['loop'], labels['an_wait']; shots = []; i = 0; frames = []
    while e.pc != 0xDEAD00:
        if e.pc == frame and (not frames or frames[-1][1] != e.screen()):
            frames.append((len(frames), e.screen()))
        if e.pc == loop and e.rb(wi) == e.rb(ri):
            shots.append(('after ' + (str(script[i - 1]) if i else 'start'), e.screen()))
            if i < len(script): post(*script[i]); i += 1
        e.step()
        if e.steps > 20_000_000: raise RuntimeError('stuck at %06X' % e.pc)
        e.steps += 1
    shots.append(('returned (RECORDER)', e.screen()))
    print('animation frames shown: %d, menu screens: %d, guard violations: %d %s'
          % (len(frames), len(shots), len(bad), ['%06X->%06X' % x for x in bad[:5]]))
    assert not bad, 'write outside the allowed RAM'
    if quiet: return shots, frames
    for name, s in shots:
        print('---', name)
        for row in s: print(row)
    return shots, frames


def main():
    img, code, labels = build_image()
    out = os.path.join(ROOT, 'work', 'v007')
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'os.bin'), 'wb').write(img)
    open(os.path.join(out, 'rosetta.bin'), 'wb').write(code)
    shutil.copyfile(os.path.join(out, 'os.bin'), os.path.join(out, '$SYSPRO2.VS1'))
    build(os.path.join(ROOT, 'upd', 'x_VS840EXv205'), bytes(img), out, 'rosetta')
    back, _, _ = decode(out)
    assert back[0x10000:0x100000] == img, 'decode mismatch'
    print('ok: code %d bytes at %06X, hook %06X, flash sum %08X' % (len(code), CODE, labels['hook'], flash_sum(img)))
    if '--test' in sys.argv: test(img, labels, len(code), quiet=True)


if __name__ == '__main__':
    main()
