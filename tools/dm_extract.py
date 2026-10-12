"""Read what DMCombat needs from the player's own Dark Messiah install - no Crowbar, no other programs.

  python tools/dm_extract.py "<Dark Messiah Might and Magic Single Player folder>" [out dir, default build/dm]

Unpacks from Dark Messiah's packs (vpks/*_dir.vpk) the first-person arm (first_basic), its animations
(first_animations_basic, first_animations_sword), the arm's glove and sleeve textures (player_gloves_1, player_leather_2, player_leather_1) and the "adrenaline reached"
sound, and decodes the models (tools/dm_mdl.py) into the layout the build tools read (the earlier DMHL2 project's,
there made with Crowbar):
  <out>/dm_decomp/out/first_basic/First_Reference_basic.smd               skeleton + arm mesh
  <out>/dm_decomp/out/<anim model>/<anim model>.qc                        $animation ... { fps N }
  <out>/dm_decomp/out/<anim model>/<anim model>_anims/<animation>.smd
  <out>/dm_extract/<anim model>.json                                      sequences + events (tools/mdl44.py)
  <out>/dm_extract/mm/...                                                 the unpacked files
gen_sword_paths.py and build_arms.py read <out> (default build/dm; DMC_DMHL2 overrides). Everything stays on this PC (build/ is not shipped).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dm_mdl  # noqa: E402
import dm_vpk  # noqa: E402
import mdl44  # noqa: E402

MODELS = "mm/models/npc/player/"
FILES = [MODELS + "first_basic.mdl", MODELS + "first_basic.vvd", MODELS + "first_basic.dx90.vtx",
         MODELS + "first_animations_basic.mdl", MODELS + "first_animations_sword.mdl",
         "mm/materials/models/npc_player/player_gloves_1.vtf", "mm/materials/models/npc_player/player_leather_2.vtf",
         "mm/materials/models/npc_player/player_leather_1.vtf",
         "mm/sound/arkane/character_sheet/adrenaline_reached.wav"]
ANIM_MODELS = ["first_animations_basic", "first_animations_sword"]
STUDIO_DELTA = 0x4  # animdesc flag: additive pose layer (not used by DMCombat)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    dm = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "build", "dm")
    vpks = os.path.join(dm, "vpks")
    if not os.path.isdir(vpks):
        raise SystemExit("no vpks folder in %s - is this the Dark Messiah single player folder?" % dm)
    ext = os.path.join(out, "dm_extract")
    got = set(dm_vpk.extract(vpks, ext, FILES))
    missing = [f for f in FILES if f not in got]
    if missing:
        raise SystemExit("not found in Dark Messiah's packs: %s" % ", ".join(missing))
    print("unpacked %d files from %s" % (len(got), vpks))

    dec = os.path.join(out, "dm_decomp", "out")
    src = os.path.join(ext, *MODELS.split("/"))

    ref = dm_mdl.MDL(os.path.join(src, "first_basic.mdl"))
    d = os.path.join(dec, "first_basic")
    os.makedirs(d, exist_ok=True)
    ref.write_reference_smd(os.path.join(d, "First_Reference_basic.smd"))
    print("first_basic: %d bones, %d triangles" % (len(ref.bones), len(ref.mesh())))

    for name in ANIM_MODELS:
        m = dm_mdl.MDL(os.path.join(src, name + ".mdl"))
        d = os.path.join(dec, name)
        ad = os.path.join(d, name + "_anims")
        os.makedirs(ad, exist_ok=True)
        qc = ['$modelname "%s.mdl"\n' % name]
        n = skipped = 0
        for a in m.anims:
            if a["name"].startswith("@"):  # Valve's internal reference pose
                continue
            if a["flags"] & STUDIO_DELTA:
                skipped += 1
                continue
            m.write_anim_smd(a, os.path.join(ad, a["name"] + ".smd"))
            qc.append('$animation "%s" "%s_anims\\%s.smd" {\n\tfps %g\n}\n\n' % (a["name"], name, a["name"], a["fps"]))
            n += 1
        open(os.path.join(d, name + ".qc"), "w", newline="\n").write("".join(qc))
        json.dump(mdl44.read_model(os.path.join(src, name + ".mdl")), open(os.path.join(ext, name + ".json"), "w"),
                  indent=1)
        print("%s: %d animations (%d additive layers skipped), events -> %s.json" % (name, n, skipped, name))
    print("done -> %s  (use it as DMC_DMHL2)" % os.path.normpath(out))


if __name__ == "__main__":
    main()
