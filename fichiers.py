"""
PixelShell — lecture et écriture des fichiers.

  - Importer : PNG, GIF (toutes ses images), JPEG, BMP, WebP…
  - Exporter : PNG, planche de sprites PNG, GIF animé
  - Projet   : un fichier .pxshell (du JSON lisible) qui garde TOUT : les images de
               l'animation, la palette, la grille, la vitesse… pour reprendre plus tard.
"""

import base64
import io
import json

import numpy as np
from PIL import Image, ImageOps, ImageSequence

import moteur

EXTENSION_PROJET = ".pxshell"
FORMATS_IMAGE = "*.png *.gif *.jpg *.jpeg *.bmp *.webp *.tga *.tif *.tiff"


def _vers_rgba(pil):
    pil = ImageOps.exif_transpose(pil) if pil.format == "JPEG" else pil
    return np.asarray(pil.convert("RGBA")).copy()


def importer(chemin):
    """Renvoie (images, durée d'une image en ms ou None). Un GIF animé donne plusieurs images."""
    with Image.open(chemin) as pil:
        images, durees = [], []
        for image in ImageSequence.Iterator(pil):
            images.append(moteur.nettoyer_alpha(_vers_rgba(image)))
            durees.append(image.info.get("duration"))
            if len(images) >= 256:
                break
    duree = next((d for d in durees if d), None)
    # Toutes les images d'une animation doivent avoir la même taille
    h, w = images[0].shape[:2]
    images = [i if i.shape[:2] == (h, w) else moteur.redimensionner_toile(i, w, h) for i in images]
    return images, duree


def _png_base64(img):
    tampon = io.BytesIO()
    Image.fromarray(img, "RGBA").save(tampon, "PNG", optimize=True)
    return base64.b64encode(tampon.getvalue()).decode("ascii")


def enregistrer_png(chemin, img, echelle=1, rapport=1):
    Image.fromarray(moteur.agrandir(img, echelle, rapport), "RGBA").save(chemin, "PNG", optimize=True)


def enregistrer_planche(chemin, images, echelle=1, rapport=1, colonnes=0):
    enregistrer_png(chemin, moteur.planche(images, colonnes), echelle, rapport)


def enregistrer_gif(chemin, images, ips=8, echelle=1, rapport=1):
    """GIF animé avec transparence. Le GIF n'a que 256 couleurs, ce qui suffit toujours
    en pixel art : on construit la palette nous-mêmes pour ne perdre aucune couleur."""
    grandes = [moteur.agrandir(i, echelle, rapport) for i in images]
    couleurs = moteur.couleurs_utilisees(images, limite=255)
    palette = [(0, 0, 0)] + [moteur.hex_vers_rgba(c)[:3] for c in couleurs]  # 0 = transparent
    table = {c: i for i, c in enumerate(palette)}
    plat = sum((list(c) for c in palette), []) + [0] * (3 * (256 - len(palette)))
    cadres = []
    for img in grandes:
        indices = np.zeros(img.shape[:2], np.uint8)
        opaques = img[..., 3] > 0
        if opaques.any():
            rvb = img[opaques][:, :3]
            if len(table) > 255:  # plus de 255 couleurs : on ramène à la plus proche
                rvb = moteur.quantifier(img, couleurs)[opaques][:, :3]
            indices[opaques] = [table.get(tuple(int(v) for v in p), 1) for p in rvb]
        cadre = Image.fromarray(indices, "P")
        cadre.putpalette(plat)
        cadres.append(cadre)
    cadres[0].save(chemin, "GIF", save_all=True, append_images=cadres[1:], loop=0,
                   duration=max(20, round(1000 / max(1, ips))), transparency=0, disposal=2,
                   optimize=False)


def enregistrer_projet(chemin, images, reglages):
    donnees = {"format": "pixelshell", "version": 1,
               "largeur": int(images[0].shape[1]), "hauteur": int(images[0].shape[0]),
               "reglages": reglages, "images": [_png_base64(i) for i in images]}
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=1)


def charger_projet(chemin):
    with open(chemin, encoding="utf-8") as f:
        donnees = json.load(f)
    if donnees.get("format") != "pixelshell":
        raise ValueError("Ce fichier n'est pas un projet PixelShell.")
    images = []
    for b64 in donnees["images"]:
        with Image.open(io.BytesIO(base64.b64decode(b64))) as pil:
            images.append(moteur.nettoyer_alpha(np.asarray(pil.convert("RGBA")).copy()))
    return images, donnees.get("reglages", {})
