"""Write a patched VS card image back to the card raw, without Windows mounting it in between.

lock + dismount the volume -> read the whole card -> it must equal <expected.img> (else abort)
-> write only the 512-byte sectors that differ in <new.img> -> read back and compare all
-> eject the media, so Windows can't remount it and write System Volume Information again.

usage (needs an elevated prompt if Windows refuses raw writes):
  python -I tools/cardwrite.py J <expected.img> <new.img>
  python -I tools/cardwrite.py J - <new.img> <backup.img>    whatever is on the card now is saved to backup.img
                                                              first, then replaced (VS + Windows changes discarded)
"""
import ctypes, sys
from ctypes import wintypes as W

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateFileW.restype = W.HANDLE
GENERIC_RW = 0xC0000000; SHARE_RW = 3; OPEN_EXISTING = 3
FSCTL_LOCK_VOLUME = 0x90018; FSCTL_DISMOUNT_VOLUME = 0x90020; FSCTL_UNLOCK_VOLUME = 0x9001C
IOCTL_STORAGE_EJECT_MEDIA = 0x2D4808; IOCTL_STORAGE_MEDIA_REMOVAL = 0x2D4804


def ioctl(h, code):
    n = W.DWORD()
    if not k32.DeviceIoControl(h, code, None, 0, None, 0, ctypes.byref(n), None):
        raise OSError(ctypes.get_last_error(), 'ioctl %X' % code)


def seek(h, off):
    if not k32.SetFilePointerEx(h, ctypes.c_longlong(off), None, 0): raise OSError(ctypes.get_last_error(), 'seek')


def read(h, off, n):
    seek(h, off); buf = ctypes.create_string_buffer(n); got = W.DWORD()
    if not k32.ReadFile(h, buf, n, ctypes.byref(got), None): raise OSError(ctypes.get_last_error(), 'read @%X' % off)
    return buf.raw[:got.value]


def write(h, off, data):
    seek(h, off); got = W.DWORD()
    if not k32.WriteFile(h, data, len(data), ctypes.byref(got), None) or got.value != len(data):
        raise OSError(ctypes.get_last_error(), 'write @%X' % off)


def read_all(h, size):
    out = bytearray(); step = 1 << 20
    for off in range(0, size, step): out += read(h, off, min(step, size - off))
    return bytes(out)


def main():
    letter, exp_p, new_p = sys.argv[1].rstrip(':\\'), sys.argv[2], sys.argv[3]
    new = open(new_p, 'rb').read()
    exp = None if exp_p == '-' else open(exp_p, 'rb').read()
    assert len(new) % 512 == 0 and (exp is None or len(exp) == len(new))
    h = k32.CreateFileW('\\\\.\\%s:' % letter, GENERIC_RW, SHARE_RW, None, OPEN_EXISTING, 0, None)
    if h in (None, W.HANDLE(-1).value): raise SystemExit('open failed: %d (run elevated?)' % ctypes.get_last_error())
    ioctl(h, FSCTL_LOCK_VOLUME); ioctl(h, FSCTL_DISMOUNT_VOLUME)
    print('locked + dismounted')
    cur = read_all(h, len(new))
    if exp is None:
        open(sys.argv[4], 'wb').write(cur); exp = cur
        print('backup of the card as it was:', sys.argv[4])
    if cur != exp:
        bad = [i for i in range(0, len(exp), 512) if cur[i:i + 512] != exp[i:i + 512]]
        ioctl(h, FSCTL_UNLOCK_VOLUME)
        raise SystemExit('card != expected image, %d sectors differ, first %s - nothing written' % (len(bad), [hex(x) for x in bad[:8]]))
    secs = [i for i in range(0, len(new), 512) if new[i:i + 512] != exp[i:i + 512]]
    runs = []
    for s in secs:
        if runs and runs[-1][1] == s: runs[-1][1] = s + 512
        else: runs.append([s, s + 512])
    for a, b in runs: write(h, a, new[a:b])
    print('wrote %d sectors in %d runs' % (len(secs), len(runs)))
    back = read_all(h, len(new))
    if back != new: raise SystemExit('VERIFY FAILED - card left locked, do not remove, tell Claude')
    print('verify ok: card == new image')
    try:
        ioctl(h, IOCTL_STORAGE_EJECT_MEDIA); print('ejected - pull the card now')
    except OSError as e:
        print('eject failed (%s) - card stays locked until this exits; pull it before Windows remounts' % e)
    k32.CloseHandle(h)


if __name__ == '__main__':
    main()
