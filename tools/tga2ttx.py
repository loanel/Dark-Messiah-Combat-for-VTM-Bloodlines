"""TGA -> Bloodlines texture (.tth + .ttz) + .vmt.

Bloodlines' .tth = "TTH\\0" 1.0, mip count, aspect byte, uint32 chunk size, 8 zero bytes per mip, uint32 VTF size,
uint32 .ttz size, then the first <chunk> bytes of a VTF 7.1 (header + thumbnail); .ttz = zlib(rest of the VTF).
Verified by reassembling the game's own kantanablade_clr_wield (SDK notes: service/ttx_struct.inf).
The VTF is made by the SDK's VTFCmd (DXT1, mipmaps, VTF 7.1).

usage: python tools/tga2ttx.py <VTFCmd.exe> <out materials dir> <material path for the vmt> <file.tga>...
  e.g. ... build/game/materials/models/weapons/dm_katana models/weapons/dm_katana modelsrc/.../dm_glove.tga
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib


def pack(vtf):
    assert vtf[:4] == b"VTF\0" and struct.unpack_from("<II", vtf, 4) == (7, 1), "need VTF 7.1"
    hdr = struct.unpack_from("<I", vtf, 12)[0]
    mips = vtf[56]
    tw, th = vtf[61], vtf[62]
    thumb = (tw * th) // 2 if tw and th else 0  # DXT1 thumbnail
    chunk = vtf[:hdr + thumb]
    rest = zlib.compress(vtf[len(chunk):], 9)
    tth = b"TTH\0\x01\x00" + bytes([mips, 0]) + struct.pack("<I", len(chunk)) + b"\0" * (8 * mips)
    tth += struct.pack("<II", len(vtf), len(rest)) + chunk
    return tth, rest


def main():
    vtfcmd, out_dir, mat_path = sys.argv[1:4]
    os.makedirs(out_dir, exist_ok=True)
    for tga in sys.argv[4:]:
        name = os.path.splitext(os.path.basename(tga))[0]
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([vtfcmd, "-file", os.path.abspath(tga), "-output", tmp, "-format", "DXT1",
                            "-alphaformat", "DXT5", "-version", "7.1"], check=True, capture_output=True)
            vtf = open(os.path.join(tmp, name + ".vtf"), "rb").read()
        tth, ttz = pack(vtf)
        open(os.path.join(out_dir, name + ".tth"), "wb").write(tth)
        open(os.path.join(out_dir, name + ".ttz"), "wb").write(ttz)
        with open(os.path.join(out_dir, name + ".vmt"), "w", newline="\r\n") as f:
            f.write('"VertexLitGeneric"\n{\n\t"$baseTexture" "%s/%s"\n}\n' % (mat_path, name))
        print("%s: VTF %d bytes -> tth %d + ttz %d" % (name, len(vtf), len(tth), len(ttz)))


if __name__ == "__main__":
    main()
