"""Dark Messiah Combat for VTM Bloodlines installer: builds everything from the player's own games and installs it into the Unofficial Patch.

  install.bat                              install (or repair: run it again)
  install.bat --dark-messiah "<folder>"    when Dark Messiah isn't found automatically
  install.bat --uninstall                  remove Dark Messiah Combat and restore every file it replaced

Requirements (installed by the player): Bloodlines + Unofficial Patch v12.0, the Bloodlines SDK (in
<Bloodlines>\\SDKBinaries), Dark Messiah of Might and Magic (single player), Python 3 with numpy and Pillow.
This folder must sit inside the Bloodlines folder. Nothing is downloaded and nothing connects to the internet: the
tools only read the game installs and write into this folder and the Bloodlines folder.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.dirname(ROOT)
UP = os.path.join(GAME, "Unofficial_Patch")
SDK = os.path.join(GAME, "SDKBinaries")
MANIFEST = os.path.join(ROOT, "backup", "install_manifest.json")
PY = sys.executable

# The game builds the plug-in was made for (Unofficial Patch v12.0): PE timestamps, as checked by dmcombat.vtm
BUILDS = {os.path.join("Vampire", "dlls", "vampire.dll"): 0x41AFAFAE,
          os.path.join("Vampire", "cl_dlls", "client.dll"): 0x41AFAF63,
          os.path.join("Bin", "engine.dll"): 0x41AFAF48}
SDK_FILES = ["studiomdl-sw.exe", "studiovtmb49k.exe", os.path.join("assets", "gameinfo.txt"),
             os.path.join("tools", "Texture Utils", "VTFCmd.exe")]
DM_FOLDER = "Dark Messiah Might and Magic Single Player"

STEPS = [  # (title, tool and arguments; "{dm}" = the Dark Messiah folder)
    ("Dark Messiah: arm, animations, textures, sound", ["dm_extract.py", "{dm}"]),
    ("Bloodlines: player characters (14 x 4 outfits)", ["get_pc_models.py", "models/character/pc/.*/"]),
    ("Bloodlines: melee weapons", ["get_weapon_models.py"]),
    ("Weapons placed in the hand", ["weapon_prep.py"]),
    ("Occult blade textures", ["make_occult_blade.py"]),
    ("Arm, adrenaline bar and effect textures, sound", ["make_textures.py"]),
    ("Melee item files", ["make_items.py"]),
    ("Keybind defaults (disciplines on Q)", ["make_keys.py"]),
    ("Dark Messiah motion and hit windows", ["gen_sword_paths.py"]),
    ("Arm models for every character (Bloodlines SDK)", ["build_arms.py"]),
]


def fail(msg):
    print("\nERROR: " + msg)
    sys.exit(1)


def pe_timestamp(path):
    with open(path, "rb") as f:
        d = f.read(4096)
    return struct.unpack_from("<I", d, struct.unpack_from("<I", d, 0x3C)[0] + 8)[0]


def game_running():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Vampire.exe", "/NH"], capture_output=True, text=True)
    return "vampire.exe" in r.stdout.lower()


def check_bloodlines():
    if not (os.path.exists(os.path.join(GAME, "Vampire.exe")) and os.path.isdir(os.path.join(UP, "vdata", "items"))
            and os.path.isdir(os.path.join(GAME, "Bin", "loader"))):
        fail("this folder must be inside the Bloodlines folder, with the Unofficial Patch installed.\n"
             "       Found instead: %s" % GAME)
    for rel, stamp in BUILDS.items():
        p = os.path.join(GAME, rel)
        if not os.path.exists(p) or pe_timestamp(p) != stamp:
            fail("%s is not the Unofficial Patch v12.0 build Dark Messiah Combat was made for." % rel)
    print("  Bloodlines + Unofficial Patch v12.0: %s" % GAME)


def check_sdk():
    missing = [f for f in SDK_FILES if not os.path.exists(os.path.join(SDK, f))]
    if missing:
        fail("Bloodlines SDK not found in %s (missing %s). Install the Bloodlines SDK into the game folder."
             % (SDK, ", ".join(missing)))
    print("  Bloodlines SDK: %s" % SDK)


def check_writable():
    """Bloodlines under Program Files (Steam's default library) is write-protected without administrator rights."""
    for d in (ROOT, os.path.join(UP, "vdata", "items"), os.path.join(GAME, "Bin", "loader"), GAME):
        probe = os.path.join(d, "~dmcombat_write_test.tmp")
        try:
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
        except OSError:
            fail("can't write to %s.\n       Bloodlines is in a protected folder (for example under Program Files): "
                 "right-click install.bat and choose \"Run as administrator\"." % d)
    free = shutil.disk_usage(ROOT).free
    if free < 400 * 1024 * 1024:
        fail("only %d MB free on this drive; the build needs about 250 MB." % (free // (1024 * 1024)))


def steam_libraries():
    roots = []
    try:
        import winreg
        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(winreg.QueryValueEx(k, value)[0])
            except OSError:
                pass
    except ImportError:
        pass
    libs = []
    for r in roots:
        libs.append(r)
        vdf = os.path.join(r, "steamapps", "libraryfolders.vdf")
        if os.path.exists(vdf):
            for line in open(vdf, encoding="utf-8", errors="replace"):
                parts = line.strip().split('"')
                if len(parts) >= 4 and parts[1] == "path":
                    libs.append(parts[3].replace("\\\\", "\\"))
    libs.append(os.path.dirname(os.path.dirname(GAME)))  # the library Bloodlines is in
    return libs


def gog_folders():
    out = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games") as games:
            for i in range(winreg.QueryInfoKey(games)[0]):
                try:
                    with winreg.OpenKey(games, winreg.EnumKey(games, i)) as g:
                        if "dark messiah" in winreg.QueryValueEx(g, "gameName")[0].lower():
                            out.append(winreg.QueryValueEx(g, "path")[0])
                except OSError:
                    pass
    except (ImportError, OSError):
        pass
    return out


def is_dark_messiah(folder):
    return bool(folder) and bool(glob.glob(os.path.join(folder, "vpks", "*_dir.vpk")))


def find_dark_messiah(given):
    if given:
        if not is_dark_messiah(given):
            fail("no Dark Messiah packs (vpks\\*_dir.vpk) in %s" % given)
        return given
    candidates = [os.path.join(lib, "steamapps", "common", DM_FOLDER) for lib in steam_libraries()] + gog_folders()
    for c in candidates:
        if is_dark_messiah(c):
            return os.path.normpath(c)
    print("  Dark Messiah wasn't found automatically.")
    folder = input("  Paste the Dark Messiah single player folder (the one with 'vpks' in it): ").strip().strip('"')
    if not is_dark_messiah(folder):
        fail("no Dark Messiah packs in %s - run again with --dark-messiah \"<folder>\"" % folder)
    return folder


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ---------------------------------------------------------------------------------------------------- install
def install_files():
    """(source in this folder, destination in the game). Everything Dark Messiah Combat puts into the game."""
    b = os.path.join(ROOT, "build")
    files = [(os.path.join(ROOT, "bin", "dmcombat.vtm"), os.path.join(GAME, "Bin", "loader", "dmcombat.vtm")),
             (os.path.join(b, "game", "dmcombat_dm.bin"), os.path.join(GAME, "dmcombat_dm.bin"))]
    for src_dir, dst_dir, pattern in (
            (os.path.join(b, "game", "models", "weapons", "dm_katana"),
             os.path.join(UP, "models", "weapons", "dm_katana"), "v_dm_katana_arm*"),
            (os.path.join(b, "game", "materials", "models", "weapons", "dm_katana"),
             os.path.join(UP, "materials", "models", "weapons", "dm_katana"), "*"),
            (os.path.join(b, "game", "materials", "hud", "new_ui"), os.path.join(UP, "materials", "hud", "new_ui"),
             "dm_adrenaline*"),
            (os.path.join(b, "game", "sound", "dmcombat"), os.path.join(UP, "sound", "dmcombat"), "*"),
            (os.path.join(b, "items"), os.path.join(UP, "vdata", "items"), "*.txt"),
            (os.path.join(b, "keys", "scripts"), os.path.join(UP, "scripts"), "*"),
            (os.path.join(b, "keys", "cfg"), os.path.join(UP, "cfg"), "*")):
        for src in sorted(glob.glob(os.path.join(src_dir, pattern))):
            files.append((src, os.path.join(dst_dir, os.path.basename(src))))
    return files


def install(args):
    print("Dark Messiah Combat for VTM Bloodlines - installer\n\nChecking requirements:")
    check_bloodlines()
    check_sdk()
    check_writable()
    if game_running():
        fail("close the game first (Vampire.exe is running).")
    if not os.path.exists(os.path.join(ROOT, "bin", "dmcombat.vtm")):
        fail("bin\\dmcombat.vtm (the plug-in) is missing: use the release download, or build it with build.bat.")
    dm = find_dark_messiah(args.dark_messiah)
    print("  Dark Messiah: %s" % dm)

    t0 = time.time()
    for i, (title, cmd) in enumerate(STEPS, 1):
        print("\n[%d/%d] %s" % (i, len(STEPS), title))
        r = subprocess.run([PY, os.path.join(ROOT, "tools", cmd[0])] + [a.replace("{dm}", dm) for a in cmd[1:]],
                           cwd=ROOT)
        if r.returncode:
            fail("step %d (%s) failed - see the messages above." % (i, title))

    print("\nInstalling into %s" % UP)
    files = install_files()
    missing = [s for s, d in files if not os.path.exists(s)]
    if missing or len(files) < 60:
        fail("the build is incomplete, nothing installed (missing: %s)" % ", ".join(missing[:5]))
    # files the game already had: originals are kept in backup/ by make_items.py / make_keys.py
    replaced = {d for s, d in files if os.path.basename(os.path.dirname(d)) in ("items", "scripts", "cfg")}
    for d in replaced:
        backup = os.path.join(ROOT, "backup", "items_orig" if d.endswith(".txt") and "items" in d else "keys_orig",
                              os.path.basename(d))
        if not os.path.exists(backup):
            fail("no backup of %s - nothing installed" % d)
    stale = glob.glob(os.path.join(UP, "models", "weapons", "dm_katana", "v_dm_katana*"))
    for p in stale:  # no models left over from an older build
        os.remove(p)
    for src, dst in files:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
    ini = os.path.join(GAME, "dmcombat.ini")
    ini_created = not os.path.exists(ini)
    if ini_created:
        shutil.copyfile(os.path.join(ROOT, "dist", "dmcombat.ini"), ini)
    r = subprocess.run([PY, os.path.join(ROOT, "tools", "make_keys.py"), "--bind"], cwd=ROOT)
    keys_ok = r.returncode == 0
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    json.dump({"installed": [{"path": os.path.relpath(d, GAME), "sha256": sha256(d),
                              "replaced": d in replaced} for s, d in files],
               "ini_created": ini_created, "dark_messiah": dm, "time": time.strftime("%Y-%m-%d %H:%M:%S")},
              open(MANIFEST, "w"), indent=1)
    print("\nDone in %d s: %d files installed (%d game files replaced, originals in backup\\)."
          % (time.time() - t0, len(files), len(replaced)))
    if not keys_ok:
        print("WARNING: your own key bindings (cfg\\config.cfg) could not be updated - see the message above. Set\n"
              "         \"Cast Discipline Power\" to Q yourself in Options > Keyboard (right mouse is the block).")
    print("Start the game with the Unofficial Patch (its shortcut, or Vampire.exe -game Unofficial_Patch).")
    print("Settings: dmcombat.ini in the game folder. Uninstall: install.bat --uninstall")


def uninstall(args):
    print("Dark Messiah Combat for VTM Bloodlines - uninstall")
    check_writable()
    if game_running():
        fail("close the game first (Vampire.exe is running).")
    if not os.path.exists(MANIFEST):
        fail("no install record (%s) - nothing to uninstall from this folder." % MANIFEST)
    m = json.load(open(MANIFEST))
    restored = removed = 0
    for e in m["installed"]:
        dst = os.path.join(GAME, e["path"])
        if e["replaced"]:
            kind = "items_orig" if e["path"].lower().endswith(".txt") and "items" in e["path"].lower() else "keys_orig"
            shutil.copyfile(os.path.join(ROOT, "backup", kind, os.path.basename(dst)), dst)
            restored += 1
        elif os.path.exists(dst):
            os.remove(dst)
            removed += 1
    for d in (os.path.join(UP, "models", "weapons", "dm_katana"), os.path.join(UP, "materials", "models", "weapons",
                                                                               "dm_katana"),
              os.path.join(UP, "sound", "dmcombat")):
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
    r = subprocess.run([PY, os.path.join(ROOT, "tools", "make_keys.py"), "--unbind"], cwd=ROOT)
    if r.returncode:
        print("WARNING: your key bindings could not be restored - set \"Cast Discipline Power\" in Options > Keyboard.")
    os.remove(MANIFEST)
    print("Removed %d files, restored %d original game files. dmcombat.ini and dmcombat.log stay in the game folder."
          % (removed, restored))


def main():
    sys.stdout.reconfigure(line_buffering=True)  # our lines in order with the tools' output
    ap = argparse.ArgumentParser(description="Dark Messiah Combat installer (offline)")
    ap.add_argument("--uninstall", action="store_true", help="remove Dark Messiah Combat, restore the replaced game files")
    ap.add_argument("--dark-messiah", help="the Dark Messiah single player folder, if not found automatically")
    args = ap.parse_args()
    uninstall(args) if args.uninstall else install(args)


if __name__ == "__main__":
    main()
