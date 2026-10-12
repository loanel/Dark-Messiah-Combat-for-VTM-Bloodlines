# DMCombat: how the mod was built

DMCombat brings Dark Messiah of Might and Magic's first-person melee combat to Vampire: The Masquerade - Bloodlines
(Unofficial Patch v12.0). In Bloodlines, melee weapons are fought in third person with dice-rolled hits. With DMCombat
the player sees their own arm in first person, swinging the weapon with Dark Messiah's animations. The mod adds:
- a fast-attack chain and directional power attacks;
- timed parries, an adrenaline meter and finishing moves;
- every player melee weapon, on the arm of the player's own character and outfit.

This report covers the work from the first feasibility check (2026-10-09) to the finished weapon set (2026-10-11) and
the follow-up session on a second PC (2026-10-12, steps 17–22), as Goal, Tools used and Result for each major step. Technical detail (addresses, file formats) is in `MODLOG.md`.

**Ground rules kept throughout:**
- No game files from either game are shipped. Everything taken from the games is read from the user's own installs
  and stays on that PC.
- Everything new lives in `DMCombat_dev/` inside the game folder, as a git repository.
- Original files the install replaces are backed up first.

---

## 1. Feasibility and plan

**Goal.** Find out whether Dark Messiah's sword combat can be brought into Bloodlines, and how.

**Tools used.**
- Reading the game folders.
- A new reader for Bloodlines' own pack format (`tools/vtmbvpk.py`). Bloodlines' VPKs are not Valve's format.
- A model header reader (`tools/mdlhdr.py`).
- Text and RTTI string scans of `vampire.dll` (server) and `client.dll`.
- The earlier DMHL2 project, which had already decompiled Dark Messiah's sword animations and written its rules down
  (`SPEC_sword.md`).

**Result.** `MODDING_PLAN.md`. Findings:
- Bloodlines models are format 2531.
- The public Bloodlines SDK compiler builds only one-bone, one-frame props.
- Melee items show nothing in first person (`w_null.mdl`).
- Damage is dice-based.
- The Unofficial Patch's Game Mod Loader loads native `.vtm` plug-ins.

Two routes were considered: (A) bring Dark Messiah's animated first-person models, or (B) re-implement Dark Messiah's
rules in a plug-in. Route B was approved. Route A turned out to be possible later in a different form (step 12).

## 2. Workspace, backups and toolchain

**Goal.** A safe place to work, and the tools needed for native code and reverse engineering.

**Tools used.**
- git.
- Visual Studio 2022 Build Tools, MSVC x86, installed with winget.
- Ghidra 12.1.4 with Temurin JDK 21, downloaded and SHA-256 verified.
- Python packages numpy, pillow, pefile and capstone.
- `subst W:`, because Ghidra's launcher and the MSVC build break on paths with spaces.

**Result.**
- The `DMCombat_dev/` repo.
- Backups of saves, configs and loader ini files in `backup/`.
- Ghidra projects of both game DLLs in `re/`, with a headless runner `re/gh.sh`.
- Small analysis scripts: `tools/xref.py` (vtable slots, thunks, virtual calls), `tools/thunk.py` and
  `tools/disasm.py`.

## 3. Reverse engineering Bloodlines' melee code

**Goal.** Know where Bloodlines decides swings, hits, blocks, damage, knockback and the first-person view, so the
plug-in can take them over.

**Tools used.**
- Ghidra headless analysis.
- RTTI. The class names in the DLLs give every weapon class's vtable; for example `CWeaponMelee_Katana` is
  `0x104d73e4`.
- capstone disassembly scripts and string cross-references.
- In-game tests reading `dmcombat.log`.

**Result.** A map of the melee system, recorded in `MODLOG.md`:
- The weapon think (vtable slot 319) and the hit routine MeleeHit (slot 270).
- The vanilla hit test, the dice-roll records, the block check `WasMeleeBlocked`, and knockback activity and force by
  direction.
- The trace function and the damage-info structure.
- The weapon sound call.
- On the client: the first-person view placement (`CalcViewModelView`), the viewmodel's bone setup
  (`BuildTransformations`) and the HUD blood bar's draw calls.

## 4. The plug-in skeleton

**Goal.** Native code running inside the game that can safely replace game functions.

**Tools used.**
- C++ built as a Win32 DLL with the static CRT (`build.bat`).
- The Game Mod Loader's export convention: `loaded_vampire` and `loaded_client` are called after each game DLL loads.
- vtable-slot and call-site patching.

**Result.** `src/dmcombat` and `bin/dmcombat.vtm`:
- Module identity checks: exact DLL timestamps and sizes. Unknown builds disable the hooks instead of crashing.
- `dmcombat.ini` with live reload.
- A log, `dmcombat.log`.
- Later a crash catcher: `dmcombat_crash.txt` plus a minidump, with code addresses as module+offset.
- An exit watchdog.
- `install.sh` and `install.sh --uninstall`.

## 5. Dark Messiah's sword motion in first person

**Goal.** Show the katana moving exactly as Dark Messiah's sword does.

**Tools used.**
- The DMHL2 project's decompile of Dark Messiah's first-person animations: the files extracted from the user's Dark
  Messiah packs, then decompiled with Crowbar 0.74 to SMD. The SMD reader is `smd.py`.
- `tools/gen_sword_paths.py`: samples the sword-hand path of 73 sequences (1,659 frames) in eye space into
  `dm_paths.h`, which is never committed.
- A client hook on `CalcViewModelView`.
- Bloodlines' own one-bone ground katana model `g_katana.mdl`.

**Result.**
- The rigid katana plays Dark Messiah's idle, fast attacks A–E, directional power attacks (charge, hold, release) and
  parries.
- A state machine reads the mouse and movement keys: tap for the fast chain, hold 0.36 s for a power attack, the
  direction comes from the movement keys, the right mouse button parries.
- Placement was tuned live with the user: offset 16/-2/-20, viewmodel fov 54.
- `tools/vm_fit.py` and `tools/vm_center.py` checked offline that the blade stays on screen and crosses the crosshair
  during hits.

## 6. Real hits on the server

**Goal.** Swings hit enemies when Dark Messiah's animation says the blade connects, with Bloodlines' damage rules
(stats, Melee skill, disciplines, armour).

**Tools used.** Hooks on every melee weapon's think, traces along the real blade pose per frame, and Bloodlines' own
MeleeHit, dice-roll and knockback functions called from the plug-in.

**Result.**
- Hit windows per move (`dm_hitwindows.h`), up to 8 victims per swing.
- Damage is Bloodlines' own dice roll (rolled per victim), scaled: fast 0.75×, power 2.5×.
- Power attacks break guards.
- Left and right power attacks knock enemies sideways (side knockback activities), the others backwards.
- Swing sounds per strike.
- Extra reach per attack class.
- Enemies get their normal chance to block or dodge each new attack.

## 7. Parry

**Goal.** Dark Messiah-style blocking that actually stops damage.

**Tools used.** A redirect of the player branch of `WasMeleeBlocked`, and a hook on the dice-roll function that lowers
the net hit.

**Result.**
- Holding the right mouse button raises the guard.
- A parry within 0.3 s of the hit is perfect: free, and the attacker staggers.
- A later block costs 1 blood point.
- With no blood left, the hit gets through softened.
- The parry animations play on blocked hits.

## 8. Adrenaline and finishing moves

**Goal.** Dark Messiah's adrenaline meter and its special moves, fitted to Bloodlines.

**Tools used.**
- Character stat offsets (the Melee skill).
- Hooks on the HUD blood bar's paint (`CHUDSprite` draw calls).
- New textures (`tools/gen_adrenaline_fx.py`), converted to Bloodlines' texture format by `tools/tga2ttx.py`, a new
  converter for Bloodlines' `.tth`/`.ttz`, built on VTFCmd.
- The engine's 2D sound call.
- Bloodlines' embedded Python, to store the meter in save games.

**Result.**
- The meter fills on landed hits (fast 0.5, power 3) and decays slowly. The requirement shrinks as the Melee skill
  rises.
- A gold bar next to the blood bar.
- When the meter is full: Dark Messiah's "adrenaline reached" sound (taken from the user's Dark Messiah install), a
  red reticle, red screen-edge pulses, and a dark red streak along the blade during adrenaline strikes.
- Moves:
  - left power attack: behead;
  - stab power attacks: impale, with the longest reach;
  - other directions: the two-hit huge combo.
- All adrenaline strikes deal 7.5× damage.
- The meter is saved in the game's save files.

## 9. Stability fixes

**Goal.** No crashes, no stuck states.

**Tools used.** The crash catcher's reports, Ghidra, and timing logs.

**Result.**
- **Hit-recoil gap:** taking a hit makes Bloodlines skip the weapon's update for up to 1.7 s. A fallback runs the
  combat logic from the client frame.
- **Impact effects:** the "trace did not hit anything" console error is fixed.
- **Animation events:** stripped from borrowed models; they caused a sound crash.
- **Engine sound guard:** a bad sound name is now played as silence instead of crashing.
- **Root cause of the sound crash:** weapons first given in the middle of a level had their sounds loaded too late. At
  every level start the plug-in now preloads all 11 melee weapons, through the fists the player always carries.

## 10. A hand on the sword

**Goal.** See a hand holding the weapon, not a floating katana.

**Tools used.**
- Bloodlines SDK v2.20's `studiomdl.exe` (one-bone props).
- Crowbar 0.65 (CroVtmb, a VTMB build of Crowbar) to decompile `g_katana`.
- `tools/build_katana_hand.py`, which bakes Dark Messiah's gloved arm (from the decompile) around the grip.
- `tga2ttx.py` for its textures.

**Result.** A first version with a rigid hand and forearm. It was replaced by step 12.

## 11. Reading Bloodlines models without Crowbar

**Goal.** Turn any Bloodlines model into editable source automatically. Crowbar is GUI-only.

**Tools used.** Format study and a Crowbar decompile as reference. The result was compared triangle by triangle.

**Result.**
- `tools/vtmb_mdl2smd.py`: a new reader for MDL 2531 plus VTX (version 107). It matched Crowbar on 5,761 of 5,773
  triangles. It handles the three vertex encodings: 44-byte skinned, 12-byte quantised and 2-byte strip vertices.
- `tools/get_pc_models.py`: extracts and converts all player character models (14 characters × 4 outfits).
- `tools/vtmb_bones.py`: reads bone transforms.

## 12. An animated arm (Route A after all)

**Goal.** A real animated first-person arm driven by Dark Messiah's animations, despite the SDK compiler's one-bone
limit.

**Tools used.**
- **The discovery:** the SDK also ships `studiovtmb49k.exe`, a formatter that turns a model compiled by Alien Swarm's
  `studiomdl-sw.exe` into a Bloodlines model. It does this by reusing the skeleton of an existing Bloodlines model.
- Donor skeleton: `v_thaumaturgy.mdl` (42 bones).
- `tools/build_katana_arm.py` builds the source.
- `build_arm.sh` runs compile + format + event strip (`tools/strip_mdl_events.py`).
- A client hook on the viewmodel's `BuildTransformations`. Each frame it overwrites the arm's bone matrices with Dark
  Messiah's animation:
  `bone = eye × offset × D(frame) × inverse(rest)`.

**Result.**
- The first-person arm moves exactly like Dark Messiah's.
- Fingers are baked in the grip pose.
- Unused bones are collapsed, and so are all bones when the weapon is holstered.

## 13. The player's own arm for every character and outfit

**Goal.** The arm looks like the character you play (7 clans × 2 genders) in the outfit you wear (4 per character),
and changes when you change armour.

**Tools used.**
- `tools/pc_arm.py`: retargets each Bloodlines arm onto Dark Messiah's arm skeleton segment by segment, from joint
  positions, with the thumb roll taken from the palm.
- Per-character models: bones 1–11 are the weapons, then one 7-bone arm block per outfit.
- **Model loading:** a hook on the weapons' Precache loads all arm models at level load.
- **Model swap:** a server-side `SetModel` on the viewmodel (found by its vtable; it has no class name) puts in the
  current character's model.
- **Character and outfit:** the client reads both from the player model's path.
- **Thumb:** the angle was picked by the user from a grid of renders (`tools/vm_preview.py`, `tools/hand_preview.py`).

**Result.** All 14 characters work in game, and the arm swaps live on armour changes and save loads.

## 14. Every player melee weapon

**Goal.** Katana, occult blade, knife, tire iron, fire axe, sledgehammer, torch, baton, bush hook, baseball bat and
severed arm, all held correctly with the attacking side facing forward.

**Tools used.**
- `tools/weapon_prep.py`, which places each weapon:
  1. finds the handle axis (PCA), the head end and the real handle centre (surface sampling);
  2. turns the attacking side (the thin edge, or the far-reaching side) onto the katana's edge direction;
  3. applies per-weapon grip, roll, flip and scale.
- `tools/make_items.py` patches every melee item file: arm viewmodel, first-person camera, crosshair. The originals
  are backed up.
- The plug-in finds the held weapon by its client class and shows only that weapon's bone.

**Result.** All 11 weapons in game. Per-weapon fixes from the user's checks:
- Knife and baton flipped.
- Tire iron and its bent end turned forward.
- **Occult blade:** its ground model's blade decoded broken, so it uses the clean katana mesh with the occult
  textures. It also got its own high-contrast blade texture (`tools/make_occult_blade.py`, made from the game's
  texture at build time) and a crosshair block, which its item file never had.
- **Sledgehammer:** 10% smaller so the fingers close around the handle. Its two bright, blade-like swing sounds were
  replaced with deeper ones, chosen by decoding the game's ADPCM sounds and comparing their brightness.

## 15. Outfits: one hand, changing sleeves

**Goal.** Heavy armours deformed the hand (a big cuff stuck out over it). The user wanted the base outfit's hand in
every outfit, with only the armour changing around it.

**Tools used.** Mesh surgery in `build_katana_arm.py`:
- **Wrist weights:** the wrist helper bone's weight is shared 50/50 with the hand, so cuffs bend with the grip.
- **Hand swap:** the base hand (armor_0) is put inside each outfit's sleeve.
- **Gaps:** the base hand extends 2 units up the forearm, tapered so it stays inside the sleeve.
- **Sleeve holes:** sleeve pieces the hand used to cover are kept.
- **Lists:** `OWN_HANDS` for gloved outfits, `LEAVE_OUT` for an unwanted frill.

**Result.** 13 of 14 characters use the base hand in their outfits. Gloved and special outfits keep their own hand.
One silent converter limit was found by bisecting: at most 22 materials per model. Merging two occult blade textures
into one atlas freed a slot for every character.

## 16. Review tooling instead of manual checking

**Goal.** Let the user check 56 outfits × 11 weapons without trying each in game.

**Tools used.**
- `tools/arm_sheet.py`: a textured software rasteriser that renders with the game's real textures (decoded by
  `tools/ttx2png.py`, a new `.tth`/`.ttz` reader).
- The same pose maths as the plug-in.
- Orbit and fixed cameras.

**Result.**
- `build/arm_sheets/`: each character, outfits × four sides of the hand.
- `build/gallery_outfits/`: every weapon on every character.
- `build/gallery/`: each weapon in close-up on a male and a female hand, and at rest and mid-swing from behind, the
  right, above and the front.

The user reviewed these galleries and confirmed all weapons and outfits.

## 17. Moving to a second PC

**Goal.** Continue on another computer from the handoff zip, and leave the environment ready for future work.

**Tools used.**
- The handoff notes (`HANDOFF.md`) and the project memory carried over in the zip.
- Checks of the new PC: game DLL versions (the plug-in's build check), where Dark Messiah is installed, Python and its
  packages, Visual Studio Build Tools.
- The full build from the notes: `build.bat`, `gen_sword_paths.py`, `weapon_prep.py`, `make_occult_blade.py`,
  `make_items.py`, `build_arm.sh`, `install.sh`, then `cmp` of every installed file.
- Ghidra and its JDK unpacked from the archived downloads, tested on the Bloodlines project.

**Result.** Everything rebuilt and installed with no code changes. Three environment quirks were written down (Windows
paths for Python, `subst W:` from PowerShell, forward slashes for the Ghidra runner).

## 18. The torch's flame

**Goal.** The torch's fire burned at the player's body instead of on the drawn torch.

**Tools used.**
- String cross-references and decompilation of the torch class on the server and client, and of the game's particle
  entity (`env_particle`) on both sides.
- Reading the particle scripts from the game's packs (`vtmbvpk.py`).
- A vtable comparison of the torch against plain melee weapons, to see what the torch does differently.

**Result.**
- The game attaches the flame to the torch's *world* model, the one the character's body holds. DMCombat's first-person
  view never shows that body, so the flame stayed at its hand below the camera.
- The plug-in now hooks the particle's per-frame follow update and moves the flame onto the head of the drawn torch.
  The drawn arm uses a different field of view from the world, so the point is corrected for that and lands exactly
  on the torch on screen.
- Tunable live with `torch_flame` in `dmcombat.ini`. Confirmed in game.

## 19. Disciplines on Q

**Goal.** The right mouse button is the block, but the Unofficial Patch casts disciplines with it too. Move the
discipline key, without taking a key from guns and without overriding a player's own layout.

**Tools used.**
- The game's keybind lists: the Options action list (`kb_act.lst`), the defaults (`kb_def.lst`, `default.cfg`) and the
  player's `config.cfg`.
- A new tool, `tools/make_keys.py`.

**Result.**
- "Cast Discipline Power" is on **Q** by default (it was free and sits next to W). R stays reload.
- It's an ordinary keybind: players can change it in Options. The installer moves a player's bind only if it's still
  on the right mouse button and Q is free, and uninstall puts it back.
- If a player binds it back to the right mouse button, the plug-in prints a console warning instead of fighting it.
- Confirmed in game.

## 20. First person only with melee weapons

**Goal.** The camera toggle still switched to third person with a melee weapon, where Bloodlines' own animations
don't fit DMCombat's weapons. Guns already lock first person.

**Tools used.** A comparison of the camera classes in the item files with the ones the game's code knows.

**Result.** The camera class used so far ("noswitch", from an optional Unofficial Patch mod) isn't a class the game
knows; it only stopped the automatic switch. The melee items now use the game's own `force_1st`. Confirmed in game.

## 21. Melee skill requirements (checked, no change)

**Goal.** Find out whether weapons with a melee requirement should be locked for weak characters.

**Tools used.** Decompiling the item parser and the attack calculation, and the hit log.

**Result.** Bloodlines never restricts equipping. The requirement lowers the attack value: Base Lethality + (melee pool
− requirement). DMCombat's hits go through the game's dice and damage code, so this still applies. The user chose to
keep the vanilla behaviour.

## 22. Pre-release audit

**Goal.** Before publishing: make sure the repository contains nothing harmful, does no downloads or network access,
and has no mistakes that would misbehave on someone else's PC.

**Tools used.** Searches of every tracked file for network, process, delete and path patterns; the plug-in's import
table; a read-through of the install and build scripts; test runs from different folders.

**Result.**
- No network code anywhere; the plug-in uses only Windows' basic system libraries and the game's own DLLs, and writes
  only inside the game folder. No game data in the tracked files.
- Fixed: the installer depended on the folder it was started from, and it decided whether to install the arm models
  by an obsolete file, so a fresh build would have installed none. It now checks the game folder, installs nothing
  unless the build is complete, and works from anywhere.
- `build.bat` finds any Visual Studio 2017+ edition.
- Personal paths removed from the journal.
- What still stands between this repository and a player-friendly offline installer is listed in `DEPLOYMENT.md`.

---

## Tools at a glance

| Tool | Origin | Used for |
|---|---|---|
| Visual Studio 2022 Build Tools (MSVC x86) | Microsoft, installed with winget | Building `dmcombat.vtm` |
| Ghidra 12.1.4 + Temurin JDK 21 | Downloaded (SHA-256 verified) | Reverse engineering vampire.dll, client.dll, engine.dll |
| Python 3 + numpy, pillow, pefile, capstone | pip | All tools: mesh maths, images, PE parsing, disassembly |
| Bloodlines SDK v2.20 (`SDKBinaries`) | User's install | `studiomdl.exe` (props), `studiomdl-sw.exe` + `studiovtmb49k.exe` (animated models), `VTFCmd.exe` (textures) |
| Crowbar 0.74 / 0.65 (CroVtmb) | DMHL2 project / a VTMB build of Crowbar on this PC | Dark Messiah animation decompile (SMD); one early Bloodlines decompile, later replaced by `vtmb_mdl2smd.py` |
| Unofficial Patch Game Mod Loader | Part of UP v12.0 | Loads the `.vtm` plug-in |
| vswhere | Part of the Visual Studio installer | `build.bat` finds Visual Studio (offline) |
| New tools in `tools/` | Written in this project | Pack reader, MDL/VTX reader, texture reader/writer, arm retargeting, weapon placement, item patching, model builds, renderers, audio analysis |

## Numbers

- Plug-in: 12 C++ modules (server combat, viewmodel/arm, HUD, FX, save, crash, exit watchdog, data loading, hit windows).
- 15 arm models: the base model plus 14 characters, each holding 11 weapons and 4 outfit blocks (40 of 42 bones).
- 11 item files patched; originals restored by `install.sh --uninstall`. Keybind defaults patched the same way.
- 27 Python tools.
- Journal: `MODLOG.md`. Plan: `MODDING_PLAN.md`.
