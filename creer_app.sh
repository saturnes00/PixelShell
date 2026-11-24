#!/bin/bash
# Mode développement (macOS) : crée « PixelShell.app » dans ~/Applications, qui lance
# directement le code de ce dossier (tes modifications sont prises en compte tout de suite).
# À relancer si tu déplaces le dossier PixelShell.
# Pour une app autonome à partager : pyinstaller pixelshell.spec (voir README).
set -e
cd "$(dirname "$0")"
DOSSIER="$(pwd)"
APP="$HOME/Applications/PixelShell.app"
# Python du venv s'il existe, sinon celui du système
PY="$DOSSIER/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

# 1. Icônes (png, ico, icns)
"$PY" outils/icones.py

# 2. Le paquet .app : un simple dossier avec une structure précise
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp icone.icns "$APP/Contents/Resources/icone.icns"
cat > "$APP/Contents/Info.plist" <<FIN
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>PixelShell</string>
  <key>CFBundleDisplayName</key><string>PixelShell</string>
  <key>CFBundleIdentifier</key><string>local.pixelshell</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleExecutable</key><string>PixelShell</string>
  <key>CFBundleIconFile</key><string>icone</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
</dict>
</plist>
FIN
# Sur Apple Silicon, on force arm64 : lancé depuis le Finder, un Python « universel »
# peut sinon démarrer en mode Intel (Rosetta) et ne plus trouver numpy.
ARCH=""
[ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ] && ARCH="arch -arm64"
cat > "$APP/Contents/MacOS/PixelShell" <<FIN
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
exec $ARCH "$PY" "$DOSSIER/app.py" "\$@" 2>>"$DOSSIER/erreurs.log"
FIN
chmod +x "$APP/Contents/MacOS/PixelShell"
touch "$APP"
echo "🐚 Application créée : $APP"
