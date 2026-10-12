"""Sample Dark Messiah's sword motion into a table the plug-in plays back on a rigid katana.

For every DM first-person sword sequence: per frame, the transform of DM's "RightHand" attachment (where DM mounts
the sword entity) in Source eye space (x forward, y left, z up, camera at origin). Uses the same geometry the DMHL2
viewmodel used (verified in game there): DM arm model -> eye space via F_PREVIEW, attachment SK_R_Hand -3 0 0 rot 90 0 0,
blade roll 90 deg (edge-first).

Also the hit windows (open / close / impact cycles) from the sword animations' events, with the DMHL2 rules
(gen_sword_table.py): open = event 2107 (or 2109 / start), close = 2190 (or the next open / end), impact = 2186 / 2102.

Inputs come from the user's own Dark Messiah install, read by tools/dm_extract.py into build/dm (dm_decomp/out SMDs,
dm_extract/first_animations_sword.json = the model's events). Never shipped.
Output: build/game/dmcombat_dm.bin (tools/dm_data.py format), installed next to dmcombat.ini; the plug-in reads it at
startup and stays off without it.

usage: python tools/gen_sword_paths.py [<Dark Messiah data dir>, default build/dm]
"""
import glob
import math
import os
import re
import sys

import json

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dm_data  # noqa: E402

DMHL2 = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "dm")
import smd  # noqa: E402  (tools/smd.py: SMD + forward kinematics)

DEC = os.path.join(DMHL2, "dm_decomp", "out")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "game", "dmcombat_dm.bin")

# Same constants as DMHL2 tools/dmtools/build_viewmodel.py.
F_PREVIEW = np.eye(4)
F_PREVIEW[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
F_PREVIEW[:3, 3] = (-6.0, 0.0, 10.0)
HAND = "SK_R_Hand"
ATTACH = smd.make((-3.0, 0.0, 0.0), tuple(math.radians(a) for a in (90.0, 0.0, 0.0)))
ROLL = np.eye(4)
ROLL[:3, :3] = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]  # 90 deg about sword-space Y

# Animated arm (dm_arm.cpp, tools/build_katana_arm.py): per frame, for each driven Dark Messiah bone, its motion relative
# to the reference pose D = E_frame * inverse(E_ref) in eye space; drives the glock skeleton bone ARM_GLOCK_BONES[i].
ARM_DM_BONES = ["SK_Spine_4", "SK_R_Collarbone", "SK_R_Shoulder", "SK_R_Elbow", "SK_R_Forearm", "SK_R_Wrist", "SK_R_Hand"]

BASIC = ["anm_sword_noshield_idle", "anm_sword_noshield_draw", "anm_sword_noshield_undraw",
         "anm_sword_noshield_kick_low", "anm_sword_noshield_kick_medium"]


def fps_table(qc):
    out = {}
    text = open(qc, encoding="latin1").read()
    for m in re.finditer(r'\$animation\s+"([^"]+)"\s+"[^"]+"\s*\{([^}]*)\}', text):
        f = re.search(r"fps\s+([\d.]+)", m.group(2))
        out[m.group(1).lower()] = float(f.group(1)) if f else 30.0
    return out


def mat_to_quat(r):
    w = math.sqrt(max(0.0, 1 + r[0, 0] + r[1, 1] + r[2, 2])) / 2
    x = math.copysign(math.sqrt(max(0.0, 1 + r[0, 0] - r[1, 1] - r[2, 2])) / 2, r[2, 1] - r[1, 2])
    y = math.copysign(math.sqrt(max(0.0, 1 - r[0, 0] + r[1, 1] - r[2, 2])) / 2, r[0, 2] - r[2, 0])
    z = math.copysign(math.sqrt(max(0.0, 1 - r[0, 0] - r[1, 1] + r[2, 2])) / 2, r[1, 0] - r[0, 1])
    return x, y, z, w


def main():
    ref = smd.SMD.read(os.path.join(DEC, "first_basic", "First_Reference_basic.smd"))
    base = ref.frames[0]
    gref = ref.globals(0)
    arm_ref_inv = [np.linalg.inv(F_PREVIEW @ gref[ref.index(n)]) for n in ARM_DM_BONES]
    fps =fps_table(os.path.join(DEC, "first_animations_sword", "first_animations_sword.qc"))
    fps.update(fps_table(os.path.join(DEC, "first_animations_basic", "first_animations_basic.qc")))

    files = sorted(glob.glob(os.path.join(DEC, "first_animations_sword", "first_animations_sword_anims", "anm_*.smd")))
    files += [os.path.join(DEC, "first_animations_basic", "first_animations_basic_anims", b + ".smd") for b in BASIC]
    seqs = []
    for path in files:
        name = os.path.splitext(os.path.basename(path))[0]
        if name == "anm_reference" or not os.path.exists(path):
            continue
        s = smd.SMD.read(path)
        hand = s.index(HAND)
        frames, arm = [], []
        arm_idx = [s.index(n) for n in ARM_DM_BONES]
        for t in range(len(s.frames)):
            g = s.globals(t, base)
            m = F_PREVIEW @ g[hand] @ ATTACH @ ROLL
            frames.append((tuple(m[:3, 3]), mat_to_quat(m[:3, :3])))
            for bi, inv in zip(arm_idx, arm_ref_inv):
                d = F_PREVIEW @ g[bi] @ inv
                arm.append((tuple(d[:3, 3]), mat_to_quat(d[:3, :3])))
        seqs.append((name, fps.get(name.lower(), 30.0), frames, arm))

    idle = next(fr for n, f, fr, a in seqs if n == "anm_sword_noshield_idle")[0]
    print("idle frame 0: pos %s" % (tuple(round(v, 2) for v in idle[0]),))
    windows = hit_windows(os.path.join(DMHL2, "dm_extract", "first_animations_sword.json"))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    dm_data.write(OUT, [(n[4:], f, fr, a) for n, f, fr, a in seqs], windows, len(ARM_DM_BONES))
    print("%d sequences, %d frames, %d hit windows -> %s" % (len(seqs), sum(len(fr) for _, _, fr, _ in seqs),
                                                           len(windows), os.path.normpath(OUT)))


def hit_windows(events_json):
    """[(sequence, index, open, close, impact)] from the sword model's animation events (DMHL2 gen_sword_table.py)."""
    m = json.load(open(events_json))
    rows = []
    for s in m["sequences"]:
        ev = sorted(s["events"], key=lambda e: e["cycle"])
        if not any(e["event"] in (2102, 2107, 2186) for e in ev):
            continue
        first = lambda code: next((e for e in ev if e["event"] == code), None)  # noqa: E731
        opens = [e for e in ev if e["event"] == 2107] or [first(2109) or {"cycle": 0.0}]
        for k, o in enumerate(opens):
            nxt = opens[k + 1]["cycle"] if k + 1 < len(opens) else 1.01
            close = next((e for e in ev if e["event"] == 2190 and o["cycle"] <= e["cycle"] < nxt), None)
            c = close["cycle"] if close else (nxt if nxt <= 1.0 else 1.0)
            if c <= o["cycle"]:
                c = min(1.0, o["cycle"] + 0.15)
            inside = [e for e in ev if o["cycle"] <= e["cycle"] <= c]
            impact = next((e for e in inside if e["event"] == 2186), None) or                 next((e for e in inside if e["event"] == 2102), None) or first(2102)
            name = s["name"].split("_", 1)[1] if s["name"].startswith(("layer_", "anm_")) else s["name"]
            rows.append((name, k, o["cycle"], c, impact["cycle"] if impact else o["cycle"]))
    return rows


if __name__ == "__main__":
    main()
