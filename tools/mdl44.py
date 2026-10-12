"""Read sequences, animations, events and bones from Source MDL files (v44-v48 headers).

usage: python -I mdl44.py <file.mdl> [--json out.json]
Prints a table: sequence, activity, frames, fps, seconds, flags, events (cycle:event:options).
"""
import json
import struct
import sys

SEQ_SIZE = 212        # mstudioseqdesc_t
EVENT_SIZE = 80       # mstudioevent_t
BONE_SIZE_48 = 216    # mstudiobone_t (v48); v44 checked at runtime


def cstr(b, off):
    end = b.index(b"\0", off)
    return b[off:end].decode("latin1")


def read_model(path):
    b = open(path, "rb").read()
    ident, ver = b[:4], struct.unpack_from("<i", b, 4)[0]
    if ident != b"IDST":
        raise ValueError("not an MDL")
    name = cstr(b, 12)
    numbones, boneindex = struct.unpack_from("<ii", b, 156)
    numlocalanim, localanimindex, numlocalseq, localseqindex = struct.unpack_from("<iiii", b, 180)

    # Bone names: sznameindex is the 2nd int of each bone, relative to the bone.
    # Detect the bone struct size from the gap between bones (works for v44 and v48).
    bones = []
    if numbones:
        bone_size = BONE_SIZE_48
        if numbones > 1:
            # first int of each bone is sznameindex; names live after the bone array, so
            # (bone0 + idx0) - (bone1 + idx1) shrinks by exactly bone_size; solve for it.
            i0 = struct.unpack_from("<i", b, boneindex)[0]
            for cand in (216, 212, 220, 224, 208, 200, 228, 232):
                i1 = struct.unpack_from("<i", b, boneindex + cand)[0]
                if boneindex + i0 < len(b) and boneindex + cand + i1 < len(b):
                    n0, n1 = cstr(b, boneindex + i0), cstr(b, boneindex + cand + i1)
                    if n0.isprintable() and n1.isprintable() and n0 and n1 and i0 - i1 == 0 + cand - cand + (i0 - i1):
                        if abs((boneindex + i0) - (boneindex + cand + i1)) < 64 * 1024 and n1 != n0:
                            bone_size = cand
                            break
        for i in range(numbones):
            base = boneindex + i * bone_size
            ni, parent = struct.unpack_from("<ii", b, base)
            bones.append({"name": cstr(b, base + ni), "parent": parent})

    anims = []
    animdesc_size = None
    if numlocalanim:
        # mstudioanimdesc_t: baseptr, sznameindex, fps, flags, numframes ... size differs by version.
        for cand in (100, 104, 96, 108, 112, 92, 88, 116, 120):
            ok = True
            for i in range(min(numlocalanim, 4)):
                base = localanimindex + i * cand
                ni = struct.unpack_from("<i", b, base + 4)[0]
                fps, flags, nframes = struct.unpack_from("<fii", b, base + 8)
                if not (0 < base + ni < len(b)) or not (0.5 <= fps <= 240) or not (0 < nframes < 100000):
                    ok = False
                    break
            if ok:
                animdesc_size = cand
                break
        for i in range(numlocalanim):
            base = localanimindex + i * animdesc_size
            ni = struct.unpack_from("<i", b, base + 4)[0]
            fps, flags, nframes = struct.unpack_from("<fii", b, base + 8)
            anims.append({"name": cstr(b, base + ni), "fps": round(fps, 3), "frames": nframes, "flags": flags})

    seqs = []
    for i in range(numlocalseq):
        base = localseqindex + i * SEQ_SIZE
        (baseptr, labeli, acti, flags, activity, actweight, numevents, eventindex) = struct.unpack_from("<iiiiiiii", b, base)
        numblends, animindexindex = struct.unpack_from("<ii", b, base + 56)
        groupsize = struct.unpack_from("<ii", b, base + 68)
        fadein, fadeout = struct.unpack_from("<ff", b, base + 104)
        keyvalueindex, keyvaluesize = struct.unpack_from("<ii", b, base + 172)
        events = []
        for e in range(numevents):
            eb = base + eventindex + e * EVENT_SIZE
            cycle, event, etype = struct.unpack_from("<fii", b, eb)
            options = cstr(b, eb + 12)
            szi = struct.unpack_from("<i", b, eb + 76)[0]
            evname = cstr(b, eb + szi) if szi else ""
            events.append({"cycle": round(cycle, 4), "event": event, "type": etype, "name": evname, "options": options})
        first_anim = struct.unpack_from("<h", b, base + animindexindex)[0] if numblends else -1
        a = anims[first_anim] if 0 <= first_anim < len(anims) else None
        kv = b[base + keyvalueindex: base + keyvalueindex + keyvaluesize].decode("latin1").strip("\0") if keyvaluesize else ""
        seqs.append({
            "name": cstr(b, base + labeli),
            "activity": cstr(b, base + acti) if acti else "",
            "actweight": actweight,
            "flags": flags,
            "blends": groupsize[0] * groupsize[1],
            "anim": a["name"] if a else "",
            "frames": a["frames"] if a else 0,
            "fps": a["fps"] if a else 0,
            "seconds": round((a["frames"] - 1) / a["fps"], 3) if a and a["fps"] and a["frames"] > 1 else 0,
            "fadein": round(fadein, 3), "fadeout": round(fadeout, 3),
            "events": events,
            "keyvalues": kv,
        })
    return {"file": path, "name": name, "version": ver, "bones": bones, "anims": len(anims),
            "animdesc_size": animdesc_size, "sequences": seqs}


SEQ_FLAGS = {0x1: "loop", 0x4: "delta", 0x8: "post", 0x200: "realtime", 0x400: "local", 0x800: "hidden"}


def main():
    m = read_model(sys.argv[1])
    print(f"{m['name']}  v{m['version']}  bones={len(m['bones'])} anims={m['anims']} seqs={len(m['sequences'])} (animdesc {m['animdesc_size']} B)")
    for s in m["sequences"]:
        fl = ",".join(v for k, v in SEQ_FLAGS.items() if s["flags"] & k)
        ev = " ".join(f"{e['cycle']:.2f}:{e['event']}{('/' + e['options']) if e['options'] else ''}" for e in s["events"])
        print(f"{s['name']:<52} {s['activity']:<28} {s['frames']:>4}f {s['fps']:>5}fps {s['seconds']:>6}s {fl:<12} {ev}")
    if "--json" in sys.argv:
        json.dump(m, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)


if __name__ == "__main__":
    main()
