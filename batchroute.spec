# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

repo_root = Path(SPECPATH).resolve()

# Pre-collect data files and hidden imports so we can pass them directly to Analysis.
all_datas: list[tuple[str, str]] = []
all_binaries: list[tuple[str, str]] = []
all_hiddenimports = [
    "scapy.layers.all",
    "scapy.arch.linux",
    "scapy.arch.windows",
    "scapy.arch.bpf.core",
    "scapy.arch.common",
    "dns.versioned",
    "pandas._libs.tslibs.base",
]

for pkg in ("dash", "dash_cytoscape", "plotly", "pandas", "dns"):
    tmp_datas, tmp_binaries, tmp_hiddenimports = collect_all(pkg)
    all_datas.extend(tmp_datas)
    all_binaries.extend(tmp_binaries)
    all_hiddenimports.extend(tmp_hiddenimports)

# Explicitly bundle our custom visualizer assets so Dash can serve them.
asset_dir = repo_root / "visualizer" / "assets"
if asset_dir.exists():
    for f in asset_dir.rglob("*"):
        if f.is_file():
            dest = str(f.parent.relative_to(repo_root))
            all_datas.append((str(f), dest))

block_cipher = None

a = Analysis(
    [str(repo_root / "src" / "main.py")],
    pathex=[str(repo_root)],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="batchroute",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="batchroute",
)
