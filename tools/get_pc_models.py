"""Pull Bloodlines player models out of the game and convert them for build_katana_arm.py (no Crowbar needed).

For every player model whose path matches the pattern: extract its .mdl and .dx80.vtx from the game's VPKs, prefer the
Unofficial Patch's loose copy where one exists, and convert it with tools/vtmb_mdl2smd.py into
modelsrc/pc_auto/<name>/ (<name>.qc + <name>_REF.smd). The files are the user's own game data and stay local.

usage: python tools/get_pc_models.py [path regex]     default: male Toreador, all four outfits
  e.g. "models/character/pc/(male|female)/toreador/"   or   "models/character/pc/.*/"  (every clan, both genders)
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

pattern = sys.argv[1] if len(sys.argv) > 1 else "models/character/pc/male/toreador/"
listing = subprocess.run([PY, os.path.join(HERE, "vtmbvpk.py"), os.path.join(GAME, "Vampire"), "list",
                          pattern + r".*\.mdl$"], capture_output=True, text=True).stdout
paths = sorted({l.split()[1] for l in listing.splitlines() if len(l.split()) >= 2})
print("%d player models match %s" % (len(paths), pattern))
vtmb_mdl2smd.MODEL_SIZE = vtmb_mdl2smd.probe(None)
for mdl in paths:
    # name by path, not by file: the files are inconsistent (malk_girl_armor_1, plain "nosferatu" for the male base
    # outfit...), the folders aren't: models/character/pc/<gender>/<clan>/armor<N> (gangrel male: armor_<N>)
    m = re.match(r"models/character/pc/(male|female)/([a-z]+)/armor_?(\d)/", mdl.lower())
    if not m or "beastial" in mdl.lower():  # gangrel_male_beastial (frenzy form) shares armor_0's folder
        print("  %s: not a clan outfit, skipped" % mdl)
        continue
    name = "%s_%s_armor_%s" % (m.group(2), m.group(1), m.group(3))
    work = os.path.join(ROOT, "extract", "pc_auto")
    stem = re.escape(os.path.splitext(mdl)[0])
    subprocess.run([PY, os.path.join(HERE, "vtmbvpk.py"), os.path.join(GAME, "Vampire"), "x",
                    stem + r"\.(mdl|dx80\.vtx)$", work], capture_output=True)
    src = os.path.join(work, mdl)
    for ext in (".mdl", ".dx80.vtx"):  # the Unofficial Patch's loose files win, like in the game
        up = os.path.join(GAME, "Unofficial_Patch", os.path.splitext(mdl)[0] + ext)
        if os.path.exists(up):
            shutil.copyfile(up, os.path.splitext(src)[0] + ext)
    if not os.path.exists(src) or not os.path.exists(os.path.splitext(src)[0] + ".dx80.vtx"):
        print("  %s: missing files, skipped" % name)
        continue
    try:
        ref, n, tex, cds = vtmb_mdl2smd.convert(src, os.path.join(ROOT, "modelsrc", "pc_auto", name))
        print("  %s: %d triangles" % (name, n))
    except Exception as e:  # noqa: BLE001
        print("  %s: conversion failed (%s)" % (name, e))
