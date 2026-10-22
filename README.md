<p align="center"><img src="assets/rosetta_vs840_boot.gif" width="560" alt="Rosetta OS boot animation and home menu on the VS-840EX LCD (emulator render)"></p>

<p align="center"><a href="https://discord.gg/R3CQkFdRtf"><img src="https://img.shields.io/badge/Discord-join%20the%20server-5865F2?logo=discord&logoColor=white" alt="Join the Discord"></a></p>

# VS-840EX Rosetta OS (sampler conversion)

> **Runs on real hardware (Rosetta OS 0.07, 2026-10-21).** A VS-840EX boots into the Roland-chan / ROSETTA boot
> animation and then the **Rosetta home menu** (HR-GP5-style folder-tab UI, keys and dial). RECORDER returns to the
> stock VS. Installs from a CF card (or Zip, or MIDI). The menu entries for the looper, FX, sampler and synth are
> placeholders for now: the real features come next. Published early so people can follow along, check the
> findings and help. Questions, hardware reports and ideas: **[Discord](https://discord.gg/R3CQkFdRtf)**.

Goal: turn the Roland **VS-840EX** digital studio into a **guitar looper / sampler / synth**, by porting the
[SP-808 Rosetta Looper OS](https://github.com/yuyoi/Sp-808-rosetta-looper-OS-). It's the same platform: an
**H8S/2655 CPU and a Roland ESP2 DSP (TC170C140)**, so the assembler, emulator, UI ideas and DSP programs carry
over. The VS-840EX adds what a looper wants: a hi-Z **GUITAR IN**, real **faders**, a **foot switch** jack, an
8-track (64 V-track) record/overdub engine, S/PDIF out and IDE storage (Zip, or CF/SD instead of it).

Part of the Rosetta family, after [Rosetta ROM](https://github.com/yuyoi/Rompler-RosettaRom) (D-110) and the
[SP-808 Rosetta Looper OS](https://github.com/yuyoi/Sp-808-rosetta-looper-OS-).

## What works

- **Boots into Rosetta (0.07, on hardware):** the stock splash is replaced by the Roland-chan + ROSETTA picture, then
  the 45-frame SP-808 boot animation plays (any key skips) and the **Rosetta home menu** comes up: black folder tab
  with the bold title, status on the right, 3 rows, inverted selection bar, scroll bar. UP/DOWN or the dial move,
  ENTER opens, RECORDER goes to the stock VS. Pages entered from home use the full screen (no tab bar).
- **Decode Roland's update** (`VS840EXv205.zip`: 8 SMF files of SysEx, model ID `00 0C`) into the plain OS image.
  7-bit packed data, no compression, no encryption. `decode_upd.py` was checked against the plain VS-840's
  Zip-disk update (`$SYSPRO2.VS1`, a raw image): **0 bytes differ**.
- **Encode an image back into the 8 SMFs.** `make_smf.py` re-encodes the stock 1.05 and EX 2.05 images into
  **all 16 of Roland's files, byte for byte**, so every check the receiver makes is known and recomputed:
  a Roland checksum per message, a 7-bit sum of the whole image in the end message, the same version text in all 8.
- **The OS image runs at 0x110000** (0xF0000 bytes) and ends with a **32-bit flash sum at 0x1FFF00** (byte sum of
  0x110000-0x1FFEFF minus the 31-byte disk-ID field at 0x11064A). The builds recompute it.
- **Boot ROM dumped** (0.03, on hardware) through Roland's own hidden "SYSTEM FILE Wr" developer function, pointed at
  address 0: the H8S/2655's 128 KB mask ROM. It checks only the "NM_SYSTEM" header of the flash; if that is broken
  it reflashes from raw disk sectors. **A build with a good header that crashes has no ROM rescue**, so all Rosetta
  code runs **after the OS's own update-file check**: a disk update ("Version up ?") always stays reachable.
- **LCD decoded:** 136 x 32 dots in a RAM shadow buffer (0x403200, 17 strips of 8 px) streamed to the glass by a
  ROM interrupt; the ROM's 5x7 font is reused for pixel-positioned text (`rui.py`).
- **Panel and events decoded:** Roland's event queue (keys, dial), all power-on key combos (test modes, MIDI update,
  developer menu), the key code table.
- **VS cards on a PC (important):** the VS formats cards as **FAT16 with fewer than 4085 clusters** (64 KB
  clusters). Windows treats that as **FAT12**: every multi-cluster file reads as "corrupt", and **when Windows
  mounts the card it writes `System Volume Information` with FAT12 entries into the FAT16 table, breaking take
  chains**. `vscard.py` checks / repairs / adds files on a raw card image; `cardwrite.py` writes it back with the
  volume locked, verifies, and ejects.
- **Emulator** (`vsemu.py`): runs the real ROM and OS routines with the VS memory map; it faults on memory that
  doesn't exist and the build tests trap any write from Rosetta code outside the screen, its own RAM and the stack.

## State in one look

| part | state |
|---|---|
| decode / re-encode Roland's update, flash sum, all checksums | works |
| install from CF (disk update), card tools without Windows writing to the card | works on hardware |
| boot ROM dump (0.03), Roland-chan splash | works on hardware |
| boot animation + Rosetta home menu (0.07) | **works on hardware** |
| SOUND TEST (0.08): own DSP block in core 0, tone 440 / input thru / both / off | built; thru silent on hw, being debugged over MIDI |
| MIDI remote (0.09): keys, dial, ping, memory read/write, live DSP word writes over SysEx + `vsremote.py` loop tests | emulator-tested |
| "Setup ERROR -32746" with a CF card in place of the Zip (stock behaviour, ENTER continues) | being investigated |
| sampler / synth (new direction: no recorder) | next: the VS's ESP2 = the SP-808's two-core chip, KEYS/DDS port |

## Use

You must supply Roland's **own update file** (`VS840EXv205.zip`, VS-840EX OS 2.05, from roland.com). It is
Roland's copyrighted code and is not in this repo. Unzip it into `upd/x_VS840EXv205/`, then:

```
python -I tools/decode_upd.py upd/x_VS840EXv205 upd/raw.bin             # Roland update -> raw pages
python -I -c "d=open('upd/raw.bin','rb').read(); open('vs840ex_v205_os.bin','wb').write(d[0x10000:0x100000])"
python -I tools/build_v007.py                                            # -> work/v007/rosetta-1..8.mid + $SYSPRO2.VS1
```

The boot animation frames come from the SP-808 project (`sp808/assets/roland_chan_frames.npz`, checked out next to
this repo). `--test` runs the emulator test; it needs your own boot ROM dump (`vs840ex_bootrom.bin`, made with the
0.03 build), which is Roland code and not in this repo.

Install, either way:
- **Disk (tested):** put `$SYSPRO2.VS1` in the root of a VS-formatted Zip/CF and power on: "Version up ?" -> YES.
  Use `vscard.py add` + `cardwrite.py`; **don't copy it with Windows Explorer** (see the card note above).
- **MIDI:** hold **MODE + INPUT + ENTER** at power-on, answer YES to "Receive MIDI-EX?", then run
  `python -I tools/send_smf.py work/v007` (Windows, any MIDI interface). Answer YES at the end and power-cycle.

Back to stock at any time: the same way with Roland's own update files.

**Legal:** this repo contains no Roland code. The build scripts patch **your own** decoded image. Please don't share
built images or SMFs: share this repo instead.

## Files

| File | |
|---|---|
| `tools/decode_upd.py`, `tools/make_smf.py` | Roland SMF update <-> OS image, all checksums recomputed |
| `tools/build_v001.py` .. `tools/build_v007.py` | each version as a build script (`build_v007.py` = current) |
| `tools/vsdsp.py` | Rosetta DSP blocks for core 0 (saw / thru), checked in the esp.py cycle simulator |
| `tools/midirem.py`, `tools/vsremote.py`, `tools/winmidi.py` | MIDI remote in the firmware; PC side: keys, SysEx, record + analyse audio |
| `tools/rui.py` | Rosetta UI library: pixel text with the ROM font, bold, rectangles, clipping (H8S code) |
| `tools/vsemu.py` | VS-840EX memory map on the H8S emulator (ROM + OS + LCD), faults on non-existent RAM |
| `tools/send_smf.py` | play the update SMFs to a MIDI out (winmm SysEx) |
| `tools/vscard.py`, `tools/cardwrite.py` | VS card image check / repair / add file; raw write-back with verify and eject |
| `tools/h8sdis.py`, `tools/xref.py`, `tools/h8asm.py`, `tools/h8emu.py`, `tools/esp.py` | H8S disassembler, xref builder, assembler, emulator, ESP2 DSP decoder (from the SP-808 project) |
| `NOTES.md` | memory map, update format, ROM, LCD, events, key combos, every finding |

## Credits and legal

- **Made by JunkSmithWizard (JSW) together with Claude (Anthropic's AI).**
- Roland-chan / Hex Girl is JSW's own drawing.
- Roland and V-Studio are trademarks of Roland Corporation. This project is not affiliated with Roland.
  No Roland code or data is distributed here.
- MIT licensed (see `LICENSE`).

## TODO

- [x] Decode + re-encode Roland's update, byte-exact; flash sum and update checksums.
- [x] VS card tools (Windows FAT12 misread, safe raw write).
- [x] Rosetta OS 0.01 on hardware (version string, flash sum).
- [x] Dump the boot ROM (0.03); map its reset path and recovery.
- [x] LCD, font, events, key combos; Roland-chan boot screen + animation; Rosetta home menu (0.07).
- [ ] Kill "Setup ERROR" with CF cards; way back from the recorder to Rosetta.
- [x] SOUND TEST (0.08) + MIDI remote and loop-test tool (0.09).
- [ ] Audio I/O confirmed on hw (tone, thru) over the MIDI + audio loop.
- [ ] Sampler / synth: port the SP-808 KEYS + DDS-DSP programs to the VS's ESP2.
- [ ] Map the DSP program (one ESP2: mixer, EQ, effects) and the free budget.
- [ ] Looper on the tracks: layers = tracks, faders = levels, foot switch = REC / PLAY / DUB / undo.
- [ ] Own DSP effects (port the SP-808 MFX), sampler, DDS-DSP synth.
