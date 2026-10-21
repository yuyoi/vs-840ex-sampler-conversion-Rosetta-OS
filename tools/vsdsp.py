"""Rosetta DSP blocks for the VS-840EX core 0 (ESP2), checked in the esp.py cycle simulator.

Stock core 0 (boot program, 0x291 words from OS 0x1AC0C6, loader 0x113D84) reads the inputs from g[0B] g[0D] g[0F]
g[11] and writes the master pair g[C0] / g[C2] (other outputs / sends: g[96] g[98] g[8A]-g[90] g[9E]); it ends with
INT at 0x28F, no jumps. Our block sits after it (TEST_AT = 0x2C0, 32 words), so its writes to the outputs are the
last ones in every sample and win; turning the block back into the saved stock words gives the stock sound back.
i[0x44] / i[0x45] are never read or written by the stock program: the oscillator phase lives there.

Host loads words with ROM 0x5A3A (r0 = word * 4, bit 12 = core 1; er1 -> 4 bytes = ROM-order word + E byte),
which also updates the RAM image (core 0 at 0x5B3FFA).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esp
from esp import encode as E

TEST_AT, TEST_LEN = 0x2C0, 32
PH = 0x44
INPUTS = (0x0B, 0x0D, 0x0F, 0x11)
OUTPUTS = (0xC0, 0xC2, 0x96, 0x98, 0x9E)
FS = 44100


def osc_coefs(hz):
    """phase increment per sample (of 2^24) = 0x400000*a>>7 + 0x10000*b>>7 = a*32768 + b*512"""
    inc = round(hz / FS * (1 << 24))
    a = min(127, inc // 32768); b = min(127, round((inc - a * 32768) / 512))
    return a, b, (a * 32768 + b * 512) * FS / (1 << 24)


def block(tone_lvl, in_lvl, hz=440.0):
    """32 DSP-view words: saw (tone_lvl/128 of full scale) + inputs (in_lvl/64 each) -> all outputs"""
    a, b, _ = osc_coefs(hz)
    w = [0] * TEST_LEN
    w[0] = E(0x04, PH + 1, 6, 64)            # A = last sample's phase (i[PH+1] = the cell written one sample ago)
    w[1] = E(0x00, 4, 7, a)                  # A += 0x400000 * a >> 7
    w[2] = E(0x00, 3, 7, b)                  # A += 0x10000 * b >> 7
    w[5] = E(0x40, PH, 7, 0)                 # i[PH] = raw(A) (A as of word 2: 3-cycle latency), wraps = saw
    w[6] = E(0x14, PH, 7, tone_lvl)          # B = saw * tone_lvl >> 7
    for k, g in enumerate(INPUTS):
        w[7 + k] = E(0x20, g, 3, in_lvl)     # B += g[in] * in_lvl >> 6   (op 0x20, sh = 3: acc B, shift 6)
    for k, g in enumerate(OUTPUTS):
        w[13 + k] = E(0x3C, g, 7, 0)         # g[out] = sat(B) (B as of word 10)
    return w


MODES = {'TONE': (16, 0), 'THRU': (0, 32), 'BOTH': (12, 32)}


def to_bytes(words):
    """DSP-view words -> the 4-byte entries ROM 0x5A3A takes (ROM order, E byte 0)"""
    out = bytearray()
    for w in words:
        assert (w >> 23) == 0
        out += esp.dsp_to_rom(w).to_bytes(3, 'big') + b'\0'
    return bytes(out)


def stock_core0():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    b = open(os.path.join(root, 'vs840ex_v205_os.bin'), 'rb').read(); o = 0x1AC0C6 - 0x110000
    return [esp.rom_to_dsp((b[o + 4 * i] << 16) | (b[o + 4 * i + 1] << 8) | b[o + 4 * i + 2]) for i in range(0x291)]


def simulate(mode, n=400, inputs=(1000, 2000, 3000, 4000)):
    """stock core 0 + our block; returns the per-sample value written to g[C0] by our block and the stock C0"""
    prog = stock_core0() + [0] * (768 - 0x291)
    prog[TEST_AT:TEST_AT + TEST_LEN] = block(*MODES[mode])
    gram = [0] * 256
    core = esp.Core(prog, gram, name='core0')
    out = []; cur = {}
    def tr(c, pc, w):
        op, mem, sh, coef, e = esp.fields(w)
        if op in (0x38, 0x3C) and mem == 0xC0: cur[pc] = gram[(mem + c.pos) & 0xFF]
    core.trace = tr
    for s in range(n):
        for k, g in enumerate(INPUTS): gram[(g + core.pos) & 0xFF] = inputs[k]   # the codec fills the inputs
        cur.clear(); core.run_sample()
        out.append((cur.get(TEST_AT + 13), cur.get(0x235)))
    return out


if __name__ == '__main__':
    a, b, hz = osc_coefs(440); print('osc coefs', a, b, '-> %.2f Hz' % hz)
    t = simulate('TONE')
    ours = [x for x, _ in t]
    # saw: count wraps (large negative jumps) over the run -> frequency
    jumps = sum(1 for i in range(1, len(ours)) if ours[i] < ours[i - 1] - 0x40000)
    print('TONE: first', ours[:5], 'min/max', min(ours), max(ours), 'wraps in %d samples: %d (expect %.1f)'
          % (len(ours), jumps, len(ours) * hz / FS))
    th = simulate('THRU')
    print('THRU: our C0 =', th[-1][0], '(inputs 1000+2000+3000+4000, x 32/64 -> expect 5000)')
    bo = simulate('BOTH')
    print('BOTH: min/max', min(x for x, _ in bo), max(x for x, _ in bo))
