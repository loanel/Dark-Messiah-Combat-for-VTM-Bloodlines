"""Build the animated katana viewmodel source: an arm + Bloodlines' katana, skinned to the skeleton of Bloodlines' own
Thaumaturgy viewmodel (v_thaumaturgy.mdl, 42 bones) (the SDK can't compile animations; its formatter studiovtmb49k turns a model compiled with the Alien
Swarm studiomdl into a Bloodlines model that reuses an existing Bloodlines skeleton).

The plug-in drives the bones itself every frame (dm_viewmodel.cpp): donor bone <- the Dark Messiah bone mapped to it,
  boneToWorld = eye * (tilt|offset) * D(frame) * inverse(poseToBone)   with   D = E_frame(dm bone) * inverse(E_ref)
so every mesh is written in Dark Messiah's reference pose, in eye space (x forward, y left, z up; DMHL2's F_PREVIEW).
Arm variants: the formatter keeps one model per bodypart, so every variant is in the same mesh on its own block of 7
donor bones (variant v: bones 1+7v .. 7+7v, in the order Spine_4, Collarbone, Shoulder, Elbow, Forearm twist, Wrist,
Hand). The plug-in drives the selected variant's block and collapses the others to a point (invisible). The donor's
hierarchy and animations don't matter: every bone with vertices is overwritten.
  0 = Dark Messiah's arm (fallback), then every Bloodlines player model in modelsrc/pc_auto/ (tools/get_pc_models.py)
  (its right arm retargeted onto DM's, tools/pc_arm.py; its own materials). 5 variants fit in the 42-bone donor.
Finger vertices are baked into their pose relative to the hand at a gripping frame (sword idle frame 0); the katana
goes on the hand at DM's sword mount with the rigid sword's katana -> sword mapping.
Writes src/dmcombat/dm_armvariants.h (player model file name -> variant).

Inputs: the user's own Dark Messiah files read by tools/dm_extract.py (build/dm), the Bloodlines weapons and player models
converted by tools/get_weapon_models.py / get_pc_models.py, and the game's v_pistol_glock.mdl. Outputs (modelsrc/v_dm_katana_arm, never shipped).

usage: python tools/build_katana_arm.py <Dark Messiah data dir (build/dm)> <v_thaumaturgy.mdl> [--grip -13]
"""
import argparse
import collections
import glob
import itertools
import math
import os
import re
import shutil
import sys

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("dmhl2")
ap.add_argument("donor")
ap.add_argument("--grip", type=float, default=-13.0)
ap.add_argument("--grip-anim", default="anm_sword_noshield_idle")
ap.add_argument("--thumb-along", type=float, default=0.3, help="character thumbs: swing towards the guard, 0 = DM grip, 1 = fully along the handle")
ap.add_argument("--thumb-wrap", type=float, default=0.0, help="character thumbs: degrees around the handle axis (user pick 2026-10-10: along 0.3, wrap 0)")
ap.add_argument("--own-hands", action="store_true", help="character arms: keep each outfit's own hand (default: every outfit gets the base outfit armor_0's hand, only the sleeve changes - user request 2026-10-11)")
ap.add_argument("--hand-extend", type=float, default=2.0, help="character arms: the base hand reaches this far (units) up the forearm under the outfit's sleeve, so short sleeves leave no gap")
ap.add_argument("--wrist-to-hand", type=float, default=0.5, help="character arms: share of the Bloodlines wrist helper bone's weight moved to the hand, so sleeve ends and glove cuffs bend with DM's cocked grip instead of sticking out over the hand (brujah heavy leather, 2026-10-11)")
ap.add_argument("--weapon-smd", help="use this katana-space weapon mesh (tools/weapon_prep.py) instead of the katana")
ap.add_argument("--character", help="e.g. toreador_male: its outfits as variants 1-4 (default: base model, DM arm only)")
args = ap.parse_args()

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import smd  # noqa: E402  (tools/smd.py)
import pc_arm  # noqa: E402
import vtmb_bones  # noqa: E402

DEC = os.path.join(args.dmhl2, "dm_decomp", "out")
KATANA = os.path.join(ROOT, "modelsrc", "ground", "g_katana", "g_katana_REF.smd")  # --weapon-smd overrides (previews)
OUT = os.path.join(ROOT, "modelsrc", "v_dm_katana_arm")
OUT_H = os.path.join(ROOT, "src", "dmcombat", "dm_armvariants.h")
XMODEL = "vthaum"  # the formatter finds xmodel/<first chunk of the ref smd name>.mdl

F = np.eye(4)
F[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
F[:3, 3] = (-6.0, 0.0, 10.0)
ATTACH = smd.make((-3.0, 0.0, 0.0), tuple(math.radians(a) for a in (90.0, 0.0, 0.0)))
ROLL = np.eye(4)
ROLL[:3, :3] = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
FIX = np.eye(4)
FIX[:3, :3] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]
FIX[:3, 3] = -(FIX[:3, :3] @ np.array([0, 0, args.grip]))

# slot in each variant's bone block (same order as ARM_DM_BONES in gen_sword_paths.py)
DRIVE = {"SK_Spine_4": 0, "SK_R_Collarbone": 1, "SK_R_Shoulder": 2, "SK_R_Elbow": 3, "SK_R_Forearm": 4,
         "SK_R_Wrist": 5, "SK_R_Hand": 6}
HAND_SLOT = 6
BLOCK = 7


import weapon_prep  # noqa: E402  (weapon list/order)
NW = len(weapon_prep.WEAPONS)


def block_base(v):
    return 1 + NW + BLOCK * v
MATS = {"player_gloves_1": "dm_glove", "player_leather_2": "dm_sleeve", "player_leather_1": "dm_sleeve2"}

# Unlike static props (turned +90 deg about z by studiomdl), animated models compile as written: SMD space = model space
# (checked: the compiled .vvd vertex extents equal the SMD's). Model space is Dark Messiah's eye space.


def read_tris(s):
    """SMD triangles -> (material, [(pos4, normal3, uv, [(bone, weight)])] * 3)."""
    cur, mat = [], None
    for line in s.triangles:
        v = line.split()
        if len(v) < 9:
            mat = line.strip()
            continue
        links = [(int(v[10 + 2 * k]), float(v[11 + 2 * k])) for k in range(int(v[9]))] \
            if len(v) > 9 and int(v[9]) > 0 else [(int(v[0]), 1.0)]
        cur.append((np.array([*map(float, v[1:4]), 1.0]), np.array([*map(float, v[4:7])]),
                    (float(v[7]), float(v[8])), links))
        if len(cur) == 3:
            yield mat, cur
            cur = []


def dm_triangles(ref, E_ref):
    """Dark Messiah's own arm mesh (gloves/leather), already in DM's reference pose."""
    for mat, tri in read_tris(ref):
        m = MATS.get(mat.lower())
        yield m, [(F @ p, F[:3, :3] @ n, uv, links) for p, n, uv, links in tri] if m else None


# Outfits that keep their own hand (gloves, or the base hand didn't fit their sleeve) - user's in-game check
# 2026-10-11. Everything else gets the base outfit's hand.
OWN_HANDS = {("malkavian_male", 2), ("malkavian_male", 3),
             ("malkavian_female", 1), ("malkavian_female", 2), ("malkavian_female", 3),
             ("nosferatu_male", 3),
             ("toreador_male", 1), ("toreador_male", 2), ("toreador_male", 3),
             ("tremere_male", 2)}  # tremere_male 2: skin showed through an opening in the sleeve (10-11)
HAND_EXTEND = {("ventrue_male", 2): 0.0, ("ventrue_male", 3): 0.0}  # (character, outfit) -> units, overrides --hand-extend (ventrue_male 2-3: tight sleeves, the extension poked through; no gap without it)
TAPER = 0.3  # the base hand's forearm extension is up to 30% thinner at its top end (inside the sleeve)
# outfit materials left out on purpose (user, 2026-10-11): toreador_female outfit 2's feather frill bristles around
# the hand in first person
LEAVE_OUT = {("toreador_female", 2): {"TorFA2cuff"}}


def _tri_samples(P, n):
    return [P[0] + (P[1] - P[0]) * a / n + (P[2] - P[0]) * b / n for a in range(n + 1) for b in range(n + 1 - a)]


def hand_cloud(v, extend):  # extend 0 for "is this sleeve piece covered": the extension is bare skin
    """Points over the surface of a player model's hand (as pc_triangles(part="hand") takes it), in its bind pose."""
    pc = smd.SMD.read(v["ref"])
    handish = {i for i, n, _ in pc.nodes if n == "Bip01 R Hand" or n.startswith("Bip01 R Finger")}
    g0 = pc.globals(0)
    W = g0[pc.index("Bip01 R Hand")][:3, 3]
    up = g0[pc.index("Bip01 R Forearm")][:3, 3] - W
    up /= np.linalg.norm(up)
    pts = []
    for _, tri in read_tris(pc):
        P = [p[:3] for p, _, _, _ in tri]
        hw = sum(w for _, _, _, links in tri for b, w in links if b in handish) / 3
        if hw > 0.5 or all(np.dot(q - W, up) < extend for q in P):
            pts += _tri_samples(P, 6)
    return np.array(pts)


def pc_triangles(ref, E_ref, v, part="all", extend=0.0, keep_off=None):
    """A Bloodlines player model's right arm, retargeted onto DM's reference arm (tools/pc_arm.py).
    part: "all", "hand" (triangles mostly on the hand and finger bones) or "sleeve" (the rest)."""
    pc = smd.SMD.read(v["ref"])
    idle_g = None
    if v.get("idle"):
        idle = smd.SMD.read(v["idle"])
        idle.nodes = pc.nodes
        idle_g = idle.globals(0, pc.frames[0])
    amap = pc_arm.retarget(ref, E_ref, pc, pc.globals(0), idle_g, log=lambda s: print("  " + s))
    names_pc = {n for _, n, _ in pc.nodes}
    wrist_pc = pc.index("Bip01 R Wrist") if "Bip01 R Wrist" in names_pc else -1
    hand_pc = pc.index("Bip01 R Hand")
    handish = {i for i, n, _ in pc.nodes if n == "Bip01 R Hand" or n.startswith("Bip01 R Finger")}
    g0 = pc.globals(0)
    wrist_at = g0[hand_pc][:3, 3]
    up_arm = g0[pc.index("Bip01 R Forearm")][:3, 3] - wrist_at
    up_arm /= np.linalg.norm(up_arm)
    for mat, tri in read_tris(pc):
        if part != "all":
            hw = sum(w for _, _, _, links in tri for b, w in links if b in handish) / 3
            is_hand = hw > 0.5
            if part == "sleeve" and is_hand and keep_off is not None:
                # the outfit's own wrist-area pieces the base hand doesn't cover (cuff ends, sleeve rims weighted to
                # the hand) stay, or the sleeve has holes: within 1.5 units of the wrist joint and > 0.3 units off
                # the base hand's surface
                P = [p[:3] for p, _, _, _ in tri]
                if np.dot(sum(P) / 3 - wrist_at, up_arm) > -1.5 and                         max(np.linalg.norm(keep_off - q, axis=1).min() for q in _tri_samples(P, 2)) > 0.3:
                    is_hand = False
            if part == "hand" and not is_hand and extend > 0:
                # extended hand: also the forearm surface up to <extend> units above the wrist joint, which the
                # outfit's sleeve covers - where the sleeve ends short of the base hand there's no gap
                # all three corners (long forearm triangles reaching far up the arm poked through the sleeves)
                is_hand = all(np.dot(p[:3] - wrist_at, up_arm) < extend for p, _, _, _ in tri)
            if is_hand != (part == "hand"):
                continue
        out = []
        for p, n, uv, links in tri:
            if part == "hand" and extend > 0:
                # the base hand's forearm part tapers towards the arm's axis (up to TAPER thinner at <extend> above
                # the wrist joint), so it stays inside the outfit's sleeve (ventrue_male's bare forearm is thicker
                # than his sleeves and poked through)
                t = np.dot(p[:3] - wrist_at, up_arm)
                if t > 0:
                    radial = p[:3] - wrist_at - t * up_arm
                    p = p.copy()
                    p[:3] -= radial * TAPER * min(t / extend, 1.0)
            mapped = []
            for b, w in links:
                if b not in amap:
                    continue
                if b == wrist_pc and hand_pc in amap and args.wrist_to_hand > 0:
                    mapped.append((amap[hand_pc], w * args.wrist_to_hand))
                    w *= 1 - args.wrist_to_hand
                mapped.append((amap[b], w))
            ws = sum(w for _, w in mapped)
            if ws < 0.5:  # torso, head, left arm, eyes, teeth
                out = None
                break
            pos, nn, dl = np.zeros(4), np.zeros(3), []
            for (a, dmb), w in mapped:
                pos += (w / ws) * (a @ p)
                nn += (w / ws) * (a[:3, :3] @ n)
                dl.append((dmb, w / ws))
            out.append((pos, nn / (np.linalg.norm(nn) or 1), uv, dl))
        yield (mat, out) if out else (None, None)


def find_pc_models():
    """Player models converted by tools/get_pc_models.py (modelsrc/pc_auto/<name>/<name>.qc + _REF.smd)."""
    out, seen = [], set()
    for qc in sorted(glob.glob(os.path.join(ROOT, "modelsrc", "pc_auto", "*", "*.qc"))):
        text = open(qc, encoding="latin1").read()
        name = re.search(r'\$modelname\s+"([^"]+)"', text)
        studio = re.search(r'studio\s+"([^"]+)"', text)
        if not name or not studio:
            continue
        key = os.path.basename(os.path.dirname(qc)).lower()  # <clan>_<gender>_armor_<N> (tools/get_pc_models.py)
        ref = os.path.join(os.path.dirname(qc), studio.group(1) + ".smd")
        if key in seen or not os.path.exists(ref):
            continue
        seen.add(key)
        out.append(dict(key=key, ref=ref, idle=None, cd=re.findall(r'\$cdmaterials\s+"([^"]+)"', text)))
    return out


def katana_tris(E_ref, hand, hand_bone, path=None):
    """A katana-space weapon mesh (tools/weapon_prep.py) on the reference hand at DM's sword mount, on one bone."""
    mount = E_ref[hand] @ ATTACH @ ROLL @ FIX
    katana = [l.rstrip("\n") for l in open(path or args.weapon_smd or KATANA, encoding="latin1")]
    i = katana.index("triangles") + 1
    tris, cur, mat = [], [], None
    while i < len(katana) and katana[i].strip() != "end":
        v = katana[i].split()
        i += 1
        if len(v) < 9:
            mat = katana[i - 1].strip()
            continue
        p = mount @ np.array([*map(float, v[1:4]), 1.0])
        nrm = mount[:3, :3] @ np.array([*map(float, v[4:7])])
        cur.append((p[:3], nrm, (float(v[7]), float(v[8])), [(hand_bone, 1.0)]))
        if len(cur) == 3:
            tris.append((mat, cur))
            cur = []
    return tris


def main():
    ref = smd.SMD.read(os.path.join(DEC, "first_basic", "First_Reference_basic.smd"))
    names = {i: n for i, n, p in ref.nodes}
    parent = {i: p for i, n, p in ref.nodes}
    hand = ref.index("SK_R_Hand")

    def under_hand(i):
        i = parent[i]
        while i >= 0:
            if i == hand:
                return True
            i = parent[i]
        return False

    target = {}  # dm bone -> (slot in the variant's bone block, bake matrix)
    E_ref = {b: F @ m for b, m in ref.globals(0).items()}
    a = smd.SMD.read(os.path.join(DEC, "first_animations_basic", "first_animations_basic_anims", args.grip_anim + ".smd"))
    a.nodes = ref.nodes
    E_grip = {b: F @ m for b, m in a.globals(0, ref.frames[0]).items()}
    hand_rel = E_ref[hand] @ np.linalg.inv(E_grip[hand])
    for i, n in names.items():
        if n in DRIVE:
            target[i] = (DRIVE[n], np.eye(4))
        elif under_hand(i):  # finger/thumb: its grip pose relative to the hand, in the hand's reference frame
            target[i] = (HAND_SLOT, hand_rel @ E_grip[i] @ np.linalg.inv(E_ref[i]))

    # Thumb along the handle (character hands): Dark Messiah's grip wraps the thumb across the grip, which its glove
    # hides; Bloodlines' long bare thumbs then stick out sideways. Their baked thumb is turned about its base joint
    # until it points along the handle towards the blade (vertices partly on the thumb turn partly).
    thumbs = {i for i, n in names.items() if "thumb" in n.lower()}
    t1, t4 = ref.index("Sk_R_Thumb_1"), ref.index("Sk_R_Thumb_4")
    J = (hand_rel @ E_grip[t1])[:3, 3]
    tdir = (hand_rel @ E_grip[t4])[:3, 3] - J
    tdir /= np.linalg.norm(tdir)
    mount = E_ref[hand] @ ATTACH @ ROLL @ FIX
    blade = mount[:3, :3] @ np.array([0.0, 0.0, 1.0])  # katana model +z = towards the blade
    blade /= np.linalg.norm(blade)
    axis = np.cross(tdir, blade)
    ang = math.atan2(np.linalg.norm(axis), np.dot(tdir, blade)) * args.thumb_along
    axis = axis / (np.linalg.norm(axis) or 1)
    K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    R_thumb = np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * K @ K
    # wrap: turn the thumb around the handle's own axis (through the grip centre), degrees, after the swing
    wa = math.radians(args.thumb_wrap)
    Kb = np.array([[0, -blade[2], blade[1]], [blade[2], 0, -blade[0]], [-blade[1], blade[0], 0]])
    R_wrap = np.eye(3) + math.sin(wa) * Kb + (1 - math.cos(wa)) * Kb @ Kb
    C_grip = mount[:3, 3]
    print("thumb: swing %.0f deg (thumb_along %.2f), wrap %.0f deg" % (math.degrees(ang), args.thumb_along, args.thumb_wrap))

    def arm_tris(source, base, align_thumb=False):
        tris, dropped = [], 0
        for mat, tri in source:
            if mat is None:
                dropped += 1
                continue
            out, ok = [], True
            for p, nrm, uv, links in tri:
                mapped = [(target[b], w) for b, w in links if b in target]
                wsum = sum(w for _, w in mapped)
                if wsum < 0.5:  # mostly skinned to bones we don't drive (left arm, head)
                    ok = False
                    break
                pos, nn, weights = np.zeros(3), np.zeros(3), {}
                for (gb, bake), w in mapped:
                    w /= wsum
                    pos += w * (bake @ p)[:3]
                    nn += w * (bake[:3, :3] @ nrm)
                    weights[base + gb] = weights.get(base + gb, 0) + w
                if align_thumb:
                    tw = sum(w for b, w in links if b in thumbs) / wsum
                    if tw > 0:
                        moved = R_thumb @ (pos - J) + J
                        moved = R_wrap @ (moved - C_grip) + C_grip
                        pos = pos + tw * (moved - pos)
                        nn = nn + tw * (R_wrap @ R_thumb @ nn - nn)
                top = sorted(weights.items(), key=lambda kv: -kv[1])[:3]
                s = sum(w for _, w in top)
                out.append((pos, nn / (np.linalg.norm(nn) or 1), uv, [(b, w / s) for b, w in top]))
            if ok:
                tris.append((mat, out))
            else:
                dropped += 1
        return tris, dropped

    bones = vtmb_bones.read_bones(args.donor)
    skel = ["version 1", "nodes"] + ['%d "%s" %d' % (k, b["name"], b["parent"]) for k, b in enumerate(bones)]
    skel += ["end", "skeleton", "time 0"]
    for k, b in enumerate(bones):
        m = np.eye(4)
        m[:3, :3] = vtmb_bones.quat_matrix(*b["quat"])
        m[:3, 3] = b["pos"]
        pos, rot = smd.split(m)
        skel.append("%d %.6f %.6f %.6f %.6f %.6f %.6f" % (k, *pos, *rot))
    skel += ["end"]

    def vline(pos, nn, u, w, links):
        return "%d %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %d %s" % (
            links[0][0], *pos, *nn, u, w, len(links), " ".join("%d %.6f" % bw for bw in links))

    def write_smd(fname, tris, backfaces):
        lines = skel + ["triangles"]
        for m, verts in tris:
            lines.append(m)
            lines += [vline(pos, nn, u, w, l) for pos, nn, (u, w), l in verts]
            if backfaces and m in MATS.values():  # Dark Messiah's arm is one-sided
                lines.append(m)
                lines += [vline(pos, -nn, u, w, l) for pos, nn, (u, w), l in reversed(verts)]
        lines.append("end")
        open(os.path.join(OUT, fname), "w", newline="\n").write("\n".join(lines) + "\n")

    model = "v_dm_katana_arm" + ("_" + args.character if args.character else "")
    out = os.path.join(OUT, model)
    os.makedirs(os.path.join(out, "xmodel"), exist_ok=True)
    for old in glob.glob(os.path.join(out, "*.smd")):
        os.remove(old)
    # Bone layout (dm_armvariants.h): bones 1..NW = one per melee weapon (weapon_prep.WEAPONS order, the plug-in shows
    # the held one), then 7-bone arm blocks from ARM_FIRST. Base model: block 0 = Dark Messiah's arm. Character model:
    # block N = the character's outfit armor_N (no DM arm - the base model has it, and the bones are needed).
    all_tris, cds = [], ["models/weapons/dm_katana/", "models/weapons/katana/"]  # ours first, then the katana's
    for w, name in enumerate(weapon_prep.WEAPONS):
        tris = katana_tris(E_ref, hand, 1 + w, os.path.join(ROOT, "modelsrc", "weapons", name + ".smd"))
        all_tris += tris
        src_dir = os.path.dirname(os.path.join(ROOT, weapon_prep.WEAPONS[name][0]))
        for qc in glob.glob(os.path.join(src_dir, "*.qc")):
            cds += [c for c in re.findall(r'\$cdmaterials\s+"([^"]+)"', open(qc, encoding="latin1").read()) if c not in cds]
    print("%s: %d weapons on bones 1-%d" % (model, NW, NW))
    n_weapon_tris = len(all_tris)
    if not args.character:
        tris, dropped = arm_tris(dm_triangles(ref, E_ref), block_base(0))
        print("  block 0: Dark Messiah arm, %d triangles" % len(tris))
        all_tris += tris
    else:
        for v in find_pc_models():
            m = re.match(re.escape(args.character) + r"_armor_(\d)$", v["key"])
            if not m:
                continue
            k = int(m.group(1))
            if block_base(k) + 6 >= len(bones):
                print("  %s: no room in the donor skeleton, skipped" % v["key"])
                continue
            base = next((b for b in find_pc_models() if b["key"] == args.character + "_armor_0"), None)
            if k == 0 or args.own_hands or not base or (args.character, k) in OWN_HANDS:
                src = pc_triangles(ref, E_ref, v)
            else:  # the base outfit's hand inside this outfit's sleeve
                ext = HAND_EXTEND.get((args.character, k), args.hand_extend)
                src = itertools.chain(pc_triangles(ref, E_ref, v, "sleeve", keep_off=hand_cloud(base, 0.0)),
                                      pc_triangles(ref, E_ref, base, "hand", ext))
                cds += [c for c in base["cd"] if c not in cds]
            tris, dropped = arm_tris(src, block_base(k), align_thumb=True)
            skip = LEAVE_OUT.get((args.character, k), set())
            if skip:
                tris = [t for t in tris if t[0] not in skip]
            print("  block %d: %s, %d arm triangles (%s)" % (k, v["key"], len(tris), ", ".join(sorted({m for m, _ in tris}))))
            all_tris += tris
            cds += [c for c in v["cd"] if c not in cds]
    # studiovtmb49k's formatter fails silently (exit 1, no output) with more than 22 materials in a model (found by
    # bisecting toreador_female, 23). Over the limit, the outfits' smallest decorations go (never weapons or hands).
    MAX_MATERIALS = 22
    weapon_mats = {m for m, _ in all_tris[:n_weapon_tris]}
    on_hand, tris_of = collections.Counter(), collections.Counter()
    for m, verts in all_tris[n_weapon_tris:]:
        tris_of[m] += 1
        on_hand[m] += all((max(l, key=lambda bw: bw[1])[0] - block_base(0)) % 7 == 6 for _, _, _, l in verts)
    hand_mats = {m for m in tris_of if on_hand[m] > tris_of[m] / 2}
    while len({m for m, _ in all_tris}) > MAX_MATERIALS:
        counts = collections.Counter(m for m, _ in all_tris if m not in weapon_mats | hand_mats)
        if not counts:
            break
        drop, n = min(counts.items(), key=lambda kv: kv[1])
        print("  WARNING: over %d materials - outfit material %s (%d triangles) left out" % (MAX_MATERIALS, drop, n))
        all_tris = [t for t in all_tris if t[0] != drop]
    ref_name = XMODEL + "_katana_arm_ref"
    write_smd(os.path.join(model, ref_name + ".smd"), all_tris, True)
    shutil.copyfile(args.donor, os.path.join(out, "xmodel", XMODEL + ".mdl"))

    # texture folders: normalised and deduplicated, without the player models' ones the arm never uses (teeth, eyes,
    # held guns) - studiovtmb49k's formatter fails silently with too many (toreador_female had 26)
    norm = []
    for c in cds:
        c = c.replace("/", "\\").lstrip("\\")
        low = c.lower().rstrip("\\")
        if low.endswith(("teeth", "eyes")) or (low.endswith("\\wield") and "katana" not in low):
            continue
        if low not in [n.lower().rstrip("\\") for n in norm]:
            norm.append(c)
    cd_lines = "".join('$cdmaterials "%s"\n' % c for c in norm)
    qc = f'''// GENERATED by tools/build_katana_arm.py
$modelname "weapons/dm_katana/{model}.mdl"
$body "arm" "{ref_name}"
{cd_lines}$surfaceprop "Kitchen_Utensils"
$sequence "idle" "{ref_name}" fps 30
'''
    open(os.path.join(out, model + ".qc"), "w", newline="\n").write(qc)

    h = ["// GENERATED by tools/build_katana_arm.py. Arm models: bones 1..DM_NUM_WEAPON_BONES = the melee weapons",
         "// (dm_weapons.h order), then 7-bone arm blocks: base model block 0 = Dark Messiah's arm, character model block N",
         "// = the character's outfit armor_N (read from the player's model path).",
         "#pragma once", "",
         "static const int DM_NUM_WEAPON_BONES = %d;" % NW,
         "static const int DM_ARM_VARIANTS = %d;" % ((len(bones) - 1 - NW) // BLOCK),
         "#define DM_ARM_VARIANT_BASE(v) (%d + %d * (v))" % (1 + NW, BLOCK)]
    open(OUT_H, "w", newline="\n").write("\n".join(h) + "\n")
    print("wrote %s" % out)

if __name__ == "__main__":
    main()
