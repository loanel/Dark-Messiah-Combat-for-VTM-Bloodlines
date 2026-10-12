"""Read files out of Source engine VPK packs (v1/v2: Dark Messiah's vpks/*_dir.vpk). Bloodlines' own packs are a
different format (tools/vtmbvpk.py).

  from dm_vpk import extract
  extract(vpk_dir, out_dir, ["mm/models/npc/player/first_basic.*"])   # fnmatch globs, case-insensitive
"""
import fnmatch
import glob
import os
import struct


def _cstr(f):
    b = bytearray()
    while (c := f.read(1)) not in (b"\0", b""):
        b += c
    return b.decode("latin1")


def entries(vpk_dir):
    """(dir_vpk, data_start, path, archive, offset, length, preload) for every file in every *_dir.vpk."""
    for p in sorted(glob.glob(os.path.join(vpk_dir, "*_dir.vpk"))):
        with open(p, "rb") as f:
            sig, ver, tree_size = struct.unpack("<III", f.read(12))
            if sig != 0x55AA1234 or ver not in (1, 2):
                raise ValueError("%s: not a VPK v1/v2 directory" % p)
            if ver == 2:
                f.read(16)
            header = f.tell()
            while (ext := _cstr(f)):
                while (d := _cstr(f)):
                    while (name := _cstr(f)):
                        crc, pre, arc, off, ln, _term = struct.unpack("<IHHIIH", f.read(18))
                        preload = f.read(pre)
                        path = "%s/%s.%s" % (d, name, ext) if d != " " else "%s.%s" % (name, ext)
                        yield p, header + tree_size, path, arc, off, ln, preload


def extract(vpk_dir, out_dir, patterns):
    """Extract the files matching any pattern; returns the list of in-pack paths written (lower case)."""
    done = []
    for dirp, data_start, path, arc, off, ln, pre in entries(vpk_dir):
        lp = path.lower()
        if not any(fnmatch.fnmatch(lp, pat.lower()) for pat in patterns):
            continue
        if arc == 0x7FFF:  # stored in the _dir.vpk itself, after the tree
            src, pos = dirp, data_start + off
        else:
            src, pos = dirp.replace("_dir.vpk", "_%03d.vpk" % arc), off
        with open(src, "rb") as g:
            g.seek(pos)
            blob = pre + g.read(ln)
        dst = os.path.join(out_dir, *lp.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as g:
            g.write(blob)
        done.append(lp)
    return done
