"""Move "Cast Discipline Power" (vm_discipline) off the right mouse button: DMCombat's block is on RMB.

The default becomes Q (unbound in the Unofficial Patch, next to W). It stays an ordinary keybind: players change it in
Options > Keyboard ("Cast Discipline Power", scripts/kb_act.lst) and the plug-in doesn't care which key it is.

  python tools/make_keys.py            patched defaults -> build/keys/ (originals backed up once to backup/keys_orig/):
                                         scripts/kb_def.lst  (Options "Use defaults")
                                         cfg/default.cfg     (a new or reset config)
  python tools/make_keys.py --bind     the player's own binds (cfg/config.cfg): MOUSE2 -> Q, only when discipline is
                                       still on MOUSE2 and Q is unbound; recorded in backup/keys_orig/rebound.txt
  python tools/make_keys.py --unbind   undoes --bind (only if the player hasn't rebound it since)

config.cfg is rewritten by the game when it quits: --bind / --unbind with the game closed.
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UP = os.path.join(os.path.dirname(ROOT), "Unofficial_Patch")
BACKUP = os.path.join(ROOT, "backup", "keys_orig")
OUT = os.path.join(ROOT, "build", "keys")
REBOUND = os.path.join(BACKUP, "rebound.txt")
KEY = "q"
FILES = {  # relative path -> (pattern of the MOUSE2 line, replacement)
    "scripts/kb_def.lst": (r'(?m)^"MOUSE2"[ \t]+"vm_discipline"[^\r\n]*',
                           '"%s"\t\t\t"vm_discipline"' % KEY),  # no comment: the Options parser may not skip one
    "cfg/default.cfg": (r'(?m)^bind "MOUSE2" "vm_discipline"[^\r\n]*',
                        'bind "%s" "vm_discipline"\t// DMCombat: right mouse blocks' % KEY),
}
CONFIG = os.path.join(UP, "cfg", "config.cfg")
BIND_RE = r'(?mi)^bind "%s" "([^"]*)"'


def read(path):
    return open(path, "rb").read().decode("latin1")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(text.encode("latin1"))


def build_defaults():
    os.makedirs(BACKUP, exist_ok=True)
    for rel, (pat, rep) in FILES.items():
        live = os.path.join(UP, rel)
        bak = os.path.join(BACKUP, os.path.basename(rel))
        if not os.path.exists(bak):
            if "DMCombat" in read(live):
                raise SystemExit("%s is already patched and no original is backed up" % live)
            shutil.copyfile(live, bak)
        orig = read(bak)
        if re.search(r'(?mi)^(?:bind )?"%s"[ \t]' % KEY, orig):
            raise SystemExit("%s: key %s is already bound there" % (bak, KEY))
        text, n = re.subn(pat, rep, orig, count=1)
        if not n:
            raise SystemExit("%s: no MOUSE2 discipline line - the Unofficial Patch changed?" % bak)
        write(os.path.join(OUT, rel), text)
        print("%-20s MOUSE2 -> %s" % (rel, KEY.upper()))


def bind_config(undo):
    text = read(CONFIG)
    m2 = re.search(BIND_RE % "MOUSE2", text)
    k = re.search(BIND_RE % KEY, text)
    if not undo:
        if not m2 or m2.group(1) != "vm_discipline":
            if k and k.group(1) == "vm_discipline":
                print("config.cfg: Cast Discipline Power already on %s" % KEY.upper())
            else:
                print("config.cfg: discipline is not on MOUSE2 (player's own layout) - left alone")
            return
        if k:
            print('config.cfg: %s is already bound to "%s" - left alone; rebind in Options' % (KEY.upper(), k.group(1)))
            return
        text = text[:m2.start()] + 'bind "%s" "vm_discipline"' % KEY + text[m2.end():]
        write(CONFIG, text)
        os.makedirs(BACKUP, exist_ok=True)
        open(REBOUND, "w").write("config.cfg: vm_discipline moved from MOUSE2 to %s by make_keys.py --bind\n" % KEY)
        print("config.cfg: Cast Discipline Power MOUSE2 -> %s" % KEY.upper())
    else:
        if not os.path.exists(REBOUND):
            return
        if k and k.group(1) == "vm_discipline" and not m2:
            text = text[:k.start()] + 'bind "MOUSE2" "vm_discipline"' + text[k.end():]
            write(CONFIG, text)
            print("config.cfg: Cast Discipline Power back on MOUSE2")
        else:
            print("config.cfg: discipline was rebound by the player since - left alone")
        os.remove(REBOUND)


if __name__ == "__main__":
    if "--bind" in sys.argv:
        bind_config(False)
    elif "--unbind" in sys.argv:
        bind_config(True)
    else:
        build_defaults()
