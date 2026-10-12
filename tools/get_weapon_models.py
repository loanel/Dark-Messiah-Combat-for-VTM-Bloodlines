"""Pull the Bloodlines melee weapon meshes out of the game and convert them for tools/weapon_prep.py (no Crowbar).

Extracts each model's .mdl and .dx80.vtx from the game's packs (the Unofficial Patch's loose copy wins, like in the
game) and converts it with tools/vtmb_mdl2smd.py:
  modelsrc/ground/<g_name>/<g_name>_REF.smd   katana, knife, tire iron (world models); fire axe, sledgehammer, torch
  modelsrc/wield/<w_name>/<w_name>_REF.smd    baton, bush hook, baseball bat, severed arm (their ground models use a
                                              vertex encoding we don't decode; the held models are the same meshes)
The katana (also the occult blade's mesh) is written as Crowbar wrote it (--crowbar-uv): the arm models were tuned on
that decompile. The files are the player's own game data and stay on this PC (modelsrc/ is not shipped).

usage: python tools/get_weapon_models.py
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAME = os.path.dirname(ROOT)
PY = sys.executable
sys.path.insert(0, HERE)
import vtmb_mdl2smd  # noqa: E402

# (model path in the game without extension, modelsrc subfolder, Crowbar-compatible output)
MODELS = [
    ("models/weapons/katana/world/g_katana", "ground", True),
    ("models/weapons/knife/world/g_knife", "ground", False),
    ("models/weapons/tireiron/world/g_tireiron", "ground", False),
    ("models/weapons/fire_axe/ground/g_fire_axe", "ground", False),
    ("models/weapons/sledgehammer/ground/g_sledgehammer", "ground", False),
    ("models/weapons/torch/ground/g_torch", "ground", False),
    ("models/weapons/baton/wield/w_m_baton", "wield", False),
    ("models/weapons/bushhook/wield/w_m_bushhook", "wield", False),
    ("models/weapons/baseball_bat/wield/w_m_baseball_bat", "wield", False),
    ("models/weapons/severed_arm/wield/w_m_severed_arm", "wield", False),
]


def main():
    vtmb_mdl2smd.MODEL_SIZE = vtmb_mdl2smd.probe(None)
    work = os.path.join(ROOT, "extract", "weapons")
    failed = []
    for path, kind, crowbar in MODELS:
        subprocess.run([PY, os.path.join(HERE, "vtmbvpk.py"), os.path.join(GAME, "Vampire"), "x",
                        re.escape(path) + r"\.(mdl|dx80\.vtx)$", work], capture_output=True)
        src = os.path.join(work, path)
        for ext in (".mdl", ".dx80.vtx"):  # the Unofficial Patch's loose files win
            up = os.path.join(GAME, "Unofficial_Patch", path + ext)
            if os.path.exists(up):
                os.makedirs(os.path.dirname(src), exist_ok=True)
                shutil.copyfile(up, src + ext)
        stem = os.path.basename(path)
        if not (os.path.exists(src + ".mdl") and os.path.exists(src + ".dx80.vtx")):
            print("  %s: not found in the game" % stem)
            failed.append(stem)
            continue
        ref, n, tex, cds = vtmb_mdl2smd.convert(src + ".mdl", os.path.join(ROOT, "modelsrc", kind, stem), crowbar)
        print("  %-18s %4d triangles  %s" % (stem, n, ", ".join(tex)))
    if failed:
        raise SystemExit("missing weapon models: %s" % ", ".join(failed))


if __name__ == "__main__":
    main()
