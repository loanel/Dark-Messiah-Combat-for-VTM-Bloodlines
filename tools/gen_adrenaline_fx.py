"""Adrenaline-ready screen effects (our own art, no game files): a red reticle ring drawn over the crosshair and
soft red glows for the left/right screen edges (Dark Messiah flashed the screen edges when adrenaline was full).
usage: python tools/gen_adrenaline_fx.py <out dir for the TGAs>"""
import os, sys
import numpy as np
from PIL import Image

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
RED = (235, 30, 20)

def save(name, alpha):
    a = np.clip(alpha, 0, 1)
    img = np.zeros(a.shape + (4,), np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = RED
    img[..., 3] = (a * 255).astype(np.uint8)
    Image.fromarray(img, 'RGBA').save(os.path.join(out, name + '.tga'))

# reticle: ring of radius ~0.62 with four gaps at the diagonals and a small centre dot
n = 64
y, x = np.mgrid[0:n, 0:n] + 0.5
dx, dy = (x - n / 2) / (n / 2), (y - n / 2) / (n / 2)
r = np.hypot(dx, dy)
ring = np.exp(-((r - 0.62) / 0.07) ** 2)
ang = np.abs(np.sin(2 * np.arctan2(dy, dx)))  # 0 on the axes, 1 on the diagonals
ring *= np.clip((1 - ang) * 3, 0, 1)
dot = np.exp(-(r / 0.09) ** 2)
glow = 0.35 * np.exp(-((r - 0.62) / 0.22) ** 2)
save('dm_adrenalinereticle', ring + dot + glow)

# edges: 128 x 512, full at the screen edge, fading inward and towards the top/bottom
w, h = 128, 512
y, x = np.mgrid[0:h, 0:w] + 0.5
fall = (1 - x / w) ** 2.2
vert = np.sin(np.pi * y / h) ** 0.6
left = fall * vert * 0.9
save('dm_adrenalineedgel', left)
save('dm_adrenalineedger', left[:, ::-1])
print('ok')
