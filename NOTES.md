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
