"""Play update SMFs (SysEx only) to a MIDI out port with the files' own timing, like a sequencer would.

VS-840EX side: hold MODE + INPUT + ENTER at power-on -> "Receive MIDI-EX?" -> YES -> "Now Waiting...",
then run this. After the 8th file the unit asks "Update SysPRG ?" / "Version Up?" -> YES.

usage: python -I tools/send_smf.py <folder with the 8 .mid files> [port substring]   (default: focusrite/scarlett)
       python -I tools/send_smf.py --list
"""
import ctypes, glob, os, sys, time
from ctypes import wintypes as W

wm = ctypes.WinDLL('winmm')


class MIDIOUTCAPS(ctypes.Structure):
    _fields_ = [('wMid', W.WORD), ('wPid', W.WORD), ('vDriverVersion', W.UINT), ('szPname', W.WCHAR * 32),
                ('wTechnology', W.WORD), ('wVoices', W.WORD), ('wNotes', W.WORD), ('wChannelMask', W.WORD),
                ('dwSupport', W.DWORD)]


class MIDIHDR(ctypes.Structure):
    pass
MIDIHDR._fields_ = [('lpData', ctypes.c_void_p), ('dwBufferLength', W.DWORD), ('dwBytesRecorded', W.DWORD),
                    ('dwUser', ctypes.c_size_t), ('dwFlags', W.DWORD), ('lpNext', ctypes.POINTER(MIDIHDR)),
                    ('reserved', ctypes.c_size_t), ('dwOffset', W.DWORD), ('dwReserved', ctypes.c_size_t * 8)]
MHDR_DONE = 1


def midi_outs():
    out = []
    for i in range(wm.midiOutGetNumDevs()):
        c = MIDIOUTCAPS(); wm.midiOutGetDevCapsW(i, ctypes.byref(c), ctypes.sizeof(c)); out.append(c.szPname)
    return out


def vlq(b, i):
    v = 0
    while True:
        c = b[i]; i += 1; v = (v << 7) | (c & 0x7F)
        if c < 0x80: return v, i


def events(path):
    """-> list of (seconds, sysex bytes incl. F0 .. F7). Type 0 SMF, SysEx + tempo meta only (what Roland ships)."""
    b = open(path, 'rb').read()
    assert b[:4] == b'MThd'
    div = int.from_bytes(b[12:14], 'big'); assert div < 0x8000
    i = 14; assert b[i:i + 4] == b'MTrk'
    end = i + 8 + int.from_bytes(b[i + 4:i + 8], 'big'); i += 8
    tempo, t, out = 500000, 0.0, []
    while i < end:
        d, i = vlq(b, i); t += d * tempo / div / 1e6
        st = b[i]; i += 1
        if st == 0xF0:
            n, i = vlq(b, i); out.append((t, b'\xF0' + b[i:i + n])); i += n
        elif st == 0xFF:
            typ = b[i]; n, i = vlq(b, i + 1)
            if typ == 0x51: tempo = int.from_bytes(b[i:i + 3], 'big')
            i += n
            if typ == 0x2F: break
        else:
            sys.exit('unexpected status %02X in %s' % (st, path))
    return out


def main():
    names = midi_outs()
    if sys.argv[1] == '--list':
        for i, n in enumerate(names): print(i, n)
        return
    files = sorted(glob.glob(os.path.join(sys.argv[1], '*.mid')), key=lambda p: int(p.rsplit('-', 1)[1].split('.')[0]))
    assert len(files) == 8, files
    subs = [sys.argv[2]] if len(sys.argv) > 2 else ['focusrite', 'scarlett']
    idx = next((i for s in subs for i, n in enumerate(names) if s.lower() in n.lower()), None)
    if idx is None: sys.exit('no MIDI out matching %s in %s' % (subs, names))
    evs = [events(f) for f in files]
    total = sum(e[-1][0] for e in evs)
    print('port: %s, %d files, %d SysEx, ~%.0f s' % (names[idx], len(files), sum(map(len, evs)), total))
    h = W.HANDLE()
    r = wm.midiOutOpen(ctypes.byref(h), idx, 0, 0, 0)
    if r: sys.exit('midiOutOpen failed: %d (port in use by another program?)' % r)
    try:
        for f, ev in zip(files, evs):
            print('sending', os.path.basename(f), end='', flush=True)
            t0 = time.perf_counter()
            for k, (t, msg) in enumerate(ev):
                while time.perf_counter() - t0 < t: time.sleep(0.001)
                buf = ctypes.create_string_buffer(msg, len(msg))
                hd = MIDIHDR(lpData=ctypes.cast(buf, ctypes.c_void_p), dwBufferLength=len(msg), dwBytesRecorded=len(msg))
                wm.midiOutPrepareHeader(h, ctypes.byref(hd), ctypes.sizeof(hd))
                r = wm.midiOutLongMsg(h, ctypes.byref(hd), ctypes.sizeof(hd))
                if r: sys.exit('\nmidiOutLongMsg failed: %d' % r)
                while not hd.dwFlags & MHDR_DONE: time.sleep(0.0005)
                wm.midiOutUnprepareHeader(h, ctypes.byref(hd), ctypes.sizeof(hd))
                if k % 100 == 0: print('.', end='', flush=True)
            print(' done')
    finally:
        wm.midiOutClose(h)
    print('all 8 sent. On the unit: answer YES to the update question, then power cycle when told.')


if __name__ == '__main__':
    main()
