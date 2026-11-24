# Recette PyInstaller : transforme le code Python en application autonome.
#   pyinstaller pixelshell.spec
# Résultat dans dist/ : « PixelShell.app » (macOS), dossier PixelShell avec PixelShell.exe
# (Windows) ou l'exécutable PixelShell (Linux). Python et Qt sont inclus.
import sys

MAC = sys.platform == "darwin"
WINDOWS = sys.platform.startswith("win")
VERSION = "1.0.0"

a = Analysis(
    ["app.py"],
    # La police pixel des titres (Silkscreen, licence OFL) voyage avec sa licence
    datas=[("icone.png", "."), ("polices/*.ttf", "polices"), ("polices/OFL-Silkscreen.txt", "polices")],
    hiddenimports=["PySide6.QtSvg"],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "IPython", "numba", "PySide6.QtNetwork",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtWebEngineCore"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PixelShell",
    console=False,          # pas de fenêtre de terminal
    icon="icone.icns" if MAC else ("icone.ico" if WINDOWS else None),
    target_arch=None,
)

coll = COLLECT(exe, a.binaries, a.datas, name="PixelShell")

if MAC:
    app = BUNDLE(
        coll,
        name="PixelShell.app",
        icon="icone.icns",
        bundle_identifier="io.github.saturnes00.pixelshell",
        version=VERSION,
        info_plist={
            "CFBundleName": "PixelShell",
            "CFBundleDisplayName": "PixelShell",
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            # Double-cliquer un .pxshell dans le Finder l'ouvre dans PixelShell
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Projet PixelShell",
                "CFBundleTypeExtensions": ["pxshell"],
                "CFBundleTypeRole": "Editor",
            }],
        },
    )
