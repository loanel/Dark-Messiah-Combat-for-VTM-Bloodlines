"""DMCombat's textures and sound, made from the player's own game files (nothing from either game is shipped).

  python tools/make_textures.py [Dark Messiah data dir, default build/dm]

1. Arm (base model): Dark Messiah's player_gloves_1 / player_leather_2 / player_leather_1 (unpacked by
   tools/dm_extract.py) -> materials/models/weapons/dm_katana/dm_glove, dm_sleeve, dm_sleeve2.
2. Adrenaline bar, from Bloodlines' blood bar (the Unofficial Patch's file wins, as in the game):
   dm_adrenaline = hud/new_ui/bloodbar turned gold, dm_adrenalinebottom = bloodbarbottom turned gold,
   dm_adrenalineglow = the gold fill brighter, dm_adrenalineframe = bloodbarframe cut to the column of the tube.
3. Adrenaline-ready effects (our own art): tools/gen_adrenaline_fx.py -> dm_adrenalinereticle, edgel, edger.
4. Sound: Dark Messiah's adrenaline_reached.wav -> sound/dmcombat/adrenaline_reached.wav.
Textures go through the Bloodlines SDK's VTFCmd (<Bloodlines>\\SDKBinaries\\tools\\Texture Utils\\VTFCmd.exe) and
tools/tga2ttx.py. Output: build/game/materials/..., build/game/sound/... (installed by install.py).
"""
import colorsys
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAME = os.path.dirname(ROOT)
sys.path.insert(0, HERE)
import tga2ttx  # noqa: E402

VTFCMD = os.path.join(GAME, "SDKBinaries", "tools", "Texture Utils", "VTFCmd.exe")
OUT = os.path.join(ROOT, "build", "game")
WORK = os.path.join(ROOT, "build", "textures")  # intermediate TGAs
ARM = {"player_gloves_1": "dm_glove", "player_leather_2": "dm_sleeve", "player_leather_1": "dm_sleeve2"}
HUD_VMT = ('UnlitGeneric\n{\n\t"$basetexture"\t"hud/new_ui/%s"\n\t"$translucent" "1"\n\t"$ignorez" "1"\n'
           '\t"$vertexcolor" "1"\n\t"$vertexalpha" "1"\n}\n')


def vtf_to_image(vtf_path, work, fmt="png"):
    """Decode a VTF with the SDK's VTFCmd, as the textures were first made: PNG keeps the alpha channel (VTFCmd's TGA
    export loses it); the arm textures were made from its TGA export (opaque)."""
    subprocess.run([VTFCMD, "-file", os.path.abspath(vtf_path), "-output", os.path.abspath(work),
                    "-exportformat", fmt], check=True, capture_output=True)
    return Image.open(os.path.join(work, os.path.splitext(os.path.basename(vtf_path))[0] + "." + fmt))


def game_texture(rel, work):
    """A Bloodlines texture (materials/<rel>.tth + .ttz): the Unofficial Patch's loose copy, else the game's packs."""
    src = os.path.join(GAME, "Unofficial_Patch", "materials", rel)
    if not os.path.exists(src + ".tth"):
        subprocess.run([sys.executable, os.path.join(HERE, "vtmbvpk.py"), os.path.join(GAME, "Vampire"), "x",
                        re.escape("materials/" + rel) + r"\.(tth|ttz)$", work], check=True, capture_output=True)
        src = os.path.join(work, "materials", rel)
    h = open(src + ".tth", "rb").read()
    mips = h[6]
    o = 12 + 8 * mips
    vtf_size, ttz_size = struct.unpack_from("<II", h, o)
    vtf = h[o + 8:] + (zlib.decompress(open(src + ".ttz", "rb").read()) if ttz_size else b"")
    if len(vtf) != vtf_size:
        raise SystemExit("%s: texture doesn't reassemble (%d of %d bytes)" % (rel, len(vtf), vtf_size))
    path = os.path.join(work, os.path.basename(rel) + ".vtf")
    open(path, "wb").write(vtf)
    return vtf_to_image(path, work).convert("RGBA")


def recolour(im, hue, light_mul, light_add, sat_mul):
    im = im.copy()
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            r2, g2, b2 = colorsys.hls_to_rgb(hue, min(1.0, l * light_mul + light_add), min(1.0, s * sat_mul))
            px[x, y] = (int(r2 * 255), int(g2 * 255), int(b2 * 255), a)
    return im


def to_game(tgas, out_dir, mat_path, hud, newline="\r\n"):
    for tga in tgas:
        name = os.path.splitext(os.path.basename(tga))[0]
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([VTFCMD, "-file", os.path.abspath(tga), "-output", tmp, "-format", "DXT1",
                            "-alphaformat", "DXT5", "-version", "7.1"], check=True, capture_output=True)
            vtf = open(os.path.join(tmp, name + ".vtf"), "rb").read()
        tth, ttz = tga2ttx.pack(vtf)
        os.makedirs(out_dir, exist_ok=True)
        open(os.path.join(out_dir, name + ".tth"), "wb").write(tth)
        open(os.path.join(out_dir, name + ".ttz"), "wb").write(ttz)
        vmt = HUD_VMT % name if hud else '"VertexLitGeneric"\n{\n\t"$baseTexture" "%s/%s"\n}\n' % (mat_path, name)
        with open(os.path.join(out_dir, name + ".vmt"), "w", newline=newline) as f:
            f.write(vmt)
        print("  %s" % name)


def main():
    dm = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "dm")
    dm_files = os.path.join(dm, "dm_extract", "mm")
    if not os.path.exists(VTFCMD):
        raise SystemExit("VTFCmd not found: %s - install the Bloodlines SDK into the game folder" % VTFCMD)
    if not os.path.isdir(dm_files):
        raise SystemExit("no Dark Messiah data in %s - run tools/dm_extract.py first" % dm)
    arm_dir = os.path.join(WORK, "arm")
    hud_dir = os.path.join(WORK, "hud")
    for d in (arm_dir, hud_dir):
        os.makedirs(d, exist_ok=True)

    print("arm textures (Dark Messiah):")
    tgas = []
    with tempfile.TemporaryDirectory() as tmp:
        for src, dst in ARM.items():
            vtf = os.path.join(dm_files, "materials", "models", "npc_player", src + ".vtf")
            shutil.copyfile(vtf, os.path.join(tmp, dst + ".vtf"))  # export under our name
            im = vtf_to_image(os.path.join(tmp, dst + ".vtf"), tmp, "tga").convert("RGB")  # opaque: DXT1
            path = os.path.join(arm_dir, dst + ".tga")
            im.save(path)
            tgas.append(path)
    to_game(tgas, os.path.join(OUT, "materials", "models", "weapons", "dm_katana"), "models/weapons/dm_katana", False)

    print("adrenaline bar (Bloodlines blood bar):")
    with tempfile.TemporaryDirectory() as tmp:
        fill = game_texture("hud/new_ui/bloodbar", tmp)
        bottom = game_texture("hud/new_ui/bloodbarbottom", tmp)
        frame = game_texture("hud/new_ui/bloodbarframe", tmp)
    gold = recolour(fill, 0.115, 1.35, 0.04, 1.05)  # amber / gold
    gold.save(os.path.join(hud_dir, "dm_adrenaline.tga"))
    recolour(bottom, 0.115, 1.35, 0.04, 1.05).save(os.path.join(hud_dir, "dm_adrenalinebottom.tga"))
    recolour(gold, 0.13, 1.6, 0.18, 0.75).save(os.path.join(hud_dir, "dm_adrenalineglow.tga"))  # blink when full
    col = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    col.paste(frame.crop((84, 300, 114, 701)), (84, 300))  # only the rails around the tube
    col.save(os.path.join(hud_dir, "dm_adrenalineframe.tga"))
    print("adrenaline-ready effects (own art):")
    subprocess.run([sys.executable, os.path.join(HERE, "gen_adrenaline_fx.py"), hud_dir], check=True,
                   capture_output=True)
    bar = ["dm_adrenaline", "dm_adrenalinebottom", "dm_adrenalineglow", "dm_adrenalineframe"]
    fx = ["dm_adrenalinereticle", "dm_adrenalineedgel", "dm_adrenalineedger"]  # their vmts were written with LF
    hud_out = os.path.join(OUT, "materials", "hud", "new_ui")
    to_game([os.path.join(hud_dir, n + ".tga") for n in bar], hud_out, "hud/new_ui", True)
    to_game([os.path.join(hud_dir, n + ".tga") for n in fx], hud_out, "hud/new_ui", True, "\n")

    snd = os.path.join(OUT, "sound", "dmcombat")
    os.makedirs(snd, exist_ok=True)
    shutil.copyfile(os.path.join(dm_files, "sound", "arkane", "character_sheet", "adrenaline_reached.wav"),
                    os.path.join(snd, "adrenaline_reached.wav"))
    print("sound: sound/dmcombat/adrenaline_reached.wav")


if __name__ == "__main__":
    main()
