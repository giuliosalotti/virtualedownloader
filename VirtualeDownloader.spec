# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — VirtualeDownloader macOS .app
Build: pyinstaller VirtualeDownloader.spec --clean --noconfirm
"""

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Includi la cartella templates nel bundle
        ('templates', 'templates'),
    ],
    hiddenimports=[
        # Flask e dipendenze a volte non vengono rilevate in automatico
        'flask',
        'jinja2',
        'jinja2.ext',
        'werkzeug',
        'werkzeug.serving',
        'werkzeug.routing',
        'werkzeug.middleware.proxy_fix',
        'bs4',
        'requests',
        'certifi',
        'urllib3',
        'charset_normalizer',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL', 'PyQt5', 'wx'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VirtualeDownloader',
    debug=False,
    strip=False,
    upx=False,
    console=False,          # nessuna finestra terminale su macOS
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='VirtualeDownloader',
)

app = BUNDLE(
    coll,
    name='VirtualeDownloader.app',
    icon=None,              # sostituisci con 'icon.icns' per un'icona personalizzata
    bundle_identifier='com.giuliosalotti.virtualedownloader',
    info_plist={
        'CFBundleName':             'Virtuale Downloader',
        'CFBundleDisplayName':      'Virtuale Downloader',
        'CFBundleVersion':          '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable':  True,
        'NSRequiresAquaSystemAppearance': False,  # supporta dark mode
    },
)
