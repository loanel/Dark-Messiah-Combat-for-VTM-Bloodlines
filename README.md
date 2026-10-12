# DMCombat

Dark Messiah of Might and Magic's first-person melee combat for **Vampire: The Masquerade - Bloodlines** with the
**Unofficial Patch v12.0**.

- You see your own character's arm in first person, swinging the weapon with Dark Messiah's animations.
- Fast-attack chains and directional power attacks, timed parries on the right mouse button, an adrenaline meter and
  finishing moves.
- All 11 player melee weapons, on the arm of your own character and outfit.
- Hits still use Bloodlines' own dice, stats and weapon requirements.

This repository contains no files from either game. The installer builds everything from **your own copies** of both
games, on your PC.

## Requirements

Install these first:

1. **Vampire: The Masquerade - Bloodlines** (Steam or GOG) with the **Unofficial Patch v12.0**. DMCombat checks the
   exact game builds and stays off with any other version.
2. **The Bloodlines SDK**, installed into the game folder (its tools end up in `<Bloodlines>\SDKBinaries`). The
   installer uses its model compiler and texture tool.
3. **Dark Messiah of Might and Magic** (single player, Steam or GOG). Its animations, arm and one sound are read from
   your copy.
4. **Python 3.8 or newer** (python.org or the Microsoft Store) with **numpy** and **Pillow**:
   `python -m pip install numpy pillow`.

**Offline:** nothing in this repository downloads anything or connects to the internet. The installer only reads your
game installs and writes into this folder and your Bloodlines folder.

## Install

1. Download the latest release and unpack it **into your Bloodlines folder**, so you get
   `<Bloodlines>\DMCombat\install.bat`. (The release includes the ready-built plug-in, `bin\dmcombat.vtm`.)
2. Close the game and run `install.bat`.

It checks everything above, finds Dark Messiah through Steam or GOG (or asks; or run
`install.bat --dark-messiah "<folder>"`), builds the models, textures and data (about a minute) and installs them into
the Unofficial Patch. It replaces 11 melee item files and 2 keybind default files; the originals are kept in
`DMCombat\backup` and every installed file is listed in `backup\install_manifest.json`.

- **Uninstall:** `install.bat --uninstall` removes everything and restores the original files.
- **Repair** (after a game or patch update): run `install.bat` again.

## Playing

Start Bloodlines the way the Unofficial Patch is always started: its desktop shortcut, which runs
`Vampire.exe -game Unofficial_Patch`. From Steam, add `-game Unofficial_Patch` to the game's launch options
(Properties > Launch options). Started without the patch, the game runs without DMCombat.

- **Left mouse:** attack. Tap for the fast chain; hold for a power attack, aimed by the movement key (W/A/S/D) held when
  it starts. With the adrenaline meter full, a released power attack becomes a finishing move.
- **Right mouse:** block / parry (a block just before the hit is a perfect parry). While holding a power attack, it
  re-aims the attack with the movement key held at that moment.
- **Q:** cast the selected discipline. The installer moves "Cast Discipline Power" from the right mouse button to Q;
  change it in Options > Keyboard like any other key.
- Melee weapons stay in first person.
- Settings: `dmcombat.ini` in the game folder, reloaded while the game runs. Log: `dmcombat.log`.

## Building the plug-in yourself

The release includes `bin\dmcombat.vtm`. To build it from `src\dmcombat`: Visual Studio 2017 or newer (or its Build
Tools) with "Desktop development with C++", then run `build.bat` from a path without spaces (for example a drive letter
mapped with `subst W: "<Bloodlines>\DMCombat"`). Run `python tools\weapon_prep.py` and `python tools\build_arms.py`
first (or the installer once): they write two generated headers the plug-in includes.

## Repository

| Path | What |
|---|---|
| `install.bat`, `install.py` | The installer (checks, build steps, install, uninstall) |
| `src/dmcombat/` | The plug-in (C++, loaded by the Unofficial Patch's Game Mod Loader) |
| `tools/` | Python tools the installer runs: readers for both games' packs and models, weapon placement, arm models, textures, item and keybind patching |
| `build.bat` | Builds the plug-in |
| `dist/dmcombat.ini` | Default settings |
| `docs/DMCombat_REPORT.md` | How the mod was built, step by step |
| `docs/PROMPTING_GUIDE.md` | How it was built with an AI coding agent (Claude): prompts, statistics, lessons |

The two documents describe the whole development. They mention a development journal and analysis tools that aren't
part of this repository.

## Credits and disclaimer

- Wesp5 and contributors: the Unofficial Patch and its Game Mod Loader.
- The Bloodlines SDK authors.
- Built by loanel together with Claude (Anthropic) in Claude Code; see `docs/PROMPTING_GUIDE.md`.

Not affiliated with or endorsed by Paradox Interactive, Ubisoft, Activision or Troika. "Vampire: The Masquerade" and
"Dark Messiah of Might and Magic" are trademarks of their owners and are used here only to describe compatibility.
You need your own copies of both games.

Licence: MIT (see `LICENSE`), for the code in this repository only.
