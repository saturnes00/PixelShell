"""
PixelShell — le moteur : tout ce qui touche aux pixels, sans aucune interface.

Une image est un tableau numpy de forme (hauteur, largeur, 4) en uint8 : rouge, vert,
bleu, alpha. Un pixel est soit opaque (alpha 255), soit vide (alpha 0) : en pixel art,
pas de demi-mesure.

Les outils renvoient des listes de points (x, y) ; c'est `tamponner` qui les pose sur
l'image avec la bonne taille de pinceau et les symétries. Comme ça chaque outil reste
une petite fonction facile à lire et à tester.
"""

from collections import deque

import numpy as np

VIDE = (0, 0, 0, 0)
TAILLE_MAX = 2048  # assez pour une planche de sprites (ex. 12 images de 100 × 80 = 1200 × 80)

# ---------------------------------------------------------------------------
# Palettes (ajouter une ligne ici suffit pour qu'elle apparaisse dans l'app)
# ---------------------------------------------------------------------------

PALETTES = {
    "PICO-8": ["#000000", "#1d2b53", "#7e2553", "#008751", "#ab5236", "#5f574f", "#c2c3c7",
               "#fff1e8", "#ff004d", "#ffa300", "#ffec27", "#00e436", "#29adff", "#83769c",
               "#ff77a8", "#ffccaa"],
    # Les couleurs du jeu Montauk (mises à jour avec les dessins de Saynt du 18/11/2026)
    "Montauk": ["#000000", "#f0f0f0", "#cfccda", "#8c8c96", "#464650", "#1a00e6", "#3512f9",
                "#2838f0", "#0e0e82", "#f01414", "#ff1818", "#ee1616", "#b90000", "#ac3424",
                "#460606", "#5a0000", "#ffd61e", "#ff9600", "#942a1e", "#b03616", "#1a782c",
                "#96baaa"],
    "Game Boy": ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"],
    "Sweetie 16": ["#1a1c2c", "#5d275d", "#b13e53", "#ef7d57", "#ffcd75", "#a7f070",
                   "#38b764", "#257179", "#29366f", "#3b5dc9", "#41a6f6", "#73eff7",
                   "#f4f4f4", "#94b0c2", "#566c86", "#333c57"],
    "Endesga 32": ["#be4a2f", "#d77643", "#ead4aa", "#e4a672", "#b86f50", "#733e39",
                   "#3e2731", "#a22633", "#e43b44", "#f77622", "#feae34", "#fee761",
                   "#63c74d", "#3e8948", "#265c42", "#193c3e", "#124e89", "#0099db",
                   "#2ce8f5", "#ffffff", "#c0cbdc", "#8b9bb4", "#5a6988", "#3a4466",
                   "#262b44", "#181425", "#ff0044", "#68386c", "#b55088", "#f6757a",
                   "#e8b796", "#c28569"],
    "Commodore 64": ["#000000", "#ffffff", "#880000", "#aaffee", "#cc44cc", "#00cc55",
                     "#0000aa", "#eeee77", "#dd8855", "#664400", "#ff7777", "#333333",
                     "#777777", "#aaff66", "#0088ff", "#bbbbbb"],
    "NES (extrait)": ["#000000", "#fcfcfc", "#bcbcbc", "#7c7c7c", "#a40000", "#e40058",
                      "#f83800", "#fca044", "#f8b800", "#00b800", "#58d854", "#0058f8",
                      "#3cbcfc", "#6844fc", "#d800cc", "#f878f8"],
    "Crunch Crab": ["#060508", "#1f1b26", "#524b5a", "#8b8392", "#f4eee8", "#ff7a3d",
                    "#ff5b3a", "#ff4f62", "#ff3d9a", "#ffb547", "#bef264"],
    "Noir & blanc": ["#000000", "#ffffff"],
    "Néon": ["#0b0221", "#3d1a78", "#ff2a6d", "#05d9e8", "#d1f7ff"],
}


def hex_vers_rgba(c):
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255)


def rgba_vers_hex(c):
    return "#{:02x}{:02x}{:02x}".format(*c[:3])


# ---------------------------------------------------------------------------
# Toile
# ---------------------------------------------------------------------------

def nouvelle(largeur, hauteur):
    return np.zeros((hauteur, largeur, 4), np.uint8)


def nettoyer_alpha(img):
    """Force chaque pixel à être opaque ou vide (les images importées ont souvent
    des bords semi-transparents)."""
    img = img.copy()
    vide = img[..., 3] < 128
    img[vide] = 0
    img[~vide, 3] = 255
    return img


ANCRES = ["Centre", "Haut gauche", "Haut", "Haut droite", "Gauche", "Droite",
          "Bas gauche", "Bas", "Bas droite"]


def _decalage_ancre(ancre, ecart):
    """Où placer l'ancienne image dans la nouvelle, sur un axe (ecart = nouveau - ancien)."""
    if ancre == "debut":
        return 0
    if ancre == "fin":
        return ecart
    return ecart // 2


def redimensionner_toile(img, largeur, hauteur, ancre="Centre"):
    """Agrandit ou rogne la toile SANS étirer les pixels (on ajoute du vide ou on coupe)."""
    h, w = img.shape[:2]
    mots = ancre.lower()
    ax = "debut" if "gauche" in mots else ("fin" if "droite" in mots else "milieu")
    ay = "debut" if "haut" in mots else ("fin" if "bas" in mots else "milieu")
    dx = _decalage_ancre(ax, largeur - w)
    dy = _decalage_ancre(ay, hauteur - h)
    sortie = nouvelle(largeur, hauteur)
    # Zone commune entre l'ancienne et la nouvelle image
    x0, y0 = max(0, dx), max(0, dy)
    x1, y1 = min(largeur, dx + w), min(hauteur, dy + h)
    if x1 > x0 and y1 > y0:
        sortie[y0:y1, x0:x1] = img[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    return sortie


def coller(fond, morceau, x, y):
    """Pose `morceau` sur `fond` avec son coin en (x, y). Ses pixels vides laissent voir
    le fond, et ce qui dépasse de la toile est coupé. Renvoie une nouvelle image."""
    sortie = fond.copy()
    h, w = fond.shape[:2]
    mh, mw = morceau.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + mw), min(h, y + mh)
    if x1 <= x0 or y1 <= y0:
        return sortie
    bout = morceau[y0 - y:y1 - y, x0 - x:x1 - x]
    plein = bout[..., 3] > 0
    sortie[y0:y1, x0:x1][plein] = bout[plein]
    return sortie


def zone_dans(selection, largeur, hauteur):
    """La partie d'une sélection (x, y, l, h) qui tombe vraiment sur la toile, ou None."""
    x, y, w, h = selection
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(largeur, x + w), min(hauteur, y + h)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1 - x0, y1 - y0


def decaler(img, dx, dy):
    """Fait glisser tout le dessin ; ce qui sort d'un côté revient de l'autre."""
    return np.roll(img, (dy, dx), axis=(0, 1))


def retourner(img, horizontal=True):
    return img[:, ::-1].copy() if horizontal else img[::-1].copy()


# ---------------------------------------------------------------------------
# Outils de dessin : chacun renvoie des points
# ---------------------------------------------------------------------------

def ligne(x0, y0, x1, y1):
    """Algorithme de Bresenham : la ligne la plus nette possible, sans pixel en trop."""
    points = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return points
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def rectangle(x0, y0, x1, y1, plein=False):
    xa, xb = sorted((x0, x1))
    ya, yb = sorted((y0, y1))
    if plein:
        return [(x, y) for y in range(ya, yb + 1) for x in range(xa, xb + 1)]
    points = [(x, y) for x in range(xa, xb + 1) for y in (ya, yb)]
    points += [(x, y) for y in range(ya + 1, yb) for x in (xa, xb)]
    return points


def ellipse(x0, y0, x1, y1, plein=False):
    """Ellipse inscrite dans le rectangle : on garde les pixels dont le centre est dedans,
    puis, pour le contour, ceux qui touchent l'extérieur."""
    xa, xb = sorted((x0, x1))
    ya, yb = sorted((y0, y1))
    w, h = xb - xa + 1, yb - ya + 1
    y, x = np.mgrid[0:h, 0:w]
    rx, ry = w / 2, h / 2
    dedans = ((x + 0.5 - rx) / rx) ** 2 + ((y + 0.5 - ry) / ry) ** 2 <= 1.0
    if not plein:
        bord = np.pad(dedans, 1)
        voisins_pleins = (bord[:-2, 1:-1] & bord[2:, 1:-1] & bord[1:-1, :-2] & bord[1:-1, 2:])
        dedans = dedans & ~voisins_pleins
    ys, xs = np.nonzero(dedans)
    return list(zip((xs + xa).tolist(), (ys + ya).tolist()))


def symetriser(points, largeur, hauteur, sym_x=False, sym_y=False):
    """Ajoute les reflets des points (miroir vertical et/ou horizontal autour du centre)."""
    sortie = set(points)
    if sym_x:
        sortie |= {(largeur - 1 - x, y) for x, y in sortie}
    if sym_y:
        sortie |= {(x, hauteur - 1 - y) for x, y in sortie}
    return sortie


def tamponner(img, points, couleur, taille=1, sym_x=False, sym_y=False):
    """Pose la couleur sur chaque point, avec un pinceau carré de `taille` pixels.
    Modifie l'image en place et renvoie le nombre de pixels réellement changés."""
    h, w = img.shape[:2]
    avant = img.copy()
    debut = -(taille // 2)
    pinceau = [(i, j) for j in range(debut, debut + taille) for i in range(debut, debut + taille)]
    tous = {(x + i, y + j) for x, y in points for i, j in pinceau}
    for x, y in symetriser(tous, w, h, sym_x, sym_y):
        if 0 <= x < w and 0 <= y < h:
            img[y, x] = couleur
    return int(np.any(avant != img, axis=2).sum())


def remplir(img, x, y, couleur):
    """Pot de peinture : colorie la zone d'une même couleur qui touche (x, y), en 4 directions.
    Les pixels vides comptent comme une couleur (le « vide »)."""
    h, w = img.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return 0
    cible = tuple(int(v) for v in img[y, x])
    if cible[3] == 0:
        cible = VIDE
    couleur = tuple(couleur)
    if cible == couleur:
        return 0
    # On compare des entiers 32 bits plutôt que des quadruplets : beaucoup plus rapide
    vue = np.ascontiguousarray(img).view(np.uint32)[..., 0]
    if cible == VIDE:
        meme = img[..., 3] == 0
    else:
        meme = vue == np.array([cible], np.uint8).view(np.uint32)[0]
    zone = np.zeros((h, w), bool)
    file = deque([(x, y)])
    zone[y, x] = True
    while file:
        cx, cy = file.popleft()
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if 0 <= nx < w and 0 <= ny < h and not zone[ny, nx] and meme[ny, nx]:
                zone[ny, nx] = True
                file.append((nx, ny))
    img[zone] = couleur
    return int(zone.sum())


def remplacer_couleur(img, ancienne, nouvelle_couleur):
    """Change une couleur partout dans l'image (utile pour retoucher une palette)."""
    masque = np.all(img == np.array(ancienne, np.uint8), axis=2)
    img[masque] = nouvelle_couleur
    return int(masque.sum())


# ---------------------------------------------------------------------------
# Couleurs
# ---------------------------------------------------------------------------

def couleurs_utilisees(images, limite=256):
    """Les couleurs opaques présentes dans une ou plusieurs images, de la plus fréquente
    à la plus rare."""
    pixels = np.concatenate([i.reshape(-1, 4) for i in images])
    pixels = pixels[pixels[:, 3] > 0]
    if len(pixels) == 0:
        return []
    uniques, nombres = np.unique(pixels[:, :3], axis=0, return_counts=True)
    ordre = np.argsort(-nombres)[:limite]
    return ["#{:02x}{:02x}{:02x}".format(*uniques[i]) for i in ordre]


def quantifier(img, palette):
    """Ramène chaque pixel opaque à la couleur la plus proche de la palette.
    Distance « rouge-moyen » : simple et bien plus juste à l'œil qu'une distance RVB brute."""
    if not palette:
        return img.copy()
    pal = np.array([hex_vers_rgba(c)[:3] for c in palette], np.float32)
    rvb = img[..., :3].reshape(-1, 1, 3).astype(np.float32)
    rmoy = (rvb[..., 0] + pal[None, :, 0]) / 2
    d = rvb - pal[None]
    dist = (2 + rmoy / 256) * d[..., 0] ** 2 + 4 * d[..., 1] ** 2 + (2 + (255 - rmoy) / 256) * d[..., 2] ** 2
    plus_proche = pal[np.argmin(dist, axis=1)].astype(np.uint8)
    sortie = img.copy()
    sortie[..., :3] = plus_proche.reshape(img.shape[:2] + (3,))
    sortie[sortie[..., 3] == 0] = 0
    return sortie


def reduire(img, largeur, hauteur):
    """Réduit une grande image (photo, dessin) à la taille de la grille.
    Chaque pixel final prend la couleur la plus représentée de sa case : c'est plus net
    qu'une moyenne, qui donnerait des couleurs boueuses."""
    from PIL import Image
    pil = Image.fromarray(img, "RGBA")
    # Réduction en deux temps : d'abord ×4 lissé, puis « mode » de chaque bloc de 4×4
    inter = np.asarray(pil.resize((largeur * 4, hauteur * 4), Image.Resampling.BOX))
    blocs = inter.reshape(hauteur, 4, largeur, 4, 4).transpose(0, 2, 1, 3, 4).reshape(hauteur, largeur, 16, 4)
    # On prend le pixel du bloc le plus proche de la médiane : net, et sans couleur inventée
    mediane = np.median(blocs.astype(np.float32), axis=2, keepdims=True)
    idx = np.argmin(np.abs(blocs.astype(np.float32) - mediane).sum(axis=3), axis=2)
    sortie = np.take_along_axis(blocs, idx[..., None, None], axis=2)[:, :, 0]
    return nettoyer_alpha(sortie)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def agrandir(img, echelle=1, rapport=1):
    """Agrandit sans lissage (chaque pixel devient un carré net). `rapport` = 2 pour des
    pixels deux fois plus larges que hauts (le look Atari de Montauk)."""
    return np.repeat(np.repeat(img, echelle, axis=0), echelle * rapport, axis=1)


def planche(images, colonnes=0):
    """Assemble les images d'une animation en une planche de sprites (une grille)."""
    n = len(images)
    colonnes = colonnes or n
    lignes = -(-n // colonnes)
    h, w = images[0].shape[:2]
    sortie = nouvelle(w * colonnes, h * lignes)
    for i, img in enumerate(images):
        y, x = divmod(i, colonnes)
        sortie[y * h:(y + 1) * h, x * w:(x + 1) * w] = img
    return sortie


def decouper(img, largeur, hauteur):
    """L'inverse de `planche` : découpe une planche de sprites en images de largeur × hauteur."""
    h, w = img.shape[:2]
    images = []
    for y in range(0, h - hauteur + 1, hauteur):
        for x in range(0, w - largeur + 1, largeur):
            case = img[y:y + hauteur, x:x + largeur]
            if case[..., 3].any():  # on ignore les cases vides en fin de planche
                images.append(case.copy())
    return images or [img[:hauteur, :largeur].copy()]
