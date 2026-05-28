#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# build_macos.sh  —  Crea VirtualeDownloader.app con PyInstaller
# Uso:  chmod +x build_macos.sh && ./build_macos.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

echo ""
echo "📦  Virtuale Downloader — build macOS .app"
echo "────────────────────────────────────────────"

# Attiva virtualenv se esiste
if [[ -f "venv/bin/activate" ]]; then
    echo "🐍  Attivazione virtualenv…"
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

# Installa PyInstaller se mancante
if ! command -v pyinstaller &> /dev/null; then
    echo "⬇️   Installazione PyInstaller…"
    pip install pyinstaller
fi

# Pulizia cartelle precedenti
echo "🧹  Pulizia build precedente…"
rm -rf build/ dist/

# Build
echo "🏗️   Build in corso (1-2 minuti)…"
pyinstaller VirtualeDownloader.spec --clean --noconfirm

echo ""
echo "✅  Build completata!"
echo ""
echo "   📁  App:    dist/VirtualeDownloader.app"
echo "   🚀  Apri:   open dist/VirtualeDownloader.app"
echo ""
echo "⚠️   Prima esecuzione su macOS:"
echo "   Se Gatekeeper blocca l'app, usa tasto destro → Apri → Apri"
echo ""
