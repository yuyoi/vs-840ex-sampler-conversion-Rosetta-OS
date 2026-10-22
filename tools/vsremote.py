"""Drive the VS-840EX (Rosetta OS 0.09+) from the PC over MIDI and check its audio: hardware-in-the-loop tests.
Windows only (winmm via winmidi.py), numpy for the analysis.

Cables: PC MIDI OUT -> VS MIDI IN, VS MIDI OUT -> PC MIDI IN (replies), VS outputs -> interface inputs (records),
interface output -> VS input (only for `thru`).

usage:
  python -I tools/vsremote.py ports
  python -I tools/vsremote.py ping
  python -I tools/vsremote.py key ENTER [EXIT UP ...]      remote panel keys (names from the VS key table)
  python -I tools/vsremote.py dial +1
  python -I tools/vsremote.py read 0x110624 15
  python -I tools/vsremote.py write 0x430000 12AB34
  python -I tools/vsremote.py dspw 0 0x2C5 HHHHHHHH        one DSP word (4 bytes, ROM order + E byte)
  python -I tools/vsremote.py tone [--secs 2]              SOUND TEST > TONE, record, peak Hz / level per channel
  python -I tools/vsremote.py thru [--hz 1000]             SOUND TEST > THRU, play a tone into the VS, record
  options: --midi SUB (out), --midiin SUB, --audio SUB (record), --play SUB (playback), --rate 48000
"""
import ctypes, os, sys, time, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winmidi as wm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = ('BUSS1 BUSS2 BUSS3 BUSS4 BUSS5 BUSS6 BUSS7 BUSS8 BUSSE TR1 TR2 TR3 TR4 TR5 TR6 TR7 TR8 MODE INPUT EQ PAN EFXL '
         'AUXL SOLO MONITOR EFFECT EZ DISP UTILITY UNDO VARI UP RIGHT DOWN LEFT ENTER EXIT PUNCH LOC1 LOC2 LOC3 LOC4 '
         'LOOP SCRUB SCENE CLEAR ZERO REW FF STOP PLAY REC SHIFT FOOT').split()
KEY = {n: i for i, n in enumerate(NAMES)}


def opt(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name); v = sys.argv[i + 1]; del sys.argv[i:i + 2]; return v
    return default


def nib(v, n): return [(v >> (4 * (n - 1 - k))) & 0xF for k in range(n)]


class VS:
    def __init__(self, out_sub=None, in_sub=None):
        self.o = wm.Midi(out_sub)
        self.i = wm.MidiIn(in_sub) if in_sub != '-' else None
        print('MIDI out: %s, in: %s' % (self.o.name, self.i.name if self.i else '-'))

    def long(self, data):
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        h = wm.MIDIHDR(ctypes.addressof(buf), len(data), len(data), 0, 0, None, 0, 0)
        wm.wm.midiOutPrepareHeader(self.o.h, ctypes.byref(h), ctypes.sizeof(h))
        wm.wm.midiOutLongMsg(self.o.h, ctypes.byref(h), ctypes.sizeof(h))
        while not h.dwFlags & 1: time.sleep(0.001)
        wm.wm.midiOutUnprepareHeader(self.o.h, ctypes.byref(h), ctypes.sizeof(h))

    def sysex(self, body, timeout=2.0):
        if self.i: self.i.poll()
        self.long([0xF0, 0x7D, 0x56] + list(body) + [0xF7])
        if not self.i: return None
        end = time.time() + timeout
        while time.time() < end:
            for m in self.i.poll():
                if m[1:3] == b'\x7D\x56' and m[3] == (body[0] | 0x40): return m[4:-1]
            time.sleep(0.005)
        raise SystemExit('no reply to SysEx cmd %d (VS MIDI OUT -> PC MIDI IN connected? Rosetta menu open?)' % body[0])

    def ping(self): return bytes(self.sysex([1])).decode('ascii', 'replace')
    def read(self, addr, n):
        r = self.sysex([2] + nib(addr, 6) + nib(n, 2))
        return bytes((r[2 * k] << 4) | r[2 * k + 1] for k in range(len(r) // 2))
    def write(self, addr, data): self.sysex([3] + nib(addr, 6) + sum((nib(b, 2) for b in data), []))
    def dspw(self, core, idx, word4): self.sysex([4, core] + nib(idx, 3) + sum((nib(b, 2) for b in word4), []))
    def key(self, k, gap=0.12):
        code = KEY[k] if isinstance(k, str) else k
        self.o.send(0x9F, code, 0x40); time.sleep(0.02); self.o.send(0x8F, code, 0); time.sleep(gap)
    def dial(self, d, gap=0.12): self.o.send(0xBF, 1, 64 + d); time.sleep(gap)
    def home(self):
        """from anywhere in Rosetta to the home screen, cursor on the first row"""
        for _ in range(3): self.key('EXIT')
        for _ in range(6): self.key('UP')
    def sound(self, row):
        """SOUND TEST page, select row (0 TONE, 1 THRU, 2 BOTH, 3 OFF)"""
        self.home(); self.key('ENTER')
        for _ in range(4): self.key('UP')
        for _ in range(row): self.key('DOWN')
        self.key('ENTER')
    def close(self):
        self.o.close()
        if self.i: self.i.close()


def record(audio, rate, secs, play=None, play_hz=0):
    r = wm.Rec(audio, rate)
    p = wm.Play(play, rate) if play else None
    if p: p.tone(play_hz, int(secs * 1000) + 200, level=0.25)
    end = time.time() + secs
    while time.time() < end: r.poll(); time.sleep(0.02)
    path = os.path.join(ROOT, 'work', 'cap.wav'); r.stop(path)
    if p: p.close()
    return path


def analyse(path):
    import numpy as np
    w = wave.open(path); fs = w.getframerate(); ch = w.getnchannels()
    x = np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(float).reshape(-1, ch) / 32768.0
    x = x[len(x) // 4:]                                       # skip the start
    out = []
    for c in range(ch):
        s = x[:, c] - x[:, c].mean()
        rms = float(np.sqrt((s ** 2).mean())) or 1e-9
        spec = np.abs(np.fft.rfft(s * np.hanning(len(s))))
        f = float(np.fft.rfftfreq(len(s), 1 / fs)[spec[1:].argmax() + 1])
        out.append((c, f, 20 * np.log10(rms)))
    return out


def main():
    rate = int(opt('--rate', '48000')); audio = opt('--audio', 'focusrite'); play = opt('--play', None)
    secs = float(opt('--secs', '2')); hz = float(opt('--hz', '1000'))
    mo, mi = opt('--midi'), opt('--midiin')
    a = sys.argv[1:]
    if not a or a[0] == 'ports':
        print('MIDI out:', wm.midi_outs()); print('MIDI in:', wm.midi_ins()); print('audio in:', wm.wave_ins())
        print('audio out:', wm.wave_outs()); return
    vs = VS(mo, mi)
    try:
        c = a[0]
        if c == 'ping': print(vs.ping())
        elif c == 'key':
            for k in a[1:]: vs.key(k.upper())
        elif c == 'dial': vs.dial(int(a[1]))
        elif c == 'read':
            d = vs.read(int(a[1], 0), int(a[2], 0)); print(d.hex(' '), '|', d)
        elif c == 'write': vs.write(int(a[1], 0), bytes.fromhex(a[2])); print('ok')
        elif c == 'dspw': vs.dspw(int(a[1]), int(a[2], 0), bytes.fromhex(a[3])); print('ok')
        elif c in ('tone', 'thru'):
            print('VS:', vs.ping())
            vs.sound(0 if c == 'tone' else 1); time.sleep(0.3)
            path = record(audio, rate, secs, play if c == 'thru' else None, hz)
            vs.sound(3)
            for ch, f, db in analyse(path):
                print('input ch %d: peak %.1f Hz, %.1f dBFS rms' % (ch + 1, f, db))
            print('expect: %s' % ('~440 Hz saw' if c == 'tone' else '%.0f Hz from the PC' % hz), '| wav:', path)
        else: print(__doc__)
    finally:
        vs.close()


if __name__ == '__main__':
    main()
