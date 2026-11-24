"""
PixelShell — composants du panneau de réglages.

Repris de Crunch Crab (même look, même comportement) :
  - Glissiere   : curseur dessiné comme un bargraphe (VU-mètre de table de mixage)
  - Curseur     : nom + valeur + glissière + petite phrase d'explication
  - Interrupteur, Liste : idem pour un oui/non et une liste de choix
  - Section     : bloc repliable numéroté, avec un voyant quand il est modifié

Propres à PixelShell :
  - BoiteOutils : la grille des outils de dessin (crayon, gomme, pot…)
  - Nuancier    : la palette ; un clic choisit la couleur, clic droit pour la modifier
  - Pastilles   : couleur principale / secondaire, l'une sur l'autre
  - BandeImages : les images de l'animation, en miniatures
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from PySide6.QtWidgets import (QAbstractButton, QColorDialog, QComboBox, QGridLayout, QHBoxLayout,
                               QLabel, QMenu, QPushButton, QSlider, QSizePolicy, QSpinBox,
                               QVBoxLayout, QWidget)

import theme as t

MARGE = 18  # marge intérieure gauche/droite du panneau


def _etiquette_aide(texte):
    aide = QLabel(texte)
    aide.setObjectName("aide")
    aide.setWordWrap(True)
    return aide


# ---------------------------------------------------------------------------
# Glissière en bargraphe
# ---------------------------------------------------------------------------

class Glissiere(QSlider):
    """Un QSlider (clavier, accessibilité, signaux) redessiné en rangée de petites barres.

    - Les réglages à deux sens (ex. -100 → 100) se remplissent depuis le centre.
    - Un clic place directement la valeur ; double-clic : valeur de départ.
    - La molette fait défiler le panneau au lieu de changer la valeur par accident
      (sauf si le curseur a été cliqué juste avant).
    """
    doubleClic = Signal()

    LARGEUR_BARRE = 3
    ECART = 2

    def __init__(self, mini, maxi, defaut, neutre=None):
        super().__init__(Qt.Orientation.Horizontal)
        self.setRange(mini, maxi)
        self.setValue(defaut)
        self.defaut = defaut
        # Point d'où part le remplissage : la valeur « sans effet » (0, ou 100 % pour un gamma…)
        self.origine = neutre if neutre is not None else (0 if mini < 0 < maxi else mini)
        self.setFixedHeight(20)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._survol = False

    def _ratio(self, v):
        etendue = max(1, self.maximum() - self.minimum())
        return (v - self.minimum()) / etendue

    def _zone(self):
        return QRectF(6, 0, self.width() - 12, self.height())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        zone = self._zone()
        pas = self.LARGEUR_BARRE + self.ECART
        n = max(2, int((zone.width() + self.ECART) // pas))
        debut = zone.left() + (zone.width() - (n * pas - self.ECART)) / 2
        r_val, r_orig = self._ratio(self.value()), self._ratio(self.origine)
        bas, haut = sorted((r_orig, r_val))
        actif = self.isEnabled()
        eteinte = QColor(t.BORD_FORT)
        # À sa valeur de départ, le réglage reste gris : seul ce qu'on a touché s'allume
        au_repos = self.value() == self.defaut
        grise = QColor(t.TRES_DISCRET)
        cy = zone.center().y()
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            pos = i / (n - 1)
            allumee = actif and bas - 1e-9 <= pos <= haut + 1e-9 and r_val != r_orig
            # Les barres grandissent un peu vers la valeur, comme un VU-mètre
            h = 10 if allumee else 6
            p.setBrush((grise if au_repos else t.couleur_degrade(pos)) if allumee else eteinte)
            p.drawRoundedRect(QRectF(debut + i * pas, cy - h / 2, self.LARGEUR_BARRE, h), 1, 1)
        # Repère de la valeur de départ (petit point sous la rangée)
        x0 = zone.left() + self._ratio(self.defaut) * zone.width()
        p.setBrush(QColor(t.TRES_DISCRET))
        p.drawEllipse(QPointF(x0, cy + 8), 1.2, 1.2)
        # Poignée : un trait vertical clair, souligné d'accent au survol
        x = zone.left() + r_val * zone.width()
        if self._survol or self.isSliderDown():
            p.setBrush(QColor(255, 91, 58, 70))
            p.drawRoundedRect(QRectF(x - 5, cy - 10, 10, 20), 4, 4)
        p.setBrush(QColor(t.TEXTE) if actif else QColor(t.TRES_DISCRET))
        p.drawRoundedRect(QRectF(x - 2, cy - 8, 4, 16), 2, 2)

    def _valeur_en(self, x):
        zone = self._zone()
        r = min(1.0, max(0.0, (x - zone.left()) / max(1.0, zone.width())))
        return round(self.minimum() + r * (self.maximum() - self.minimum()))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self.setValue(self._valeur_en(e.position().x()))
            e.accept()

    def mouseMoveEvent(self, e):
        if self.isSliderDown():
            self.setValue(self._valeur_en(e.position().x()))

    def mouseReleaseEvent(self, _):
        self.setSliderDown(False)
        self.update()

    def mouseDoubleClickEvent(self, _):
        self.setValue(self.defaut)
        self.doubleClic.emit()

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()

    def enterEvent(self, _):
        self._survol = True
        self.update()

    def leaveEvent(self, _):
        self._survol = False
        self.update()


# ---------------------------------------------------------------------------
# Lignes de réglage
# ---------------------------------------------------------------------------

class Curseur(QWidget):
    change = Signal()

    def __init__(self, nom, mini, maxi, defaut, suffixe="", aide="", neutre=None):
        super().__init__()
        self.defaut = defaut
        self.suffixe = suffixe
        lay = QVBoxLayout(self)
        lay.setContentsMargins(MARGE, 6, MARGE, 6)
        lay.setSpacing(4)
        self.haut = QHBoxLayout()
        self.haut.setSpacing(6)
        self.etiquette = QLabel(nom)
        self.etiquette.setObjectName("etiquette")
        self.etiquette.setToolTip("Double-clic pour revenir à la valeur de départ")
        self.val = QLabel()
        self.val.setObjectName("valeur")
        self.haut.addWidget(self.etiquette)
        self.haut.addStretch()
        self.haut.addWidget(self.val)
        self.slider = Glissiere(mini, maxi, defaut, neutre)
        self.slider.valueChanged.connect(self._maj)
        lay.addLayout(self.haut)
        lay.addWidget(self.slider)
        if aide:
            lay.addWidget(_etiquette_aide(aide))
        self._modifie = None
        self._maj()

    def _maj(self):
        v = self.slider.value()
        self.val.setText(f"{v}{self.suffixe}")
        modifie = v != self.defaut
        if modifie != self._modifie:  # on ne repolit le style que si l'état change
            self._modifie = modifie
            self.val.setProperty("modifie", modifie)
            self.val.style().unpolish(self.val)
            self.val.style().polish(self.val)
        self.change.emit()

    def mouseDoubleClickEvent(self, _):
        self.slider.setValue(self.defaut)

    def valeur(self):
        return self.slider.value()

    def definir(self, v):
        self.slider.setValue(int(v))


class Bascule(QAbstractButton):
    """Interrupteur dessiné : pastille qui glisse, fond en dégradé quand c'est activé."""

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setFixedSize(34, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 0.0
        self._anim = QVariantAnimation(self, duration=140)
        self._anim.valueChanged.connect(self._bouger)
        self.toggled.connect(self._animer)

    def _bouger(self, v):
        self._pos = float(v)
        self.update()

    def _animer(self, coche):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if coche else 0.0)
        self._anim.start()

    def placer(self, coche):
        """Change l'état sans animation (chargement d'un style)."""
        self.blockSignals(True)
        self.setChecked(coche)
        self.blockSignals(False)
        self._anim.stop()
        self._pos = 1.0 if coche else 0.0
        self.update()

    def sizeHint(self):
        return QSize(34, 20)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(QColor(t.BORD_FORT), 1))
        p.setBrush(QColor(t.CHAMP))
        p.drawRoundedRect(r, 10, 10)
        if self._pos > 0:
            p.setOpacity(self._pos)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(t.degrade(r))
            p.drawRoundedRect(r, 10, 10)
            p.setOpacity(1)
        x = 3 + self._pos * (self.width() - 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.TEXTE) if self._pos > 0.5 else QColor(t.DISCRET))
        p.drawEllipse(QRectF(x, 3, 14, 14))


class Interrupteur(QWidget):
    change = Signal()

    def __init__(self, nom, defaut, aide=""):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(MARGE, 7, MARGE, 7)
        lay.setSpacing(3)
        ligne = QHBoxLayout()
        etiquette = QLabel(nom)
        etiquette.setObjectName("etiquette")
        self.case = Bascule()
        self.case.placer(defaut)
        self.case.toggled.connect(lambda _: self.change.emit())
        ligne.addWidget(etiquette)
        ligne.addStretch()
        ligne.addWidget(self.case)
        lay.addLayout(ligne)
        if aide:
            lay.addWidget(_etiquette_aide(aide))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        # Toute la ligne est cliquable, pas seulement l'interrupteur
        if e.button() == Qt.MouseButton.LeftButton:
            self.case.toggle()

    def valeur(self):
        return self.case.isChecked()

    def definir(self, v):
        if bool(v) != self.case.isChecked():
            self.case.placer(bool(v))
            self.change.emit()


class Liste(QWidget):
    """Liste de choix, avec des flèches ‹ › pour passer d'un choix à l'autre."""
    change = Signal()

    def __init__(self, nom, choix, aide="", fleches=False):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(MARGE, 6, MARGE, 6)
        lay.setSpacing(5)
        if nom:
            e = QLabel(nom)
            e.setObjectName("etiquette")
            lay.addWidget(e)
        ligne = QHBoxLayout()
        ligne.setSpacing(6)
        self.combo = QComboBox()
        self.combo.addItems(choix)
        self.combo.setMaxVisibleItems(25)
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo.currentTextChanged.connect(lambda _: self.change.emit())
        ligne.addWidget(self.combo, 1)
        if fleches:
            for nom_icone, pas, bulle in (("gauche", -1, "Choix précédent"), ("droite", 1, "Choix suivant")):
                b = QPushButton()
                b.setObjectName("fleche")
                b.setIcon(t.icone(nom_icone, t.DISCRET, 14))
                b.setToolTip(bulle)
                b.setFixedHeight(30)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _=False, pas=pas: self.decaler(pas))
                ligne.addWidget(b)
        lay.addLayout(ligne)
        if aide:
            lay.addWidget(_etiquette_aide(aide))

    def decaler(self, pas):
        n = self.combo.count()
        self.combo.setCurrentIndex((self.combo.currentIndex() + pas) % n)

    def valeur(self):
        return self.combo.currentText()

    def definir(self, v):
        self.combo.setCurrentText(v)


# ---------------------------------------------------------------------------
# Section repliable
# ---------------------------------------------------------------------------

class _EnTete(QWidget):
    """Ligne de titre d'une section : numéro, titre en police pixel, voyant, chevron."""
    clic = Signal()

    def __init__(self, numero, titre):
        super().__init__()
        self.numero = f"{numero:02d}"
        self.titre = titre.upper()
        self.ouvert = False
        self.modifiee = False
        self._survol = False
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2
        p.setFont(t.police_pixel(8))
        p.setPen(QColor(t.TRES_DISCRET))
        p.drawText(QRectF(MARGE, 0, 30, self.height()), Qt.AlignmentFlag.AlignVCenter, self.numero)
        p.setFont(t.police_pixel(16))
        p.setPen(QColor(t.ACCENT_CLAIR if self._survol else t.TEXTE))
        largeur = p.fontMetrics().horizontalAdvance(self.titre)
        p.drawText(QRectF(MARGE + 24, 0, largeur + 4, self.height()), Qt.AlignmentFlag.AlignVCenter,
                   self.titre)
        t.point_lumineux(p, QPointF(MARGE + 24 + largeur + 12, cy), 3, t.ACCENT, self.modifiee)
        pix = t.pixmap_icone("bas" if self.ouvert else "droite", t.DISCRET, 14)
        p.drawPixmap(QPointF(self.width() - 22, cy - 7), pix)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clic.emit()

    def enterEvent(self, _):
        self._survol = True
        self.update()

    def leaveEvent(self, _):
        self._survol = False
        self.update()


class Section(QWidget):
    """Bloc repliable : un titre numéroté, une phrase d'explication, un bouton de remise à zéro."""
    _compteur = 0

    def __init__(self, titre, sous_titre, ouvert=False, reinit=None):
        super().__init__()
        Section._compteur += 1
        self.titre = titre
        self.cles = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        trait = QWidget()
        trait.setFixedHeight(1)
        trait.setStyleSheet(f"background: {t.BORD};")
        lay.addWidget(trait)
        tete = QHBoxLayout()
        tete.setContentsMargins(0, 0, MARGE - 8 if reinit else 0, 0)
        tete.setSpacing(2)
        self.entete = _EnTete(Section._compteur, titre)
        self.entete.clic.connect(self.basculer)
        tete.addWidget(self.entete, 1)
        if reinit:
            b = QPushButton()
            b.setObjectName("reinit")
            b.setIcon(t.icone("reinit", t.TRES_DISCRET, 14))
            b.setToolTip("Remettre cette section à zéro")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda: reinit(self))
            tete.addWidget(b)
        lay.addLayout(tete)
        self.corps = QWidget()
        self.corps_lay = QVBoxLayout(self.corps)
        self.corps_lay.setContentsMargins(0, 0, 0, 10)
        self.corps_lay.setSpacing(0)
        st = QLabel(sous_titre)
        st.setObjectName("sousTitre")
        st.setWordWrap(True)
        self.corps_lay.addWidget(st)
        lay.addWidget(self.corps)
        self.corps.setVisible(ouvert)
        self.entete.ouvert = ouvert
        self.modifiee = False

    def marquer(self, modifiee):
        if modifiee != self.modifiee:
            self.modifiee = modifiee
            self.entete.modifiee = modifiee
            self.entete.update()

    def basculer(self):
        self.corps.setVisible(not self.corps.isVisible())
        self.entete.ouvert = self.corps.isVisible()
        self.entete.update()

    def ajouter(self, w, cle=None):
        self.corps_lay.addWidget(w)
        if cle:
            self.cles.append(cle)
        return w



# ---------------------------------------------------------------------------
# Boîte à outils
# ---------------------------------------------------------------------------

OUTILS = [  # (clé, nom, icône, raccourci, explication)
    ("selection", "Sélection", "selection", "S",
     "Glisse pour choisir une zone, puis glisse dedans pour la bouger (Alt : en copie). "
     "Copier, couper, coller, Suppr. Échap : désélectionner."),
    ("crayon", "Crayon", "crayon", "B", "Pose des pixels. Clic droit : couleur secondaire."),
    ("gomme", "Gomme", "gomme", "E", "Rend les pixels transparents."),
    ("pot", "Pot de peinture", "pot", "F", "Remplit une zone d'une même couleur."),
    ("pipette", "Pipette", "pipette", "I", "Prend la couleur d'un pixel. Astuce : Alt avec n'importe quel outil."),
    ("ligne", "Ligne", "ligne", "L", "Glisse pour tracer. Maj : angles de 45°."),
    ("rectangle", "Rectangle", "rectangle", "R", "Glisse pour tracer. Maj : un carré."),
    ("ellipse", "Ellipse", "ellipse", "O", "Glisse pour tracer. Maj : un cercle."),
    ("deplacer", "Déplacer", "deplacer", "M", "Fait glisser tout le dessin (il revient de l'autre côté)."),
]


class BoutonOutil(QAbstractButton):
    """Une case de la boîte à outils : icône, et la lettre du raccourci dans le coin."""

    def __init__(self, nom_icone, lettre):
        super().__init__()
        self.nom_icone = nom_icone
        self.lettre = lettre
        self._survol = False
        self.setCheckable(True)
        self.setFixedSize(QSize(57, 46))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        if self.isChecked():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(t.degrade(r))
        else:
            p.setPen(QPen(QColor(t.BORD_FORT if self._survol else t.BORD), 1))
            p.setBrush(QColor(t.CHAMP_SURVOL if self._survol else t.CHAMP))
        p.drawRoundedRect(r, 10, 10)
        couleur = t.ENCRE if self.isChecked() else (t.TEXTE if self._survol else t.DISCRET)
        p.drawPixmap(QPointF(self.width() / 2 - 10, self.height() / 2 - 10),
                     t.pixmap_icone(self.nom_icone, couleur, 20))
        p.setFont(t.police_pixel(8))
        p.setPen(QColor(t.ENCRE if self.isChecked() else t.TRES_DISCRET))
        p.drawText(QRectF(0, 3, self.width() - 6, 12), Qt.AlignmentFlag.AlignRight, self.lettre)

    def enterEvent(self, _):
        self._survol = True
        self.update()

    def leaveEvent(self, _):
        self._survol = False
        self.update()


class Nombre(QWidget):
    """Un nombre qu'on tape au clavier (les flèches ↑ ↓ marchent aussi, Maj = par 10).
    Pour les grandes plages (1 → 2048 px), plus précis qu'un curseur."""
    change = Signal()

    def __init__(self, nom, mini, maxi, defaut, suffixe="", aide=""):
        super().__init__()
        self.defaut = defaut
        lay = QVBoxLayout(self)
        lay.setContentsMargins(MARGE, 5, MARGE, 5)
        lay.setSpacing(3)
        ligne = QHBoxLayout()
        etiquette = QLabel(nom)
        etiquette.setObjectName("etiquette")
        self.champ = QSpinBox()
        self.champ.setRange(mini, maxi)
        self.champ.setValue(defaut)
        self.champ.setSuffix(suffixe)
        self.champ.setFixedWidth(96)
        self.champ.setAlignment(Qt.AlignmentFlag.AlignRight)
        # Le changement n'est appliqué qu'à Entrée (ou en quittant le champ), pas à chaque chiffre
        self.champ.setKeyboardTracking(False)
        self.champ.valueChanged.connect(lambda _: self.change.emit())
        ligne.addWidget(etiquette)
        ligne.addStretch()
        ligne.addWidget(self.champ)
        lay.addLayout(ligne)
        if aide:
            lay.addWidget(_etiquette_aide(aide))

    def valeur(self):
        return self.champ.value()

    def definir(self, v):
        self.champ.setValue(int(v))


class BoiteOutils(QWidget):
    change = Signal(str)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(MARGE, 6, MARGE, 6)
        lay.setSpacing(8)
        # La grille vit dans un bloc de hauteur fixe : sinon le texte d'aide en dessous,
        # qui change de longueur selon l'outil, écrase la 2e rangée de boutons
        bloc = QWidget()
        grille = QGridLayout(bloc)
        grille.setContentsMargins(0, 0, 0, 0)
        grille.setSpacing(6)
        self.boutons = {}
        for i, (cle, nom, ic, lettre, aide) in enumerate(OUTILS):
            b = BoutonOutil(ic, lettre)
            b.setToolTip(f"{nom} ({lettre})\n{aide}")
            b.clicked.connect(lambda _=False, cle=cle: self.definir(cle))
            grille.addWidget(b, i // 5, i % 5)
            self.boutons[cle] = b
        lignes = -(-len(OUTILS) // 5)
        bloc.setFixedHeight(lignes * 46 + (lignes - 1) * 6)
        lay.addWidget(bloc)
        self.aide = _etiquette_aide("")
        # Hauteur réservée pour 3 lignes : Qt calcule mal la hauteur d'un texte qui passe à la
        # ligne dans une zone qui défile, et les boutons du dessus se faisaient écraser
        self.aide.setFixedHeight(self.aide.fontMetrics().lineSpacing() * 3 + 4)
        self.aide.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.aide)
        self.outil = None
        self.definir("crayon")

    def definir(self, cle):
        for c, b in self.boutons.items():
            b.setChecked(c == cle)
        if cle != self.outil:
            self.outil = cle
            nom, aide = next((o[1], o[4]) for o in OUTILS if o[0] == cle)
            self.aide.setText(f"{nom} : {aide}")
            self.change.emit(cle)

    def valeur(self):
        return self.outil


# ---------------------------------------------------------------------------
# Couleurs
# ---------------------------------------------------------------------------

class Pastilles(QWidget):
    """Couleur principale (clic gauche) posée sur la secondaire (clic droit).
    Clic : choisir une couleur ; la petite flèche les échange (X)."""
    echange = Signal()
    demande = Signal(int)  # 0 = principale, 1 = secondaire

    def __init__(self):
        super().__init__()
        self.couleurs = ["#000000", "#ffffff"]
        self.setFixedSize(64, 54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Clic : changer la couleur · Flèche (X) : échanger principale / secondaire")

    def definir(self, principale, secondaire):
        self.couleurs = [principale, secondaire]
        self.update()

    def _carres(self):
        return QRectF(0.5, 0.5, 36, 36), QRectF(20.5, 16.5, 36, 36)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        avant, arriere = self._carres()
        for r, c in ((arriere, self.couleurs[1]), (avant, self.couleurs[0])):
            p.setPen(QPen(QColor(t.FOND), 3))
            p.setBrush(QColor(c))
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QPen(QColor(255, 255, 255, 50), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), 7, 7)
        p.drawPixmap(QPointF(44, 0), t.pixmap_icone("retablir", t.DISCRET, 14))

    def mousePressEvent(self, e):
        avant, arriere = self._carres()
        pos = e.position()
        if pos.x() > 40 and pos.y() < 16:
            self.echange.emit()
        elif avant.contains(pos):
            self.demande.emit(0)
        elif arriere.contains(pos):
            self.demande.emit(1)


class Nuancier(QWidget):
    """Les couleurs de la palette. Clic gauche : couleur principale ; clic droit : menu
    (prendre en secondaire, modifier, supprimer). La couleur choisie est entourée."""
    choisi = Signal(str, int)       # couleur, 0 = principale / 1 = secondaire
    modifie = Signal(list)          # nouvelle liste de couleurs
    remplace = Signal(str, str)     # ancienne, nouvelle (pour recolorer le dessin)

    COTE = 26

    def __init__(self):
        super().__init__()
        self.couleurs = []
        self.actives = ("", "")
        self.grille = QGridLayout(self)
        self.grille.setContentsMargins(MARGE, 6, MARGE, 6)
        self.grille.setSpacing(6)
        self.boutons = []

    def definir(self, couleurs, actives=None):
        if actives is not None:
            self.actives = actives
        if list(couleurs) != self.couleurs or not self.grille.count():
            self._reconstruire(couleurs)
        for c, b in zip(self.couleurs, self.boutons):
            self._habiller(b, c)

    def _habiller(self, b, c):
        if c.lower() == self.actives[0].lower():
            bord = f"2px solid {t.TEXTE}"
        elif c.lower() == self.actives[1].lower():
            bord = f"2px dashed {t.DISCRET}"
        else:
            bord = "1px solid rgba(255,255,255,40)"
        b.setStyleSheet(f"background: {c}; border-radius: 7px; padding: 0; border: {bord};")

    def _reconstruire(self, couleurs):
        self.couleurs = list(couleurs)
        while self.grille.count():
            w = self.grille.takeAt(0).widget()
            w.hide()
            w.deleteLater()
        self.boutons = []
        par_ligne = 9
        for i, c in enumerate(self.couleurs + ["+"]):
            b = QPushButton()
            b.setFixedSize(self.COTE, self.COTE)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if c == "+":
                b.setIcon(t.icone("plus", t.DISCRET, 12))
                b.setToolTip("Ajouter une couleur")
                b.setStyleSheet(f"border-radius: 7px; border: 1px dashed {t.BORD_FORT};"
                                "background: transparent; padding: 0;")
                b.clicked.connect(self._ajouter)
                b.setEnabled(len(self.couleurs) < 256)
            else:
                b.setToolTip(f"{c}\nClic : couleur principale · Clic droit : plus d'options")
                b.clicked.connect(lambda _=False, c=c: self.choisi.emit(c, 0))
                b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                b.customContextMenuRequested.connect(lambda _p, i=i, b=b: self._menu(i, b))
                self.boutons.append(b)
            self.grille.addWidget(b, i // par_ligne, i % par_ligne)
        self.grille.setColumnStretch(par_ligne, 1)

    def _menu(self, i, bouton):
        c = self.couleurs[i]
        m = QMenu(self)
        m.addAction("Prendre en couleur secondaire", lambda: self.choisi.emit(c, 1))
        m.addAction("Modifier (et recolorer le dessin)…", lambda: self._editer(i))
        a = m.addAction("Retirer de la palette", lambda: self.modifie.emit(
            self.couleurs[:i] + self.couleurs[i + 1:]))
        a.setEnabled(len(self.couleurs) > 1)
        m.exec(bouton.mapToGlobal(bouton.rect().bottomLeft()))

    def _editer(self, i):
        ancienne = self.couleurs[i]
        c = QColorDialog.getColor(QColor(ancienne), self, "Modifier la couleur")
        if c.isValid() and c.name() != ancienne:
            self.remplace.emit(ancienne, c.name())

    def _ajouter(self):
        c = QColorDialog.getColor(QColor(self.actives[0] or "#ffffff"), self, "Nouvelle couleur")
        if c.isValid() and c.name() not in self.couleurs:
            self.modifie.emit(self.couleurs + [c.name()])
            self.choisi.emit(c.name(), 0)


# ---------------------------------------------------------------------------
# Images de l'animation
# ---------------------------------------------------------------------------

def damier(p, rect, case=4):
    """Le damier gris qui montre la transparence, dessiné sous les images."""
    p.save()
    p.setClipRect(rect)
    p.fillRect(rect, QColor("#2a2530"))
    clair = QColor("#38323f")
    y = 0
    while rect.top() + y < rect.bottom():
        x = (int(y / case) % 2) * case
        while rect.left() + x < rect.right():
            p.fillRect(QRectF(rect.left() + x, rect.top() + y, case, case), clair)
            x += case * 2
        y += case
    p.restore()


class VignetteImage(QAbstractButton):
    COTE = 64

    def __init__(self, numero):
        super().__init__()
        self.numero = numero
        self.image = None
        self.rapport = 1
        self.actif = False
        self._survol = False
        self.setFixedSize(self.COTE, self.COTE + 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cadre = QRectF(1, 1, self.COTE - 2, self.COTE - 2)
        chemin = QPainterPath()
        chemin.addRoundedRect(cadre, 9, 9)
        p.save()
        p.setClipPath(chemin)
        p.fillRect(cadre, QColor(t.CHAMP))
        if self.image is not None:
            w, h = self.image.width() * self.rapport, self.image.height()
            e = min((cadre.width() - 8) / w, (cadre.height() - 8) / h)
            cible = QRectF(0, 0, w * e, h * e)
            cible.moveCenter(cadre.center())
            damier(p, cible)
            p.drawImage(cible, self.image)
        p.restore()
        if self.actif:
            p.setPen(QPen(t.degrade(cadre), 2))
        else:
            p.setPen(QPen(QColor(t.BORD_FORT if self._survol else t.BORD), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(chemin)
        p.setFont(t.police_pixel(8))
        p.setPen(QColor(t.TEXTE if (self._survol or self.actif) else t.DISCRET))
        p.drawText(QRectF(0, self.COTE + 4, self.width(), 14), Qt.AlignmentFlag.AlignHCenter,
                   f"{self.numero:02d}")

    def enterEvent(self, _):
        self._survol = True
        self.update()

    def leaveEvent(self, _):
        self._survol = False
        self.update()


class BandeImages(QWidget):
    """Les images de l'animation, côte à côte, sur 3 par ligne."""
    choisi = Signal(int)

    def __init__(self):
        super().__init__()
        self.grille = QGridLayout(self)
        self.grille.setContentsMargins(MARGE, 4, MARGE, 8)
        self.grille.setHorizontalSpacing(8)
        self.grille.setVerticalSpacing(6)
        self.vignettes = []

    def definir(self, images, actif, rapport=1):
        """`images` : liste de QImage."""
        while len(self.vignettes) > len(images):
            v = self.vignettes.pop()
            self.grille.removeWidget(v)
            v.deleteLater()
        while len(self.vignettes) < len(images):
            i = len(self.vignettes)
            v = VignetteImage(i + 1)
            v.clicked.connect(lambda _=False, i=i: self.choisi.emit(i))
            self.grille.addWidget(v, i // 4, i % 4)
            self.vignettes.append(v)
        self.grille.setColumnStretch(4, 1)
        for i, (v, img) in enumerate(zip(self.vignettes, images)):
            v.image, v.actif, v.rapport = img, i == actif, rapport
            v.setToolTip(f"Image {i + 1}")
            v.update()
