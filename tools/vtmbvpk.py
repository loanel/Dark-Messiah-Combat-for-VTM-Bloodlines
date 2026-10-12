"""List/extract files from Bloodlines VPKs. Footer: u32 count, u32 dir_offset, u8 flag.
Entry: u32 name_len, name, u32 offset, u32 size. Later packs override earlier ones."""
import struct, sys, re, os
def entries(p):
    with open(p, 'rb') as f:
        f.seek(-9, 2); n, off, flag = struct.unpack('<IIB', f.read(9))
        if flag: return
        f.seek(off)
        for _ in range(n):
            l = struct.unpack('<I', f.read(4))[0]; name = f.read(l).decode('latin1')
            o, s = struct.unpack('<II', f.read(8)); yield name, o, s
def index(d):
    idx = {}
    for fn in sorted(os.listdir(d)):
        if re.match(r'pack\d+\.vpk$', fn):
            for name, o, s in entries(os.path.join(d, fn)): idx[name.lower()] = (fn, o, s)
    return idx
if __name__ == '__main__':
    d, cmd, pat = sys.argv[1], sys.argv[2], re.compile(sys.argv[3], re.I)
    out = sys.argv[4] if len(sys.argv) > 4 else None
    for name, (fn, o, s) in sorted(index(d).items()):
        if not pat.search(name): continue
        print(fn, name, s)
        if cmd == 'x':
            dst = os.path.join(out, name); os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(os.path.join(d, fn), 'rb') as f: f.seek(o); open(dst, 'wb').write(f.read(s))
