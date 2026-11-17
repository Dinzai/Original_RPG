"""Compile or check scripts: python3 -m python_to_js Scripts --check --json."""
import argparse
import json
from pathlib import Path
import sys
from . import Compiler, TranspileError


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('paths', nargs='+', type=Path)
    p.add_argument('--check', action='store_true', help='Validate without writing generated files')
    p.add_argument('--json', action='store_true', help='Emit editor-friendly JSON diagnostics')
    p.add_argument('--output', type=Path, help='Output directory (required unless --check)')
    args = p.parse_args()
    if not args.check and args.output is None:
        p.error('--output is required unless --check is used')
    results, compiled, destinations = [], [], set()
    for path in args.paths:
        if not path.exists():
            results.append(dict(file=str(path), ok=False, message='Path does not exist'))
            continue
        files = sorted(path.rglob('*.py')) if path.is_dir() else [path]
        if not files:
            results.append(dict(file=str(path), ok=False, message='No Python scripts found'))
        for file in files:
            try:
                compiler = Compiler(file.read_text(encoding='utf-8-sig'), str(file), module_suffix='.js')
                js = compiler.compile()
                rel = file.relative_to(path) if path.is_dir() else Path(file.name)
                dest = rel.with_suffix('.js')
                if dest in destinations:
                    raise ValueError(f'Output collision: {dest}')
                destinations.add(dest)
                compiled.append((dest, js, compiler.mapping, str(file)))
                results.append(dict(file=str(file), ok=True))
            except TranspileError as e:
                results.append(dict(ok=False, **e.as_dict()))
            except (OSError, UnicodeError, ValueError) as e:
                results.append(dict(file=str(file), ok=False, message=str(e)))
    success = bool(results) and all(r['ok'] for r in results)
    if success and not args.check:
        # Validate all first; never generate a partially compatible script set.
        for rel, js, mapping, original in compiled:
            target = args.output / rel
            if target.exists() or target.with_suffix('.js.python-map.json').exists():
                p.error(f'Output already exists: {target}; choose an empty output directory')
        for rel, js, mapping, original in compiled:
            target = args.output / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(js, encoding='utf-8')
            target.with_suffix('.js.python-map.json').write_text(json.dumps(dict(source=original, lines=mapping), indent=2), encoding='utf-8')
    if args.json:
        print(json.dumps(dict(ok=success, scripts=results), indent=2))
    else:
        for r in results:
            print(f"{r['file']}: " + ('Web compatible (supported subset)' if r['ok'] else f"{r.get('line', 1)}:{r.get('column', 1)}: {r['message']}"))
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
