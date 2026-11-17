"""Read-only preflight for editor launch/save, or python3 web_compatibility.py --project GAME."""
import argparse
import json
from pathlib import Path, PurePosixPath
from python_to_js import Compiler, TranspileError
from viper_export import attachment, scene_files, source, ExportError


def check_project(project):
    """Validate attached Python scripts without importing/executing gameplay code.

    Returns JSON-serializable diagnostics. A successful result means the scripts
    use the supported language subset, not that every engine API exists on web.
    Call on save or before Play; the editor may continue running Python on failure.
    """
    root = Path(project).resolve()
    results = []
    try:
        objects = []
        for rel in scene_files(root):
            raw = json.loads(source(root, rel).read_text(encoding='utf-8-sig'))
            if not isinstance(raw, dict) or not isinstance(raw.get('generics', []), list):
                raise ValueError(f'{rel}: expected a scene object with a generics array')
            objects += [raw.get('player'), *raw.get('generics', [])]
        seen = set()
        for obj in objects:
            if obj is None:
                continue
            if not isinstance(obj, dict):
                raise ValueError('Scene entities must be objects')
            path, language = attachment(obj)
            if not path or language != 'python' or path in seen:
                continue
            seen.add(path)
            try:
                compiler = Compiler(source(root, path).read_text(encoding='utf-8-sig'), path,
                                    resolve=lambda name: (root / path).parent.joinpath(name + '.py').is_file(), kind='behaviour')
                compiler.compile()
                # Helper modules a script imports (import globals) must compile too.
                for name in compiler.local_modules:
                    helper = (PurePosixPath(path).parent / (name + '.py')).as_posix()
                    if helper not in seen:
                        seen.add(helper)
                        Compiler(source(root, helper).read_text(encoding='utf-8-sig'), helper,
                                 resolve=lambda n, h=helper: (root / h).parent.joinpath(n + '.py').is_file(), kind='module').compile()
                results.append(dict(file=path, ok=True))
            except TranspileError as e:
                results.append(dict(ok=False, **e.as_dict()))
            except (OSError, UnicodeError, ExportError) as e:
                results.append(dict(file=path, ok=False, message=str(e)))
    except (OSError, UnicodeError, ValueError) as e:
        results.append(dict(file='scene.json', ok=False, message=str(e)))
    return dict(ok=all(r['ok'] for r in results), scripts=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = check_project(args.project)
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
