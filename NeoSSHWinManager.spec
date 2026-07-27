# -*- mode: python ; coding: utf-8 -*-
import re

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('src', 'src'), ('assets', 'assets')],
    hiddenimports=[
        'PyQt6.sip',
        'win32api', 'win32con', 'winreg',
        'keyring', 'keyring.backends.Windows',
        # src/permission_repair.py's UAC relaunch (request_elevated_repair) —
        # PyInstaller's static analysis has a history of missing win32com's
        # compiled COM shell extension unless hinted explicitly.
        'win32com.shell', 'win32com.shell.shell', 'win32com.shell.shellcon',
        'win32event', 'win32process',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Only modules nothing pulls in at runtime: stdlib excludes like
        # 'email'/'http'/'xml' break urllib.request and save almost nothing
        # next to Qt WebEngine.
        'tkinter',
        '_pytest', 'pytest',
    ],
    noarchive=False,
    optimize=0,
)

# QtWebEngine (Chromium) ships debug-only resource variants and translations
# for ~50 locales we never use. In --onefile mode every one of these bytes is
# re-extracted to a fresh %TEMP%\_MEI... folder on every single app launch, so
# trimming this data cuts both the exe size and the startup extraction time.
_KEEP_QM_LANGS = {'en', 'de'}

def _keep_datafile(entry):
    dest = entry[0].replace('\\', '/').lower()
    if dest.endswith('.debug.pak') or dest.endswith('.debug.bin'):
        return False
    if '/qtwebengine_locales/' in dest:
        return dest.endswith('/en-us.pak') or dest.endswith('/de.pak')
    m = re.search(r'/qt(?:_help)?_([a-z]{2}(?:_[a-z]{2})?)\.qm$', dest)
    if m:
        return m.group(1) in _KEEP_QM_LANGS
    return True

a.datas = [d for d in a.datas if _keep_datafile(d)]

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
    strip=False,
    upx=False,
    upx_exclude=[],
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
