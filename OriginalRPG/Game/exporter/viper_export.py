#!/usr/bin/env python3
"""Viper game exporter. Python 3.10+, standard library only."""
import argparse
import ast
import csv
import hashlib
import html
import json
import math
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import struct
import sys
import tempfile
from python_to_js import Compiler, TranspileError

VERSION = 1
LAYERS = ('ground', 'grass', 'collision', 'above')


class ExportError(ValueError):
    pass


def number(value, label, minimum=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ExportError(f'{label}: expected a finite number')
    if minimum is not None and value < minimum:
        raise ExportError(f'{label}: must be >= {minimum}')
    if integer and int(value) != value:
        raise ExportError(f'{label}: expected an integer')
    return int(value) if integer else value


def relative(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ExportError(f'Expected a project-relative path: {value!r}')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or p.as_posix() == '.':
        raise ExportError(f'Path must remain inside the project: {value!r}')
    return p.as_posix()


def source(root, value):
    rel = relative(value)
    path = root / rel
    # Do not silently copy files reached through symlinks, even internal ones.
    for part in [path, *path.parents]:
        if part == root:
            break
        if part.is_symlink():
            raise ExportError(f'Symlinks are not exportable: {rel}')
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ExportError(f'Missing project file: {rel}')
    return path


def png_size(path):
    with path.open('rb') as f:
        header = f.read(24)
    if header.startswith(b'\x89PNG\r\n\x1a\n') and len(header) == 24:
        return struct.unpack('>II', header[16:24])
    return None


def attachment(obj):
    path = obj.get('script', '')
    if isinstance(path, dict):
        language = path.get('language')
        path = path.get('path', '')
    else:
        language = obj.get('script_language')
    if not path:
        return '', ''
    path = relative(path)
    inferred = {'.py': 'python', '.js': 'javascript', '.mjs': 'javascript'}.get(Path(path).suffix.lower())
    if inferred is None:
        raise ExportError(f'{path}: script must end in .py, .js or .mjs')
    if language is not None and language != inferred:
        raise ExportError(f'{path}: script_language does not match its extension')
    return path, inferred


def audio_bank(data, require, label, music=False):
    if not isinstance(data, list) or len(data) > 128:
        raise ExportError(f'{label}: expected an array with at most 128 sounds')
    names = set()
    result = []
    for item in data:
        if not isinstance(item, dict):
            raise ExportError(f'{label}: expected sound objects')
        name = item.get('name')
        if not isinstance(name, str) or not 1 <= len(name) <= 128 or '\0' in name or name in names:
            raise ExportError(f'{label}: sound names must be unique, nonempty strings (max 128 characters)')
        names.add(name)
        path = relative(item.get('file'))
        if '\0' in path or Path(path).suffix.lower() not in ('.wav', '.mp3', '.flac'):
            raise ExportError(f'{label}: choose WAV, MP3 or FLAC audio')
        require(path)
        volume = number(item.get('volume', 1), f'{label}.volume', 0)
        if volume > 1:
            raise ExportError(f'{label}.volume: maximum is 1')
        for key in ('loop', 'autoplay'):
            if not isinstance(item.get(key, False), bool):
                raise ExportError(f'{label}.{key}: expected a boolean')
        result.append(dict(name=name, file=path, volume=volume, loop=item.get('loop', False), autoplay=item.get('autoplay', False)))
    if music and sum(c['autoplay'] for c in result) > 1:
        raise ExportError('Only one music track may autoplay')
    return result


def audio_section(data, key, require, label):
    if not isinstance(data, dict):
        raise ExportError(f'{label}: expected an object')
    unsupported = set(data) - {key}
    if unsupported:
        raise ExportError(f'{label}: unknown audio fields {sorted(unsupported)}')
    return {key: audio_bank(data.get(key, []), require, label, key == 'music')}


def prepare_scene(root, raw, target, require):
    if not isinstance(raw, dict):
        raise ExportError('scene.json must contain an object')
    unsupported = set(raw) - {'player', 'generics', 'maps', 'map', 'settings', 'schema_version', 'audio'}
    if target == 'web' and unsupported:
        raise ExportError(f'Web runtime does not support scene sections: {sorted(unsupported)}')
    result = {'schema_version': VERSION, 'settings': raw.get('settings', {}), 'player': None, 'generics': [], 'maps': []}
    result['audio'] = audio_section(raw.get('audio', {}), 'music', require, 'scene.audio')
    settings = result['settings']
    if not isinstance(settings, dict):
        raise ExportError('settings must be an object')
    # Default canvas = the desktop window (viper.h WINDOW_WIDTH/HEIGHT).
    for key, default in [('width', 1200), ('height', 800)]:
        settings[key] = number(settings.get(key, default), key, 1, True)
        if settings[key] > 8192:
            raise ExportError(f'{key}: maximum is 8192')
    settings['title'] = str(settings.get('title', 'Viper Game'))
    settings['zoom'] = number(settings.get('zoom', 1), 'zoom', 0.01)
    settings['fixedStep'] = number(settings.get('fixedStep', 1 / 60), 'fixedStep', 0.001)
    if settings['fixedStep'] > 0.1:
        raise ExportError('fixedStep: maximum is 0.1 seconds')
    seen = set()

    def entity(obj, kind):
        if not isinstance(obj, dict):
            raise ExportError(f'{kind}: expected an object')
        obj = json.loads(json.dumps(obj))
        ident = obj.get('id')
        number(ident, f'{kind}.id', 0, True)
        if ident in seen:
            raise ExportError(f'Duplicate object ID: {ident}')
        seen.add(ident)
        if kind == 'Generic':
            # Trigger zones (Generic::LoadEdit): saved as type EventTile or trigger.enabled.
            trigger = obj.get('trigger', {})
            shape = obj.get('shape', {})
            if not isinstance(trigger, dict) or not isinstance(shape, dict):
                raise ExportError(f'{kind} {ident}: trigger and shape must be objects')
            obj['eventTile'] = obj.get('type') == 'EventTile' or trigger.get('enabled') is True
            obj['trigger'] = {'enabled': obj['eventTile'], 'active': trigger.get('active', True) is not False}
            obj['shape'] = {'width': number(shape.get('width', 20), f'{kind} {ident}.shape.width', 0.001),
                            'height': number(shape.get('height', 20), f'{kind} {ident}.shape.height', 0.001)}
        obj['type'] = kind
        name = obj.get('name', kind)
        tags = obj.get('tags', [])
        if not isinstance(name, str) or not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ExportError(f'{kind} {ident}: name must be a string and tags a list of strings')
        obj['name'], obj['tags'] = name, tags
        obj['audio'] = audio_section(obj.get('audio', {}), 'sfx', require, f'{kind} {ident}.audio')
        pos = obj.get('position', {})
        for axis in ('x', 'y'):
            number(pos.get(axis), f'{kind}.position.{axis}')
        sprite = obj.get('sprite')
        if not isinstance(sprite, dict):
            raise ExportError(f'{kind} {ident}: sprite metadata is required')
        sprite['file'] = relative(sprite.get('file'))
        image = require(sprite['file'])
        for key in ('xFrame', 'yFrame'):
            number(sprite.get(key), f'sprite.{key}', 1, True)
        number(sprite.get('speed', 0), 'sprite.speed', 0)
        number(sprite.get('animTime', 0.18), 'sprite.animTime', 0)
        size = png_size(image)
        if size and (size[0] % sprite['xFrame'] or size[1] % sprite['yFrame']):
            raise ExportError(f"{sprite['file']}: image dimensions must divide evenly by frame counts")
        path, language = attachment(obj)
        if path:
            script_file = require(path)
            expected = 'javascript' if target == 'web' else 'python'
            if language != expected and not (target == 'web' and language == 'python'):
                raise ExportError(f'{kind} {ident}: {path} is {language}; {target} requires {expected}. No scripts are silently discarded.')
            if language == 'python':
                try:
                    ast.parse(script_file.read_text(encoding='utf-8-sig'), filename=path)
                except (SyntaxError, UnicodeError) as e:
                    raise ExportError(f'{path}: invalid Python source: {e}') from e
            obj['script'] = path
            obj['script_language'] = language
        if kind == 'Player':
            style = obj.get('style', 'TOPDOWN')
            if style not in ('TOPDOWN', 'ARCADE', 'PLATFORMER'):
                raise ExportError(f'Unknown player style: {style}')
            if target == 'web' and style == 'PLATFORMER':
                raise ExportError('Web PLATFORMER physics is not implemented; select TOPDOWN or ARCADE')
            obj['style'] = style
            frames = obj.get('movementFrames')
            if frames is None:
                # Original test-player ordering for a 3-column, 4-row sheet.
                frames = [9, 11, 6, 8, 3, 5, 0, 2] if sprite['xFrame'] == 3 and sprite['yFrame'] == 4 else [0] * 8
            if not isinstance(frames, list) or len(frames) != 8:
                raise ExportError('movementFrames must contain eight start/end frame numbers')
            total = sprite['xFrame'] * sprite['yFrame']
            frames = list(frames)
            for i in range(0, 8, 2):
                a = number(frames[i], 'movementFrames', 0, True)
                b = number(frames[i + 1], 'movementFrames', a, True)
                if b >= total:
                    # The editor saves its default walk frames even on a one-frame
                    # sprite; the runtime would reset them too, so don't fail.
                    frames[i], frames[i + 1] = 0, 0
            obj['movementFrames'] = frames
        else:
            mode = obj.get('ai', {}).get('mode', 'EMPTY')
            if mode not in ('EMPTY', 'BASIC', 'RANDOM', 'CHASE'):
                raise ExportError(f'Unknown AI mode: {mode}')
            obj['ai'] = {'mode': mode}
        return obj

    if raw.get('player') is not None:
        result['player'] = entity(raw['player'], 'Player')
    if not isinstance(raw.get('generics', []), list):
        raise ExportError('generics must be an array')
    result['generics'] = [entity(g, 'Generic') for g in raw.get('generics', [])]
    maps = raw.get('maps', [])
    if not maps and 'map' in raw:
        maps = [raw['map']]
    if not isinstance(maps, list):
        raise ExportError('maps must be an array')
    for saved in maps:
        if not isinstance(saved, dict):
            raise ExportError('Each map must be an object')
        tile_size = number(saved.get('tileSize', 16), 'tileSize', 1, True)
        image = relative(saved.get('image'))
        image_path = require(image)
        dimensions = png_size(image_path)
        if dimensions and (dimensions[0] % tile_size or dimensions[1] % tile_size):
            raise ExportError(f'{image}: atlas dimensions must divide evenly by tileSize')
        m = {'map': saved.get('map', ''), 'image': image, 'tileSize': tile_size}
        sources = saved.get('sources', {})
        for layer in LAYERS:
            states = saved.get(layer, [])
            if not isinstance(states, list):
                raise ExportError(f'{layer}: saved tiles must be an array')
            path = sources.get(layer, '')
            tiles = []
            if path:
                path = require(path)
                with path.open(newline='', encoding='utf-8-sig') as f:
                    rows = list(csv.reader(f))
                if rows and any(len(row) != len(rows[0]) for row in rows):
                    raise ExportError(f'{path.name}: CSV must be rectangular')
                for y, row in enumerate(rows):
                    for x, cell in enumerate(row):
                        try:
                            frame = int(cell.strip())
                        except ValueError as e:
                            raise ExportError(f'{path.name}: invalid tile at row {y + 1}, column {x + 1}') from e
                        if frame < -1:
                            raise ExportError(f'{path.name}: only -1 represents an empty tile')
                        if frame != -1:
                            if dimensions and frame >= (dimensions[0] // tile_size) * (dimensions[1] // tile_size):
                                raise ExportError(f'{path.name}: tile frame {frame} exceeds atlas')
                            tiles.append({'frame': frame, 'x': x * tile_size, 'y': y * tile_size})
                if states:
                    if len(states) != len(tiles):
                        raise ExportError(f"{m['map']} {layer}: saved tile count differs from CSV; rebuild/resave the map")
                    for tile, state in zip(tiles, states):
                        for axis in ('x', 'y'):
                            tile[axis] = number(state.get(axis), f'{layer}.{axis}')
            elif states:
                # A future editor can save atlas frames explicitly. Runtime IDs are never frames.
                for state in states:
                    if 'frame' not in state:
                        raise ExportError(f"{m['map']} {layer}: CSV source missing; runtime tile IDs cannot recover atlas frames")
                    frame = number(state['frame'], 'tile.frame', 0, True)
                    if dimensions and frame >= (dimensions[0] // tile_size) * (dimensions[1] // tile_size):
                        raise ExportError('tile.frame exceeds atlas')
                    tiles.append({'frame': frame, 'x': number(state.get('x'), 'tile.x'), 'y': number(state.get('y'), 'tile.y')})
            m[layer] = tiles
        result['maps'].append(m)
    return result


def scene_files(root):
    """scene.json first, then every extra scene under Scenes/ (game.load_scene)."""
    files = ['scene.json']
    scenes = root / 'Scenes'
    if scenes.is_dir() and not scenes.is_symlink():
        files += sorted(p.relative_to(root).as_posix() for p in scenes.rglob('*.json') if p.is_file())
    return files


def export_game(project, output, target='web', runtime=None, includes=()):
    root = Path(project).resolve()
    output = Path(output).absolute()
    if target not in ('web', 'linux', 'windows'):
        raise ExportError(f'Unknown target: {target}')
    if output.exists():
        raise ExportError(f'Output already exists: {output}. Choose a new directory.')
    if output.resolve() == root or root.is_relative_to(output.resolve()):
        raise ExportError('Output must not contain the project')
    # Plan all project files before staging output, including the full Assets/Scripts
    # trees so script helper modules and dynamically loaded assets are bundled.
    required = {}
    def require(rel):
        rel = relative(rel)
        path = source(root, rel)
        required[rel] = path
        return path
    # Every scene is validated and exported; scene.json is the start scene.
    raws, scenes = {}, {}
    for rel in scene_files(root):
        try:
            raws[rel] = json.loads(require(rel).read_text(encoding='utf-8'))
        except (ValueError, OSError) as e:
            raise ExportError(f'Cannot read {rel}: {e}') from e
        try:
            scenes[rel] = prepare_scene(root, raws[rel], target, require)
        except ExportError as e:
            raise ExportError(f'{rel}: {e}') from e
    raw, scene = raws['scene.json'], scenes['scene.json']
    for rel in ['Assets', 'Scripts', 'Scenes', *includes]:
        rel = relative(rel)
        tree = root / rel
        if output.resolve().is_relative_to(tree.resolve()):
            raise ExportError(f'Output cannot be inside an exported source tree: {rel}')
        if tree.is_symlink():
            raise ExportError(f'Symlinks are not exportable: {rel}')
        if not tree.exists():
            if rel in includes:
                raise ExportError(f'Missing include: {rel}')
            continue
        paths = [tree] if tree.is_file() else sorted(tree.rglob('*'))
        for file in paths:
            if file.is_symlink():
                raise ExportError(f'Symlinks are not exportable: {file.relative_to(root)}')
            if file.is_file() and '__pycache__' not in file.parts:
                require(file.relative_to(root).as_posix())
    # Compile every attached Python script once, before creating output. A dedicated
    # namespace avoids overwriting hand-authored JavaScript beside the source.
    generated = {}
    script_map = {}
    warnings = []
    if target == 'web':
        def sibling(original, name):
            return (PurePosixPath(original).parent / (name + '.py')).as_posix()

        def compile_file(original, kind, importer=None):
            # Behaviour scripts and the helper modules they import (import globals).
            # Each file becomes one ES module, shared by every script that imports it.
            destination = '_viper_python/' + original + '.js'
            if destination in generated:
                return destination
            try:
                compiler = Compiler(required[original].read_text(encoding='utf-8-sig'), original,
                                    resolve=lambda name: sibling(original, name) in required, kind=kind)
                generated[destination] = compiler.compile()
            except (TranspileError, UnicodeError) as e:
                raise ExportError(f'{e}' + (f' (imported by {importer})' if importer else '')) from e
            generated[destination + '.python-map.json'] = json.dumps(
                {'source': original, 'lines': compiler.mapping}, indent=2)
            for name in compiler.local_modules:
                compile_file(sibling(original, name), 'module', original)
            return destination

        def compile_python(original, attached):
            try:
                destination = compile_file(original, 'behaviour')
            except ExportError as e:
                if attached:
                    raise ExportError(f'Web Python compilation failed: {e}') from e
                # Unattached files may be helpers; only game.spawn(..., script) needs them.
                warnings.append(f'{original} is not spawnable on web: {e}')
                return None
            script_map[original] = destination
            return destination
        for prepared in scenes.values():
            for obj in [prepared.get('player'), *prepared.get('generics', [])]:
                if not obj or not obj.get('script'):
                    continue
                if obj.get('script_language') == 'python':
                    obj['script'] = compile_python(obj['script'], True)
                    obj['script_language'] = 'javascript'
                else:
                    script_map[obj['script']] = obj['script']
        # Any script under Scripts/ can be attached later by game.spawn(image, x, y, cols, rows, script).
        for rel in sorted(required):
            if rel.startswith('Scripts/') and rel not in script_map:
                suffix = Path(rel).suffix.lower()
                if suffix == '.py':
                    # Files without class Behaviour are helper modules (e.g. globals.py);
                    # they are compiled when a script imports them.
                    if re.search(r'^class\s+Behaviour\b', required[rel].read_text(encoding='utf-8-sig', errors='replace'), re.M):
                        compile_python(rel, False)
                elif suffix in ('.js', '.mjs') and 'export' in required[rel].read_text(encoding='utf-8-sig', errors='replace'):
                    script_map[rel] = rel
        scene['scripts'] = script_map
        scene['scenes'] = {rel: {key: data[key] for key in ('player', 'generics', 'maps', 'audio')}
                           for rel, data in scenes.items() if rel != 'scene.json'}
        if any(p == '_viper_python' or p.startswith('_viper_python/') for p in required):
            raise ExportError('Project files conflict with reserved _viper_python output directory')
    reserved = {'game.json', 'index.html', 'runtime.js', 'audio.js', 'boot.js', 'manifest.json'} if target == 'web' else {'manifest.json', 'runtime-manifest.json'}
    if reserved.intersection(required):
        raise ExportError(f'Project files conflict with exporter files: {sorted(reserved.intersection(required))}')
    runtime_files = {}
    native_manifest = None
    if target != 'web':
        if runtime is None:
            raise ExportError(f'{target}: --runtime must identify a prebuilt standalone runtime directory')
        runtime_root = Path(runtime).resolve()
        try:
            native_manifest = json.loads((runtime_root / 'runtime-manifest.json').read_text())
        except (OSError, ValueError) as e:
            raise ExportError(f'Cannot read runtime-manifest.json: {e}') from e
        if native_manifest.get('target') != target or native_manifest.get('api_version') != VERSION:
            raise ExportError('Runtime target/API version does not match export')
        entry = relative(native_manifest.get('entrypoint'))
        files = native_manifest.get('files', [])
        if not isinstance(files, list) or entry not in files:
            raise ExportError('Runtime manifest must list every payload file, including entrypoint')
        if not native_manifest.get('standalone'):
            raise ExportError('Runtime must include Python and its dependencies (standalone=true)')
        for rel in files:
            rel = relative(rel)
            if rel in required or rel in reserved:
                raise ExportError(f'Runtime/project file conflict: {rel}')
            runtime_files[rel] = source(runtime_root, rel)
        python_version = native_manifest.get('python_version')
        if python_version is not None and not re.fullmatch(r'3\.\d+', str(python_version)):
            raise ExportError('Runtime python_version must be a major.minor version, e.g. 3.10')
        linux_layouts = [p for p in runtime_files if re.fullmatch(r'python/lib/python3\.\d+/encodings/__init__\.py', p)]
        if not linux_layouts and 'python/Lib/encodings/__init__.py' not in runtime_files:
            raise ExportError('Runtime must list its bundled Python encodings package')
        if target == 'linux' and python_version is not None and f'python/lib/python{python_version}/encodings/__init__.py' not in runtime_files:
            raise ExportError('Runtime python_version does not match its bundled encodings layout')
        module_suffix = '.so' if target == 'linux' else '.pyd'
        if not any(Path(p).name.startswith('libviper') and p.endswith(module_suffix) for p in runtime_files):
            raise ExportError('Runtime must list its matching libviper module')
        with runtime_files[entry].open('rb') as f:
            magic = f.read(4)
        if (target == 'linux' and magic != b'\x7fELF') or (target == 'windows' and magic[:2] != b'MZ'):
            raise ExportError('Native entrypoint has the wrong executable format')
        if target == 'linux' and not os.access(runtime_files[entry], os.X_OK):
            raise ExportError('Linux runtime entrypoint must be executable')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.viper-export-', dir=output.parent))
    try:
        for rel, path in {**required, **runtime_files}.items():
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        if target == 'web':
            for rel, content in generated.items():
                dest = stage / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding='utf-8')
            web = Path(__file__).parent / 'web'
            for name in ('runtime.js', 'audio.js', 'boot.js'):
                shutil.copy2(web / name, stage / name)
            (stage / 'game.json').write_text(json.dumps(scene, indent=2, allow_nan=False), encoding='utf-8')
            title = html.escape(scene['settings']['title'])
            (stage / 'index.html').write_text((web / 'index.html').read_text().replace('{{TITLE}}', title), encoding='utf-8')
        else:
            # Native engine reads its own original scene format. Add inferred language.
            for obj in [raw.get('player'), *raw.get('generics', [])]:
                if obj is not None:
                    path, language = attachment(obj)
                    if path:
                        obj['script'], obj['script_language'] = path, language
            (stage / 'scene.json').write_text(json.dumps(raw, indent=2, allow_nan=False), encoding='utf-8')
            (stage / 'runtime-manifest.json').write_text(json.dumps(native_manifest, indent=2), encoding='utf-8')
        hashes = {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(stage.rglob('*')) if p.is_file()}
        manifest = {'exporter_version': VERSION, 'target': target, 'entrypoint': 'index.html' if target == 'web' else native_manifest['entrypoint'], 'files': hashes}
        if warnings:
            manifest['warnings'] = warnings
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        # Refuse a destination created by another process during packaging.
        if output.exists():
            raise ExportError('Output appeared during export; nothing was overwritten')
        stage.rename(output)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target', choices=('web', 'linux', 'windows'), default='web')
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--include', action='append', default=[])
    args = parser.parse_args()
    try:
        result = export_game(args.project, args.output, args.target, args.runtime, args.include)
        print(f"Exported {args.target}: {args.output} ({len(result['files'])} files)")
        for warning in result.get('warnings', []):
            print(f'Warning: {warning}', file=sys.stderr)
    except (ExportError, OSError, TypeError, AttributeError) as e:
        print(f'Export failed: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
