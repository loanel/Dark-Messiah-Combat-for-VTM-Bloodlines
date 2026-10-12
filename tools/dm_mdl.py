"""Dark Messiah model reader (Source MDL v44 + VVD v4 + VTX v7): skeleton, animations and the reference mesh as SMD,
so no Crowbar is needed. Reads the player's own Dark Messiah files; nothing from it is shipped.

Layouts (Source SDK studio.h, checked against Crowbar 0.74's decompile of the same files):
  studiohdr: numbones/boneindex +156, numlocalanim/localanimindex +180, numlocalseq/localseqindex +188,
             numtextures/textureindex +204, numbodyparts/bodypartindex +232.
  bone (216 B): sznameindex, parent, ..., pos +32, quat +44, rot (RadianEuler) +60, posscale +72, rotscale +84.
  animdesc (100 B): sznameindex +4, fps +8, flags +12, numframes +16, nummovements +20, animblock +52, animindex +56.
  anim data: per animated bone {byte bone, byte flags, short nextoffset}, then by flags RAWROT (Quaternion48),
             RAWPOS (Vector48), ANIMROT / ANIMPOS (3 short offsets to run-length encoded values, x scale).
"""
import math
import os
import struct

RAWPOS, RAWROT, ANIMPOS, ANIMROT, DELTA, RAWROT2 = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20


def cstr(b, off):
    return b[off:b.index(b"\0", off)].decode("latin1")


def quat48(b, p):
    """Quaternion48: x, y 16 bits, z 15 bits, sign of w in the top bit."""
    x, y, zw = struct.unpack_from("<HHH", b, p)
    qx, qy, qz = (x - 32768) / 32768.0, (y - 32768) / 32768.0, ((zw & 0x7FFF) - 16384) / 16384.0
    w = math.sqrt(max(0.0, 1.0 - qx * qx - qy * qy - qz * qz))
    return qx, qy, qz, -w if zw & 0x8000 else w


def vector48(b, p):
    return struct.unpack_from("<3e", b, p)


def quat_to_euler(q):
    """Quaternion -> SMD RadianEuler (R = Rz Ry Rx), as Source's QuaternionAngles."""
    x, y, z, w = q
    m00, m10, m20 = 1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)
    m21, m22 = 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)
    m11, m12 = 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)
    sy = max(-1.0, min(1.0, -m20))
    if abs(sy) < 0.999999:
        return math.atan2(m21, m22), math.asin(sy), math.atan2(m10, m00)
    return math.atan2(-m12, m11), math.asin(sy), 0.0


def euler_matrix(r):
    cx, sx, cy, sy, cz, sz = (math.cos(r[0]), math.sin(r[0]), math.cos(r[1]), math.sin(r[1]),
                              math.cos(r[2]), math.sin(r[2]))
    return [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx]]


def matrix_euler(m):
    sy = max(-1.0, min(1.0, -m[2][0]))
    if abs(sy) < 0.999999:
        return math.atan2(m[2][1], m[2][2]), math.asin(sy), math.atan2(m[1][0], m[0][0])
    return math.atan2(-m[1][2], m[1][1]), math.asin(sy), 0.0


def root_unturn(pos, rot):
    """Rz(-90 deg) applied to a root bone's local transform (Crowbar's decompile of animation root bones)."""
    m = euler_matrix(rot)
    m = [m[1], [-v for v in m[0]], m[2]]  # Rz(-90) @ m: rows (x, y) -> (y, -x)
    return [pos[1], -pos[0], pos[2]], list(matrix_euler(m))


class MDL:
    def __init__(self, path):
        self.path = path
        self.b = b = open(path, "rb").read()
        if b[:4] != b"IDST":
            raise ValueError("%s: not a Source model" % path)
        self.version = struct.unpack_from("<i", b, 4)[0]
        if self.version != 44:
            raise ValueError("%s: model version %d, expected 44 (Dark Messiah)" % (path, self.version))
        numbones, boneindex = struct.unpack_from("<ii", b, 156)
        self.bones = []
        for i in range(numbones):
            o = boneindex + i * 216
            ni, parent = struct.unpack_from("<ii", b, o)
            self.bones.append(dict(
                name=cstr(b, o + ni), parent=parent,
                pos=struct.unpack_from("<3f", b, o + 32), quat=struct.unpack_from("<4f", b, o + 44),
                rot=struct.unpack_from("<3f", b, o + 60),
                posscale=struct.unpack_from("<3f", b, o + 72), rotscale=struct.unpack_from("<3f", b, o + 84)))
        numanim, animindex = struct.unpack_from("<ii", b, 180)
        self.anims = []
        for i in range(numanim):
            o = animindex + i * 100
            ni = struct.unpack_from("<i", b, o + 4)[0]
            fps, flags, frames, nmove = struct.unpack_from("<fiii", b, o + 8)
            block, data = struct.unpack_from("<ii", b, o + 52)
            self.anims.append(dict(name=cstr(b, o + ni), fps=fps, flags=flags, frames=frames, movements=nmove,
                                   block=block, data=o + data))

    # ------------------------------------------------------------------ animations
    def _value(self, p, frame, scale):
        """Source ExtractAnimValue: run-length encoded shorts {valid, total} + values."""
        b, k = self.b, frame
        while True:
            valid, total = b[p], b[p + 1]
            if total == 0:
                return 0.0
            if total > k:
                break
            k -= total
            p += (valid + 1) * 2
        idx = k + 1 if valid > k else valid
        return struct.unpack_from("<h", b, p + idx * 2)[0] * scale

    def animation(self, anim):
        """Frames of local bone transforms: [[(pos3, euler3 radians) per bone]] (SMD convention R = Rz Ry Rx)."""
        if anim["block"] != 0:
            raise ValueError("%s: animation %s is in an external anim block" % (self.path, anim["name"]))
        if anim["movements"]:
            raise ValueError("%s: animation %s has movement data (not supported)" % (self.path, anim["name"]))
        b = self.b
        recs = {}
        p = anim["data"]
        while True:
            bone, flags, nxt = struct.unpack_from("<BBh", b, p)
            recs[bone] = (flags, p + 4)
            if nxt == 0:
                break
            p += nxt
        frames = []
        for f in range(anim["frames"]):
            fr = []
            for i, bn in enumerate(self.bones):
                pos, rot = list(bn["pos"]), list(bn["rot"])
                if i in recs:
                    flags, d = recs[i]
                    if flags & RAWROT2:
                        raise ValueError("%s: Quaternion64 rotation not supported (bone %s)" % (self.path, bn["name"]))
                    delta = flags & DELTA
                    if flags & RAWROT:  # one pose for every frame (studio.h pQuat48 / pPos)
                        rot = list(quat_to_euler(quat48(b, d)))
                        if flags & RAWPOS:
                            pos = list(vector48(b, d + 6))
                    elif flags & RAWPOS:
                        pos = list(vector48(b, d))
                    if flags & ANIMROT:
                        offs = struct.unpack_from("<3h", b, d)
                        rot = [(self._value(d + offs[j], f, bn["rotscale"][j]) if offs[j] else 0.0)
                               + (0.0 if delta else bn["rot"][j]) for j in range(3)]
                        d += 6
                    elif delta and not flags & RAWROT:
                        rot = [0.0, 0.0, 0.0]
                    if flags & ANIMPOS:
                        offs = struct.unpack_from("<3h", b, d)
                        pos = [(self._value(d + offs[j], f, bn["posscale"][j]) if offs[j] else 0.0)
                               + (0.0 if delta else bn["pos"][j]) for j in range(3)]
                    elif delta and not flags & RAWPOS:
                        pos = [0.0, 0.0, 0.0]
                if bn["parent"] < 0:  # studiomdl stores animations turned +90 deg about z; Crowbar turns them back
                    pos, rot = root_unturn(pos, rot)
                fr.append((tuple(pos), tuple(rot)))
            frames.append(fr)
        return frames

    # ------------------------------------------------------------------ reference mesh (.vvd + .dx90.vtx, LOD 0)
    def mesh(self):
        """[(material, [vertex x3])], vertex = (pos3, normal3, (u, v), [(bone, weight)]). Coordinates in model space,
        bone weights as stored; v as in the file (SMD writes 1 - v)."""
        b = self.b
        base = os.path.splitext(self.path)[0]
        v = open(base + ".vvd", "rb").read()
        x = open(base + ".dx90.vtx", "rb").read()
        if v[:4] != b"IDSV" or struct.unpack_from("<i", v, 4)[0] != 4:
            raise ValueError("%s.vvd: not a version 4 vertex file" % base)
        nfix = struct.unpack_from("<i", v, 48)[0]
        vstart = struct.unpack_from("<i", v, 56)[0]
        if nfix:
            raise ValueError("%s.vvd: vertex fixups not supported" % base)
        if struct.unpack_from("<i", x, 0)[0] != 7:
            raise ValueError("%s.dx90.vtx: not a version 7 strip file" % base)

        def vert(i):
            o = vstart + i * 48
            w = struct.unpack_from("<3f", v, o)
            bones = v[o + 12:o + 15]
            n = v[o + 15]
            pos = struct.unpack_from("<3f", v, o + 16)
            nrm = struct.unpack_from("<3f", v, o + 28)
            uv = struct.unpack_from("<2f", v, o + 40)
            return pos, nrm, uv, [(bones[k], w[k]) for k in range(n)]

        numtex, texindex = struct.unpack_from("<ii", b, 204)
        textures = [cstr(b, texindex + i * 64 + struct.unpack_from("<i", b, texindex + i * 64)[0]) for i in range(numtex)]
        numskinref, _, skinindex = struct.unpack_from("<iii", b, 220)
        skin = struct.unpack_from("<%dh" % numskinref, b, skinindex)
        numbp, bpindex = struct.unpack_from("<ii", b, 232)
        xnbp, xbpoff = struct.unpack_from("<ii", x, 28)
        tris = []
        for bp in range(numbp):
            mbp = bpindex + bp * 16
            nmod, _, modindex = struct.unpack_from("<iii", b, mbp + 4)
            xbp = xbpoff + bp * 8
            xnmod, xmodoff = struct.unpack_from("<ii", x, xbp)
            for mi in range(nmod):
                mo = mbp + modindex + mi * 148
                nmesh, meshindex, _, vertexindex = struct.unpack_from("<iiii", b, mo + 72)
                xm = xbp + xmodoff + mi * 8
                _, xlodoff = struct.unpack_from("<ii", x, xm)
                xl = xm + xlodoff  # LOD 0
                xnmesh, xmeshoff = struct.unpack_from("<ii", x, xl)
                for me in range(nmesh):
                    mm = mo + meshindex + me * 116
                    material, _, _, vertexoffset = struct.unpack_from("<iiii", b, mm)
                    mat = textures[skin[material]]
                    xme = xl + xmeshoff + me * 9
                    nsg, sgoff = struct.unpack_from("<ii", x, xme)
                    for g in range(nsg):
                        sg = xme + sgoff + g * 25
                        nv, voff, ni, ioff, ns, soff = struct.unpack_from("<6i", x, sg)
                        for s in range(ns):
                            st = sg + soff + s * 27
                            sni, sioff = struct.unpack_from("<ii", x, st)
                            if x[st + 18] & 2:
                                raise ValueError("%s.dx90.vtx: triangle strips not supported" % base)
                            idx = struct.unpack_from("<%dH" % sni, x, sg + ioff + sioff * 2)
                            for t in range(0, sni, 3):
                                tri = []
                                for k in (0, 2, 1):  # VTX winding -> SMD winding
                                    orig = struct.unpack_from("<H", x, sg + voff + idx[t + k] * 9 + 4)[0]
                                    tri.append(vert(vertexindex // 48 + vertexoffset + orig))
                                tris.append((mat, tri))
        return tris

    # ------------------------------------------------------------------ SMD output
    def nodes_text(self):
        return "".join('  %d "%s" %d\n' % (i, bn["name"], bn["parent"]) for i, bn in enumerate(self.bones))

    def write_reference_smd(self, path):
        """Skeleton in the bind pose + the reference mesh (Crowbar's <model>_Reference SMD)."""
        with open(path, "w", encoding="latin1", newline="\n") as f:
            f.write("version 1\nnodes\n" + self.nodes_text() + "end\nskeleton\n  time 0\n")
            for i, bn in enumerate(self.bones):
                f.write("    %d %.6f %.6f %.6f %.6f %.6f %.6f\n" % (i, *bn["pos"], *bn["rot"]))
            f.write("end\ntriangles\n")
            for mat, tri in self.mesh():
                f.write(mat + "\n")
                for pos, nrm, (u, v), links in tri:
                    f.write("  %d %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %d%s\n" % (
                        links[0][0], *pos, *nrm, u, 1.0 - v, len(links),
                        "".join(" %d %.6f" % (bi, w) for bi, w in links)))
            f.write("end\n")

    def write_anim_smd(self, anim, path):
        with open(path, "w", encoding="latin1", newline="\n") as f:
            f.write("version 1\nnodes\n" + self.nodes_text() + "end\nskeleton\n")
            for t, fr in enumerate(self.animation(anim)):
                f.write("  time %d\n" % t)
                for i, (p, r) in enumerate(fr):
                    f.write("    %d %.6f %.6f %.6f %.6f %.6f %.6f\n" % (i, *p, *r))
            f.write("end\n")


if __name__ == "__main__":
    import sys
    m = MDL(sys.argv[1])
    print("%s v%d: %d bones, %d animations" % (os.path.basename(m.path), m.version, len(m.bones), len(m.anims)))
