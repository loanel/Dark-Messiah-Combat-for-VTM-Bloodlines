"""Bloodlines texture (.tth + .ttz) -> PNG (top mip; DXT1/DXT5 or BGR888/BGRA8888). Inverse of tga2ttx.py's packing.

usage: python tools/ttx2png.py <file.tth> <out.png>
"""
import struct
import sys
import zlib

import numpy as np
from PIL import Image


def load_vtf(tth_path):
    tth = open(tth_path, "rb").read()
    mips = tth[6]
    chunk = struct.unpack_from("<I", tth, 8)[0]
    o = 12 + 8 * mips + 8
    return tth[o:o + chunk] + zlib.decompress(open(tth_path[:-4] + ".ttz", "rb").read())


def dxt_colors(c0, c1):
    def rgb(c):
        return np.stack([((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31], -1)
    a, b = rgb(c0).astype(np.int32), rgb(c1).astype(np.int32)
    four = c0 > c1
    c2 = np.where(four[:, None], (2 * a + b) // 3, (a + b) // 2)
    c3 = np.where(four[:, None], (a + 2 * b) // 3, 0)
    return np.stack([a, b, c2, c3], 1)  # blocks x 4 x 3


def decode(vtf):
    w, h = struct.unpack_from("<HH", vtf, 16)
    fmt = struct.unpack_from("<i", vtf, 52)[0]
    bw, bh = max(w // 4, 1), max(h // 4, 1)
    if fmt in (13, 15):  # DXT1, DXT5
        bs = 8 if fmt == 13 else 16
        data = np.frombuffer(vtf[len(vtf) - bw * bh * bs:], np.uint8).reshape(-1, bs)
        col = data[:, bs - 8:]
        c0 = col[:, 0].astype(np.uint16) | (col[:, 1].astype(np.uint16) << 8)
        c1 = col[:, 2].astype(np.uint16) | (col[:, 3].astype(np.uint16) << 8)
        pal = dxt_colors(c0, c1)
        bits = col[:, 4:8].astype(np.uint32)
        idx = bits[:, 0] | (bits[:, 1] << 8) | (bits[:, 2] << 16) | (bits[:, 3] << 24)
        sel = (idx[:, None] >> (2 * np.arange(16))) & 3
        px = pal[np.arange(len(pal))[:, None], sel]  # blocks x 16 x 3
        img = px.reshape(bh, bw, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 3)
        return Image.fromarray(img.astype(np.uint8), "RGB")
    if fmt in (2, 3):  # BGR888, BGR888? (VTF: 2 = BGR888, 3 = BGR888)
        a = np.frombuffer(vtf[len(vtf) - w * h * 3:], np.uint8).reshape(h, w, 3)[:, :, ::-1]
        return Image.fromarray(a.copy(), "RGB")
    if fmt == 12:  # BGRA8888
        a = np.frombuffer(vtf[len(vtf) - w * h * 4:], np.uint8).reshape(h, w, 4)[:, :, [2, 1, 0, 3]]
        return Image.fromarray(a.copy(), "RGBA")
    raise SystemExit("unsupported VTF format %d" % fmt)


if __name__ == "__main__":
    vtf = load_vtf(sys.argv[1])
    assert vtf[:4] == b"VTF\0", "not a VTF"
    im = decode(vtf)
    im.save(sys.argv[2])
    print("%s: %dx%d format %d" % (sys.argv[2], im.width, im.height, struct.unpack_from("<i", vtf, 52)[0]))
