"""dmcombat_dm.bin: the Dark Messiah data the plug-in plays back, generated on the player's PC from their own Dark Messiah
install (tools/gen_sword_paths.py) and read by the plug-in at startup (src/dmcombat/dm_data.cpp). Nothing in it is
shipped: the repository and the release contain only this format and the code that builds it.

Layout (little endian):
  header : char magic[4] = "DMCD", u32 version = 1, u32 numPaths, u32 armBones (7), u32 numWindows
  path   : char name[64], f32 fps, u32 numFrames,
           f32 keys[numFrames][7]            sword-hand transform per frame (pos xyz, quat xyzw), eye space
           f32 arm[numFrames][armBones][7]   each driven arm bone's motion relative to the reference pose
  window : char name[64], u32 index, f32 open, f32 close, f32 impact   hit windows from the animation events (cycles)
"""
import struct

MAGIC, VERSION, NAME = b"DMCD", 1, 64


def write(path, paths, windows, arm_bones):
    """paths: [(name, fps, keys [(pos3, quat4)], arm [(pos3, quat4)] * frames*arm_bones)];
    windows: [(name, index, open, close, impact)]"""
    with open(path, "wb") as f:
        f.write(MAGIC + struct.pack("<IIII", VERSION, len(paths), arm_bones, len(windows)))
        for name, fps, keys, arm in paths:
            assert len(arm) == len(keys) * arm_bones
            f.write(name.encode("ascii").ljust(NAME, b"\0")[:NAME])
            f.write(struct.pack("<fI", fps, len(keys)))
            for p, q in keys + arm:
                f.write(struct.pack("<7f", *p, *q))
        for name, index, o, c, imp in windows:
            f.write(name.encode("ascii").ljust(NAME, b"\0")[:NAME])
            f.write(struct.pack("<Ifff", index, o, c, imp))


def read(path):
    """-> (paths {name: (fps, keys [[7 floats]], arm [[7 floats]])}, windows [(name, index, open, close, impact)])"""
    b = open(path, "rb").read()
    assert b[:4] == MAGIC, "not a dmcombat_dm.bin"
    version, n_paths, arm_bones, n_windows = struct.unpack_from("<IIII", b, 4)
    assert version == VERSION
    o = 20
    paths = {}
    for _ in range(n_paths):
        name = b[o:o + NAME].split(b"\0")[0].decode("ascii")
        fps, frames = struct.unpack_from("<fI", b, o + NAME)
        o += NAME + 8
        vals = struct.unpack_from("<%df" % (7 * frames * (1 + arm_bones)), b, o)
        o += 4 * len(vals)
        rows = [list(vals[i:i + 7]) for i in range(0, len(vals), 7)]
        paths[name] = (fps, rows[:frames], rows[frames:])
    windows = []
    for _ in range(n_windows):
        name = b[o:o + NAME].split(b"\0")[0].decode("ascii")
        index, op, cl, imp = struct.unpack_from("<Ifff", b, o + NAME)
        o += NAME + 16
        windows.append((name, index, op, cl, imp))
    return paths, windows
