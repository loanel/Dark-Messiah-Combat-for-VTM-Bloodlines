"""The occult blade's own blade texture: the game's kantanablade_clr_wield2 (the katana's steel tinted purple) with
more contrast and colour, so it reads as a different sword from the katana (chosen option
"contrast 2.0, colour 2.0"). Read from the user's Bloodlines packs at build time -> build/game/materials/models/
weapons/dm_katana/dm_occult_blade (tools/tga2ttx.py). weapon_prep.MATERIALS maps the blade to it.

usage: python tools/make_occult_blade.py [contrast] [colour]
"""
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageEnhance

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAME = os.path.dirname(ROOT)
sys.path.insert(0, HERE)
import ttx2png  # noqa: E402
import vtmbvpk  # noqa: E402

contrast = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
colour = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
SRC = "materials/models/weapons/katana/kantanablade_clr_wield2"
OUT = os.path.join(ROOT, "build", "game", "materials", "models", "weapons", "dm_katana")
VTFCMD = os.path.join(GAME, "SDKBinaries", "tools", "Texture Utils", "VTFCmd.exe")

# The fitting and the guard share one texture (left / right half; weapon_prep.ATLAS remaps their UVs): one material
# fewer in every arm model - studiovtmb49k's formatter takes at most 22 (toreador_female had 23).
FITTING = "materials/models/weapons/katana/kantanafitting_clr_wield2"
GUARD = "materials/models/weapons/katana/kantanatsubla_clr_view2"

idx = vtmbvpk.index(os.path.join(GAME, "Vampire"))


def game_texture(path, tmp):
    for ext in (".tth", ".ttz"):
        fn, o, n = idx[path + ext]
        with open(os.path.join(GAME, "Vampire", fn), "rb") as f:
            f.seek(o)
            open(os.path.join(tmp, "src" + ext), "wb").write(f.read(n))
    return ttx2png.decode(ttx2png.load_vtf(os.path.join(tmp, "src.tth"))).convert("RGB")


def to_game(im, name, tmp):
    tga = os.path.join(tmp, name + ".tga")
    im.save(tga)
    subprocess.run([sys.executable, os.path.join(HERE, "tga2ttx.py"), VTFCMD, OUT, "models/weapons/dm_katana", tga],
                   check=True)


with tempfile.TemporaryDirectory() as tmp:
    im = game_texture(SRC, tmp)
    im = ImageEnhance.Color(ImageEnhance.Contrast(im).enhance(contrast)).enhance(colour)
    to_game(im, "dm_occult_blade", tmp)
    a, b = game_texture(FITTING, tmp), game_texture(GUARD, tmp)
    h = max(a.height, b.height)
    w = max(a.width, b.width, h // 2)
    atlas = Image.new("RGB", (2 * w, h))
    atlas.paste(a.resize((w, h)), (0, 0))
    atlas.paste(b.resize((w, h)), (w, 0))
    to_game(atlas, "dm_occult_fittings", tmp)
print("occult blade textures: blade contrast %.1f, colour %.1f; fitting + guard atlas" % (contrast, colour))
