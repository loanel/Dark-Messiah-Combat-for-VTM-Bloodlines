"""Minimal Source SMD reader/writer with forward kinematics (numpy).

Rotation convention (Valve SMD): radians, R = Rz(z) @ Ry(y) @ Rx(x); local transform = T(pos) @ R.
"""
import math

import numpy as np


def euler_to_mat(x, y, z):
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def mat_to_euler(r):
    # inverse of Rz @ Ry @ Rx
    sy = -r[2, 0]
    sy = max(-1.0, min(1.0, sy))
    y = math.asin(sy)
    if abs(sy) < 0.999999:
        x = math.atan2(r[2, 1], r[2, 2])
        z = math.atan2(r[1, 0], r[0, 0])
    else:  # gimbal lock
        x = math.atan2(-r[1, 2], r[1, 1])
        z = 0.0
    return x, y, z


def make(pos, rot):
    m = np.eye(4)
    m[:3, :3] = euler_to_mat(*rot)
    m[:3, 3] = pos
    return m


def split(m):
    return tuple(m[:3, 3]), mat_to_euler(m[:3, :3])


class SMD:
    def __init__(self):
        self.nodes = []      # [(index, name, parent)]
        self.frames = []     # [ {bone: (pos3, rot3)} ]
        self.triangles = []  # raw lines (material + 3 vertex lines per tri)

    @classmethod
    def read(cls, path):
        s = cls()
        sec = None
        cur = None
        with open(path, encoding="latin1") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("//"):
                    continue
                if sec is None:
                    if line in ("nodes", "skeleton", "triangles"):
                        sec = line
                    continue
                if line == "end":
                    sec = None
                    continue
                if sec == "nodes":
                    a = line.split('"')
                    s.nodes.append((int(a[0]), a[1], int(a[2])))
                elif sec == "skeleton":
                    if line.startswith("time"):
                        cur = {}
                        s.frames.append(cur)
                    else:
                        v = line.split()
                        cur[int(v[0])] = (tuple(map(float, v[1:4])), tuple(map(float, v[4:7])))
                elif sec == "triangles":
                    s.triangles.append(raw.rstrip("\n"))
        return s

    def write(self, path):
        with open(path, "w", encoding="latin1", newline="\n") as f:
            f.write("version 1\nnodes\n")
            for i, n, p in self.nodes:
                f.write(f'{i} "{n}" {p}\n')
            f.write("end\nskeleton\n")
            for t, fr in enumerate(self.frames):
                f.write(f"time {t}\n")
                for b in sorted(fr):
                    (px, py, pz), (rx, ry, rz) = fr[b]
                    f.write(f"{b} {px:.6f} {py:.6f} {pz:.6f} {rx:.6f} {ry:.6f} {rz:.6f}\n")
            f.write("end\n")
            if self.triangles:
                f.write("triangles\n" + "\n".join(self.triangles) + "\nend\n")

    def index(self, name):
        for i, n, p in self.nodes:
            if n.lower() == name.lower():
                return i
        raise KeyError(name)

    def parents(self):
        return {i: p for i, n, p in self.nodes}

    def globals(self, frame_idx, base_frame=None):
        """World matrices for every bone at a frame. Bones missing from the frame use base_frame."""
        fr = self.frames[frame_idx]
        par = self.parents()
        out = {}
        for i, n, p in sorted(self.nodes):  # parents always precede children in SMD
            pr = fr.get(i) or (base_frame or {}).get(i)
            if pr is None:
                continue
            loc = make(*pr)
            out[i] = loc if p < 0 else out[p] @ loc
        return out
