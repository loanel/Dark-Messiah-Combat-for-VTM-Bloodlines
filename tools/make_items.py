"""Patch every melee weapon's item file for DMCombat (same three changes the katana got):
  viewmodel -> models/weapons/dm_katana/v_dm_katana_arm.mdl (the arm model; the plug-in swaps in the character's),
  camera_class "melee" -> "force_1st" (first person only: the third-person melee animations don't fit our weapons; "noswitch"
  from UP's View Free Weapons is no class the game knows - it only stopped the automatic switch), and the commented-out crosshair block enabled.
Originals are backed up once to backup/items_orig/ (an original is a file without "DMCombat" in it); patched copies
go to build/items/ for install.py.

usage: python tools/make_items.py
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import weapon_prep  # noqa: E402

UP_ITEMS = os.path.join(os.path.dirname(ROOT), "Unofficial_Patch", "vdata", "items")
BACKUP = os.path.join(ROOT, "backup", "items_orig")
OUT = os.path.join(ROOT, "build", "items")
VIEWMODEL = "models/weapons/dm_katana/v_dm_katana_arm.mdl"
SOUND_SWAPS = {"item_w_sledgehammer.txt": [("Weapons/Melee/Sledgehammer/Swish_2.wav", "Weapons/Melee/Baseball_Bat/Swish_1.wav"),
                                           ("Weapons/Melee/Sledgehammer/Swish_3.wav", "Weapons/Melee/Baseball_Bat/Swish_3.wav")]}

os.makedirs(BACKUP, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
for name, (_, _, item) in weapon_prep.VTABLES.items():
    fname = item + ".txt"
    bak = os.path.join(BACKUP, fname)
    live = os.path.join(UP_ITEMS, fname)
    if not os.path.exists(bak):
        src = live
        data = open(src, "rb").read()
        if b"DMCombat" in data:
            raise SystemExit("%s is already patched and no original is backed up" % src)
        shutil.copyfile(src, bak)
    text = open(bak, "rb").read().decode("latin1")
    n_vm = 0

    def vm(m):
        global n_vm
        n_vm += 1
        return '%s"viewmodel"\t"%s"\t// DMCombat: animated arm (dmcombat.vtm)' % (m.group(1), VIEWMODEL)

    # the active (uncommented) viewmodel line only
    text, n1 = re.subn(r'(?m)^([ \t]*)"viewmodel"[ \t]+"[^"]*"[^\r\n]*', lambda m: '%s"viewmodel"\t"%s"\t// DMCombat: animated arm (dmcombat.vtm)' % (m.group(1), VIEWMODEL), text, count=1)
    text, n2 = re.subn(r'"camera_class"(\s+)"melee"', r'"camera_class"\1"force_1st"\t// DMCombat: first person only', text, count=1)
    m = re.search(r'(?m)^[ \t]*//[ \t]*"crosshair"[\s\S]*?\n[ \t]*//[ \t]*\}[ \t]*\r?\n(?:[ \t]*//[ \t]*\}[ \t]*\r?\n)?', text)
    n3 = 0
    if m:
        block = re.sub(r'(?m)^([ \t]*)//[ \t]?', r'\1', m.group(0))
        block = block.replace('"crosshair"', '"crosshair"\t// DMCombat: aim point', 1)
        text = text[:m.start()] + block + text[m.end():]
        n3 = 1
    elif '"crosshair"' not in text:
        # no crosshair block at all (item_w_occultblade): add the katana's one at the end of SpriteData
        sd = re.search(r'SpriteData\s*\{', text)
        if sd:
            depth, i = 1, sd.end()
            while depth and i < len(text):
                depth += {"{": 1, "}": -1}.get(text[i], 0)
                i += 1
            close = i - 1  # SpriteData's closing brace
            block = ('\t"crosshair"\t// DMCombat: aim point (added; the original has none)\r\n\t{\r\n\t\t"640"\r\n\t\t{\r\n'
                     '\t\t\t"file"\t\t"crosshairs"\r\n\t\t\t"x"\t\t\t"0"\r\n\t\t\t"y"\t\t\t"48"\r\n'
                     '\t\t\t"width"\t\t"24"\r\n\t\t\t"height"\t"24"\r\n\t\t}\r\n\t}\r\n\t')
            text = text[:close] + block + text[close:]
            n3 = 1
    # swing sounds: the sledgehammer's Swish_2/3 are as bright as the katana's (spectral centroid ~3.2-4.0 kHz vs
    # 3.8-4.3 kHz; user: "blade whoosh"); its Swish_1 (2.6 kHz) stays, the other two become the bat's deepest
    for old, new in SOUND_SWAPS.get(fname, ()):
        text = re.sub(re.escape('"%s"' % old), '"%s"' % new, text, flags=re.I)
    open(os.path.join(OUT, fname), "wb").write(text.encode("latin1"))
    print("%-24s viewmodel %d, camera %d, crosshair %d" % (fname, n1, n2, n3))
