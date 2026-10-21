# VS-840EX Rosetta OS — notes

**TL;DR**
- Target: **VS-840EX**. All mods start from `vs840ex_v205_os.bin`.
- Same platform as the SP-808: **H8S/2655 CPU + TC170C140 (Roland ESP2) DSP**. The sp808 tools are copied into `tools/`.
- The OS image runs at **0x110000**, 0xF0000 bytes, and ends with a flash sum at 0x1FFF00.
- Encoder and decoder are proven: re-encoding both stock images reproduces all 16 Roland SMFs byte for byte.
- **Rosetta OS 0.01 WORKS ON HARDWARE (2026-10-21):** installed from CF via `$SYSPRO2.VS1`; test mode shows `ROSETTA OS 0.01` and flash sum `04947642` (= ours). The boot after the update showed "Setup ERROR" (IDE drive didn't answer the identify at 0x12701C) once (cause unknown; first suspect the CF waking slowly).

## Files
| Path | What |
|---|---|
| `vs840ex_v205_os.bin` | EX OS 2.05 (Mar 21 2001), image for 0x110000-0x1FFFFF |
| `vs840_v105.bin` | plain VS-840 OS 1.05, same layout (= Roland's `$SYSPRO2.VS1`) |
| `upd/`, `docs/` | Roland downloads + PDFs, untouched |
| `tools/decode_upd.py` | SMFs -> image (page 01 = image offset 0) |
| `tools/make_smf.py` | image -> 8 SMFs, using Roland's files as the template, all checksums recomputed |
| `tools/build_v001.py` | Rosetta OS 0.01 build -> `work/v001/` (rosetta-1..8.mid, os.bin, `$SYSPRO2.VS1`) |
| `tools/send_smf.py` | plays the 8 SMFs to a MIDI out (winmm SysEx, the files' own timing, ~14 min) |
| `tools/vscard.py`, `tools/cardwrite.py` | VS card image check / repair / add file, raw write-back |
| `tools/h8sdis.py xref.py h8asm.py h8emu.py esp.py` | copied from sp808/tools. `xref.py img out.pkl [base]`, base defaults to 0x110000 |

## Memory map (service notes Feb 1998 + image)
- 0x000000-0x0FFFFF CS0 "EXT ROM" / internal mask ROM. **The OS calls ~458 routines here** (0x2E36 = print string at row/col, 0x296A / 0x2BCE = print formatted, 0x4A6E = memcpy, 0x4C4E = delay, ...). Not dumped yet.
- 0x100000-0x10FFFF: flash boot block (SMF page 00, never in an update). Contents unknown.
- **0x110000-0x1FFFFF: OS image.** 0x110000 = 64 `JMP @abs24` trampolines (vector N -> 0x110000+4N). 0x110600 = header `NM_SYSTEM`, `FLASH<time>/<date>`, version string at **0x110624**, disk-ID field at 0x11064A (31 bytes).
- **0x1FFF00: u32 flash sum** = 32-bit sum of bytes 0x110000..0x1FFEFF minus the 31 bytes at 0x11064A. Checked by the test-mode version screen (0x113F10..0x114070, "Bad FLASH!!"). Verified on 1.05 + 2.05.
- RAM 0x400000+ (H8S internal 0xFFxxxx too); updater buffers at 0x5E5FE0-0x5E6080.
- CS1/CS7 gate array, CS2 16 Mbit DRAM, CS3 IDE (Zip), CS4 DSP, CS5 LCD, CS6 SCSI (VS4S-1). IRQ1 DSP, IRQ2 SCSI, IRQ3 IDE.
- Parts: CPU HD6472655F/HD6432655F, flash LH28F800SUT-70, DSP TC170C140, DRAM HM5118160J + HM514800CJ, codec AK4520A, S/PDIF TC9271F, sub-MCU uPD78L005.
- Codenames: `NM50D` = VS-840 (FAT volume label "NM50D 0.004"), `ST25B` = VS-880. The disk filesystem is FAT12/16 with a "Roland  " OEM name.

## Update paths
- **SMF (MIDI):** `F0 41 00 00 0C 12 a0..a3 body ck F7`. Data at `00 00 01 PP`: 4 nibbles offset + 224 bytes 7-bit packed -> 196 bytes. Control messages:
  - `01 02` part start/end
  - `01 03` version text, formatted `"<ver>\0 <date> <time>\0"` (37 bytes). Parts 2-8 must match part 1 ("MID Version Err"); it is not compared with the running OS.
  - `01 01` end: (~sum(image)) & 0x7F ("Total ChkSUM Err")
  - Each message has a Roland checksum ("MID CheckSUM Err").
- **The MIDI receiver is in the OS** (0x16AC00-0x16C000, "Receive MIDI-EX?" at 0x16BF46), entered with MODE+INPUT+ENTER at power-on. So **a build that crashes before that point has no MIDI recovery** unless the boot block or mask ROM has its own. Keep early-boot code untouched until a ROM dump says otherwise.
- **Disk:** the OS knows `$SYSPROG.VS1`, `$SYSPRO2.VS1`, `$USERDAT.VS1`, `$USERID.VS1`. For the plain 840, `$SYSPRO2.VS1` = the raw image ("Update Sysprg?" at power-on). **Confirmed on the EX 2026-10-21** (v0.01 installed this way). **Never copy files to a VS card with Windows** (see VS cards below).
- Test mode: MONITOR SEL + SOLO at power-on. It shows the version string and checks the flash sum. There is also "Developer MODE!" (0x1A8AE7, used at 0x11AC24) and an easter-egg string "Fumika!".

## VS cards (Zip / CF / SD)
- Boot sector OEM `RolandBS`, label `NM50D 0.004`, FAT16, 512-byte sectors, 128 sectors per cluster (64 KB), 1 reserved sector, 2 FATs, 512 root entries. A 245 MB CF card has 3919 clusters.
- **Under 4085 clusters, Windows takes it as FAT12.** Multi-cluster files read as corrupt, and on mount Windows creates `System Volume Information` (a folder + WPSettings.dat + IndexerVolumeGuid). That writes 3 FAT12 entries (1.5 bytes each) into the FAT16 table and the folder/file data into clusters the takes own.
- Repair on the 2026-10-21 card: FAT16 entries 40/73/106 got a high byte of FF (restore 00); entries 41/74/107 lost their low nibble. The nibbles were solved uniquely (41->48, 74->80, 107->112): every used cluster has one predecessor and all four takes are 168 clusters. About 64 KB of take audio under clusters 54/98/142 is overwritten for good.
- Takes are recorded 4 at a time with interleaved chains. Song folders `SONGnnnn.VS1` hold `TAKEnnnn.VR8`, `SONG.VR8`, `EVENTLS0.VR8`, `MIXER/MARKER0/EFFECT/SYNCTRK/TRKNAME.VS1`.
- Safe route: read the volume raw (`\\.\J:` works without admin), patch the image with `vscard.py`, write it back with `cardwrite.py` (lock + dismount, compare with the backup, write the changed sectors, read back, eject).

## Status / next
1. **HW test v0.01:** flash `work/v001` (MIDI via send_smf.py, or `$SYSPRO2.VS1` on a VS-formatted CF/Zip). Then test mode should show `ROSETTA OS 0.01` with no "Bad FLASH!!".
2. Dump the mask ROM + boot block to disk (SP-808 trick: call the OS save-file routine on 0x000000-0x10FFFF), then load them into h8emu.
3. Map the LCD (CS5, 0x2E36 print API), key scan, normal boot screen -> own UI + Hex Girl boot logo.
4. DSP: one ESP2 (CS4), via sp808 esp.py -> own FX, looper/sampler, DDS synth.

## Power-on key combos (scan 0x11AAD8, key names 0x1F6F2E)
Key codes: 09-10 TR1-8, 11 MODE, 12 INPUT, 13 EQ, 14 PAN, 15 EFXL, 16 AUXL, 17 SOLO, 18 MONITOR, 19 EFFECT, 1A EZ, 1B DISP, 1C UTILITY, 1D UNDO, 1E VARI, 1F UP, 20 RIGHT, 21 DOWN, 22 LEFT, 23 ENTER, 24 EXIT, 25 PUNCH, 26-29 LOC1-4, 2A LOOP, 2B SCRUB, 2C SCENE, 2D CLEAR, 2E ZERO, 2F REW, 30 FF, 31 STOP, 32 PLAY, 33 REC, 34 SHIFT, 35 FOOT.
Boot bitmask: b0 MONITOR, b1 SOLO, b2 INPUT, b3 EQ, b4 EFXL, b5 AUXL, b6 RIGHT, b7 REC, b8-b11 TR1-4, b12 MODE, b13 ENTER, b14 PLAY, b15 PAN.

| mask | keys | does |
|---|---|---|
| 0003 | MONITOR + SOLO | test mode (0x184258 r0=?) |
| 001C / 002C / 8028 / 8012 | INPUT+EQ+EFXL / INPUT+EQ+AUXL / EQ+AUXL+PAN / SOLO+EFXL+PAN | other test modes (0x184258) |
| 3004 | MODE + INPUT + ENTER | receive MIDI-EX (OS update over MIDI, 0x16BF24) |
| 3008 | MODE + ENTER + EQ | send MIDI-EX (0x16BD66) |
| 1044 | MODE + RIGHT + INPUT | "Developer MODE!" |
| 41C0 | PLAY + REC + TR1 + RIGHT | SYS&USR FILE Wr ($SYSPROG.VS1 = flash 0x100000, 1 MB) |
| 4180 | PLAY + REC + TR1 | SYSTEM FILE Wr ($SYSPRO2.VS1 = 0x110000, 0xF0000). **0.02: ROM dump, ROMDUMP.VS1 = 0x000000, 1 MB** |
| 4280 / 4480 / 4880 | PLAY + REC + TR2 / TR3 / TR4 | SYSTEM FILE Del / USER FILE Wr ($USERDAT.VS1 = 0x100000, 64 KB) / USER FILE Del |
| 2F00 | ENTER + TR1-4 | WRITE FLAG ? |
| 0180 | REC + TR1 | Force HD MODE |
| 2040 / 2001 | ENTER + RIGHT / ENTER + MONITOR | VerupFat RESERVE / RELEASE |
| 0440 / 0240 | TR3 + RIGHT / TR2 + RIGHT | Zip Compare Test / Zip Verify Copy |
| 2080 | ENTER + REC | Force Init |

File writer: 0x12AFAA(r0l drive, e0 0xFFFF, er1 name "NAME    EXT", stack: addr, len); writes len (64 KB multiple) from addr in 64 KB chunks.
Flash map: 0x100000-0x10FFFF = user area ($USERDAT), 0x110000-0x1FFFFF = OS. No flash boot block: the boot code is the CPU's ROM below 0x100000.

## Boot ROM (dumped 2026-10-21 with v0.03, `vs840ex_bootrom.bin`, Roland code, not in git)
- ROMDUMP.VS1 = 1 MB from 0x000000: **0x00000-0x1FFFF = the H8S/2655's 128 KB mask ROM** ("NMCPUMASK 11:45:23/Feb 24 1998"); 0x20000-0xFFFFF = empty CS0 bus (mostly FF + noise).
- Vectors: reset -> 0x500; every other vector -> 0x110020 + 4n (the OS trampoline table).
- Reset path 0x6D2: init -> **0x79C6 flash check** -> `jmp 0x110700` (OS entry). No key combos in the ROM.
- 0x79C6:
  - if an external ROM at 0x20600 carries "NM_SYSTEM" and a different build time than the flash -> version up from it (dev/service EPROM, absent here).
  - else if the flash header at 0x110600 != "NM_SYSTEM" -> **"BAD FLASH!!"**, 10 s, drive init, then **0x7652 = version up from raw disk sectors**: header sector LBA 0x2F7FF must start with "NM_SYSTEM", pages 1..15 come from LBA 0x2F800 + n*0x80 (64 KB each) -> flash 0x100000 + n*64K. Fails -> "Can't VersionUp!" (hang).
  - the flash sum at 0x1FFF00 is NOT checked by the ROM (only by the OS test screen).
- So the ROM recovery only runs when the header is broken. **An OS build with a good header that crashes has no ROM rescue.** Rule: keep every patch after the OS's own update-file check (combo routine 0x11A9D2 -> 0x11B3DA -> 0x1164C6), so a disk update ("Version up ?") always stays reachable.
- The raw-LBA layout matches the OS dev combos "VerupFatRESERVE/RELEASE" (they reserve those clusters) and the "VS-840 Version up DISK ID" field at 0x11064A.
- ROM API used by the OS: 0x2E36 print string (r0 col, e0 row, er1 str), 0x296A print formatted, 0x4A6E memcpy (er0 dst, er1 src, len on stack), 0x4A4E memset, 0x4C4E delay ms, 0x2186 strcmp, 0x752C disk read (er0 LBA, r1l count, dst on stack), 0x6FD0 flash write page.

## LCD (decoded 2026-10-21)
- Controller at CS5: 0xA00000 = command/status (bit 7 busy), 0xA00001 = data. Init (ROM 0x2594): 01 02 13 08 05 20 40 80 FF; address = 0x20|row (17) + 0x80|col (34). Only the ROM touches it; an interrupt streams the shadow buffer.
- **Shadow buffer 0x403200, 17 strips x 0x22 bytes.** Strip g = x 8g..8g+7; bytes 2..33 = dot rows 0..31 (MSB = left); bytes 0..1 probably the segment part (time digits, meters). Dot matrix = **136 x 32**. ROM 0x268A clears it (0x242 bytes).
- Text: ROM 0x2E36 print(r0 col, e0 row, er1 str) uses 6x8 cells -> 4 lines x 22 chars.
- Bitmaps: ROM 0x4106 blit(r0h y?, r0l x, r1h h-1, r1l w-1, stack src); source = rows of ceil(w/8) bytes, MSB left.
- **Boot splash** = 0x113DC0 (called from the main boot at 0x11AA4C, right after LCD init + clear): blit 136x32 from **0x1B57EF** (544 bytes). Second small bitmap 0x1B56AF (320 bytes) at x=0x3B from 0x113DDA (called from 0x113EE4).
- Main boot = 0x11A9D2 (from the OS entry 0x110700 -> 0x1108E6): init, LCD, splash, 500 ms key-combo window, combos, update-file check 0x11B3DA, then the main UI.
- tools/vsemu.py = VS memory map on h8emu (ROM + OS + LCD regs); runs ROM routines like 0x2E36 natively. A full boot stops at LCD waits that need interrupts (0x42B0 waits for 0xFFF88C == 4).

## Events, RAM, the Rosetta home hook (0.06)
- Event queue: ring of 128 x 12 bytes at 0x5B7A34, write index 0x5B8034, read index 0x5B8035. 0x11D3F8(dst on stack) pops one (empty -> type 0); 0x11D44E posts (12-byte event on the stack); 0x11D4CC flushes.
- Event = w type, w a, w b, w c, l timestamp. **Type 1 = panel key {a = 1 press, b = key code (+ shift offsets 0x5B7926/0x5B7928)}** (scanner 0x11C6E2); **type 2 = dial {a = signed delta x accel}** (encoder IRQ 0x11C916 reads GA 0x200020 high byte).
- Stock main loop 0x11B588: pops an event, dispatches by type (1 0x14E84E, 2 0x177898, 3 0x15EEC6, 4 0x163AF6), then 0x117D48 (the huge hand-written screen switch). Housekeeping each pass: 0x142A20, 0x177612, 0x13E6B6, 0x115AE6.
- RAM: init data 0x5B58E4 (from flash 0x1F6EEE, 0x11BC), bss 0x5B6AA0-0x5EF32A, heap 0x5EF32A-0x5FFFFF (cleared at boot). Low DRAM: LCD 0x403200, disk sector buffer 0x403464 (64 KB), serial rings 0x401200 + n*0x800, big buffers from 0x413A8C. **On-chip 0xFFDC00-0xFFEBFF is unused (only stack depth); Rosetta's variables live at 0xFFDC00.**
- Free flash: 0x1F80AA-0x1FFEFF (~32 KB). Rosetta code at 0x1F9000.
- **UI rule (user): the folder-tab bar is for the home screen only; pages entered from it use the full 32 px (no top bar).**
- **0.06 hook:** 0x11B588 `mov.w @er5,r0; cmp.w #3,r0` -> `jsr hook; nop`. hook runs home() once per power-on (magic 'RSTA' at 0xFFDC00), then redoes the 2 instructions; rts keeps the CCR for the following bne. home saves the LCD buffer, runs its own menu on Roland's event queue, restores the buffer on RECORDER.

## DSP (ESP2 TC170C140) host interface (found 2026-10-21 by tracing the init in vsemu)
- **Same host port scheme as the SP-808, at CS4 0x800000:** program/coefficient window 0x800000 + 4*i (4 bytes per
  word, ~768 words), mode latch **0x802003** (bits 1-0: 0 raw word write, 1 coefficient write; SP-808: 0xC02003),
  status/busy read at **0x800003** before each write.
- No code has the constant 0x80xxxx: the ROM DSP routines read the port addresses from pointers in the ROM at
  0x117A (latch/window base) and 0x117E (status), and keep a shadow of the port bytes at RAM 0x5B57FE.
- ROM DSP API (OS call counts): 0x4FF6 (699, parameter/coefficient write), 0x5514 (54), 0x5E78 (52), 0x4DCA (4,
  from the effect code 0x17BDCE..: latch/mode write), 0x4E10 (uses the two **768-word RAM images 0x5B3FFA and
  0x5B4BFA**, 0xC00 bytes each).
- 0x12D7FC (boot, mixer init) writes 86 raw words + coefficients (644 raw + 352 coefficient byte writes); the full
  program load happens elsewhere (effect/patch load around 0x17BDxx and 0x133690).
- DSP program tables in the OS: 4-byte entries = 3-byte ESP2 word (esp.py ROM order) + a tag byte (00 / 0C / 01),
  around 0x1E6000-0x1F6000; parameter definition pointer tables at 0x1D1A36, 0x1D9CC4 ... (effect algorithms).
- Next: capture the full 768-word image (RAM 0x5B3FFA after the patch load) and decode it with esp.py: find the audio
  inputs/outputs (codec AK4520A, GUITAR IN, INPUTS, MASTER OUT) and the external delay RAM (HM514800, 4 Mbit).

## Direction (user, 2026-10-21): no recorder, the VS becomes a sampler/synth
- Rosetta takes over the whole ESP2 (the SP-808 KEYS sampler + DDS-DSP synth programs are the same instruction set).
- DSP-RAM sampling = short (~5-6 s total in 4 Mbit) but instant / pitched / polyphonic; long samples later via disk.
- Menu: SAMPLER / SYNTH / FX / SYSTEM; the stock VS stays reachable only as a hidden SYSTEM entry (recovery/debug).
- **Two ESP2 cores, exactly like the SP-808:** core 0 window 0x800000, core 1 window 0x801000, latch 0x802003
  (SP-808: 0xC00000 / 0xC01000 / 0xC02003). RAM images: 0x5B3FFA = core 0, 0x5B4BFA = core 1 (the ROM picks by a
  flag bit). The init 0x12D7FC writes 996 bytes to core 0, 2200 to core 1, 176 latch writes. On the SP-808 only
  core 1 reaches the external delay RAM; expect the same here (HM514800, 4 Mbit). The SP-808 KEYS / DDS / MFX DSP
  programs (keysdsp.py, mfxdsp.py) are written for this chip and should port with new I/O addresses.

## Stock DSP programs and I/O (2026-10-22)
- Boot program loader 0x113D84: 0x291 words per core, core 0 from OS 0x1AC0C6, core 1 from 0x1ACB0E (4-byte
  entries), via ROM 0x5A3A. Test-mode loader 0x18227C: 0x300 words, core 0 0x1D821A, core 1 0x1D8E1A (AUDIO check).
- ROM 0x5A3A = write one DSP word: r0 = byte offset (bit 12 = core 1), er1 -> 4 bytes (ROM order + E); waits on the
  status 0x800003 bit 7, writes the RAM image (0x5B3FFA / 0x5B4BFA) and the chip. ROM 0x4DCA(r0 = n) writes latch
  shadow byte 0x5B57FE + n to 0x802000 + n (latch 0x802003: shadow 0x5B5801, bit 0 = coefficient mode).
  ROM pointers: 0x1176 = 0x800000, 0x117A = 0x802000, 0x117E = 0x800003.
- **Core 0 I/O:** inputs g[0B] g[0D] g[0F] g[11] (4 channels), master g[C0] / g[C2]; other outputs / sends g[96]
  g[98] g[8A]-g[90] g[9E]. Core 1 reads g[17] g[19] g[41] g[43] (sends?), writes g[80] g[82] g[A2]-g[AC].
  Stock core 0 ends with INT at 0x28F, no jumps; i[44]/i[45] are free.
- **0.08 SOUND TEST** (tools/vsdsp.py, simulated in esp.py): a 32-word block at core-0 word 0x2C0 = saw 440 Hz
  (-18 dB) and/or the 4 inputs at half gain -> every output candidate; OFF restores the saved stock words.
