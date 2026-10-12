"""Build the animated arm viewmodels with the Bloodlines SDK (see tools/build_katana_arm.py).

  v_dm_katana_arm.mdl              base model named in the melee item files (Dark Messiah's arm only)
  v_dm_katana_arm_<character>.mdl  one per player character in modelsrc/pc_auto (tools/get_pc_models.py); variant N =
                                   outfit armor_N; the plug-in swaps it in at runtime

usage: python tools/build_arms.py [character ...]     (default: base + every character found)
Needs tools/dm_extract.py's output (build/dm, or DMC_DMHL2) and the SDK in <Bloodlines>\\SDKBinaries
(studiomdl-sw.exe compiles, studiovtmb49k.exe converts to Bloodlines' format). Output: build/game/models/...
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAME = os.path.dirname(ROOT)
SDK = os.path.join(GAME, "SDKBinaries")
PY = sys.executable
DONOR = os.path.join(ROOT, "extract", "vmall", "models", "weapons", "thaumaturgy", "view", "v_thaumaturgy.mdl")
OUT_DIR = os.path.join(ROOT, "build", "game", "models", "weapons", "dm_katana")
SWARM = os.path.join(ROOT, "build", "swarm")


def characters():
    names = set()
    pc = os.path.join(ROOT, "modelsrc", "pc_auto")
    for d in os.listdir(pc) if os.path.isdir(pc) else []:
        m = re.match(r"(.+)_armor_\d$", d)
        if m:
            names.add(m.group(1))
    return sorted(names)


def build(character, dm):
    model = "v_dm_katana_arm" + ("" if character == "base" else "_" + character)
    out_mdl = os.path.join(OUT_DIR, model + ".mdl")
    for ext in (".mdl", ".dx80.vtx", ".dx7_2bone.vtx"):
        if os.path.exists(os.path.join(OUT_DIR, model + ext)):
            os.remove(os.path.join(OUT_DIR, model + ext))
    args = [PY, os.path.join(HERE, "build_katana_arm.py"), dm, DONOR] + ([] if character == "base" else
                                                                          ["--character", character])
    r = subprocess.run(args, capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if not line.startswith("  pc arm") and "attack side" not in line:
            print(line)
    if r.returncode:
        print(r.stderr)
        return False
    qc = os.path.join(ROOT, "modelsrc", "v_dm_katana_arm", model, model + ".qc")
    with open(os.path.join(SWARM, model + ".log"), "w") as log:
        subprocess.run([os.path.join(SDK, "studiomdl-sw.exe"), "-game", SWARM, "-nop4", qc], cwd=SDK,
                       stdout=log, stderr=subprocess.STDOUT)
    # folders end in "/": a trailing backslash before the closing quote of a path with spaces escapes the quote
    subprocess.run([os.path.join(SDK, "studiovtmb49k.exe"), "dummy",
                    ROOT + "/modelsrc/v_dm_katana_arm/" + model + "/",
                    ROOT + "/build/game/",
                    os.path.join(SWARM, "models", "weapons", "dm_katana", model + ".mdl")],
                   cwd=SDK, capture_output=True)
    if not os.path.exists(out_mdl):
        print("!!! %s FAILED (compile log: build/swarm/%s.log)" % (model, model))
        return False
    r = subprocess.run([PY, os.path.join(HERE, "strip_mdl_events.py"), out_mdl], capture_output=True, text=True)
    print((r.stdout.strip().splitlines() or [""])[-1])
    return r.returncode == 0


def main():
    dm = os.environ.get("DMC_DMHL2") or os.path.join(ROOT, "build", "dm")
    if not os.path.isdir(os.path.join(dm, "dm_decomp", "out", "first_basic")):
        raise SystemExit("no Dark Messiah data in %s - run: python tools/dm_extract.py \"<Dark Messiah folder>\"" % dm)
    for exe in ("studiomdl-sw.exe", "studiovtmb49k.exe", os.path.join("assets", "gameinfo.txt")):
        if not os.path.exists(os.path.join(SDK, exe)):
            raise SystemExit("Bloodlines SDK file missing: %s" % os.path.join(SDK, exe))
    if not os.path.exists(DONOR):
        subprocess.run([PY, os.path.join(HERE, "vtmbvpk.py"), os.path.join(GAME, "Vampire"), "x",
                        r"models/weapons/thaumaturgy/view/v_thaumaturgy\.mdl", os.path.join(ROOT, "extract", "vmall")],
                       check=True, capture_output=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(SWARM, exist_ok=True)
    shutil.copyfile(os.path.join(SDK, "assets", "gameinfo.txt"), os.path.join(SWARM, "gameinfo.txt"))
    chars = sys.argv[1:] or ["base"] + characters()
    failed = [c for c in chars if not build(c, dm)]
    if failed:
        raise SystemExit("FAILED MODELS: %s" % " ".join(failed))
    print("all models built (%d)" % len(chars))


if __name__ == "__main__":
    main()
