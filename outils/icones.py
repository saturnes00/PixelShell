"""Génère les icônes de l'app (icone.png, icone.ico pour Windows, icone.icns pour macOS)."""

import os

import numpy as np
from PIL import Image, ImageDraw

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# La mascotte (même dessin que dans app.py, recopié pour ne pas charger l'interface)
COQUILLE = [
    ".......XXXXX....",
    ".....XXXXXXXXX..",
    "....XXSSSSSSXXX.",
    "...XXSXXXXXXSXXX",
    "...XSXXSSSSXXSXX",
    "...XSXSXXXXSXSXX",
    "O.OXSXSXSSXSXSXX",
    "C.CXSXSXXSXSXSXX",
    "CCCXSXXSSXXSXXX.",
    ".CCXXSXXXXSXXX..",
    "CC..XXSSSSXXX...",
    "C.C.C.XXXXXX....",
]
DEGRADE = ((0xff, 0x7a, 0x3d), (0xff, 0x4f, 0x62), (0xff, 0x3d, 0x9a))


def degrade(u):
    a, b, v = (DEGRADE[0], DEGRADE[1], u / 0.5) if u < 0.5 else (DEGRADE[1], DEGRADE[2], (u - 0.5) / 0.5)
    return tuple(round(x + (y - x) * v) for x, y in zip(a, b))


def dessiner(n=1024):
    # Fond : une grille de pixels sombres, avec un halo au centre
    y, x = np.mgrid[0:n, 0:n] / n
    halo = np.clip(1 - np.hypot(x - 0.5, y - 0.52) * 2.1, 0, 1) ** 1.6
    fond = np.dstack([11 + 47 * halo, 11 + 9 * halo, 13 + 1 * halo]).astype(np.uint8)
    case = n // 32
    fond[::case, :] = (fond[::case, :] * 0.6).astype(np.uint8)
    fond[:, ::case] = (fond[:, ::case] * 0.6).astype(np.uint8)
    fond = Image.fromarray(fond)
    d = ImageDraw.Draw(fond)
    t = n * 44 // 1024
    largeur = len(COQUILLE[0])
    cw, ch = largeur * t, len(COQUILLE) * t
    x0, y0 = (n - cw) // 2, (n - ch) // 2 + n // 50
    for j, ligne in enumerate(COQUILLE):
        for i, c in enumerate(ligne):
            if c == ".":
                continue
            couleur = {"O": (236, 231, 225), "S": (26, 7, 16), "C": (255, 138, 99)}.get(c) or degrade(i / (largeur - 1))
            d.rectangle((x0 + i * t, y0 + j * t, x0 + (i + 1) * t - 3, y0 + (j + 1) * t - 3), fill=couleur)
    masque = Image.new("L", (n, n), 0)
    ImageDraw.Draw(masque).rounded_rectangle((60, 60, n - 60, n - 60), radius=210, fill=255)
    icone = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    icone.paste(fond, (0, 0), masque)
    return icone


if __name__ == "__main__":
    icone = dessiner()
    icone.save(os.path.join(RACINE, "icone.png"))
    icone.save(os.path.join(RACINE, "icone.ico"),
               sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icone.save(os.path.join(RACINE, "icone.icns"))
    print("Icônes créées : icone.png, icone.ico, icone.icns")
