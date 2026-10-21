"""VS-840EX memory map on top of the SP-808 H8S emulator (h8emu.Emu).

  0x000000-0x01FFFF  mask ROM (vs840ex_bootrom.bin)
  0x100000-0x10FFFF  flash user area (FF here)
  0x110000-0x1FFFFF  OS image
  0x400000-0x7FFFFF  DRAM (LCD shadow buffer at 0x403200, 17 rows x 0x22 bytes)
  0xA00000/1         LCD controller: command+status / data (status bit 7 = busy, always ready here)
  0xFFF000-          on-chip RAM + registers (plain memory)

    e = VSEmu(); e.call(0x2E36, setup=...)  # runs ROM and OS code natively, no stubs needed for pure routines
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h8emu

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LCD_BUF, LCD_ROWS, LCD_STRIDE = 0x403200, 17, 0x22


class VSEmu(h8emu.Emu):
    def __init__(self, os_image=None, rom=None):
        os_image = os_image or open(os.path.join(ROOT, 'vs840ex_v205_os.bin'), 'rb').read()
        rom = rom or open(os.path.join(ROOT, 'vs840ex_bootrom.bin'), 'rb').read()
        super().__init__(b'\xff' * 0x10000 + os_image)
        self.boot = bytearray(rom) + bytearray(0x100000 - len(rom))
        self.code_lo, self.code_hi = 0, 0x200000
        self.lcd_log = []                                   # ('c'|'d', value) writes to the controller

        self.io = {}                                        # other chip selects (GA, IDE, DSP, SCSI): plain memory
        self.io_reads = {}                                  # address -> fixed read value (e.g. IDE status 0x50)

    def rb(self, a):
        a &= 0xFFFFFF
        if a == 0xA00000: return 0x00                       # never busy
        if a == 0xA00001: return 0x00
        if a in self.io_reads: return self.io_reads[a]
        if 0x200000 <= a < 0x400000 or 0x600000 <= a < 0x800000 or 0x800000 <= a < 0xA00000 \
                or 0xA00000 <= a < 0xFFF000:
            return self.io.get(a, 0)
        return super().rb(a)

    def wb(self, a, v):
        a &= 0xFFFFFF
        if a in (0xA00000, 0xA00001):
            self.lcd_log.append(('c' if a == 0xA00000 else 'd', v & 0xFF)); return
        if 0x200000 <= a < 0x400000 or 0x600000 <= a < 0xFFF000:
            self.io[a] = v & 0xFF; return
        if 0x100000 <= a < 0x200000: return                 # flash writes (command sequences) ignored
        return super().wb(a, v)

    def step(self):
        # 01 41 0x yy = ORC/XORC/ANDC/LDC #yy,EXR (interrupt mask in EXR): not modelled, skip
        if self.rb(self.pc) == 0x01 and self.rb(self.pc + 1) == 0x41 and self.rb(self.pc + 2) in (4, 5, 6, 7):
            self.pc += 4; return
        return super().step()

    def screen(self):
        """136 x 32 dot matrix as a list of 32 strings ('#' = on)"""
        rows = self.lcd()
        return [''.join('#' if rows[x >> 3][2 + y] & (0x80 >> (x & 7)) else '.' for x in range(LCD_ROWS * 8))
                for y in range(32)]

    def lcd(self):
        """shadow buffer as LCD_ROWS rows of LCD_STRIDE bytes"""
        o = LCD_BUF - h8emu.RAM_LO
        return [bytes(self.ram[o + r * LCD_STRIDE:o + (r + 1) * LCD_STRIDE]) for r in range(LCD_ROWS)]
