"""Bloodlines MDL v2531 (+ .dx80.vtx) -> reference SMD (skeleton + skinned triangles) and a minimal qc, without Crowbar.

Layout (checked against Crowbar's decompile of toreador_male_armor_0):
  header: +240 numbones, +244 boneindex (bone = 160 bytes, see vtmb_bones.py), +292 numtextures, +296 textureindex
          (texture = 20 bytes, +0 sznameindex), +300 numcdtextures, +304 cdtextureindex (int offsets to strings),
          +320 numbodyparts, +324 bodypartindex
  bodypart (16 bytes): sznameindex, nummodels, base, modelindex
  model: name[128], +128 type, +132 radius, +136 nummeshes, +140 meshindex, +144 numvertices, +148 vertexindex
  mesh (60 bytes): material, modelindex, numvertices, vertexoffset, ...
  vertex (44 bytes): weight u8[3], pad, bone u16[3], pad u16, pos f32[3], normal f32[3], uv f32[2]
  .vtx (version 107): header 36 bytes, bodypart/model (8: count, offset), LOD (12: count, offset, switch),
        mesh 8 (count | flags << 16, offset), strip group 20 (u16 numVerts, u16 numIndices, ?, +8 vertOffset,
        +12 indexOffset), vertex 12 bytes (origMeshVertID u16 at +10), indices u16 = one triangle list per group.
usage: python tools/vtmb_mdl2smd.py <model.mdl> <out dir> [--crowbar-uv]   (writes <name>_REF.smd and <name>.qc)
"""
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vtmb_bones  # noqa: E402


def cstr(d, o):
    return d[o:o + 260].split(b"\0")[0].decode("latin1")


def convert(mdl_path, out_dir, crowbar_uv=False):
    d = open(mdl_path, "rb").read()
    base = os.path.splitext(mdl_path)[0]
    v = open(base + ".dx80.vtx", "rb").read()
    model_name = cstr(d, 12)
    bones = vtmb_bones.read_bones(mdl_path)

    nt, ti = struct.unpack_from("<2i", d, 292)
    textures = [cstr(d, ti + k * 20 + struct.unpack_from("<i", d, ti + k * 20)[0]) for k in range(nt)]
    ncd, cdi = struct.unpack_from("<2i", d, 300)
    cds = [cstr(d, struct.unpack_from("<i", d, cdi + 4 * k)[0]) for k in range(ncd)]
    nbp, bpi = struct.unpack_from("<2i", d, 320)

    # vtx
    vver, = struct.unpack_from("<i", v, 0)
    v_nbp, v_bpo = struct.unpack_from("<2i", v, 28)
    if v_nbp != nbp:
        raise SystemExit("vtx body parts %d != mdl %d" % (v_nbp, nbp))

    tris = []  # (material, [vertex records] * 3)
    for b in range(nbp):
        bp = bpi + b * 16
        _, nmodels, _, mi = struct.unpack_from("<4i", d, bp)
        vbp = v_bpo + b * 8
        vnm, vmo = struct.unpack_from("<2i", v, vbp)
        for m in range(nmodels):
            mo = bp + mi + m * 0  # set below
            # model size: walk by the model's own size; v2531 model = 128 name + fields; find stride from next model
            mo = bp + mi + m * MODEL_SIZE
            nmesh, meshi, nverts, verti = struct.unpack_from("<4i", d, mo + 136)
            tangi = struct.unpack_from("<i", d, mo + 152)[0]
            # Compressed props (knife, baton, bat...): 12-byte vertices = position u16[3] quantized per axis (offset
            # f32[3] at model +160, scale x at +172, scale y/z at +176/+180), then u16 (packed normal, ignored -
            # normals are rebuilt from the faces), u16 u, u16 v (/65535).
            compressed = nverts > 0 and (tangi - verti) == 12 * nverts
            if compressed:
                qoff = struct.unpack_from("<3f", d, mo + 160)
                qsc = (struct.unpack_from("<f", d, mo + 172)[0],) + struct.unpack_from("<2f", d, mo + 176)
            vm = vbp + vmo + m * 8
            vnlod, vlodo = struct.unpack_from("<2i", v, vm)
            lod = vm + vlodo  # LOD 0
            vnmesh, vmesho = struct.unpack_from("<2i", v, lod)
            for me in range(nmesh):
                mesh = mo + meshi + me * 60
                mat, _, mnv, mvo = struct.unpack_from("<4i", d, mesh)
                vme = lod + vmesho + me * 8  # Bloodlines vtx (version 107): mesh header 8 bytes
                nsg, sgo = struct.unpack_from("<2i", v, vme)
                for g in range(nsg & 0xffff):
                    sg = vme + sgo + g * 20  # strip group header 20 bytes
                    snv, sni = struct.unpack_from("<2H", v, sg)
                    svo, sio = struct.unpack_from("<2i", v, sg + 8)
                    # vertex record: 12 bytes (bone data, origMeshVertID last) on skinned models, 2 bytes (just the
                    # ID) on single-bone props - told apart by the gap to the next block in the file (the meshes'
                    # vertex blocks lie back to back, then the index lists: own index list only for one mesh)
                    vs = vertex_record_size(v, sg + svo, snv)
                    sverts = [struct.unpack_from("<H", v, sg + svo + k * vs + vs - 2)[0] for k in range(snv)]
                    idx = struct.unpack_from("<%dH" % sni, v, sg + sio)
                    for k in range(0, sni - 2, 3):  # triangle list
                        if compressed:
                            recs = [read_cvertex(d, mo + verti + (mvo + sverts[i]) * 12, qoff, qsc) for i in idx[k:k + 3]]
                            fix_normals(recs)
                        else:
                            recs = [read_vertex(d, mo + verti + (mvo + sverts[i]) * 44) for i in idx[k:k + 3]]
                        tris.append((textures[mat] if 0 <= mat < len(textures) else "mat%d" % mat, recs))

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.basename(base)
    lines = ["version 1", "nodes"] + ['%d "%s" %d' % (k, bn["name"], bn["parent"]) for k, bn in enumerate(bones)]
    lines += ["end", "skeleton", "time 0"]
    lines += ["%d %.6f %.6f %.6f %.6f %.6f %.6f" % (k, *bn["pos"], *bn["rot"]) for k, bn in enumerate(bones)]
    lines += ["end", "triangles"]
    for mat, recs in tris:
        lines.append(mat)
        # SMD winding is the reverse of the vtx order (matches Crowbar's output). crowbar_uv: UVs as Crowbar (CroVtMB)
        # writes them, fmod(value, 1) keeping the sign - used for g_katana, whose blade stores u up to +-4 and whose
        # Crowbar decompile the arm models were tuned on. Off by default: it shifts corners of one triangle differently.
        # crowbar_uv also starts each triangle at Crowbar's corner (same triangle, same winding)
        for pos, nrm, uv, links in ([recs[0], recs[2], recs[1]] if crowbar_uv else reversed(recs)):
            if crowbar_uv:
                uv = (math.fmod(uv[0], 1.0), math.fmod(uv[1], 1.0))
            lines.append("%d %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %d %s" % (
                links[0][0], *pos, *nrm, uv[0], 1.0 - uv[1], len(links), " ".join("%d %.6f" % bw for bw in links)))
    lines.append("end")
    ref = os.path.join(out_dir, stem + "_REF.smd")
    open(ref, "w", newline="\n").write("\n".join(lines) + "\n")
    qc = ['$modelname "%s"' % model_name, '$bodygroup "mainbody"', "{", '\tstudio "%s_REF"' % stem, "}"]
    qc += ['$cdmaterials "%s"' % c.replace("/", "\\") for c in cds]
    open(os.path.join(out_dir, stem + ".qc"), "w", newline="\n").write("\n".join(qc) + "\n")
    return ref, len(tris), textures, cds


MODEL_SIZE = 0  # filled in by probe()

_BLOCKS = {}  # vtx bytes -> sorted absolute starts of every strip group's vertex, index and strip blocks


def _block_starts(v):
    key = v  # by content: an id() can be reused once a file is freed
    if key not in _BLOCKS:
        starts = {len(v)}
        v_nbp, v_bpo = struct.unpack_from("<2i", v, 28)
        for b in range(v_nbp):
            vbp = v_bpo + b * 8
            vnm, vmo = struct.unpack_from("<2i", v, vbp)
            for m in range(vnm):
                vm = vbp + vmo + m * 8
                vnlod, vlodo = struct.unpack_from("<2i", v, vm)
                for l in range(vnlod):
                    lod = vm + vlodo + l * 12
                    vnmesh, vmesho = struct.unpack_from("<2i", v, lod)
                    for me in range(vnmesh):
                        vme = lod + vmesho + me * 8
                        nsg, sgo = struct.unpack_from("<2i", v, vme)
                        for g in range(nsg & 0xffff):
                            sg = vme + sgo + g * 20
                            svo, sio, so = struct.unpack_from("<3i", v, sg + 8)
                            starts |= {sg + svo, sg + sio, sg + so}
        _BLOCKS[key] = sorted(starts)
    return _BLOCKS[key]


def vertex_record_size(v, start, count):
    """2 (single-bone props: just origMeshVertID) or 12 (skinned) bytes, from the space up to the next block."""
    if count == 0:
        return 12
    nxt = next(s for s in _block_starts(v) if s > start)
    for size in (2, 12):
        if nxt - start == size * count:
            return size
    return 2 if nxt - start < 12 * count else 12


def read_vertex(d, o):
    w = d[o:o + 3]
    bones = struct.unpack_from("<3H", d, o + 4)
    pos = struct.unpack_from("<3f", d, o + 12)
    nrm = struct.unpack_from("<3f", d, o + 24)
    uv = struct.unpack_from("<2f", d, o + 36)
    links = [(bones[k], w[k] / 255.0) for k in range(3) if w[k]]
    if not links:
        links = [(bones[0], 1.0)]
    return pos, nrm, uv, links


def read_cvertex(d, o, qoff, qsc):
    q = struct.unpack_from("<3H", d, o)
    pos = tuple(qoff[k] + q[k] * qsc[k] for k in range(3))
    u, v = struct.unpack_from("<2H", d, o + 8)
    return pos, (0.0, 0.0, 1.0), (u / 65535.0, v / 65535.0), [(0, 1.0)]


def fix_normals(recs):
    """Flat normal from the triangle (the packed normal isn't decoded)."""
    a, b, c = [r[0] for r in recs]
    n = [(b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
         (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
         (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])]
    l = sum(x * x for x in n) ** 0.5 or 1.0
    n = tuple(x / l for x in n)
    for i, r in enumerate(recs):
        recs[i] = (r[0], n, r[2], r[3])


def probe(d):
    """v2531 model struct size: the first model's fields end where its meshes start? Use the bodypart's 2nd model if any,
    else any size works (one model)."""
    return 148 + 4 * 20


if __name__ == "__main__":
    MODEL_SIZE = probe(None)
    ref, n, tex, cds = convert(sys.argv[1], sys.argv[2], "--crowbar-uv" in sys.argv[3:])
    print("%s: %d triangles, materials %s, cdmaterials %s" % (ref, n, ", ".join(tex), ", ".join(cds)))
