"""Remove every animation event from a Bloodlines MDL v2531 (sets each sequence's numevents to 0).

The animated katana arm reuses the Glock viewmodel's skeleton and sequences (studiovtmb49k keeps the donor's
animations), and those carry gun events (5001 muzzle flash plus malformed entries) that must never fire on the katana.
v2531 layout: header +272 numlocalseq, +276 localseqindex; seqdesc = 764 bytes, +0 szlabelindex, +20 numevents,
+24 eventindex (checked against v_pistol_glock.mdl: labels idle01 ... attack1).

usage: python tools/strip_mdl_events.py <model.mdl>
"""
import struct
import sys

path = sys.argv[1]
d = bytearray(open(path, "rb").read())
n, idx = struct.unpack_from("<2i", d, 272)
stripped = 0
for i in range(n):
    o = idx + i * 764
    li = struct.unpack_from("<i", d, o)[0]
    label = bytes(d[o + li:o + li + 32]).split(b"\0")[0].decode("latin1")
    ne = struct.unpack_from("<i", d, o + 20)[0]
    if ne:
        struct.pack_into("<i", d, o + 20, 0)
        stripped += ne
        print("  %s: %d events removed" % (label, ne))
open(path, "wb").write(d)
print("%s: %d sequences, %d events removed" % (path, n, stripped))
