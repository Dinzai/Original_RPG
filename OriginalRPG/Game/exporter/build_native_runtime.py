#!/usr/bin/env python3
"""Assemble a standalone Viper runtime from built engine binaries and matching Python.

This stages binaries; compile the engine/libviper with your existing build first.
Use native/CMakeLists.txt to compile the Python-embedding launcher if needed.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from native_runtime import binary_info, write_manifest

# Target OS libraries supplied by the machine. Never bundle glibc/loader or GPU drivers.
SYSTEM_LINUX = re.compile(r'^(ld-linux.*|lib(c|m|pthread|dl|rt|resolv|util|nss_.*)\.so.*|lib(GL|GLX|GLdispatch|EGL|vulkan|drm).*|linux-vdso.*)$')
SYSTEM_WINDOWS = {'kernel32.dll','user32.dll','gdi32.dll','winmm.dll','shell32.dll','ole32.dll','oleaut32.dll','advapi32.dll','ws2_32.dll','opengl32.dll','ntdll.dll','comdlg32.dll','comctl32.dll','version.dll','shlwapi.dll','secur32.dll','bcrypt.dll','crypt32.dll','ucrtbase.dll','imm32.dll','setupapi.dll','dwmapi.dll','msvcrt.dll','winspool.drv','rpcrt4.dll','psapi.dll','iphlpapi.dll','normaliz.dll','netapi32.dll','userenv.dll','powrprof.dll'}


def copy_tree(source, destination):
    source, destination = Path(source), Path(destination)
    # ldd may resolve a dependency to the copy already in staging.
    # samefile also handles symlinks and hard links to the same inode.
    if destination.exists() and source.samefile(destination):
        return
    def ignored(directory, names):
        return [name for name in names if name in ('__pycache__', 'site-packages', 'test', 'tests', 'idlelib', 'tkinter', 'ensurepip') or name.endswith(('.pyc','.pyo'))]
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=False, ignore=ignored, dirs_exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != source.read_bytes():
                raise ValueError(f'Dependency filename conflict: {destination.name}')
            return
        shutil.copy2(source, destination, follow_symlinks=True)


def linux_python_libraries(python_home, version, architecture, extra_dirs=()):
    """Find matching libraries, retaining every loader-visible filename."""
    directories = [Path(python_home) / 'lib', Path(python_home) / 'lib64']
    directories += sorted((Path(python_home) / 'lib').glob('*-linux-gnu'))
    directories += [Path(p) for p in extra_dirs]
    # Only use distro paths for distro prefixes; do not silently mix a custom
    # Python installation with an unrelated system Python build.
    if Path(python_home).resolve() in (Path('/usr'), Path('/')):
        for root in (Path('/usr/lib'), Path('/lib')):
            directories += [root, *sorted(root.glob('*-linux-gnu'))]
    directories = list(dict.fromkeys(directories))
    for directory in directories:
        libraries = []
        for path in sorted(directory.glob(f'libpython{version}.so*')):
            if not path.is_file():
                continue
            if binary_info(path) == ('linux', architecture):
                libraries.append(path)
        if libraries:
            # Do not deduplicate by resolved path: .so and .so.1.0 can point
            # to the same bytes, but the dynamic loader needs the SONAME.
            return libraries
    searched = '\n  '.join(str(p) for p in directories)
    raise ValueError(
        f'Could not locate libpython{version}.so for {architecture}.\n'
        f'Searched:\n  {searched}'
    )


def dependencies(stage, target, search_dirs):
    """Resolve linked dependencies without running Viper itself. Uses trusted build outputs."""
    queue = [p for p in stage.rglob('*') if p.is_file() and p.suffix.lower() in ('.so','.pyd','.dll','.exe') or p.is_file() and p.name == 'ViperEngine']
    # Include versioned Linux .so names.
    queue += [p for p in stage.rglob('*.so.*') if p.is_file()]
    seen = set()
    if target == 'windows':
        lookup = {}
        for directory in [stage, *search_dirs]:
            for path in directory.rglob('*'):
                if path.is_file() and path.suffix.lower() == '.dll':
                    previous = lookup.get(path.name.lower())
                    if previous and previous.read_bytes() != path.read_bytes():
                        raise ValueError(f'Ambiguous DLL: {path.name}')
                    lookup[path.name.lower()] = path
        if not shutil.which('objdump'):
            raise ValueError('objdump is required to validate Windows DLL dependencies')
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        try:
            platform, architecture = binary_info(path)
        except ValueError:
            continue
        if platform != target:
            raise ValueError(f'Wrong-target binary: {path.name}')
        if architecture != binary_info(stage / ('ViperEngine' if target == 'linux' else 'ViperEngine.exe'))[1]:
            raise ValueError(f'Architecture mismatch: {path.name}')
        if target == 'linux':
            env = dict(os.environ, LD_LIBRARY_PATH=os.pathsep.join(str(p) for p in [stage, stage/'Manager', stage/'python/lib', *search_dirs]))
            result = subprocess.run(['ldd', str(path)], capture_output=True, text=True, env=env)
            if result.returncode and 'not a dynamic executable' not in result.stdout + result.stderr and 'statically linked' not in result.stdout:
                raise ValueError(f'Cannot inspect dependencies: {path.name}: {result.stderr.strip()}')
            for line in result.stdout.splitlines():
                if '=> not found' in line:
                    raise ValueError(f'Unresolved Linux dependency for {path.name}: {line.strip()}')
                match = re.match(r'\s*(\S+) => (/.+?)\s+\(0x[0-9a-fA-F]+\)\s*$', line)
                if match and not SYSTEM_LINUX.match(match[1]):
                    dest = stage / match[1]
                    copy_tree(Path(match[2]), dest); queue.append(dest)
        else:
            result = subprocess.run(['objdump', '-p', str(path)], capture_output=True, text=True)
            if result.returncode:
                raise ValueError(f'Cannot inspect PE dependencies: {path.name}')
            for name in re.findall(r'DLL Name:\s*(\S+)', result.stdout, re.I):
                key = name.lower()
                if key in SYSTEM_WINDOWS or key.startswith(('api-ms-win-', 'ext-ms-win-')):
                    continue
                if key not in lookup:
                    raise ValueError(f'Unresolved Windows dependency for {path.name}: {name}; pass --dependency directory')
                dest = stage / name
                copy_tree(lookup[key], dest); queue.append(dest)


def build_runtime(binaries, python_home, output, target, version, dependency_dirs=(), check_dependencies=True):
    binaries, python_home, output = Path(binaries).resolve(), Path(python_home).resolve(), Path(output).absolute()
    if target not in ('linux','windows') or not re.fullmatch(r'3\.\d+', version):
        raise ValueError('Expected linux/windows and Python major.minor')
    if not binaries.is_dir() or not python_home.is_dir():
        raise ValueError('Provide built engine binaries and a matching Python installation')
    if output.exists() or any(output.resolve().is_relative_to(root) or root.is_relative_to(output.resolve()) for root in (binaries, python_home)):
        raise ValueError('Choose a new output outside binary/Python source directories')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.viper-runtime-', dir=output.parent))
    try:
        # Preserve engine directory layout, but avoid bundling game assets/scripts.
        for path in binaries.iterdir():
            if path.name not in ('Assets','Scripts','python','scene.json','runtime-manifest.json','manifest.json'):
                copy_tree(path, stage/path.name)
        if target == 'linux':
            stdlib = python_home / f'lib/python{version}'
            if not stdlib.is_dir():
                raise ValueError(f'Missing matching standard library: {stdlib}')
            copy_tree(stdlib, stage/f'python/lib/python{version}')
            libraries = linux_python_libraries(
                python_home, version, binary_info(stage / 'ViperEngine')[1],
                dependency_dirs,
            )
            for library in libraries:
                copy_tree(library, stage/'python/lib'/library.name)
                copy_tree(library, stage/library.name)
        else:
            if (python_home/'Lib').is_dir():
                copy_tree(python_home/'Lib', stage/'python/Lib')
            else:
                archive = python_home/f'python{version.replace(".", "")}.zip'
                if not archive.is_file():
                    raise ValueError('Windows Python requires Lib/ or an embeddable stdlib zip')
                with zipfile.ZipFile(archive) as zipped:
                    for member in zipped.infolist():
                        rel = Path(member.filename)
                        if rel.is_absolute() or '..' in rel.parts or '\\' in member.filename:
                            raise ValueError('Unsafe Python zip member')
                    zipped.extractall(stage/'python/Lib')
            for path in python_home.rglob('*'):
                if path.is_file() and path.suffix.lower() in ('.dll','.pyd') and 'site-packages' not in path.parts:
                    # CPython native extension modules are searched in python/DLLs.
                    copy_tree(path, stage/'python/DLLs'/path.name)
                    if path.suffix.lower() == '.dll':
                        copy_tree(path, stage/path.name)
        if check_dependencies:
            dependencies(stage, target, [Path(p).resolve() for p in dependency_dirs] + [binaries, python_home/'lib', python_home])
        manifest = write_manifest(stage, target, python_version=version)
        manifest['dependency_check'] = check_dependencies
        (stage/'runtime-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        if output.exists():
            raise ValueError('Output appeared during build')
        stage.rename(output)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binaries', type=Path, required=True)
    parser.add_argument('--python-home', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target', choices=('linux','windows'), required=True)
    parser.add_argument('--python-version', required=True)
    parser.add_argument('--dependency', action='append', type=Path, default=[])
    parser.add_argument('--skip-dependency-check', action='store_true', help='For packaging fixtures only; do not ship an unchecked payload')
    args = parser.parse_args()
    try:
        result = build_runtime(args.binaries, args.python_home, args.output, args.target, args.python_version, args.dependency, not args.skip_dependency_check)
        print(f"Built runtime: {args.output} ({len(result['files'])} files)")
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f'Runtime assembly failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
