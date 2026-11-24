#!/bin/bash
# Ajoute PixelShell au menu des applications (à lancer une fois, depuis ce dossier).
set -e
ICI="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.local/share/applications ~/.local/share/icons
cp "$ICI/icone.png" ~/.local/share/icons/pixelshell.png
cat > ~/.local/share/applications/pixelshell.desktop <<FIN
[Desktop Entry]
Type=Application
Name=PixelShell
Comment=Éditeur de pixel art : sprites, tuiles et animations
Exec="$ICI/PixelShell" %f
Icon=pixelshell
Terminal=false
Categories=Graphics;2DGraphics;
FIN
echo "🐚 C'est bon, PixelShell est dans ton menu d'applications."
