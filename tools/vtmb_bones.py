"""Bloodlines MDL v2531 skeleton reader.

mstudiobone_t, 160 bytes (bone table at header +244, count +240):
  +0 sznameindex  +4 parent  +8 bonecontroller[6]  +32 pos[3]  +44 quat[4] (x y z w)  +60 posscale[3]
  +72 rotscale[4]  +88 poseToBone[3][4]  +136 flags ...  (no euler "rot" in this version)
Layout checked by recomputing every bone's global rest pose from pos/quat and comparing with inverse(poseToBone).

usage: python tools/vtmb_bones.py <model.mdl> [--smd out_skeleton.smd]
"""
import math
import struct
import sys

import numpy as np


def quat_matrix(x, y, z, w):
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def quat_euler(x, y, z, w):
    """Quaternion -> Source RadianEuler (x roll about X, y pitch about Y, z yaw about Z; R = Rz Ry Rx)."""
    m = quat_matrix(x, y, z, w)
    sy = -m[2, 0]
    ry = math.asin(max(-1.0, min(1.0, sy)))
    if abs(m[2, 0]) < 0.99999:
        rx = math.atan2(m[2, 1], m[2, 2])
        rz = math.atan2(m[1, 0], m[0, 0])
    else:
        rx = math.atan2(-m[1, 2], m[1, 1])
        rz = 0.0
    return rx, ry, rz


def read_bones(path):
    d = open(path, "rb").read()
    n, idx = struct.unpack_from("<2i", d, 240)
    bones = []
    for i in range(n):
        o = idx + i * 160
        ni, parent = struct.unpack_from("<2i", d, o)
        name = d[o + ni: o + ni + 64].split(b"\0")[0].decode("latin1")
        pos = struct.unpack_from("<3f", d, o + 32)
        quat = struct.unpack_from("<4f", d, o + 44)
        rot = quat_euler(*quat)
        p2b = np.array(struct.unpack_from("<12f", d, o + 88)).reshape(3, 4)
        bones.append(dict(name=name, parent=parent, pos=pos, quat=quat, rot=rot, p2b=p2b))
    return bones


def globals_(bones):
    g = []
    for b in bones:
        m = np.eye(4)
        m[:3, :3] = quat_matrix(*b["quat"])
        m[:3, 3] = b["pos"]
        g.append(g[b["parent"]] @ m if b["parent"] >= 0 else m)
    return g


def main():
    bones = read_bones(sys.argv[1])
    g = globals_(bones)
    worst = 0
    for i, b in enumerate(bones):
        p2b = np.eye(4)
        p2b[:3, :] = b["p2b"]
        err = np.abs(np.linalg.inv(p2b) - g[i]).max()
        worst = max(worst, err)
        print("%2d %-20s parent %2d pos %s rot %s  |p2b check %.4f" % (
            i, b["name"], b["parent"], " ".join("%.3f" % v for v in b["pos"]),
            " ".join("%.4f" % v for v in b["rot"]), err))
    print("worst poseToBone mismatch %.5f" % worst)
    if "--smd" in sys.argv:
        out = sys.argv[sys.argv.index("--smd") + 1]
        lines = ["version 1", "nodes"] + ['%d "%s" %d' % (i, b["name"], b["parent"]) for i, b in enumerate(bones)]
        lines += ["end", "skeleton", "time 0"]
        lines += ["%d %.6f %.6f %.6f %.6f %.6f %.6f" % (i, *b["pos"], *b["rot"]) for i, b in enumerate(bones)]
        lines += ["end"]
        open(out, "w", newline="\n").write("\n".join(lines) + "\n")
        print("wrote", out)


if __name__ == "__main__":
    main()
