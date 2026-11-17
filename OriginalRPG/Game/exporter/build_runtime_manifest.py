#!/usr/bin/env python3
"""Inventory an already built, staged native runtime (does not build Viper)."""
import argparse
import json
import re
from pathlib import Path
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('runtime', type=Path)
p.add_argument('--target', required=True, choices=['linux', 'windows'])
p.add_argument('--entrypoint', default=None)
p.add_argument('--python-version', help='Python major.minor used to build launcher/libviper, e.g. 3.10')
args = p.parse_args()
root = args.runtime.resolve()
entry = args.entrypoint or ('ViperEngine' if args.target == 'linux' else 'ViperEngine.exe')
if not root.is_dir() or not (root / entry).is_file() or not (root / 'python').is_dir():
    sys.exit('Stage the launcher, bundled Python 3.12, libviper, Manager/core, and platform dependencies first.')
paths = sorted(root.rglob('*'))
if any(p.is_symlink() for p in paths):
    sys.exit('Dereference staged runtime symlinks before creating its manifest (copy files with cp -L).')
files = [p.relative_to(root).as_posix() for p in paths if p.is_file() and p.name != 'runtime-manifest.json']
manifest = {'api_version': 1, 'target': args.target, 'entrypoint': entry, 'standalone': True, 'files': files}
version = args.python_version
if version is None:
    versions = {m.group(1) for file in files if (m := re.fullmatch(r'python/lib/python(3\.\d+)/encodings/__init__\.py', file))}
    if len(versions) == 1:
        version = versions.pop()
if version is not None:
    if not re.fullmatch(r'3\.\d+', version):
        sys.exit('--python-version must be major.minor, e.g. 3.10')
    manifest['python_version'] = version
(root / 'runtime-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(f'Inventoried {len(files)} runtime files. Verify loader dependencies and launch on a clean target machine before release.')
