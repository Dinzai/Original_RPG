"""Native payload validation shared by inventory, assembly, and export."""
import hashlib
import json
import os
from pathlib import Path
import re
import struct

API_VERSION = 1


def safe_path(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError(f'Invalid runtime relative path: {value!r}')
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or path.as_posix() == '.':
        raise ValueError(f'Runtime path escapes payload: {value!r}')
    return path.as_posix()


def binary_info(path):
    with Path(path).open('rb') as stream:
        header = stream.read(64)
        if header[:4] == b'\x7fELF':
            if len(header) < 20 or header[5] not in (1, 2):
                raise ValueError(f'Invalid ELF: {path}')
            endian = '<' if header[5] == 1 else '>'
            machine = struct.unpack_from(endian + 'H', header, 18)[0]
            return 'linux', {62: 'x86_64', 183: 'arm64'}.get(machine, f'elf-{machine}')
        if header[:2] == b'MZ' and len(header) >= 64:
            stream.seek(struct.unpack_from('<I', header, 60)[0])
            pe = stream.read(6)
            if pe[:4] != b'PE\0\0':
                raise ValueError(f'Invalid PE: {path}')
            machine = struct.unpack_from('<H', pe, 4)[0]
            return 'windows', {0x8664: 'x86_64', 0xaa64: 'arm64', 0x14c: 'x86'}.get(machine, f'pe-{machine}')
    raise ValueError(f'Not an ELF/PE binary: {path}')


def inventory(root, target, entrypoint=None, python_version=None):
    root = Path(root).resolve()
    entrypoint = safe_path(entrypoint or ('ViperEngine' if target == 'linux' else 'ViperEngine.exe'))
    paths = sorted(root.rglob('*'))
    if any(p.is_symlink() for p in paths):
        raise ValueError('Runtime payload must contain dereferenced files, not symlinks')
    files = [p.relative_to(root).as_posix() for p in paths if p.is_file() and p.name != 'runtime-manifest.json' and '__pycache__' not in p.parts]
    versions = {m.group(1) for file in files if (m := re.fullmatch(r'python/lib/python(3\.\d+)/encodings/__init__\.py', file))}
    if python_version is None:
        if target == 'linux' and len(versions) == 1:
            python_version = versions.pop()
        else:
            raise ValueError('Supply --python-version matching the launcher and libviper ABI')
    manifest = {'api_version': API_VERSION, 'target': target, 'entrypoint': entrypoint,
                'standalone': True, 'python_version': python_version, 'files': files,
                'sha256': {file: hashlib.sha256((root / file).read_bytes()).hexdigest() for file in files}}
    _, manifest['architecture'] = binary_info(root / entrypoint)
    validate(root, manifest, target)
    return manifest


def validate(root, manifest, target):
    root = Path(root).resolve()
    if manifest.get('target') != target or manifest.get('api_version') != API_VERSION or manifest.get('standalone') is not True:
        raise ValueError('Runtime target/API/standalone flag does not match export')
    version = manifest.get('python_version')
    if not isinstance(version, str) or not re.fullmatch(r'3\.\d+', version):
        raise ValueError('Runtime python_version must be major.minor')
    files = manifest.get('files')
    if not isinstance(files, list) or not all(isinstance(p, str) for p in files) or len(files) != len(set(files)):
        raise ValueError('Runtime files must be a unique array of paths')
    payload = {}
    for file in files:
        rel = safe_path(file)
        path = root / rel
        if any(p.is_symlink() for p in [path, *path.parents] if p != root) or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError(f'Missing or unsafe runtime file: {rel}')
        payload[rel] = path
    entry = safe_path(manifest.get('entrypoint'))
    if entry not in payload:
        raise ValueError('Runtime entrypoint must be listed')
    platform, arch = binary_info(payload[entry])
    if platform != target or manifest.get('architecture', arch) != arch:
        raise ValueError('Runtime executable target/architecture mismatch')
    if target == 'linux' and not os.access(payload[entry], os.X_OK):
        raise ValueError('Linux entrypoint must be executable')
    suffix = '.so' if target == 'linux' else '.pyd'
    modules = [file for file in files if Path(file).name.startswith('libviper') and file.endswith(suffix)]
    if not modules or not any('/' not in file for file in modules):
        raise ValueError('Runtime requires libviper module beside its launcher')
    for file in modules:
        if binary_info(payload[file]) != (target, arch):
            raise ValueError('libviper target/architecture differs from launcher')
        tagged = re.search(r'(?:cpython-|cp)(\d{2,3})', Path(file).name)
        if tagged and tagged.group(1) != version.replace('.', ''):
            raise ValueError('libviper Python ABI tag differs from python_version')
    encodings = f'python/lib/python{version}/encodings/__init__.py' if target == 'linux' else 'python/Lib/encodings/__init__.py'
    if encodings not in payload and encodings[:-3] + '.pyc' not in payload:
        raise ValueError('Runtime is missing its matching bundled Python standard library')
    python_library = f'libpython{version}.so' if target == 'linux' else f'python{version.replace(".", "")}.dll'
    libraries = [file for file in files if Path(file).name.lower().startswith(python_library.lower())]
    if not libraries:
        raise ValueError(f'Runtime is missing {python_library}')
    for file in libraries:
        if binary_info(payload[file]) != (target, arch):
            raise ValueError('Bundled Python library target/architecture differs from launcher')
    for file, digest in manifest.get('sha256', {}).items():
        if file not in payload or hashlib.sha256(payload[file].read_bytes()).hexdigest() != digest:
            raise ValueError(f'Runtime hash mismatch: {file}')
    return payload


def write_manifest(root, target, entrypoint=None, python_version=None):
    manifest = inventory(root, target, entrypoint, python_version)
    (Path(root) / 'runtime-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest
