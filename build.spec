# build.spec — PyInstaller spec for the Stock Analysis & Backtesting Dashboard.
#
#   pip install pyinstaller
#   pyinstaller build.spec
#
# Output: dist/StockDashboard/StockDashboard.exe  (onedir build).
#
# Why onedir (not onefile): onefile unpacks to a temp dir on every launch, which
# is slow and trips DLL-loading libraries like pythonnet. onedir is faster and
# easier to debug. The Edge WebView2 runtime is NOT bundled — it ships with
# Windows 11; on older machines install it from Microsoft.
#
# Troubleshooting a build:
#   * Set console=True (below) to see Python tracebacks in a terminal window.
#   * If a module is "not found" at runtime, add it to hiddenimports or add the
#     package to the collect_all loop.

from PyInstaller.utils.hooks import collect_all

datas = [('ui/web', 'ui/web')]      # bundle the HTML/CSS/JS + vendored chart lib
binaries = []
hiddenimports = [
    'config',
    'ui', 'ui.api', 'ui.server', 'ui.format',
    'data', 'data.repository', 'data.cache', 'data.provider', 'data.yfinance_provider',
    'analysis', 'analysis.indicators', 'analysis.statistics', 'analysis.backtest',
]

# Packages that need their data files / submodules / binaries pulled in explicitly.
# (pywebview's Windows backend pulls in pythonnet + clr_loader; yfinance pulls in
# curl_cffi which has native binaries.)
for pkg in ['webview', 'clr_loader', 'pythonnet', 'yfinance', 'curl_cffi',
            'backtesting', 'bokeh', 'multitasking', 'peewee']:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'pytest', 'matplotlib'],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StockDashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,        # GUI app: no console window. Set True to debug.
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='StockDashboard',
)
