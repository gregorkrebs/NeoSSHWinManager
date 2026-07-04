# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('src', 'src'), ('assets', 'assets')],
    hiddenimports=[
        'PyQt6.sip',
        'win32api', 'win32con', 'winreg',
        'keyring', 'keyring.backends.Windows',
        'webview', 'webview.platforms.winforms', 'webview.platforms.edgechromium',
        'clr', 'clr_loader',
        'comtypes', 'comtypes.client',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebChannel',
        'tkinter', 'unittest', 'email', 'http', 'xml', 'xmlrpc',
        'pydoc', 'doctest', 'difflib',
        '_pytest', 'pytest',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NeoSSHWinManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=['vcruntime140.dll', 'python3*.dll', 'Qt6Core.dll', 'Qt6Gui.dll'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='file_version_info.txt',
    icon=['assets\\app_icon.ico'],
)
