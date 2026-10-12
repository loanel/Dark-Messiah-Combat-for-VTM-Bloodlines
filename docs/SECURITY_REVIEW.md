# Security review

A review of the whole repository (every Python tool, both batch files, the C++ plug-in and the pre-built plug-in in
the v0.1 release) for security problems and for anything that could act maliciously. It was done by Claude (Anthropic)
in Claude Code, at the request of the author, as a separate check of code that Claude itself had written.

**Result:** nothing malicious, nothing that reaches the network or the internet. Two minor weaknesses in the
installer tools were found and fixed (see [Fixed](#fixed)). The rest are notes on code that looks powerful but does
only what the mod needs.

Scope: repository version 0.1 plus the hit-stun change, with the hardening below. The review covered every tracked file
and the `dmcombat.vtm` inside `Dark-Messiah-Combat-for-VTM-Bloodlines-v0.1.zip`.

## How it was checked

- Searched all code for network access (sockets, HTTP, `urllib`, `requests`, WinINet, URL downloads), starting
  programs (`subprocess`, `os.system`, `CreateProcess`, `ShellExecute`), dynamic code (`eval`, `exec`, `pickle`,
  `ctypes`), registry writes, file deletion, process and memory manipulation, and encoded or hidden data (`base64`,
  compressed blobs).
- Read every hit in context, and read in full the installer (`install.bat`, `install.py`), the pack readers
  (`tools/vtmbvpk.py`, `tools/dm_vpk.py`, `tools/dm_extract.py`), the key-binding patcher (`tools/make_keys.py`) and the
  plug-in parts that touch files, other DLLs or the process (`dm_save.cpp`, `dm_crash.cpp`, `dm_exit.cpp`,
  `dm_log.cpp`, `dm_hook.cpp`, `dm_data.cpp`, `dmcombat.cpp`, the patch sites in `dm_fx.cpp`, `dm_hud.cpp`,
  `dm_server.cpp`, `dm_viewmodel.cpp`).
- Checked string and buffer handling in the C++ code (`sprintf`, `strncpy`, `memcpy`, `sscanf`, ini reading).
- Listed the imports and text strings of the released `dmcombat.vtm`.
- Searched the repository and its history for keys, tokens, passwords and personal paths.
- Tested the two fixes against a fake game folder with a tampered install record and a pack with a `../` file name,
  and checked that real Bloodlines packs still extract normally.

## No network access and no hidden behaviour

- **Released plug-in:** `dmcombat.vtm` imports only `KERNEL32.dll` and `USER32.dll`, the standard Windows libraries. It
  has no networking library. The only other DLLs it names are the game's own (`vampire.dll`, `client.dll`,
  `engine.dll`, `tier0.dll`, `vampire_python21.dll`) and Windows' crash-dump helper `dbghelp.dll`.
- **Python tools:** none of them connect anywhere, download anything or install packages. The installer only checks
  that Python, numpy and Pillow are present and tells the player how to install them if not. The ModDB links in the
  README are only text for people to read.
- **Programs started:** the installer starts only our own `tools\*.py` scripts, `tasklist` (to see whether the game is
  running) and the Bloodlines SDK's own tools (`studiomdl-sw.exe`, `studiovtmb49k.exe`, `VTFCmd.exe`), which the player
  installs. Programs are always started directly with an argument list, never through a command shell, so a folder
  name can't inject commands.
- **Registry:** read only, to find Steam and GOG libraries (Dark Messiah's folder). Nothing is written to it.
- **Files written:** only this folder (`build\`, `backup\`) and the Bloodlines folder. Every game file the installer
  replaces (11 melee item files, 2 keybind default files) is backed up first, and every installed file is listed in
  `backup\install_manifest.json` for the uninstaller.
- **Secrets:** no keys, tokens or passwords. The commit emails are the author's GitHub noreply address and an address
  the author chose to publish.

## Code that looks powerful, and why it is there

- **Patching the game's code in memory** (`dm_hook.cpp` and the patch sites): this is how the mod hooks the game. The
  plug-in first checks the exact builds of `vampire.dll`, `client.dll` and `engine.dll` (PE timestamp and size) and
  stays off with anything else. Each patch also checks the instruction it replaces, and the memory protection is
  restored afterwards.
- **Running Python inside the game** (`dm_save.cpp`): Bloodlines runs its quest scripts in an embedded Python. The
  plug-in uses it only to store the adrenaline meter in the savegame (`G.dmAdrenaline`). The only value put into that
  code is an integer the plug-in computes itself, so no outside text can become code.
- **`TerminateProcess`** (`dm_exit.cpp`): it can only end the game's own process, and only when the player turns on
  `exit_watchdog=1` (off by default). It exists for systems where the game hangs after quitting.
- **Crash dump** (`dm_crash.cpp`): after a crash the plug-in writes `dmcombat_crash.txt` and `dmcombat_crash.dmp` next
  to the game. The `.dmp` file is a snapshot of the game's memory, so it can contain the Windows user path and similar
  details. It never leaves the PC. **When reporting a bug, share the `.txt` report, not the `.dmp` file publicly.**
- **`dbghelp.dll` loaded by name** (`dm_crash.cpp`): Windows looks in the game folder first, so a copy placed there
  would be loaded instead. Anyone who can write to the game folder can already replace the game itself, so this adds no
  real risk.
- **Reading files the plug-in didn't write:** `dmcombat.ini` (numbers only), `dmcombat_dm.bin` (every count and size
  checked against the file length before use) and the player's `cfg\config.cfg` (read only, to warn when the
  discipline key is still on the right mouse button).

## Fixed

1. **Uninstall trusted its install record.** `install.py --uninstall` deleted whatever paths
   `backup\install_manifest.json` listed. The installer writes the record correctly, but an edited or tampered record
   could have pointed at any file. Now the uninstaller skips any path outside the Bloodlines folder, and it leaves
   alone any listed file that isn't one of the mod's own (by name or folder) and has changed since the install.
2. **Bloodlines pack extraction trusted file names.** `tools/vtmbvpk.py` wrote extracted files under the names stored
   in the packs, so a name containing `../` could have written outside the output folder. The packs are the player's
   own game files, so the risk was very low; such names are now skipped. Dark Messiah's packs were already safe:
   `tools/dm_vpk.py` only extracts a fixed list of file names.

## Remaining notes

- **Robustness, not security:** a few small details in the C++ code (an unchecked memory allocation in `dm_data.cpp`,
  a model name copy that could stay unterminated if a file name were extremely long) could at worst crash the game in
  very unlikely cases. Nothing in them can be triggered or exploited from outside.
- **The pre-built plug-in:** C++ builds are not byte-for-byte reproducible, so nobody can prove that the released
  `dmcombat.vtm` was built from this exact source. Its imports and text strings match the source. To avoid trusting it,
  build it yourself with `build.bat` (see "Building the plug-in yourself" in the README).
- **Legal side:** the repository and the release contain no files from either game. Everything is built on the
  player's PC from their own copies. Built or installed files (models, textures, `dmcombat_dm.bin`) must never be
  redistributed.
