"""
PixelShell — interface graphique.

Organisation (la même que Crunch Crab) :
  - theme.py      : couleurs, polices, feuille de style, icônes
  - composants.py : les éléments du panneau (curseurs, sections, outils, nuancier, images…)
  - moteur.py     : tout ce qui touche aux pixels (outils, palettes, redimensionnement)
  - fichiers.py   : import / export (PNG, GIF, planche de sprites, projet .pxshell)
  - Toile         : la grande zone de dessin (zoom, déplacement, grille, glisser-déposer)
  - BarreEtat     : le bandeau d'infos sous la toile
  - Fenetre       : assemble le tout et fait le lien entre la souris et le moteur

Pas besoin de calcul en arrière-plan ici : même une planche de 2048 × 2048 reste rapide,
chaque coup de crayon est instantané.
"""

import json
import math
from functools import lru_cache
import os
import random
import sys
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSettings, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QIcon, QImage, QKeySequence,
                           QPainter, QPainterPath, QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QColorDialog, QFileDialog, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

import fichiers
import moteur
import theme as t
from composants import (BandeImages, BoiteOutils, Curseur, Interrupteur, Liste, Nombre, Nuancier,
                        Pastilles, Section, _etiquette_aide)

DOSSIER = t.DOSSIER
NOM = "PixelShell"
VERSION = "1.0.0"
MAC = t.MAC
WINDOWS = t.WINDOWS

CMD = "⌘" if MAC else "Ctrl+"
MAJ_CMD = "⇧⌘" if MAC else "Ctrl+Maj+"

# La mascotte : un bernard-l'hermite (le crabe de Crunch Crab) dans sa coquille.
# X = coquille, S = spirale, C = crabe, O = œil
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

ASTUCES = [
    "clic droit pour peindre avec la couleur secondaire.",
    "maintiens Alt pour prendre une couleur sur le dessin, avec n'importe quel outil.",
    "Espace + glisser (ou deux doigts sur le trackpad) pour te déplacer.",
    "pince le trackpad pour zoomer." if MAC else "Ctrl + molette pour zoomer.",
    "X échange la couleur principale et la secondaire.",
    "[ et ] changent la taille du pinceau.",
    "la symétrie gauche / droite, c'est la moitié du travail pour un personnage de face.",
    "« , » et « . » passent d'une image de l'animation à l'autre.",
    "la pelure d'oignon montre l'image d'avant en transparence : parfait pour une marche.",
    f"{CMD}S garde tout ton projet (images, palette, grille) dans un fichier .pxshell.",
    "les pixels larges (2:1) donnent le look Atari de Montauk.",
    f"outil Sélection (S) : {CMD}C copier, {CMD}X couper, {CMD}V coller, Suppr pour effacer.",
    "avec la Sélection, Alt + glisser déplace une copie de la zone.",
    "Fichier → Importer une planche découpe une bande de sprites à la taille de la grille.",
]

# Tailles toutes prêtes (largeur, hauteur)
FORMATS = {
    "8 × 8": (8, 8), "16 × 16": (16, 16), "24 × 24": (24, 24), "32 × 32": (32, 32),
    "48 × 48": (48, 48), "64 × 64": (64, 64), "128 × 128": (128, 128),
    "16 × 32 (personnage)": (16, 32), "18 × 38 (Téna, une image)": (18, 38),
    "100 × 80 (créature, une image)": (100, 80), "320 × 240 (écran Montauk)": (320, 240),
    "256 × 224 (écran console 16 bits)": (256, 224), "640 × 480": (640, 480),
}
FORMAT_PERSO = "Personnalisée"
PALETTE_DESSIN = "Couleurs du dessin"
PALETTE_PERSO = "Personnalisée"
RAPPORTS = ["Carrés (1:1)", "Larges (2:1, façon Atari)"]
EXPORTS = ["PNG (image affichée)", "Planche de sprites (PNG)", "GIF animé",
           "Toutes les images (PNG séparés)"]
ZOOMS = (("Ajuster", None), ("×4", 4), ("×8", 8), ("×16", 16), ("×32", 32))

DEFAUTS = {"outil": "crayon", "taille_pinceau": 1, "plein": False, "sym_x": False,
           "sym_y": False, "palette_nom": "PICO-8", "grille": True, "tuile": 8, "ancre": "Centre",
           "rapport": RAPPORTS[0], "oignon": False, "ips": 8, "format_export": EXPORTS[0],
           "echelle": 8, "colonnes": 0}


def vers_qimage(img):
    img = np.ascontiguousarray(img)
    h, w, _ = img.shape
    return QImage(img.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()


def depuis_qimage(q):
    """L'inverse : une QImage (par exemple venue du presse-papiers) vers un tableau RGBA."""
    q = q.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = q.width(), q.height()
    brut = np.frombuffer(q.constBits(), np.uint8, count=q.sizeInBytes())
    return moteur.nettoyer_alpha(brut.reshape(h, q.bytesPerLine())[:, :w * 4].reshape(h, w, 4).copy())


@lru_cache(maxsize=None)
def brosse_damier(case=8):
    """Le damier de transparence en carreau répétable : un seul remplissage au lieu de
    milliers de petits carrés (ça compte quand la toile fait 1200 pixels de large)."""
    pix = QPixmap(case * 2, case * 2)
    pix.fill(QColor("#2a2530"))
    p = QPainter(pix)
    clair = QColor("#38323f")
    p.fillRect(0, 0, case, case, clair)
    p.fillRect(case, case, case, case, clair)
    p.end()
    return QBrush(pix)


def dessiner_coquille(p, x, y, taille, couleur=None):
    """Dessine la mascotte. Sans couleur précise, la coquille prend le dégradé signature."""
    largeur = len(COQUILLE[0])
    for j, ligne in enumerate(COQUILLE):
        for i, c in enumerate(ligne):
            if c == ".":
                continue
            if c == "O":
                teinte = QColor(t.TEXTE)
            elif c == "S":
                teinte = QColor(t.ENCRE) if couleur is None else QColor(couleur).darker(300)
            elif c == "C":
                teinte = QColor(t.ACCENT_CLAIR)
            else:
                teinte = couleur if couleur is not None else t.couleur_degrade(i / (largeur - 1))
            p.fillRect(QRectF(x + i * taille, y + j * taille, taille - 0.5, taille - 0.5), teinte)


def pixmap_coquille(taille, couleur=None):
    echelle = 2
    pix = QPixmap(len(COQUILLE[0]) * taille * echelle, len(COQUILLE) * taille * echelle)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    dessiner_coquille(p, 0, 0, taille * echelle, couleur)
    p.end()
    pix.setDevicePixelRatio(echelle)
    return pix


# ---------------------------------------------------------------------------
# La toile
# ---------------------------------------------------------------------------

class Toile(QWidget):
    """Affiche le dessin et traduit la souris en coordonnées de pixels. Elle ne dessine
    rien elle-même : elle prévient la fenêtre, qui demande au moteur."""
    fichierDepose = Signal(str)
    pression = Signal(int, int, int, object)   # x, y, bouton (0 gauche, 1 droit), modificateurs
    glisse = Signal(int, int, object)
    relache = Signal()
    survol = Signal(int, int)                  # (-1, -1) quand la souris sort du dessin
    RAYON = 18

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(420, 320)
        self.image = None          # QImage du dessin
        self.oignon = None         # QImage de l'image précédente (pelure d'oignon)
        self.rapport = 1           # 2 = pixels deux fois plus larges que hauts
        self.grille = True
        self.tuile = 0
        self.pinceau = 1
        self.sym = (False, False)
        self.outil = "crayon"
        self.selection = None      # (x, y, largeur, hauteur) en pixels du dessin
        self.flottant = False      # la sélection contient des pixels « soulevés » qu'on déplace
        self._fourmis = 0          # décalage des pointillés animés
        self._minuteur_fourmis = QTimer(self, interval=110)
        self._minuteur_fourmis.timeout.connect(self._tic_fourmis)
        self.zoom = None           # None = ajuster à la fenêtre, sinon pixels d'écran par pixel
        self.decalage = QPointF(0, 0)
        self.zoomChange = None
        self.pixel = None          # pixel sous la souris
        self._bouton = None
        self._main = None          # position de départ d'un déplacement à la main
        self._espace = False
        self._survol_depot = False
        self._message = ""
        self._fin_message = 0
        self._zone_message = QRectF()
        self._minuteur_message = QTimer(self, interval=40)
        self._minuteur_message.timeout.connect(self._tic_message)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # --- Affichage
    def definir(self, image, oignon=None):
        self.image = image
        self.oignon = oignon
        self.update()

    def definir_selection(self, selection, flottant=False):
        self.selection, self.flottant = selection, flottant
        if selection and not self._minuteur_fourmis.isActive():
            self._minuteur_fourmis.start()
        elif not selection:
            self._minuteur_fourmis.stop()
        self.update()

    def _tic_fourmis(self):
        self._fourmis = (self._fourmis + 1) % 8
        self.update()

    def dans_selection(self, x, y):
        if not self.selection:
            return False
        sx, sy, sw, sh = self.selection
        return sx <= x < sx + sw and sy <= y < sy + sh

    def dire(self, message, duree=2.6):
        """Petite bulle de message en bas de la toile."""
        self._message = message
        self._fin_message = time.time() + duree
        self._minuteur_message.start()
        self.update()

    def _tic_message(self):
        if time.time() > self._fin_message + 0.4:
            self._message = ""
            self._minuteur_message.stop()
            self.update()
            return
        self.update(self._zone_message.toAlignedRect().adjusted(-2, -2, 2, 2))

    def echelle(self):
        """Taille d'un pixel du dessin à l'écran. Toujours un nombre entier dès qu'on
        agrandit : sinon certains pixels feraient 7 points de large et d'autres 8."""
        if self.image is None:
            return 1
        if self.zoom is None:
            m = 44
            z = min((self.width() - m * 2) / (self.image.width() * self.rapport),
                    (self.height() - m * 2) / self.image.height())
            return math.floor(z) if z >= 1 else max(0.05, z)
        return max(1, round(self.zoom)) if self.zoom >= 1 else self.zoom

    def definir_zoom(self, z):
        self.zoom = z
        self.decalage = QPointF(0, 0)
        self.update()
        if self.zoomChange:
            self.zoomChange()

    def _cible(self):
        e = self.echelle()
        w, h = self.image.width() * e * self.rapport, self.image.height() * e
        return QRectF(round((self.width() - w) / 2 + self.decalage.x()),
                      round((self.height() - h) / 2 + self.decalage.y()), w, h)

    def pixel_en(self, pos):
        c, e = self._cible(), self.echelle()
        return (math.floor((pos.x() - c.left()) / (e * self.rapport)),
                math.floor((pos.y() - c.top()) / e))

    def paintEvent(self, _):
        p = QPainter(self)
        carte = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        contour = QPainterPath()
        contour.addRoundedRect(carte, self.RAYON, self.RAYON)
        p.fillRect(self.rect(), QColor(t.FOND))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillPath(contour, t.texture_trame())
        p.save()
        p.setClipPath(contour)
        if self.image is not None:
            cible = self._cible()
            visible = cible.intersected(QRectF(self.rect()))
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.setBrushOrigin(cible.topLeft())
            p.fillRect(visible, brosse_damier(8))
            if self.oignon is not None:
                p.setOpacity(0.3)
                p.drawImage(cible, self.oignon)
                p.setOpacity(1)
            p.drawImage(cible, self.image)   # sans lissage : chaque pixel reste un carré net
            self._grille(p, cible, visible)
            self._symetries(p, cible)
            self._selection(p, cible)
            self._curseur(p, cible)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._reperes(p, cible)
        if self._survol_depot:
            self._cadre_depot(p)
        if self._message:
            self._bulle(p)
        p.restore()
        p.setPen(QPen(QColor(t.BORD), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(contour)

    def _lignes(self, p, cible, visible, pas_x, pas_y, couleur):
        """Lignes verticales et horizontales tous les `pas` pixels, seulement dans la zone visible."""
        p.setPen(QPen(couleur, 1))
        n_x = self.image.width() // pas_x
        for i in range(1, n_x + (self.image.width() % pas_x > 0)):
            x = round(cible.left() + i * pas_x * cible.width() / self.image.width())
            if visible.left() <= x <= visible.right():
                p.drawLine(QPointF(x, visible.top()), QPointF(x, visible.bottom()))
        n_y = self.image.height() // pas_y
        for j in range(1, n_y + (self.image.height() % pas_y > 0)):
            y = round(cible.top() + j * pas_y * cible.height() / self.image.height())
            if visible.top() <= y <= visible.bottom():
                p.drawLine(QPointF(visible.left(), y), QPointF(visible.right(), y))

    def _grille(self, p, cible, visible):
        if not self.grille:
            return
        if self.echelle() >= 5:
            self._lignes(p, cible, visible, 1, 1, QColor(255, 255, 255, 22))
        if self.tuile > 1 and self.echelle() * self.tuile >= 12:
            self._lignes(p, cible, visible, self.tuile, self.tuile, QColor(255, 91, 58, 110))

    def _symetries(self, p, cible):
        """Axes de symétrie en pointillés, pour savoir où tombe le miroir."""
        stylo = QPen(QColor(t.ROSE), 1, Qt.PenStyle.DashLine)
        p.setPen(stylo)
        if self.sym[0]:
            x = cible.center().x()
            p.drawLine(QPointF(x, cible.top() - 10), QPointF(x, cible.bottom() + 10))
        if self.sym[1]:
            y = cible.center().y()
            p.drawLine(QPointF(cible.left() - 10, y), QPointF(cible.right() + 10, y))

    def _selection(self, p, cible):
        """Le contour de la sélection, en pointillés qui défilent (les « fourmis »)."""
        if not self.selection:
            return
        e = self.echelle()
        x, y, w, h = self.selection
        r = QRectF(cible.left() + x * e * self.rapport, cible.top() + y * e,
                   w * e * self.rapport, h * e).adjusted(0, 0, -1, -1)
        if self.flottant:
            p.fillRect(r, QColor(255, 91, 58, 26))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0), 1))
        p.drawRect(r)
        stylo = QPen(QColor(t.TEXTE), 1, Qt.PenStyle.CustomDashLine)
        stylo.setDashPattern([4, 4])
        stylo.setDashOffset(self._fourmis)
        p.setPen(stylo)
        p.drawRect(r)
        p.setFont(t.police_mono(10))
        texte = f"{w}×{h}"
        largeur = p.fontMetrics().horizontalAdvance(texte) + 10
        etiquette = QRectF(r.left(), r.top() - 20, largeur, 16)
        if etiquette.top() < 4:
            etiquette.moveTop(r.bottom() + 4)
        p.fillRect(etiquette, QColor(6, 5, 8, 220))
        p.setPen(QColor(t.TEXTE))
        p.drawText(etiquette, Qt.AlignmentFlag.AlignCenter, texte)

    def _curseur(self, p, cible):
        """Le carré du pinceau sous la souris (et ses reflets si la symétrie est active)."""
        if self.pixel is None or self._main is not None or self._espace or self.outil == "selection":
            return
        e = self.echelle()
        ex, w, h = e * self.rapport, self.image.width(), self.image.height()
        debut = -(self.pinceau // 2)
        x, y = self.pixel[0] + debut, self.pixel[1] + debut
        positions = {(x, y)}
        if self.sym[0]:
            positions |= {(w - x - self.pinceau, py) for _, py in positions}
        if self.sym[1]:
            positions |= {(px, h - y - self.pinceau) for px, _ in positions}
        for px, py in positions:
            r = QRectF(cible.left() + px * ex, cible.top() + py * e, self.pinceau * ex, self.pinceau * e)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 160), 3))
            p.drawRect(r)
            p.setPen(QPen(QColor(t.TEXTE), 1))
            p.drawRect(r)

    def _reperes(self, p, cible):
        """Traits de coupe aux quatre coins, comme sur une épreuve d'imprimerie."""
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(QPen(QColor(t.TRES_DISCRET), 1))
        ecart, long_ = 6, 12
        for x, sx in ((cible.left(), -1), (cible.right(), 1)):
            for y, sy in ((cible.top(), -1), (cible.bottom(), 1)):
                p.drawLine(QPointF(x + sx * ecart, y), QPointF(x + sx * (ecart + long_), y))
                p.drawLine(QPointF(x, y + sy * ecart), QPointF(x, y + sy * (ecart + long_)))
        p.restore()

    def _bulle(self, p):
        reste = self._fin_message - time.time()
        alpha = max(0.0, min(1.0, (reste + 0.4) / 0.4))
        f = QFont()
        f.setPixelSize(13)
        p.setFont(f)
        largeur = p.fontMetrics().horizontalAdvance(self._message) + 74
        r = QRectF((self.width() - largeur) / 2, self.height() - 64, largeur, 38)
        self._zone_message = r
        p.setOpacity(alpha)
        p.setPen(QPen(QColor(t.BORD_FORT), 1))
        p.setBrush(QColor(14, 12, 18, 240))
        p.drawRoundedRect(r, 19, 19)
        mascotte = pixmap_coquille(1)
        p.drawPixmap(QPointF(r.left() + 16, r.center().y() - mascotte.height() / mascotte.devicePixelRatio() / 2),
                     mascotte)
        p.setPen(QColor(t.TEXTE))
        p.drawText(r.adjusted(44, 0, -16, 0), Qt.AlignmentFlag.AlignVCenter, self._message)
        p.setOpacity(1)

    def _cadre_depot(self, p):
        r = QRectF(self.rect()).adjusted(18, 18, -18, -18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 79, 98, 22))
        p.drawRoundedRect(r, 14, 14)
        p.setPen(QPen(t.degrade(r), 2, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 14, 14)
        p.setFont(t.police_pixel(24))
        p.setPen(QColor(t.TEXTE))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "DÉPOSE ICI")

    # --- Souris : dessiner, se déplacer, zoomer
    def mousePressEvent(self, e):
        if self.image is None:
            return
        self.setFocus()
        if e.button() == Qt.MouseButton.MiddleButton or self._espace:
            self._main = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        bouton = {Qt.MouseButton.LeftButton: 0, Qt.MouseButton.RightButton: 1}.get(e.button())
        if bouton is None:
            return
        self._bouton = bouton
        x, y = self.pixel_en(e.position())
        self.pression.emit(x, y, bouton, e.modifiers())

    def mouseMoveEvent(self, e):
        if self.image is None:
            return
        if self._main is not None:
            if self.zoom is None:
                self.zoom = self.echelle()  # on fige le zoom pour pouvoir se déplacer
                if self.zoomChange:
                    self.zoomChange()
            self.decalage += e.position() - self._main
            self._main = e.position()
            self.update()
            return
        x, y = self.pixel_en(e.position())
        dedans = 0 <= x < self.image.width() and 0 <= y < self.image.height()
        nouveau = (x, y) if dedans or self._bouton is not None else None
        if self._bouton is None and not self._espace:
            # Au-dessus d'une sélection, l'outil Sélection la déplace : on le montre
            bouger = self.outil == "selection" and self.dans_selection(x, y)
            self.setCursor(Qt.CursorShape.SizeAllCursor if bouger else Qt.CursorShape.CrossCursor)
        if nouveau != self.pixel:
            self.pixel = nouveau
            self.update()
            self.survol.emit(*(nouveau if dedans else (-1, -1)))
            if self._bouton is not None:
                self.glisse.emit(x, y, e.modifiers())

    def mouseReleaseEvent(self, _):
        if self._main is not None:
            self._main = None
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._espace else Qt.CursorShape.CrossCursor)
            return
        if self._bouton is not None:
            self._bouton = None
            self.relache.emit()

    def leaveEvent(self, _):
        if self._bouton is None:
            self.pixel = None
            self.survol.emit(-1, -1)
            self.update()

    def enterEvent(self, _):
        self.setFocus()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self._espace = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.update()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self._espace = False
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.update()
        else:
            super().keyReleaseEvent(e)

    def wheelEvent(self, e):
        if self.image is None:
            return
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:  # Qt traduit Ctrl en ⌘ sur Mac
            self.zoomer(1.0015 ** e.angleDelta().y(), e.position())
        else:
            if self.zoom is None:
                self.zoom = self.echelle()
            self.decalage += QPointF(e.pixelDelta()) if not e.pixelDelta().isNull() \
                else QPointF(e.angleDelta()) / 4
            self.update()

    def event(self, e):
        if e.type() == e.Type.NativeGesture and \
                e.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.zoomer(1 + e.value(), e.position())
            return True
        return super().event(e)

    def zoomer(self, facteur, autour=None):
        """Zoome en gardant le même pixel sous la souris (ou au centre)."""
        if self.image is None:
            return
        autour = autour if autour is not None else QPointF(self.width() / 2, self.height() / 2)
        avant = self._cible()
        e_avant = self.echelle()
        u = (autour - avant.topLeft()) / e_avant
        self.zoom = min(96.0, max(0.1, (self.zoom or e_avant) * facteur))
        e = self.echelle()
        w, h = self.image.width() * e * self.rapport, self.image.height() * e
        coin = autour - u * e
        self.decalage = coin - QPointF((self.width() - w) / 2, (self.height() - h) / 2)
        self.update()
        if self.zoomChange:
            self.zoomChange()

    # --- Glisser-déposer
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._survol_depot = True
            self.update()

    def dragLeaveEvent(self, _):
        self._survol_depot = False
        self.update()

    def dropEvent(self, e):
        self._survol_depot = False
        self.update()
        urls = e.mimeData().urls()
        if urls:
            self.fichierDepose.emit(urls[0].toLocalFile())


class BarreEtat(QWidget):
    """Bandeau d'infos sous la toile : voyant (vert = enregistré, ambre = modifié),
    taille, position de la souris, palette."""

    def __init__(self):
        super().__init__()
        self.texte = ""
        self.couleurs = []
        self.modifie = False
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def definir(self, texte=None, couleurs=None, modifie=None):
        if texte is not None:
            self.texte = texte
        if couleurs is not None:
            self.couleurs = list(couleurs)[:32]
        if modifie is not None:
            self.modifie = modifie
        self.update()

    def paintEvent(self, _):
        if not self.texte:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2
        x = self.width()
        cote, ecart = 8, 2
        for c in reversed(self.couleurs):
            x -= cote
            p.fillRect(QRectF(x, cy - cote / 2, cote, cote), QColor(c))
            x -= ecart
        x -= 12
        p.setFont(t.police_mono(11))
        largeur = p.fontMetrics().horizontalAdvance(self.texte)
        x -= largeur
        p.setPen(QColor(t.DISCRET))
        p.drawText(QRectF(x, 0, largeur + 2, self.height()), Qt.AlignmentFlag.AlignVCenter, self.texte)
        t.point_lumineux(p, QPointF(x - 12, cy), 3, t.AMBRE if self.modifie else t.VERT)


# ---------------------------------------------------------------------------
# La fenêtre
# ---------------------------------------------------------------------------

class Fenetre(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1440, 900)
        self.setMinimumSize(1080, 680)
        # Pendant l'auto-test, on garde des réglages à part pour ne pas toucher aux vrais
        self.prefs = QSettings("PixelShellTest" if os.environ.get("PIXELSHELL_TEST") else NOM, NOM)

        # Le document
        self.images = [moteur.nouvelle(32, 32)]
        self.actuelle = 0
        self.palette = list(moteur.PALETTES["PICO-8"])
        self.principale, self.secondaire = "#000000", "#fff1e8"
        self.chemin_projet = None
        self.chemin_image = None   # l'image ouverte (PNG…) : l'export la propose par défaut
        self.modifie = False

        # Le geste en cours
        self._base = None          # l'image avant le geste (pour les formes et le déplacement)
        self._depart = None
        self._dernier = None
        self._couleur_geste = None
        self._avant_redim = None   # les images avant un changement de taille (voir _taille_changee)
        self._bloquer = False
        self.historique = []
        self.pos_historique = -1
        self._image_lue = None     # pendant la lecture de l'animation

        # La sélection : un rectangle (x, y, l, h). Quand on la déplace, ses pixels sont
        # « soulevés » (self.flottant) au-dessus du reste de l'image (self._sous).
        # self.image contient toujours le résultat des deux, donc l'export et la sauvegarde
        # voient exactement ce qui est affiché.
        self.selection = None
        self.flottant = None
        self._sous = None
        self._bouge = None         # (x, y) de la sélection au début d'un déplacement
        self.presse_papiers = None
        self._couleurs_cache = []

        self.minuteur_histo = QTimer(singleShot=True, interval=450)
        self.minuteur_histo.timeout.connect(self._memoriser)
        self.minuteur_lecture = QTimer(self)
        self.minuteur_lecture.timeout.connect(self._tic_lecture)

        self._construire()
        self._menus()
        try:
            r = json.loads(self.prefs.value("reglages", "{}"))
        except Exception:
            r = {}
        self._appliquer_reglages(r)
        self._reprendre_session()
        self._memoriser(modifie=False)
        self.toile.dire("Astuce : " + random.choice(ASTUCES), 6)

    # ----- Construction de l'interface
    def _bouton(self, texte, nom_icone=None, objet=None, bulle=None, couleur=t.TEXTE):
        b = QPushButton(texte)
        if nom_icone:
            b.setIcon(t.icone(nom_icone, couleur, 16))
        if objet:
            b.setObjectName(objet)
        if bulle:
            b.setToolTip(bulle)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # pour que Espace et les lettres restent à la toile
        return b

    def _construire(self):
        racine = QWidget()
        racine.setObjectName("racine")
        self.setCentralWidget(racine)
        h = QHBoxLayout(racine)
        h.setContentsMargins(12, 10, 12, 12)
        h.setSpacing(12)
        gauche = QVBoxLayout()
        gauche.setSpacing(10)

        # Barre du haut : marque, fichier, historique… et les deux gros boutons
        barre = QHBoxLayout()
        barre.setContentsMargins(6, 0, 0, 0)
        barre.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(pixmap_coquille(2))
        barre.addWidget(logo)
        barre.addSpacing(4)
        marque = QLabel(NOM.upper())
        marque.setObjectName("marque")
        barre.addWidget(marque)
        version = QLabel(f"V{VERSION}")
        version.setObjectName("version")
        barre.addWidget(version)
        barre.addSpacing(18)
        b_nouveau = self._bouton("Nouveau", "nouveau", bulle=f"Une toile vierge ({CMD}N)")
        b_nouveau.clicked.connect(self.nouveau)
        barre.addWidget(b_nouveau)
        b_ouvrir = self._bouton("Ouvrir", "ouvrir",
                                bulle=f"Ouvrir un projet ou importer une image ({CMD}O)")
        b_ouvrir.clicked.connect(self.ouvrir)
        barre.addWidget(b_ouvrir)
        self.b_annuler = self._bouton("", "annuler", "icone", f"Annuler ({CMD}Z)")
        self.b_annuler.clicked.connect(self.annuler)
        self.b_retablir = self._bouton("", "retablir", "icone", f"Rétablir ({MAJ_CMD}Z)")
        self.b_retablir.clicked.connect(self.retablir)
        barre.addWidget(self.b_annuler)
        barre.addWidget(self.b_retablir)
        barre.addStretch()
        b_enr = self._bouton("Enregistrer", "enregistrer",
                             bulle=f"Garder tout le projet dans un fichier .pxshell ({CMD}S)")
        b_enr.clicked.connect(self.enregistrer)
        barre.addWidget(b_enr)
        self.b_exporter = self._bouton("Exporter", "exporter", "principal", f"Exporter ({CMD}E)",
                                       couleur=t.ENCRE)
        self.b_exporter.clicked.connect(self.exporter)
        barre.addWidget(self.b_exporter)
        gauche.addLayout(barre)

        self.toile = Toile()
        self.toile.fichierDepose.connect(self.charger)
        self.toile.pression.connect(self._pression)
        self.toile.glisse.connect(self._glisse)
        self.toile.relache.connect(self._relache)
        self.toile.survol.connect(lambda x, y: self._maj_etat())
        self.toile.zoomChange = self._maj_boutons_zoom
        gauche.addWidget(self.toile, 1)

        # Barre du bas : lecture de l'animation, état, zoom, grille
        transport = QWidget()
        transport.setObjectName("carte")
        transport.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        tl = QHBoxLayout(transport)
        tl.setContentsMargins(10, 8, 10, 8)
        tl.setSpacing(10)
        self.b_lecture = self._bouton("", "lecture", "lecture", "Lire l'animation (Entrée)", t.ENCRE)
        self.b_lecture.clicked.connect(self.basculer_lecture)
        tl.addWidget(self.b_lecture)
        self.etat = BarreEtat()
        tl.addWidget(self.etat, 1)
        tl.addSpacing(6)
        groupe = QWidget()
        groupe.setObjectName("groupe")
        groupe.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        gl = QHBoxLayout(groupe)
        gl.setContentsMargins(3, 3, 3, 3)
        gl.setSpacing(2)
        self.boutons_zoom = {}
        for nom, z in ZOOMS:
            b = self._bouton(nom, objet="segment")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, z=z: self.toile.definir_zoom(z))
            self.boutons_zoom[z] = b
            gl.addWidget(b)
        tl.addWidget(groupe)
        self.b_grille = self._bouton("Grille", "grille", "bascule", "Afficher la grille (G)")
        self.b_grille.setCheckable(True)
        self.b_grille.toggled.connect(lambda v: self.c["grille"].definir(v))
        tl.addWidget(self.b_grille)
        gauche.addWidget(transport)
        self._maj_boutons_zoom()

        h.addLayout(gauche, 1)
        h.addWidget(self._panneau())

    def _panneau(self):
        carte = QWidget()
        carte.setObjectName("carte")
        carte.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        carte.setFixedWidth(356)
        cl = QVBoxLayout(carte)
        cl.setContentsMargins(0, 6, 0, 6)
        defile = QScrollArea()
        defile.setObjectName("defile")
        defile.setWidgetResizable(True)
        defile.setFrameShape(QScrollArea.Shape.NoFrame)
        defile.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cl.addWidget(defile)
        interieur = QWidget()
        interieur.setObjectName("panneauInterieur")
        lay = QVBoxLayout(interieur)
        lay.setContentsMargins(0, 0, 0, 16)
        lay.setSpacing(0)
        self.c = {}
        self.sections = []
        Section._compteur = 0

        def section(titre, sous_titre, ouvert=True, reinit=True):
            s = Section(titre, sous_titre, ouvert, self._reinit_section if reinit else None)
            if reinit:
                self.sections.append(s)
            lay.addWidget(s)
            return s

        def ajout(s, cle, widget):
            self.c[cle] = widget
            s.ajouter(widget, cle)
            widget.change.connect(lambda *_: self._reglage_change(cle))
            return widget

        def rangee(s, *boutons):
            w = QWidget()
            r = QHBoxLayout(w)
            r.setContentsMargins(18, 4, 18, 6)
            r.setSpacing(6)
            for b in boutons:
                r.addWidget(b)
            r.addStretch()
            s.ajouter(w)

        # 01 Outils
        s = section("Outils", "Ce qui pose les pixels.")
        ajout(s, "outil", BoiteOutils())
        self.boutons_selection = []
        for ic, bulle, fn in (("dupliquer", f"Copier la sélection ({CMD}C)", self.copier),
                              ("couper", f"Couper la sélection ({CMD}X)", self.couper),
                              ("coller", f"Coller ({CMD}V)", self.coller),
                              ("poubelle", "Effacer la sélection (Suppr)", self.supprimer_selection),
                              ("rogner", "Rogner la toile à la sélection (toutes les images)",
                               self.rogner)):
            b = self._bouton("", ic, "icone", bulle)
            b.clicked.connect(fn)
            self.boutons_selection.append(b)
        rangee(s, *self.boutons_selection)
        ajout(s, "taille_pinceau", Curseur("Taille du pinceau", 1, 8, 1, " px",
                                           "[ et ] pour la changer sans quitter le dessin."))
        ajout(s, "plein", Interrupteur("Formes pleines", False, "Rectangles et ellipses remplis."))
        ajout(s, "sym_x", Interrupteur("Symétrie gauche / droite", False,
                                       "Ce que tu dessines d'un côté apparaît en miroir de l'autre."))
        ajout(s, "sym_y", Interrupteur("Symétrie haut / bas", False))

        # 02 Couleurs
        s = section("Couleurs", "Choisis ta palette, c'est elle qui fait l'ambiance.")
        w = QWidget()
        r = QHBoxLayout(w)
        r.setContentsMargins(18, 4, 18, 4)
        r.setSpacing(12)
        self.pastilles = Pastilles()
        self.pastilles.echange.connect(self.echanger_couleurs)
        self.pastilles.demande.connect(self._demander_couleur)
        r.addWidget(self.pastilles)
        self.info_couleurs = QLabel()
        self.info_couleurs.setObjectName("info")
        r.addWidget(self.info_couleurs, 1)
        s.ajouter(w)
        choix = list(moteur.PALETTES) + [PALETTE_DESSIN, PALETTE_PERSO]
        ajout(s, "palette_nom", Liste("", choix, fleches=True))
        self.nuancier = Nuancier()
        self.nuancier.choisi.connect(self.choisir_couleur)
        self.nuancier.modifie.connect(self._palette_modifiee)
        self.nuancier.remplace.connect(self._remplacer_couleur)
        s.ajouter(self.nuancier)
        b_ramener = self._bouton("Ramener le dessin à la palette", objet="fantome",
                                 bulle="Chaque pixel prend la couleur la plus proche de la palette")
        b_ramener.clicked.connect(self.ramener_a_palette)
        rangee(s, b_ramener)

        # 03 Grille
        s = section("Grille", "La taille de ton dessin, en pixels.")
        ajout(s, "format", Liste("Format", list(FORMATS) + [FORMAT_PERSO]))
        ajout(s, "largeur", Nombre("Largeur", 1, moteur.TAILLE_MAX, 32, " px"))
        ajout(s, "hauteur", Nombre("Hauteur", 1, moteur.TAILLE_MAX, 32, " px",
                                   "Tape la taille puis Entrée. ↑ ↓ pour ajuster d'un pixel."))
        ajout(s, "ancre", Liste("Ancrage", moteur.ANCRES,
                                "Le côté qui reste en place quand tu agrandis ou rognes la toile."))
        ajout(s, "grille", Interrupteur("Afficher la grille", True))
        ajout(s, "tuile", Curseur("Repères tous les", 0, 64, 8, " px",
                                  "Une ligne plus marquée toutes les N cases : pratique pour des tuiles "
                                  "de 8 ou 16. 0 = pas de repère."))
        ajout(s, "rapport", Liste("Forme des pixels", RAPPORTS,
                                  "Les pixels larges s'appliquent aussi à l'export."))
        b_h = self._bouton("Miroir ↔", objet="fantome", bulle="Retourner l'image de gauche à droite")
        b_h.clicked.connect(lambda: self.retourner(True))
        b_v = self._bouton("Miroir ↕", objet="fantome", bulle="Retourner l'image de haut en bas")
        b_v.clicked.connect(lambda: self.retourner(False))
        b_vider = self._bouton("Vider", "poubelle", "fantome", "Effacer toute l'image affichée")
        b_vider.clicked.connect(self.vider)
        rangee(s, b_h, b_v, b_vider)

        # 04 Animation
        s = section("Animation", "Plusieurs images à la suite, pour faire marcher un personnage.")
        self.bande = BandeImages()
        self.bande.choisi.connect(self.choisir_image)
        s.ajouter(self.bande)
        b_plus = self._bouton("", "plus", "icone", "Ajouter une image vide")
        b_plus.clicked.connect(self.nouvelle_image)
        b_dup = self._bouton("", "dupliquer", "icone", "Dupliquer l'image (la base idéale pour la suivante)")
        b_dup.clicked.connect(self.dupliquer_image)
        b_suppr = self._bouton("", "poubelle", "icone", "Supprimer l'image")
        b_suppr.clicked.connect(self.supprimer_image)
        b_g = self._bouton("", "gauche", "icone", "Avancer l'image d'un cran")
        b_g.clicked.connect(lambda: self.bouger_image(-1))
        b_d = self._bouton("", "droite", "icone", "Reculer l'image d'un cran")
        b_d.clicked.connect(lambda: self.bouger_image(1))
        rangee(s, b_plus, b_dup, b_suppr, b_g, b_d)
        ajout(s, "oignon", Interrupteur("Pelure d'oignon", False,
                                        "Montre l'image précédente en transparence pour caler le mouvement."))
        ajout(s, "ips", Curseur("Vitesse", 1, 30, 8, " img/s"))

        # 05 Export
        s = section("Export", "Comment ton dessin sort de PixelShell.", reinit=False)
        ajout(s, "format_export", Liste("Format", EXPORTS))
        ajout(s, "echelle", Curseur("Agrandissement", 1, 32, 8, "×",
                                    "Chaque pixel devient un carré net de N × N pixels."))
        ajout(s, "colonnes", Curseur("Colonnes de la planche", 0, 16, 0, "",
                                     "0 = toutes les images sur une seule ligne."))
        self.info_export = _etiquette_aide("")
        self.info_export.setContentsMargins(18, 4, 18, 4)
        s.ajouter(self.info_export)

        lay.addStretch()
        defile.setWidget(interieur)
        return carte

    def _menus(self):
        def menu(titre, actions):
            m = self.menuBar().addMenu(titre)
            for nom, raccourci, fn in actions:
                if nom is None:
                    m.addSeparator()
                    continue
                a = QAction(nom, self)
                if raccourci:
                    a.setShortcut(QKeySequence(raccourci))
                a.triggered.connect(fn)
                m.addAction(a)

        menu("Fichier", [("Nouveau", QKeySequence.StandardKey.New, self.nouveau),
                         ("Ouvrir / importer…", QKeySequence.StandardKey.Open, self.ouvrir),
                         ("Importer une planche de sprites…", "Ctrl+Shift+O", self.importer_planche),
                         (None, None, None),
                         ("Enregistrer", QKeySequence.StandardKey.Save, self.enregistrer),
                         ("Enregistrer sous…", "Ctrl+Shift+S", self.enregistrer_sous),
                         ("Exporter…", "Ctrl+E", self.exporter)])
        menu("Édition", [("Annuler", QKeySequence.StandardKey.Undo, self.annuler),
                         ("Rétablir", QKeySequence.StandardKey.Redo, self.retablir),
                         (None, None, None),
                         ("Copier", QKeySequence.StandardKey.Copy, self.copier),
                         ("Couper", QKeySequence.StandardKey.Cut, self.couper),
                         ("Coller", QKeySequence.StandardKey.Paste, self.coller),
                         ("Effacer la sélection", "Backspace", self.supprimer_selection),
                         ("Tout sélectionner", QKeySequence.StandardKey.SelectAll, self.tout_selectionner),
                         ("Désélectionner", "Escape", self.deselectionner),
                         ("Rogner à la sélection", None, self.rogner),
                         (None, None, None),
                         ("Échanger les couleurs", "X", self.echanger_couleurs),
                         ("Pinceau plus petit", "[", lambda: self._pinceau(-1)),
                         ("Pinceau plus grand", "]", lambda: self._pinceau(1)),
                         (None, None, None),
                         ("Vider l'image", None, self.vider)])
        menu("Affichage", [("Ajuster à la fenêtre", "Ctrl+0", lambda: self.toile.definir_zoom(None)),
                           ("Zoomer", QKeySequence.StandardKey.ZoomIn, lambda: self.toile.zoomer(1.5)),
                           ("Dézoomer", QKeySequence.StandardKey.ZoomOut, lambda: self.toile.zoomer(1 / 1.5)),
                           ("Grille", "G", lambda: self.c["grille"].definir(not self.c["grille"].valeur()))])
        menu("Animation", [("Image précédente", ",", lambda: self.image_voisine(-1)),
                           ("Image suivante", ".", lambda: self.image_voisine(1)),
                           ("Dupliquer l'image", "Ctrl+D", self.dupliquer_image),
                           ("Lire / arrêter", "Return", self.basculer_lecture)])
        outils = self.menuBar().addMenu("Outils")
        from composants import OUTILS
        for cle, nom, _ic, lettre, _aide in OUTILS:
            a = QAction(nom, self)
            a.setShortcut(QKeySequence(lettre))
            a.triggered.connect(lambda _=False, cle=cle: self.c["outil"].definir(cle))
            outils.addAction(a)
        # Suppr fait comme Retour arrière ; le Zoom avant classique ⌘= marche aussi sans Maj
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, self.supprimer_selection)
        QShortcut(QKeySequence("Ctrl+="), self, lambda: self.toile.zoomer(1.5))

    # ----- Accès au document
    @property
    def image(self):
        return self.images[self.actuelle]

    @image.setter
    def image(self, img):
        self.images[self.actuelle] = img

    def rapport(self):
        return 2 if self.c["rapport"].valeur() == RAPPORTS[1] else 1

    def reglages(self):
        r = {k: w.valeur() for k, w in self.c.items() if k not in ("largeur", "hauteur", "format")}
        r["palette"] = list(self.palette)
        r["couleurs"] = [self.principale, self.secondaire]
        return r

    def _appliquer_reglages(self, r):
        self._bloquer = True
        for k, v in {**DEFAUTS, **r}.items():
            if k in self.c and k not in ("largeur", "hauteur", "format"):
                try:
                    self.c[k].definir(v)
                except Exception:
                    pass
        if r.get("palette"):
            self.palette = list(r["palette"])
        elif self.c["palette_nom"].valeur() in moteur.PALETTES:
            self.palette = list(moteur.PALETTES[self.c["palette_nom"].valeur()])
        if r.get("couleurs"):
            self.principale, self.secondaire = r["couleurs"]
        self._bloquer = False
        self.rafraichir(tout=True)

    def _reglage_change(self, cle):
        if self._bloquer:
            return
        if cle == "outil":
            self._ancrer()
        elif cle == "palette_nom":
            self._palette_choisie()
        elif cle in ("largeur", "hauteur", "ancre"):
            self._taille_changee()
        elif cle == "format":
            self._format_choisi()
        elif cle == "grille":
            self.b_grille.blockSignals(True)
            self.b_grille.setChecked(self.c["grille"].valeur())
            self.b_grille.blockSignals(False)
        elif cle == "ips" and self.minuteur_lecture.isActive():
            self.minuteur_lecture.setInterval(round(1000 / self.c["ips"].valeur()))
        self.rafraichir(tout=cle in ("rapport", "oignon", "echelle", "format_export", "colonnes"))
        self._marquer_sections()

    def _marquer_sections(self):
        for s in self.sections:
            s.marquer(any(self.c[k].valeur() != DEFAUTS.get(k, self.c[k].valeur())
                          for k in s.cles if k in DEFAUTS))

    def _reinit_section(self, section):
        r = {k: DEFAUTS[k] for k in section.cles if k in DEFAUTS}
        if "palette_nom" in r:
            r["palette"] = list(moteur.PALETTES[DEFAUTS["palette_nom"]])
        self._appliquer_reglages({**self.reglages(), **r})
        self._marquer_sections()

    # ----- Affichage
    def rafraichir(self, tout=False):
        """Met la toile (et, si `tout`, le panneau) à jour à partir du document."""
        tl = self.toile
        img = self._image_lue if self._image_lue is not None else self.image
        oignon = None
        if self.c["oignon"].valeur() and self.actuelle > 0 and self._image_lue is None:
            oignon = vers_qimage(self.images[self.actuelle - 1])
        tl.rapport = self.rapport()
        tl.grille = self.c["grille"].valeur()
        tl.tuile = self.c["tuile"].valeur()
        tl.pinceau = self.c["taille_pinceau"].valeur() if self.c["outil"].valeur() in ("crayon", "gomme") else 1
        tl.sym = (self.c["sym_x"].valeur(), self.c["sym_y"].valeur())
        tl.outil = self.c["outil"].valeur()
        tl.definir_selection(self.selection if self._image_lue is None else None, self.flottant is not None)
        tl.definir(vers_qimage(img), oignon)
        self._maj_etat()
        if tout:
            self._maj_panneau()

    def _maj_panneau(self):
        h, w = self.image.shape[:2]
        self._bloquer = True
        self.c["largeur"].definir(w)
        self.c["hauteur"].definir(h)
        nom = next((n for n, taille in FORMATS.items() if taille == (w, h)), FORMAT_PERSO)
        self.c["format"].definir(nom)
        self._bloquer = False
        self.pastilles.definir(self.principale, self.secondaire)
        self.nuancier.definir(self.palette, (self.principale, self.secondaire))
        self.info_couleurs.setText(f"{self.principale}\n{self.secondaire}\n{len(self.palette)} couleurs")
        self.bande.definir([vers_qimage(i) for i in self.images], self.actuelle, self.rapport())
        self.b_lecture.setVisible(len(self.images) > 1)
        for b in self.boutons_selection:
            b.setEnabled(self.selection is not None or b.toolTip().startswith("Coller"))
        self._couleurs_cache = moteur.couleurs_utilisees([self.image], limite=32)
        self.b_grille.blockSignals(True)
        self.b_grille.setChecked(self.c["grille"].valeur())
        self.b_grille.blockSignals(False)
        e, rp = self.c["echelle"].valeur(), self.rapport()
        fmt = self.c["format_export"].valeur()
        n = len(self.images)
        if fmt == EXPORTS[1]:
            cols = self.c["colonnes"].valeur() or n
            w, h = w * min(cols, n), h * -(-n // cols)
        self.info_export.setText(f"Fichier final : {w * e * rp} × {h * e} pixels"
                                 + (f", {n} images" if fmt in EXPORTS[2:] else "") + ".")
        self._maj_titre()

    def _maj_etat(self):
        h, w = self.image.shape[:2]
        morceaux = [f"{w}×{h}"]
        if self.toile.pixel and 0 <= self.toile.pixel[0] < w and 0 <= self.toile.pixel[1] < h:
            morceaux.append(f"({self.toile.pixel[0]}, {self.toile.pixel[1]})")
        if self.selection:
            morceaux.append(f"sélection {self.selection[2]}×{self.selection[3]}")
        if len(self.images) > 1:
            morceaux.append(f"image {self.actuelle + 1}/{len(self.images)}")
        morceaux.append(f"{round(self.toile.echelle() * 100)} %")
        # Les couleurs sont recalculées après chaque geste, pas à chaque mouvement de souris
        self.etat.definir("   ".join(morceaux), self._couleurs_cache, self.modifie)

    def _maj_titre(self):
        nom = os.path.basename(self.chemin_projet) if self.chemin_projet else "Sans titre"
        self.setWindowTitle(f"{nom}{' •' if self.modifie else ''} — {NOM}")

    def _maj_boutons_zoom(self):
        for z, b in self.boutons_zoom.items():
            b.setChecked(z == self.toile.zoom)
        self._maj_etat()

    # ----- Dessin : la souris parle, le moteur dessine
    def _couleur(self, bouton):
        if self.c["outil"].valeur() == "gomme":
            return moteur.VIDE
        return moteur.hex_vers_rgba(self.principale if bouton == 0 else self.secondaire)

    def _pression(self, x, y, bouton, mods):
        if self.minuteur_lecture.isActive():
            self.basculer_lecture()
        outil = self.c["outil"].valeur()
        h, w = self.image.shape[:2]
        if outil == "selection":
            return self._pression_selection(x, y, mods)
        self._ancrer()
        if outil == "pipette" or mods & Qt.KeyboardModifier.AltModifier:
            if 0 <= x < w and 0 <= y < h and self.image[y, x, 3]:
                self.choisir_couleur(moteur.rgba_vers_hex(self.image[y, x]), bouton)
            self._depart = None
            return
        self._base = self.image.copy()
        self._depart = self._dernier = (x, y)
        self._couleur_geste = self._couleur(bouton)
        if outil == "pot":
            if 0 <= x < w and 0 <= y < h:
                moteur.remplir(self.image, x, y, self._couleur_geste)
        elif outil != "deplacer":
            self._glisse(x, y, mods)
            return
        self.rafraichir()

    def _contraindre(self, x, y, mods, outil):
        """Avec Maj : lignes à 0°, 45° ou 90°, carrés et cercles parfaits."""
        if not mods & Qt.KeyboardModifier.ShiftModifier:
            return x, y
        x0, y0 = self._depart
        dx, dy = x - x0, y - y0
        if outil == "ligne":
            if abs(dx) > 2 * abs(dy):
                return x, y0
            if abs(dy) > 2 * abs(dx):
                return x0, y
        d = max(abs(dx), abs(dy))
        return x0 + d * (1 if dx >= 0 else -1), y0 + d * (1 if dy >= 0 else -1)

    def _glisse(self, x, y, mods):
        if self._depart is None:
            return
        outil = self.c["outil"].valeur()
        if outil == "selection":
            return self._glisse_selection(x, y)
        options = dict(taille=1, sym_x=self.c["sym_x"].valeur(), sym_y=self.c["sym_y"].valeur())
        if outil in ("crayon", "gomme"):
            options["taille"] = self.c["taille_pinceau"].valeur()
            moteur.tamponner(self.image, moteur.ligne(*self._dernier, x, y), self._couleur_geste, **options)
        elif outil in ("ligne", "rectangle", "ellipse"):
            x, y = self._contraindre(x, y, mods, outil)
            img = self._base.copy()
            if outil == "ligne":
                points = moteur.ligne(*self._depart, x, y)
            else:
                forme = moteur.rectangle if outil == "rectangle" else moteur.ellipse
                points = forme(*self._depart, x, y, self.c["plein"].valeur())
            moteur.tamponner(img, points, self._couleur_geste, **options)
            self.image = img
        elif outil == "deplacer":
            self.image = moteur.decaler(self._base, x - self._depart[0], y - self._depart[1])
        else:
            return
        self._dernier = (x, y)
        self.rafraichir()

    def _relache(self):
        if self._depart is None:
            return
        if self.c["outil"].valeur() == "selection":
            return self._relache_selection()
        self._depart = None
        if self._base is not None and not np.array_equal(self._base, self.image):
            self._memoriser()
        self._base = None

    # ----- Sélection
    def _pression_selection(self, x, y, mods):
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        if self.toile.dans_selection(x, y):
            # Clic dans la zone : on va la déplacer (avec Alt, on en laisse une copie derrière)
            if self.flottant is None:
                self._soulever(copie=alt)
            elif alt:
                self._sous = self.image.copy()
            self._bouge = self.selection[:2]
        else:
            # Clic ailleurs : on pose ce qui flottait et on commence une nouvelle zone
            self._ancrer()
            self._bouge = None
            self.selection = None
        self._depart = (x, y)
        self.rafraichir()

    def _soulever(self, copie=False):
        x, y, w, h = self.selection
        self._sous = self.image.copy()
        self.flottant = self.image[y:y + h, x:x + w].copy()
        if not copie:
            self._sous[y:y + h, x:x + w] = 0

    def _glisse_selection(self, x, y):
        dx, dy = x - self._depart[0], y - self._depart[1]
        if self._bouge is not None:
            nx, ny = self._bouge[0] + dx, self._bouge[1] + dy
            self.selection = (nx, ny) + self.selection[2:]
            self.image = moteur.coller(self._sous, self.flottant, nx, ny)
        else:
            h, w = self.image.shape[:2]
            (x0, y0), x, y = self._depart, min(max(x, 0), w - 1), min(max(y, 0), h - 1)
            x0, y0 = min(max(x0, 0), w - 1), min(max(y0, 0), h - 1)
            self.selection = (min(x0, x), min(y0, y), abs(x - x0) + 1, abs(y - y0) + 1)
        self.rafraichir()

    def _relache_selection(self):
        if self._bouge is not None:
            self._memoriser()
        self._depart = self._bouge = None
        self.rafraichir(tout=True)

    def _ancrer(self):
        """Pose pour de bon la zone qu'on déplaçait (elle fait déjà partie de self.image)."""
        if self.flottant is None:
            return
        self.flottant = self._sous = None
        h, w = self.image.shape[:2]
        self.selection = moteur.zone_dans(self.selection, w, h)
        self._memoriser()
        self.rafraichir(tout=True)

    def deselectionner(self):
        self._ancrer()
        if self.selection:
            self.selection = None
            self.rafraichir(tout=True)

    def tout_selectionner(self):
        self._ancrer()
        self.c["outil"].definir("selection")
        h, w = self.image.shape[:2]
        self.selection = (0, 0, w, h)
        self.rafraichir(tout=True)

    def _rien_de_selectionne(self):
        if self.selection:
            return False
        self.toile.dire("Rien de sélectionné : prends l'outil Sélection (S) et glisse sur le dessin.")
        return True

    def copier(self):
        if self._rien_de_selectionne():
            return False
        if self.flottant is not None:
            morceau = self.flottant.copy()
        else:
            x, y, w, h = self.selection
            morceau = self.image[y:y + h, x:x + w].copy()
        self.presse_papiers = morceau
        # Aussi dans le presse-papiers du système, pour coller dans une autre app
        QApplication.clipboard().setImage(vers_qimage(morceau))
        self.toile.dire(f"Copié : {morceau.shape[1]} × {morceau.shape[0]}. {CMD}V pour coller.")
        return True

    def couper(self):
        if self.copier():
            self.supprimer_selection()

    def supprimer_selection(self):
        if self._rien_de_selectionne():
            return
        if self.flottant is not None:
            self.image = self._sous
            self.flottant = self._sous = None
        else:
            x, y, w, h = self.selection
            img = self.image.copy()
            img[y:y + h, x:x + w] = 0
            self.image = img
        h, w = self.image.shape[:2]
        self.selection = moteur.zone_dans(self.selection, w, h)
        self._memoriser()
        self.rafraichir(tout=True)

    def coller(self):
        morceau = self.presse_papiers
        presse = QApplication.clipboard()
        if presse.mimeData() is not None and presse.mimeData().hasImage():
            q = presse.image()
            # Si c'est notre propre copie, on garde la nôtre (le système peut abîmer la transparence)
            if not q.isNull() and (morceau is None or (q.width(), q.height()) != morceau.shape[1::-1]):
                morceau = depuis_qimage(q)
        if morceau is None:
            self.toile.dire("Le presse-papiers est vide : copie d'abord une zone, ou une image.")
            return
        self._ancrer()
        self.c["outil"].definir("selection")
        h, w = self.image.shape[:2]
        mh, mw = morceau.shape[:2]
        x, y = self.selection[:2] if self.selection else (max(0, (w - mw) // 2), max(0, (h - mh) // 2))
        self._sous, self.flottant = self.image.copy(), morceau.copy()
        self.selection = (x, y, mw, mh)
        self.image = moteur.coller(self._sous, self.flottant, x, y)
        self._memoriser()
        self.rafraichir(tout=True)
        depasse = mw > w or mh > h
        self.toile.dire("Collé ! Glisse-le où tu veux, Échap pour le poser."
                        + (" Attention, il dépasse de la toile." if depasse else ""))

    def rogner(self):
        """La toile (toutes les images de l'animation) prend la taille de la sélection."""
        if self._rien_de_selectionne():
            return
        self._ancrer()
        x, y, w, h = self.selection
        self.images = [i[y:y + h, x:x + w].copy() for i in self.images]
        self.selection = None
        self._memoriser()
        self.rafraichir(tout=True)
        self.toile.definir_zoom(None)
        self.toile.dire(f"Toile rognée à {w} × {h}.")

    # ----- Couleurs
    def choisir_couleur(self, c, laquelle=0):
        if laquelle == 0:
            self.principale = c
        else:
            self.secondaire = c
        self._maj_panneau()

    def echanger_couleurs(self):
        self.principale, self.secondaire = self.secondaire, self.principale
        self._maj_panneau()

    def _demander_couleur(self, laquelle):
        actuelle = self.principale if laquelle == 0 else self.secondaire
        c = QColorDialog.getColor(QColor(actuelle), self,
                                  "Couleur principale" if laquelle == 0 else "Couleur secondaire")
        if c.isValid():
            self.choisir_couleur(c.name(), laquelle)

    def _palette_choisie(self):
        nom = self.c["palette_nom"].valeur()
        if nom == PALETTE_PERSO:
            return
        if nom == PALETTE_DESSIN:
            self.palette = moteur.couleurs_utilisees(self.images, limite=64) or ["#000000", "#ffffff"]
        else:
            self.palette = list(moteur.PALETTES[nom])
        if self.principale not in self.palette:
            self.principale = self.palette[0]
        if self.secondaire not in self.palette:
            self.secondaire = self.palette[-1]
        self._maj_panneau()
        self._programmer_memoire()

    def _palette_modifiee(self, couleurs):
        self.palette = list(couleurs)
        self._bloquer = True
        self.c["palette_nom"].definir(PALETTE_PERSO)
        self._bloquer = False
        self._maj_panneau()
        self._programmer_memoire()

    def _remplacer_couleur(self, ancienne, nouvelle):
        """Modifier une couleur de la palette recolore aussi tous les pixels qui l'utilisent."""
        self._ancrer()
        a, n = moteur.hex_vers_rgba(ancienne), moteur.hex_vers_rgba(nouvelle)
        total = sum(moteur.remplacer_couleur(img, a, n) for img in self.images)
        self.palette = [nouvelle if c == ancienne else c for c in self.palette]
        if self.principale == ancienne:
            self.principale = nouvelle
        if self.secondaire == ancienne:
            self.secondaire = nouvelle
        self._palette_modifiee(self.palette)
        self.rafraichir(tout=True)
        self.toile.dire(f"{total} pixels recolorés." if total else "Couleur modifiée.")
        self._memoriser()

    def ramener_a_palette(self):
        self._ancrer()
        self.images = [moteur.quantifier(i, self.palette) for i in self.images]
        self.rafraichir(tout=True)
        self._memoriser()
        self.toile.dire("Le dessin n'utilise plus que les couleurs de la palette.")

    # ----- Grille
    def _format_choisi(self):
        nom = self.c["format"].valeur()
        if nom in FORMATS:
            self._redimensionner(*FORMATS[nom])

    def _taille_changee(self):
        self._redimensionner(self.c["largeur"].valeur(), self.c["hauteur"].valeur())

    def _redimensionner(self, w, h):
        """On repart toujours des images d'avant le changement : rétrécir puis réagrandir
        avec le curseur ne perd donc rien tant que le changement n'est pas validé."""
        if self._avant_redim is None:
            self._ancrer()
            self.selection = None
            self._avant_redim = [i.copy() for i in self.images]
        ancre = self.c["ancre"].valeur()
        self.images = [moteur.redimensionner_toile(i, w, h, ancre) for i in self._avant_redim]
        self.rafraichir(tout=True)
        self._programmer_memoire()

    def retourner(self, horizontal):
        if self.flottant is not None:
            self.flottant = moteur.retourner(self.flottant, horizontal)
            self.image = moteur.coller(self._sous, self.flottant, *self.selection[:2])
        elif self.selection:
            x, y, w, h = self.selection
            img = self.image.copy()
            img[y:y + h, x:x + w] = moteur.retourner(img[y:y + h, x:x + w], horizontal)
            self.image = img
        else:
            self.image = moteur.retourner(self.image, horizontal)
        self.rafraichir(tout=True)
        self._memoriser()

    def vider(self):
        self._ancrer()
        if self.image[..., 3].any():
            self.image = np.zeros_like(self.image)
            self.rafraichir(tout=True)
            self._memoriser()

    def _pinceau(self, pas):
        c = self.c["taille_pinceau"]
        c.definir(min(8, max(1, c.valeur() + pas)))

    # ----- Animation
    def choisir_image(self, i):
        self._ancrer()
        self.selection = None
        self.actuelle = max(0, min(len(self.images) - 1, i))
        self.rafraichir(tout=True)

    def image_voisine(self, pas):
        self.choisir_image((self.actuelle + pas) % len(self.images))

    def nouvelle_image(self):
        self.images.insert(self.actuelle + 1, np.zeros_like(self.image))
        self.choisir_image(self.actuelle + 1)
        self._memoriser()

    def dupliquer_image(self):
        self.images.insert(self.actuelle + 1, self.image.copy())
        self.choisir_image(self.actuelle + 1)
        self._memoriser()

    def supprimer_image(self):
        if len(self.images) == 1:
            self.vider()
            return
        del self.images[self.actuelle]
        self.choisir_image(min(self.actuelle, len(self.images) - 1))
        self._memoriser()

    def bouger_image(self, pas):
        j = self.actuelle + pas
        if 0 <= j < len(self.images):
            self.images[self.actuelle], self.images[j] = self.images[j], self.images[self.actuelle]
            self.choisir_image(j)
            self._memoriser()

    def basculer_lecture(self):
        if self.minuteur_lecture.isActive():
            self.minuteur_lecture.stop()
            self._image_lue = None
            self.b_lecture.setIcon(t.icone("lecture", t.ENCRE, 16))
        elif len(self.images) > 1:
            self._indice_lu = self.actuelle
            self.minuteur_lecture.start(round(1000 / self.c["ips"].valeur()))
            self.b_lecture.setIcon(t.icone("pause", t.ENCRE, 16))
        self.rafraichir()

    def _tic_lecture(self):
        self._indice_lu = (self._indice_lu + 1) % len(self.images)
        self._image_lue = self.images[self._indice_lu]
        self.rafraichir()

    # ----- Historique
    def _etat(self):
        return {"images": [i.copy() for i in self.images], "actuelle": self.actuelle,
                "palette": list(self.palette), "palette_nom": self.c["palette_nom"].valeur()}

    def _programmer_memoire(self):
        self.minuteur_histo.start()

    def _memoriser(self, modifie=True):
        self.minuteur_histo.stop()
        self._avant_redim = None
        etat = self._etat()
        if 0 <= self.pos_historique < len(self.historique):
            dernier = self.historique[self.pos_historique]
            if dernier["palette"] == etat["palette"] and len(dernier["images"]) == len(etat["images"]) \
                    and all(np.array_equal(a, b) for a, b in zip(dernier["images"], etat["images"])):
                dernier["actuelle"] = etat["actuelle"]
                return
        del self.historique[self.pos_historique + 1:]
        self.historique.append(etat)
        # 200 étapes au plus, et pas plus de ~400 Mo : les grandes planches pèsent vite lourd
        poids = sum(i.nbytes for e in self.historique for i in e["images"])
        while len(self.historique) > 2 and (len(self.historique) > 200 or poids > 400_000_000):
            poids -= sum(i.nbytes for i in self.historique.pop(0)["images"])
        self.pos_historique = len(self.historique) - 1
        if modifie:
            self.modifie = True
        self.b_annuler.setEnabled(self.pos_historique > 0)
        self.b_retablir.setEnabled(False)
        self._maj_panneau()
        self._maj_etat()

    def _restaurer(self, etat):
        self.selection = self.flottant = self._sous = None
        self.images = [i.copy() for i in etat["images"]]
        self.actuelle = min(etat["actuelle"], len(self.images) - 1)
        self.palette = list(etat["palette"])
        self._bloquer = True
        self.c["palette_nom"].definir(etat["palette_nom"])
        self._bloquer = False
        self._avant_redim = None
        self.modifie = True
        self.b_annuler.setEnabled(self.pos_historique > 0)
        self.b_retablir.setEnabled(self.pos_historique < len(self.historique) - 1)
        self.rafraichir(tout=True)

    def annuler(self):
        if self.minuteur_histo.isActive():
            self._memoriser()
        if self.pos_historique > 0:
            self.pos_historique -= 1
            self._restaurer(self.historique[self.pos_historique])

    def retablir(self):
        if self.pos_historique < len(self.historique) - 1:
            self.pos_historique += 1
            self._restaurer(self.historique[self.pos_historique])

    # ----- Fichiers
    def _dossier(self):
        return self.prefs.value("dossier", os.path.expanduser("~"))

    def nouveau(self):
        """Une toile vierge de la même taille. Ça s'annule comme le reste (⌘Z)."""
        self.chemin_image = None
        self.selection = self.flottant = self._sous = None
        h, w = self.image.shape[:2]
        self.images = [moteur.nouvelle(w, h)]
        self.actuelle = 0
        self.chemin_projet = None
        self.rafraichir(tout=True)
        self._memoriser()
        self.toile.dire(f"Toile vierge de {w} × {h}. {CMD}Z pour revenir en arrière.")

    def ouvrir(self):
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un projet ou importer une image", self._dossier(),
            f"Projets et images (*{fichiers.EXTENSION_PROJET} {fichiers.FORMATS_IMAGE});;"
            f"Projets PixelShell (*{fichiers.EXTENSION_PROJET});;Images ({fichiers.FORMATS_IMAGE})")
        if chemin:
            self.charger(chemin)

    def charger(self, chemin):
        self.prefs.setValue("dossier", os.path.dirname(chemin))
        self._ancrer()
        self.selection = None
        try:
            if chemin.lower().endswith(fichiers.EXTENSION_PROJET):
                images, r = fichiers.charger_projet(chemin)
                self.images, self.actuelle = images, 0
                self._appliquer_reglages({**self.reglages(), **r})
                self.chemin_projet = chemin
                self.chemin_image = None
                self.rafraichir(tout=True)
                self._memoriser()
                self.modifie = False
                self.toile.definir_zoom(None)
                self._maj_panneau()
                self._maj_etat()
                return
            images, duree = fichiers.importer(chemin)
        except Exception as e:
            QMessageBox.warning(self, NOM, f"Impossible d'ouvrir ce fichier.\n\n{e}")
            return
        h, w = images[0].shape[:2]
        trop_grande = w > moteur.TAILLE_MAX or h > moteur.TAILLE_MAX
        # Plus de 640 px ET des milliers de couleurs : c'est sûrement une photo, pas du pixel art
        photo = max(w, h) > 640 and len(moteur.couleurs_utilisees(images[:1], limite=1000)) > 512
        if trop_grande or photo:
            images = self._reduire_import(images, w, h, garder=not trop_grande)
            if images is None:
                return
        self.images, self.actuelle = images, 0
        if duree:
            self.c["ips"].definir(max(1, min(30, round(1000 / duree))))
        # Une image ouverte depuis un fichier (un sprite de jeu…) se réexporte à sa taille
        # réelle, à la même place : sinon le jeu reçoit une image 8 fois trop grande.
        self.c["echelle"].definir(1)
        self.c["rapport"].definir(RAPPORTS[0])
        self.chemin_image = chemin if len(images) == 1 else None
        if self.chemin_image:
            self.c["format_export"].definir(EXPORTS[0])
        self.chemin_projet = None
        self.rafraichir(tout=True)
        self._memoriser()
        self.toile.definir_zoom(None)
        h, w = self.image.shape[:2]
        n = len(self.images)
        self.toile.dire(f"{os.path.basename(chemin)} : {w} × {h}" + (f", {n} images" if n > 1 else "")
                        + f", {len(moteur.couleurs_utilisees(self.images))} couleurs.")

    def _reduire_import(self, images, w, h, garder=False):
        """Une grande image (photo, dessin) est ramenée à une taille de pixel art."""
        gw, gh = self.image.shape[1], self.image.shape[0]
        largeur = 64
        hauteur = max(1, round(h * largeur / w))
        boite = QMessageBox(self)
        boite.setWindowTitle(NOM)
        boite.setText(f"Cette image fait {w} × {h} pixels et ressemble à une photo plutôt "
                      "qu'à du pixel art." if garder else
                      f"Cette image fait {w} × {h} pixels, c'est plus que le maximum "
                      f"({moteur.TAILLE_MAX} × {moteur.TAILLE_MAX}).")
        boite.setInformativeText("PixelShell peut la réduire. Tu pourras ensuite la ramener à ta "
                                 "palette (section Couleurs).")
        b_grille = boite.addButton(f"Réduire à la grille ({gw} × {gh})", QMessageBox.ButtonRole.AcceptRole)
        b_prop = boite.addButton(f"Réduire à {largeur} × {hauteur}", QMessageBox.ButtonRole.AcceptRole)
        b_garder = boite.addButton(f"Garder {w} × {h}", QMessageBox.ButtonRole.AcceptRole) if garder else None
        boite.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        boite.exec()
        if b_garder is not None and boite.clickedButton() == b_garder:
            return images
        if boite.clickedButton() == b_grille:
            return [moteur.reduire(i, gw, gh) for i in images]
        if boite.clickedButton() == b_prop:
            return [moteur.reduire(i, largeur, min(moteur.TAILLE_MAX, hauteur)) for i in images]
        return None

    def importer_planche(self):
        """Découpe une planche de sprites en images, à la taille de la grille actuelle."""
        chemin, _ = QFileDialog.getOpenFileName(self, "Importer une planche de sprites", self._dossier(),
                                                f"Images ({fichiers.FORMATS_IMAGE})")
        if chemin:
            self.importer_planche_depuis(chemin)

    def importer_planche_depuis(self, chemin):
        try:
            planche = fichiers.importer(chemin)[0][0]
        except Exception as e:
            QMessageBox.warning(self, NOM, f"Impossible d'ouvrir ce fichier.\n\n{e}")
            return
        self._ancrer()
        self.selection = None
        h, w = self.image.shape[:2]
        self.images = moteur.decouper(planche, w, h)
        self.actuelle = 0
        # Pour réexporter la planche à l'identique, au même endroit
        self.chemin_image = chemin
        self.c["format_export"].definir(EXPORTS[1])
        self.c["echelle"].definir(1)
        self.c["rapport"].definir(RAPPORTS[0])
        self.c["colonnes"].definir(planche.shape[1] // w if planche.shape[0] > h else 0)
        self.rafraichir(tout=True)
        self._memoriser()
        self.toile.dire(f"Planche découpée en {len(self.images)} images de {w} × {h}.")

    def enregistrer(self):
        if not self.chemin_projet:
            return self.enregistrer_sous()
        try:
            fichiers.enregistrer_projet(self.chemin_projet, self.images, self.reglages())
        except Exception as e:
            QMessageBox.warning(self, NOM, f"Impossible d'enregistrer.\n\n{e}")
            return False
        self.modifie = False
        self._maj_titre()
        self._maj_etat()
        self.toile.dire(f"Projet enregistré : {os.path.basename(self.chemin_projet)}")
        return True

    def enregistrer_sous(self):
        nom = os.path.basename(self.chemin_projet) if self.chemin_projet else "dessin" + fichiers.EXTENSION_PROJET
        chemin, _ = QFileDialog.getSaveFileName(self, "Enregistrer le projet",
                                                os.path.join(self._dossier(), nom),
                                                f"Projet PixelShell (*{fichiers.EXTENSION_PROJET})")
        if not chemin:
            return False
        if not chemin.lower().endswith(fichiers.EXTENSION_PROJET):
            chemin += fichiers.EXTENSION_PROJET
        self.prefs.setValue("dossier", os.path.dirname(chemin))
        self.chemin_projet = chemin
        return self.enregistrer()

    def exporter(self, chemin=None):
        fmt = self.c["format_export"].valeur()
        ext = ".gif" if fmt == EXPORTS[2] else ".png"
        if not chemin:
            base = os.path.splitext(os.path.basename(self.chemin_projet or "dessin"))[0]
            propose = os.path.join(self._dossier(), base + ext)
            if self.chemin_image and ext == ".png" and fmt != EXPORTS[3]:
                propose = self.chemin_image  # on propose de remplacer l'image ouverte
            chemin, _ = QFileDialog.getSaveFileName(self, f"Exporter : {fmt}", propose,
                                                    "GIF (*.gif)" if ext == ".gif" else "PNG (*.png)")
            if not chemin:
                return None
        if not chemin.lower().endswith(ext):
            chemin += ext
        self.prefs.setValue("dossier", os.path.dirname(chemin))
        e, rp = self.c["echelle"].valeur(), self.rapport()
        if self.chemin_image and os.path.abspath(chemin) == os.path.abspath(self.chemin_image) \
                and (e != 1 or rp != 1):
            rep = QMessageBox.question(
                self, NOM, f"Tu remplaces l'image d'origine, mais l'agrandissement est à ×{e}"
                f"{' en pixels larges' if rp != 1 else ''} : le fichier ne fera plus la même taille.\n\n"
                "Exporter plutôt à la taille réelle (×1) ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if rep == QMessageBox.StandardButton.Yes:
                e, rp = 1, 1
        try:
            if fmt == EXPORTS[0]:
                fichiers.enregistrer_png(chemin, self.image, e, rp)
            elif fmt == EXPORTS[1]:
                fichiers.enregistrer_planche(chemin, self.images, e, rp, self.c["colonnes"].valeur())
            elif fmt == EXPORTS[2]:
                fichiers.enregistrer_gif(chemin, self.images, self.c["ips"].valeur(), e, rp)
            else:
                racine = os.path.splitext(chemin)[0]
                for i, img in enumerate(self.images):
                    fichiers.enregistrer_png(f"{racine}_{i + 1:02d}.png", img, e, rp)
        except Exception as err:
            QMessageBox.warning(self, NOM, f"L'export n'a pas marché.\n\n{err}")
            return None
        self.toile.dire(f"Exporté : {os.path.basename(chemin)}")
        reveler(chemin)
        return chemin

    # ----- Session : on reprend toujours là où on s'était arrêté
    def _chemin_session(self):
        dossier = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        return os.path.join(dossier, "session" + fichiers.EXTENSION_PROJET)

    def _reprendre_session(self):
        chemin = self._chemin_session()
        if not os.path.exists(chemin):
            return
        try:
            self.images, r = fichiers.charger_projet(chemin)
            self.actuelle = min(int(r.pop("actuelle", 0)), len(self.images) - 1)
            self.chemin_projet = r.pop("chemin_projet", None)
            self.chemin_image = r.pop("chemin_image", None)
            self.modifie = bool(r.pop("modifie", False))
            self._appliquer_reglages(r)
        except Exception:
            self.images, self.actuelle = [moteur.nouvelle(32, 32)], 0
        self.rafraichir(tout=True)

    def closeEvent(self, e):
        self.minuteur_lecture.stop()
        if os.environ.get("PIXELSHELL_TEST"):
            return super().closeEvent(e)
        r = self.reglages()
        self.prefs.setValue("reglages", json.dumps(r))
        try:
            r.update(actuelle=self.actuelle, chemin_projet=self.chemin_projet, modifie=self.modifie,
                     chemin_image=self.chemin_image)
            os.makedirs(os.path.dirname(self._chemin_session()), exist_ok=True)
            fichiers.enregistrer_projet(self._chemin_session(), self.images, r)
        except Exception:
            pass
        super().closeEvent(e)


def reveler(chemin):
    """Montre le fichier dans le gestionnaire de fichiers du système."""
    import subprocess
    if os.environ.get("PIXELSHELL_TEST"):
        return
    try:
        if MAC:
            subprocess.Popen(["open", "-R", chemin])
        elif WINDOWS:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(chemin)])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(chemin)])
    except Exception:
        pass


def auto_test(dossier):
    """Vérifie que tout marche (utilisé par GitHub Actions sur les 3 systèmes) : code 0 = ok."""
    import traceback
    from PIL import Image
    os.environ["PIXELSHELL_TEST"] = "1"
    os.makedirs(dossier, exist_ok=True)
    journal = open(os.path.join(dossier, "resultat.txt"), "w", encoding="utf-8")

    def noter(m):
        print(m, flush=True)
        journal.write(m + "\n")
        journal.flush()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName("PixelShellTest")  # session à part : on ne touche pas à la vraie
    app.setApplicationName("PixelShellTest")
    t.charger_polices()
    app.setStyleSheet(t.feuille_de_style())
    try:
        f = Fenetre()
        f.show()
        app.processEvents()
        f.nouveau()
        f.c["format"].definir("16 × 16")
        assert f.image.shape == (16, 16, 4), f.image.shape
        noter("grille ok : 16 × 16")
        rouge = "#ff004d"
        f.choisir_couleur(rouge)
        for outil, de, a in (("crayon", (1, 1), (6, 1)), ("ligne", (0, 15), (15, 0)),
                             ("rectangle", (2, 2), (8, 8)), ("ellipse", (8, 8), (14, 14)),
                             ("pot", (4, 4), (4, 4)), ("gomme", (1, 1), (2, 1))):
            f.c["outil"].definir(outil)
            f._pression(*de, 0, Qt.KeyboardModifier.NoModifier)
            f._glisse(*a, Qt.KeyboardModifier.NoModifier)
            f._relache()
        assert tuple(f.image[4, 4]) == moteur.hex_vers_rgba(rouge), "le pot n'a pas rempli"
        assert f.image[1, 1, 3] == 0, "la gomme n'a pas effacé"
        noter(f"outils ok ({len(f.historique)} étapes d'historique)")
        avant = f.image.copy()
        f.c["largeur"].definir(8)
        f.c["largeur"].definir(16)
        assert np.array_equal(f.image, avant), "rétrécir puis réagrandir a perdu des pixels"
        f._memoriser()
        f.c["format"].definir("32 × 32")
        f._memoriser()
        f.annuler()
        assert f.image.shape[:2] == (16, 16)
        f.retablir()
        assert f.image.shape[:2] == (32, 32)
        noter("redimensionnement + annuler / rétablir ok")
        f.dupliquer_image()
        f.c["outil"].definir("deplacer")
        f._pression(0, 0, 0, Qt.KeyboardModifier.NoModifier)
        f._glisse(3, 0, Qt.KeyboardModifier.NoModifier)
        f._relache()
        assert len(f.images) == 2
        noter("animation ok : 2 images")
        f.c["rapport"].definir(RAPPORTS[1])
        for i, fmt in enumerate(EXPORTS):
            f.c["format_export"].definir(fmt)
            f.c["echelle"].definir(2)
            ext = ".gif" if fmt == EXPORTS[2] else ".png"
            sortie = f.exporter(os.path.join(dossier, f"export{i}{ext}"))
            assert sortie, fmt
            if i < 3:
                with Image.open(sortie) as im:
                    noter(f"export ok : {fmt} → {im.size[0]}×{im.size[1]}")
        projet = os.path.join(dossier, "test.pxshell")
        f.chemin_projet = projet
        assert f.enregistrer()
        images = [i.copy() for i in f.images]
        f.nouveau()
        f.charger(projet)
        assert len(f.images) == 2 and all(np.array_equal(a, b) for a, b in zip(images, f.images))
        noter("projet .pxshell ok (aller-retour identique)")
        gif = os.path.join(dossier, "export2.gif")
        f.charger(gif)
        assert len(f.images) == 2, len(f.images)
        grande = os.path.join(dossier, "grande.png")
        Image.fromarray((np.random.default_rng(1).random((800, 1000, 3)) * 255).astype(np.uint8)).save(grande)
        f._reduire_import = lambda images, w, h, garder=False: [moteur.reduire(i, 64, 48) for i in images]
        f.charger(grande)
        assert f.image.shape[:2] == (48, 64)
        f.ramener_a_palette()
        noter("imports ok : GIF animé, photo réduite et ramenée à la palette")

        # Grandes images de pixel art (comme celles de Montauk) : ouvertes telles quelles
        f._reduire_import = lambda *a, **k: (_ for _ in ()).throw(AssertionError("réduction demandée"))
        rng = np.random.default_rng(2)
        cases = rng.integers(0, 6, (80, 1200))
        couleurs = np.array([[0, 0, 0, 0], [185, 0, 0, 255], [255, 24, 24, 255],
                             [240, 240, 240, 255], [90, 0, 0, 255], [0, 140, 255, 255]], np.uint8)
        planche = couleurs[cases]
        planche[:, ::100] = 0  # pour que chaque image commence par une colonne vide
        chemin_planche = os.path.join(dossier, "creature.png")
        Image.fromarray(planche, "RGBA").save(chemin_planche)
        f.charger(chemin_planche)
        assert f.image.shape[:2] == (80, 1200), f.image.shape
        decor = os.path.join(dossier, "decor.png")
        Image.fromarray(couleurs[rng.integers(1, 6, (480, 640))][..., :3]).save(decor)
        f.charger(decor)
        assert f.image.shape[:2] == (480, 640)
        f.c["format"].definir("100 × 80 (créature, une image)")
        f._memoriser()
        f.importer_planche_depuis(chemin_planche)
        assert len(f.images) == 12 and f.image.shape[:2] == (80, 100), (len(f.images), f.image.shape)
        f.c["format_export"].definir(EXPORTS[1])
        f.c["echelle"].definir(1)
        f.c["rapport"].definir(RAPPORTS[0])
        sortie = f.exporter(os.path.join(dossier, "creature_export.png"))
        with Image.open(sortie) as im:
            assert np.array_equal(np.asarray(im.convert("RGBA")), planche), "la planche a changé"
        noter("grandes images ok : planche 1200×80 → 12 images → planche identique, décor 640×480")

        # Sélection : copier, coller, déplacer, copie avec Alt, effacer, rogner
        N, ALT = Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.AltModifier
        f.choisir_image(0)
        f.c["outil"].definir("selection")
        f._pression(10, 10, 0, N)
        f._glisse(19, 29, N)
        f._relache()
        assert f.selection == (10, 10, 10, 20), f.selection
        zone = f.image[10:30, 10:20].copy()
        assert f.copier()
        f.deselectionner()
        f.coller()
        assert f.flottant is not None and f.selection[2:] == (10, 20)
        x, y = f.selection[:2]
        f._pression(x, y, 0, N)
        f._glisse(x - 30, y + 5, N)
        f._relache()
        nx, ny = f.selection[:2]
        assert (nx, ny) == (x - 30, y + 5), f.selection
        f.deselectionner()
        assert np.array_equal(f.image[ny:ny + 20, nx:nx + 10][zone[..., 3] > 0], zone[zone[..., 3] > 0])
        f.c["outil"].definir("selection")
        f._pression(0, 0, 0, N)
        f._glisse(9, 9, N)
        f._relache()
        avant = f.image[0:10, 0:10].copy()
        f._pression(5, 5, 0, ALT)
        f._glisse(25, 5, ALT)
        f._relache()
        f.deselectionner()
        assert np.array_equal(f.image[0:10, 0:10], avant), "Alt aurait dû laisser une copie"
        f._pression(0, 0, 0, N)
        f._glisse(4, 4, N)
        f._relache()
        f.supprimer_selection()
        assert not f.image[0:5, 0:5, 3].any(), "la zone n'a pas été effacée"
        f.annuler()
        assert np.array_equal(f.image[0:5, 0:5], avant[0:5, 0:5]), "annuler n'a pas rendu la zone"
        f._pression(20, 10, 0, N)
        f._glisse(59, 49, N)
        f._relache()
        f.rogner()
        assert all(i.shape[:2] == (40, 40) for i in f.images) and len(f.images) == 12
        noter("sélection ok : copier, coller, déplacer, Alt-copie, effacer + annuler, rogner")

        # Une image ouverte se réexporte à sa taille réelle (pas ×8)
        f.c["format"].definir("16 × 16")
        petite = os.path.join(dossier, "sprite.png")
        Image.fromarray(couleurs[rng.integers(0, 6, (16, 16))], "RGBA").save(petite)
        f.c["echelle"].definir(8)
        f.charger(petite)
        assert f.c["echelle"].valeur() == 1 and f.chemin_image == petite
        f.exporter(petite)
        with Image.open(petite) as im:
            assert im.size == (16, 16), im.size
        noter("réexport d'une image ouverte ok : reste en 16×16")
        f.close()
        noter("TOUT EST OK")
        return 0
    except Exception:
        noter("ÉCHEC\n" + traceback.format_exc())
        return 1


class Application(QApplication):
    """Sur macOS, un fichier ouvert depuis le Finder arrive par un événement, pas par sys.argv."""
    fenetre = None

    def event(self, e):
        if e.type() == e.Type.FileOpen and self.fenetre is not None and e.file():
            self.fenetre.charger(e.file())
            return True
        return super().event(e)


def main():
    if "--auto-test" in sys.argv:
        dossier = sys.argv[sys.argv.index("--auto-test") + 1]
        sys.exit(auto_test(dossier))
    if MAC:
        # Affiche « PixelShell » dans la barre de menu au lieu de « Python » (mode développement)
        try:
            from Foundation import NSBundle
            info = NSBundle.mainBundle().localizedInfoDictionary() or \
                NSBundle.mainBundle().infoDictionary()
            info["CFBundleName"] = NOM
        except Exception:
            pass
    if WINDOWS:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PixelShell.App")
        except Exception:
            pass
    app = Application(sys.argv)
    app.setApplicationName(NOM)
    app.setOrganizationName(NOM)
    app.setStyle("Fusion")
    t.charger_polices()
    app.setStyleSheet(t.feuille_de_style())
    icone = os.path.join(DOSSIER, "icone.png")
    if os.path.exists(icone):
        app.setWindowIcon(QIcon(icone))
    f = Fenetre()
    app.fenetre = f
    f.show()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        f.charger(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
