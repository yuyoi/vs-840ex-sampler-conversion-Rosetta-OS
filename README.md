<p align="center"><a href="https://discord.gg/R3CQkFdRtf"><img src="https://img.shields.io/badge/Discord-join%20the%20server-5865F2?logo=discord&logoColor=white" alt="Join the Discord"></a></p>

# VS-840EX Rosetta OS (sampler conversion)

> **Early work, October 2026.** Roland's update format is cracked, a first trial build (**Rosetta OS 0.01**) is
> built and on a CF card, and the **hardware test is next**. Nothing here has run on a real unit yet. Published early
> so people can follow along, check the findings and help. Questions, hardware reports and ideas:
> **[Discord](https://discord.gg/R3CQkFdRtf)**.

Goal: turn the Roland **VS-840EX** digital studio into a **guitar looper / sampler / synth**, by porting the
[SP-808 Rosetta Looper OS](https://github.com/yuyoi/Sp-808-rosetta-looper-OS-). It's the same platform: an
**H8S/2655 CPU and a Roland ESP2 DSP (TC170C140)**, so the assembler, emulator, UI engine and DSP programs carry
over. The VS-840EX adds what a looper wants: a hi-Z **GUITAR IN**, real **faders**, a **foot switch** jack, an
8-track (64 V-track) record/overdub engine, S/PDIF out and IDE storage (Zip, or CF/SD instead of it).

Plans: own UI + Hex Girl boot logo, new DSP effects, a looper on the tracks and faders, a sampler, and the DDS-DSP
synth from the SP-808 build.

Part of the Rosetta family, after [Rosetta ROM](https://github.com/yuyoi/Rompler-RosettaRom) (D-110) and the
[SP-808 Rosetta Looper OS](https://github.com/yuyoi/Sp-808-rosetta-looper-OS-).

## What works

- **Decode Roland's update** (`VS840EXv205.zip`: 8 SMF files of SysEx, model ID `00 0C`) into the plain OS image.
  It uses 7-bit packed data, with no compression and no encryption. `decode_upd.py` was checked against the plain
  VS-840's Zip-disk update (`$SYSPRO2.VS1`, a raw image): **0 bytes differ**.
- **Encode an image back into the 8 SMFs.** `make_smf.py` re-encodes the stock 1.05 and EX 2.05 images into
  **all 16 of Roland's files, byte for byte**, so every check the receiver makes is known and recomputed:
  - a Roland checksum on every message
  - a 7-bit sum of the whole image in the end message ("Total ChkSUM Err")
  - the same version text in all 8 files ("MID Version Err")
- **The OS image runs at 0x110000** (0xF0000 bytes). It ends with a **32-bit flash sum at 0x1FFF00**: the byte sum
  of 0x110000-0x1FFEFF minus the 31-byte disk-ID field at 0x11064A. This was checked on both stock images. The
  test-mode version screen shows "Bad FLASH!!" when it is wrong; the builds recompute it.
- **Send the update** from a PC: `send_smf.py` plays the 8 SMFs to any MIDI out with the files' own timing (~14 min).
- **VS cards on a PC (important):** the VS formats cards as **FAT16 with fewer than 4085 clusters** (64 KB
  clusters). Windows decides the FAT type from the cluster count, so it treats the card as **FAT12**:
  - Every file bigger than one cluster (all takes) reads as "corrupt".
  - **When Windows mounts the card it writes `System Volume Information` with FAT12 entries into the FAT16 table,
    breaking take chains and overwriting take audio.**

  `vscard.py` checks, repairs and adds files to a raw card image; `cardwrite.py` writes it back with the volume
  locked and then ejects the card. A damaged card was repaired with these: the lost FAT nibbles are solved from
  chain constraints, and all takes are whole again.
- **Reverse engineering so far:** the update receiver, the flash sum, the test-mode screens, the string tables, and
  the boot-ROM print/copy routines the OS calls (`0x2E36` print at row/col, `0x4A6E` memcpy, ...).

## State in one look

| part | state |
|---|---|
| decode / re-encode Roland's update, byte-exact both ways | works (PC side) |
| flash sum + update checksums recomputed | works (PC side) |
| Rosetta OS 0.01: version string only, data change, no code | built, on the CF card, **hw test pending** |
| VS card repair / add file / raw write without Windows touching it | works on a real card |
| boot ROM + flash boot block dump | not done (the OS calls ~458 routines below 0x100000) |
| LCD, keys, faders, DSP program map | not started |

**Careful:** on the VS-840EX the MIDI update receiver (hold MODE + INPUT + ENTER at power-on) is **inside the OS**,
not in a separate boot block like on the SP-808. A build that crashes early may leave no MIDI way back. Builds stay
data-only until the boot ROM is dumped and its own recovery (if any) is known.

## Use

You must supply Roland's **own update file** (`VS840EXv205.zip`, VS-840EX OS 2.05, from roland.com). It is
Roland's copyrighted code and is not in this repo. Unzip it into `upd/x_VS840EXv205/`, then:

```
python -I tools/decode_upd.py upd/x_VS840EXv205 upd/raw.bin             # Roland update -> raw pages
python -I -c "d=open('upd/raw.bin','rb').read(); open('vs840ex_v205_os.bin','wb').write(d[0x10000:0x100000])"
python -I tools/build_v001.py                                            # -> work/v001/rosetta-1..8.mid + $SYSPRO2.VS1
```

Install, either way:
- **MIDI:** hold **MODE + INPUT + ENTER** at power-on, answer YES to "Receive MIDI-EX?", then run
  `python -I tools/send_smf.py work/v001` (Windows, any MIDI interface). Answer YES at the end and power-cycle.
- **Disk:** put `$SYSPRO2.VS1` in the root of a VS-formatted Zip/CF and power on: "Update SysPRG ?" -> YES.
  Use `vscard.py add` + `cardwrite.py`; **don't copy it with Windows Explorer** (see the card note above).

Check: power on holding **MONITOR SEL + SOLO** (test mode). It should show `ROSETTA OS 0.01`, with no "Bad FLASH!!".

**Legal:** this repo contains no Roland code. The build scripts patch **your own** decoded image. Please don't share
built images or SMFs: share this repo instead.

## Files

| File | |
|---|---|
| `tools/decode_upd.py` | Roland SMF update -> OS image (page 01 = image offset 0) |
| `tools/make_smf.py` | OS image -> 8 SMFs with Roland's files as the template, all checksums recomputed |
| `tools/build_v001.py` | Rosetta OS 0.01 (version string + flash sum) |
| `tools/send_smf.py` | play the update SMFs to a MIDI out (winmm SysEx) |
| `tools/vscard.py` | VS card image: check chains, repair Windows' SVI damage, add a file |
| `tools/cardwrite.py` | write a card image back raw: lock, verify against the backup, write changed sectors, read back, eject |
| `tools/h8sdis.py`, `tools/xref.py`, `tools/h8asm.py`, `tools/h8emu.py` | H8S disassembler, xref builder (`xref.py image.bin out.pkl [base]`), assembler, emulator (from the SP-808 project) |
| `tools/esp.py` | Roland ESP2 DSP decoder / cycle simulator (from the SP-808 project) |
| `NOTES.md` | memory map, update format, chip list, findings |

## Credits and legal

- **Made by JunkSmithWizard (JSW) together with Claude (Anthropic's AI).**
- Roland and V-Studio are trademarks of Roland Corporation. This project is not affiliated with Roland.
  No Roland code or data is distributed here.
- MIT licensed (see `LICENSE`).

## TODO

- [x] Decode + re-encode Roland's update, byte-exact; flash sum and update checksums.
- [x] VS card tools (Windows FAT12 misread, safe raw write).
- [ ] Rosetta OS 0.01 on hardware (test mode shows the new version).
- [ ] Dump the boot ROM and flash boot block; find out if there's a recovery path outside the OS.
- [ ] Map the LCD, keys, faders, foot switch; the normal boot screen.
- [ ] Own UI + Hex Girl boot logo (port the SP-808 graphics engine).
- [ ] Map the DSP program (one ESP2: mixer, EQ, effects) and the free budget.
- [ ] Looper on the tracks: layers = tracks, faders = levels, foot switch = REC / PLAY / DUB / undo.
- [ ] Own DSP effects (port the SP-808 MFX), sampler, DDS-DSP synth.
