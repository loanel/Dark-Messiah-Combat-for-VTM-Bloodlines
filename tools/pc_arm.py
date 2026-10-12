"""Retarget the right arm of a Bloodlines player model (Biped skeleton, Crowbar-decompiled REF smd) onto Dark Messiah's
first-person arm skeleton, in DM's reference pose. Used by build_katana_arm.py --pc.

Both skeletons are fitted per segment from joint POSITIONS (their bone axis conventions differ: DM bones point along
local -x and the elbow bends about local y, Biped bones along +x with the elbow bending about z). Each segment gets a
frame built the same way on both sides: origin = start joint, x = towards the next joint, roll from a shared
reference (the elbow's bend axis for clavicle/upper arm/forearm, the across-the-palm vector for the hand and fingers).
A Bloodlines vertex skinned to bone b moves by  A_b = F_dm(seg) * stretch * inverse(F_pc(seg))  (stretch scales the
segment's length to DM's, thickness stays Bloodlines'), and inherits b's mapped Dark Messiah bone.
"""
import numpy as np


def _n(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def frame(o, end, roll):
    x = _n(end - o)
    z = _n(roll - np.dot(roll, x) * x)
    y = np.cross(z, x)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, y, z, o
    return m, np.linalg.norm(end - o)


def retarget(dm, dm_g, pc, pc_g, pc_idle_g, log=print):
    """dm/pc: smd.SMD; *_g: bone index -> 4x4 global (DM in eye space). Returns {pc bone: (A 4x4, dm bone)}."""
    P = lambda n: pc_g[pc.index(n)][:3, 3]
    D = lambda n: dm_g[dm.index(n)][:3, 3]

    # elbow bend axis: DM's reference pose is bent; the Bloodlines bind pose is almost straight, so use its biped
    # convention (upper arm local z) with the sign the idle animation's elbow bend gives
    u_dm, f_dm = D("SK_R_Elbow") - D("SK_R_Shoulder"), D("SK_R_Hand") - D("SK_R_Elbow")
    bend_dm = _n(np.cross(u_dm, f_dm))
    ua = pc.index("Bip01 R UpperArm")
    if pc_idle_g is None:  # no animation decoded: Bloodlines' biped arms bend about -z (measured on toreador_male_0)
        sign, bi = -1.0, np.zeros(3)
    else:
        zi = pc_idle_g[ua][:3, 2]
        bi = np.cross(pc_idle_g[pc.index("Bip01 R Forearm")][:3, 3] - pc_idle_g[ua][:3, 3],
                      pc_idle_g[pc.index("Bip01 R Hand")][:3, 3] - pc_idle_g[pc.index("Bip01 R Forearm")][:3, 3])
        sign = 1.0 if np.dot(bi, zi) >= 0 else -1.0
    bend_pc = sign * pc_g[ua][:3, 2]
    log("pc arm: elbow bend axis sign %+d (idle bend %.2f)" % (sign, np.linalg.norm(bi)))

    # fingers: Bloodlines Finger1..4 = index..pinky (biped), Finger0 = thumb. DM letters by distance to the thumb.
    thumb = D("Sk_R_Thumb_1")
    letters = sorted("ABCD", key=lambda L: np.linalg.norm(D(dm_finger(L, 1)) - thumb))
    log("pc arm: DM fingers index..pinky = %s" % " ".join(letters))
    across_dm = _n(D(dm_finger(letters[0], 1)) - D(dm_finger(letters[3], 1)))
    across_pc = _n(P("Bip01 R Finger1") - P("Bip01 R Finger4"))

    out = {}
    pc_names = {n for _, n, _ in pc.nodes}

    def seg(pc_bones, pc_a, pc_b, dm_bone, dm_a, dm_b, roll_pc, roll_dm):
        fp, lp = frame(pc_a, pc_b, roll_pc)
        fd, ld = frame(dm_a, dm_b, roll_dm)
        st = np.diag([ld / lp if lp > 1e-6 else 1.0, 1, 1, 1])
        a = fd @ st @ np.linalg.inv(fp)
        for b in [b for b in pc_bones if b in pc_names]:  # helper bones (Bicep, Ulna...) vary between models
            out[pc.index(b)] = (a, dm.index(dm_bone))
        return ld / lp if lp > 1e-6 else 1.0

    s = []
    s.append(seg(["Bip01 R Clavicle"], P("Bip01 R Clavicle"), P("Bip01 R UpperArm"), "SK_R_Collarbone",
                 D("SK_R_Collarbone"), D("SK_R_Shoulder"), bend_pc, bend_dm))
    s.append(seg(["Bip01 R UpperArm", "Bip01 R Bicep", "Bip01 R Shoulder"], P("Bip01 R UpperArm"), P("Bip01 R Forearm"),
                 "SK_R_Shoulder", D("SK_R_Shoulder"), D("SK_R_Elbow"), bend_pc, bend_dm))
    s.append(seg(["Bip01 R Forearm", "Bip01 R Elbow"], P("Bip01 R Forearm"), P("Bip01 R Hand"), "SK_R_Elbow",
                 D("SK_R_Elbow"), D("SK_R_Hand"), bend_pc, bend_dm))
    seg(["Bip01 R Ulna"], P("Bip01 R Forearm"), P("Bip01 R Hand"), "SK_R_Forearm",
        D("SK_R_Elbow"), D("SK_R_Hand"), bend_pc, bend_dm)
    seg(["Bip01 R Wrist"], P("Bip01 R Forearm"), P("Bip01 R Hand"), "SK_R_Wrist",
        D("SK_R_Elbow"), D("SK_R_Hand"), bend_pc, bend_dm)
    knuckles_pc = np.mean([P("Bip01 R Finger%d" % k) for k in (1, 2, 3, 4)], axis=0)
    knuckles_dm = np.mean([D(dm_finger(L, 1)) for L in letters], axis=0)
    s.append(seg(["Bip01 R Hand"], P("Bip01 R Hand"), knuckles_pc, "SK_R_Hand", D("SK_R_Hand"), knuckles_dm,
                 across_pc, across_dm))
    # finger segments: Bloodlines 3 bones per finger (tip estimated), DM 4 (the 4th is the tip)
    for k, L in zip((1, 2, 3, 4), letters):
        pcs = ["Bip01 R Finger%d" % k, "Bip01 R Finger%d1" % k, "Bip01 R Finger%d2" % k]
        dms = [dm_finger(L, j) for j in (1, 2, 3, 4)]
        finger(pcs, dms, P, D, seg, across_pc, across_dm)
    # thumb: it runs roughly ALONG the across-the-palm vector, so that vector can't set its roll (near-parallel ->
    # random twist, the thumb ended up pointing down); use the palm normal instead, built the same way on both sides
    palm_pc = _n(np.cross(knuckles_pc - P("Bip01 R Hand"), across_pc))
    palm_dm = _n(np.cross(knuckles_dm - D("SK_R_Hand"), across_dm))
    finger(["Bip01 R Finger0", "Bip01 R Finger01", "Bip01 R Finger02"],
           ["Sk_R_Thumb_1", "SK_R_Thumb_2", "Sk_R_Thumb_3", "Sk_R_Thumb_4"], P, D, seg, palm_pc, palm_dm)
    log("pc arm: length ratios DM/Bloodlines clavicle %.2f upper %.2f forearm %.2f hand %.2f" % tuple(s))
    return out


def dm_finger(letter, j):
    # DM's names are inconsistent: SK_R_Finger_A1..A3 but Sk_R_Finger_A4, and the 4th finger is SK_Finger_D1..4
    if letter == "D":
        return "SK_Finger_D%d" % j
    return ("Sk_R_Finger_%s%d" if (letter == "A" and j == 4) else "SK_R_Finger_%s%d") % (letter, j)


def finger(pcs, dms, P, D, seg, across_pc, across_dm):
    pts_pc = [P(b) for b in pcs]
    pts_pc.append(pts_pc[-1] + (pts_pc[-1] - pts_pc[-2]) * 0.8)  # Bloodlines has no fingertip bone
    pts_dm = [D(b) for b in dms]
    for j in range(3):
        seg([pcs[j]], pts_pc[j], pts_pc[j + 1], dms[j], pts_dm[j], pts_dm[j + 1], across_pc, across_dm)
