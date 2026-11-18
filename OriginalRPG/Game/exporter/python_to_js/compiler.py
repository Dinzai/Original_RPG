"""Small, fail-closed Python gameplay compiler. Python 3.10+, no dependencies."""
import ast
import json
from pathlib import Path
from .errors import TranspileError

VIPER_MEMBERS = {'AIMode', 'Vec2', 'set_runtime_mode'}
AI_MODES = {'EMPTY', 'BASIC', 'RANDOM', 'CHASE'}

BUILTINS = {'len', 'abs', 'min', 'max', 'int', 'float', 'bool', 'str', 'range', 'print'}
MATH = {'sin': 1, 'cos': 1, 'tan': 1, 'atan2': 2, 'sqrt': 1, 'floor': 1, 'ceil': 1,
        'fabs': 1, 'radians': 1, 'degrees': 1, 'hypot': 2, 'pi': None, 'tau': None, 'e': None}
# Desktop scripts reach sibling modules (e.g. a shared globals.py) through sys.path.
# On web, ES modules resolve those imports directly, so path setup compiles to nothing.
PATH_MODULES = {'sys', 'os', 'os.path', 'pathlib'}
PATH_BUILTINS = {'__file__', 'str'}


def jsname(name):
    # Prefix every Python name: JS keywords and helper names cannot collide.
    return '$v_' + name


class Compiler:
    def __init__(self, source, filename='<script>', resolve=None, kind='auto', module_suffix='.py.js'):
        """kind: 'behaviour' (class Behaviour script), 'module' (imported helper) or 'auto'.
        resolve(name) says whether a sibling module name.py exists; module_suffix is the
        generated file suffix used in import specifiers."""
        self.source, self.filename = source, str(filename)
        self.resolve = resolve or self.sibling_module
        self.kind, self.module_suffix = kind, module_suffix
        self.local_modules = {}
        self.module_bindings, self.from_imports = [], []
        self.path_names, self.functions, self.global_decls = set(), set(), set()
        self.lines, self.mapping = [], []
        self.indent = 0
        self.locals, self.params, self.consts = set(), set(), set()
        self.globals, self.imports = set(), {}
        self.self_name = None
        self.temp_id = 0
        self.loop_depth = 0

    def error(self, node, message):
        raise TranspileError(self.filename, node, message, self.source)

    def emit(self, text, node=None):
        self.lines.append('  ' * self.indent + text)
        if node is not None:
            self.mapping.append({'generated_line': len(self.lines), 'python_line': node.lineno,
                                 'python_column': node.col_offset + 1})

    def temp(self):
        self.temp_id += 1
        return f'$tmp{self.temp_id}'

    def compile(self):
        try:
            tree = ast.parse(self.source, filename=self.filename)
        except SyntaxError as e:
            node = ast.Constant(None)
            node.lineno, node.col_offset = e.lineno or 1, (e.offset or 1) - 1
            self.error(node, f'Invalid Python: {e.msg}')
        behaviour = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Behaviour']
        if self.kind == 'auto':
            self.kind = 'behaviour' if behaviour else 'module'
        if self.kind == 'behaviour' and len(behaviour) != 1:
            self.error(tree, 'A script must define exactly one class Behaviour')
        if self.kind == 'module' and behaviour:
            self.error(behaviour[0], 'An imported helper module cannot define class Behaviour')
        # Module values are restricted to literal constants; no import-time side effects.
        skipped = set()
        for n in tree.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                self.import_stmt(n)
            elif self.path_setup(n) or self.main_guard(n):
                skipped.add(id(n))
            elif isinstance(n, ast.FunctionDef):
                self.define(n.name, n)
                self.functions.add(n.name)
            elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                self.define(n.targets[0].id, n)
                try:
                    if not self.literal(ast.literal_eval(n.value)):
                        self.error(n, 'Module values must be literals (numbers, strings, bools, None, lists or dicts of them)')
                except (ValueError, TypeError, SyntaxError):
                    self.error(n, 'Module values must be literals (numbers, strings, bools, None, lists or dicts of them)')
            elif (behaviour and n is behaviour[0]) or self.docstring(n):
                pass
            else:
                self.error(n, 'Only imports, sys.path setup, literal module values, helper functions and class Behaviour are supported at module scope')
        runtime = Path(__file__).with_name('runtime.js').read_text(encoding='utf-8')
        self.lines.extend(runtime.splitlines())
        # One ES module instance per helper file, so every importer shares its values
        # exactly like Python's sys.modules cache.
        for binding, spec in self.module_bindings:
            self.emit(f'import {binding} from {json.dumps(spec)};')
        self.emit('// Generated from ' + json.dumps(self.filename) + '; do not edit.')
        # Module-level values live on one mutable object so `global` writes and
        # other modules' `globals.X += 1` are seen by every reader.
        self.emit('const $module = {};')
        for name, binding, attr in self.from_imports:
            self.emit(f'const {jsname(name)} = $py.attr({binding}, {json.dumps(attr)});')
        for n in tree.body:
            if id(n) in skipped:
                continue
            if isinstance(n, ast.Assign):
                self.emit(f'$module[{json.dumps(n.targets[0].id)}] = {self.expr(n.value)};', n)
            elif isinstance(n, ast.FunctionDef):
                self.function(n, False)
                self.emit(f'$module[{json.dumps(n.name)}] = {jsname(n.name)};')
            elif isinstance(n, ast.ClassDef):
                self.class_stmt(n)
        self.emit('export default ' + ('Behaviour' if self.kind == 'behaviour' else '$module') + ';')
        return '\n'.join(self.lines) + '\n'

    def sibling_module(self, name):
        return (Path(self.filename).parent / (name + '.py')).is_file()

    @classmethod
    def literal(cls, value):
        if value is None or isinstance(value, (bool, int, float, str)):
            return True
        if isinstance(value, list):
            return all(cls.literal(v) for v in value)
        if isinstance(value, dict):
            return all(k is None or isinstance(k, (bool, int, float, str)) for k in value) and all(cls.literal(v) for v in value.values())
        return False

    def path_setup(self, n):
        """sys.path / Path(__file__) boilerplate that only exists so desktop Python finds
        sibling modules. Accept it only if it touches nothing but path names."""
        if not isinstance(n, (ast.Assign, ast.If, ast.Expr, ast.Try)):
            return False
        names = [x for x in ast.walk(n) if isinstance(x, ast.Name)]
        loads = {x.id for x in names if isinstance(x.ctx, ast.Load)}
        if not loads & (self.path_names | {'__file__'}) or not loads <= self.path_names | PATH_BUILTINS:
            return False
        stores = {x.id for x in names if isinstance(x.ctx, ast.Store)}
        if stores & (self.globals | set(self.imports)):
            return False
        self.path_names |= stores
        return True

    @staticmethod
    def main_guard(n):
        t = n.test if isinstance(n, ast.If) else None
        return (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == '__name__'
                and len(t.comparators) == 1 and isinstance(t.comparators[0], ast.Constant) and t.comparators[0].value == '__main__')

    def local_module(self, name, n):
        """Return the JS binding for a sibling module (e.g. globals.py), or None."""
        if '.' in name or not name.isidentifier() or not self.resolve(name):
            return None
        if name not in self.local_modules:
            self.local_modules[name] = './' + name + self.module_suffix
            self.module_bindings.append(('$mod_' + name, self.local_modules[name]))
        return '$mod_' + name

    def define(self, name, node):
        if name in self.globals or name in self.imports or name in BUILTINS or name == 'Behaviour':
            self.error(node, f'Duplicate or reserved module name: {name}')
        self.globals.add(name)

    @staticmethod
    def docstring(n):
        return isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)

    def import_stmt(self, n):
        unsupported = 'only math, libviper, sys.path setup and sibling script modules (e.g. import globals) are supported'
        if isinstance(n, ast.Import):
            items = []
            for alias in n.names:
                if alias.name in PATH_MODULES:
                    self.path_names.add(alias.asname or alias.name.split('.')[0])
                    continue
                if alias.name not in ('math', 'libviper'):
                    binding = self.local_module(alias.name, n)
                    if binding is None:
                        self.error(n, f'Unsupported import {alias.name!r}; {unsupported}')
                    items.append((alias.asname or alias.name, 'module:' + binding))
                    continue
                items.append((alias.asname or alias.name, alias.name))
        elif not n.level and n.module in PATH_MODULES:
            self.path_names.update(alias.asname or alias.name for alias in n.names)
            return
        elif not n.level and n.module not in ('math', 'libviper'):
            binding = self.local_module(n.module or '', n)
            if binding is None:
                self.error(n, f'Unsupported import {n.module!r}; {unsupported}')
            items = []
            for alias in n.names:
                if alias.name == '*':
                    self.error(n, 'from module import * is not supported; import the module and use module.NAME')
                # Python copies the value at import time; module.NAME stays live.
                items.append((alias.asname or alias.name, 'from:' + binding))
                self.from_imports.append((alias.asname or alias.name, binding, alias.name))
        else:
            if n.level:
                self.error(n, f'Relative imports are not supported; {unsupported}')
            items = []
            for alias in n.names:
                allowed = MATH if n.module == 'math' else VIPER_MEMBERS
                if alias.name not in allowed:
                    self.error(n, f'Unsupported {n.module} member: {alias.name}')
                value = alias.name if n.module == 'math' else 'libviper.' + alias.name
                items.append((alias.asname or alias.name, value))
        for name, value in items:
            if self.imports.get(name) == value:
                continue
            if name in self.globals or name in self.imports or name in BUILTINS or name == 'Behaviour':
                self.error(n, f'Duplicate or reserved import name: {name}')
            self.imports[name] = value

    def viper_member(self, n):
        """Resolve only statically known libviper names; reject unsupported APIs."""
        if isinstance(n, ast.Name):
            value = self.imports.get(n.id, '')
            return value if value == 'libviper' or value.startswith('libviper.') else None
        if isinstance(n, ast.Attribute):
            parent = self.viper_member(n.value)
            if parent is None:
                return None
            if parent == 'libviper' and n.attr in VIPER_MEMBERS:
                return parent + '.' + n.attr
            if parent == 'libviper.AIMode' and n.attr in AI_MODES:
                return parent + '.' + n.attr
            self.error(n, f'Unsupported Viper member: {parent}.{n.attr}')
        return None

    @staticmethod
    def viper_value(member):
        return '$py.viper' + member[len('libviper'):]

    def class_stmt(self, n):
        if n.name != 'Behaviour' or n.bases or n.keywords or n.decorator_list:
            self.error(n, 'Only undecorated class Behaviour without inheritance is supported')
        methods = [m for m in n.body if isinstance(m, ast.FunctionDef)]
        if len({m.name for m in methods}) != len(methods):
            self.error(n, 'Duplicate Behaviour methods are not supported')
        for m in methods:
            if (m.name.startswith('__') and m.name != '__init__') or m.name in ('constructor', 'prototype'):
                self.error(m, f'Unsupported special method: {m.name}')
        self.emit('export class Behaviour {', n)
        self.indent += 1
        for m in n.body:
            if isinstance(m, ast.FunctionDef):
                self.function(m, True)
            elif not (self.docstring(m) or isinstance(m, ast.Pass)):
                self.error(m, 'Behaviour may contain only methods; initialize instance state in __init__')
        self.indent -= 1
        self.emit('}')

    def function(self, n, method):
        a = n.args
        if n.decorator_list or a.vararg or a.kwarg or a.kwonlyargs or a.posonlyargs or n.returns or any(x.annotation for x in a.args):
            self.error(n, 'Decorators, annotations, positional-only, keyword-only and variadic parameters are not supported')
        args = [x.arg for x in a.args]
        if method and (not args or args[0] != 'self'):
            self.error(n, 'Behaviour methods must take self as their first parameter')
        if len(args) != len(set(args)):
            self.error(n, 'Duplicate function parameter')
        if method and n.name == '__init__':
            for stmt in ast.walk(n):
                if isinstance(stmt, ast.Return) and stmt.value is not None and not (isinstance(stmt.value, ast.Constant) and stmt.value.value is None):
                    self.error(stmt, '__init__ cannot return a value')
        self.self_name = args.pop(0) if method else None
        self.params = set(args)
        if a.defaults:
            self.error(n, 'Default parameters are not supported yet; pass arguments explicitly')
        stores = [x for stmt in n.body for x in ast.walk(stmt) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)]
        self.global_decls = set()
        for g in (x for stmt in n.body for x in ast.walk(stmt) if isinstance(x, (ast.Global, ast.Nonlocal))):
            if isinstance(g, ast.Nonlocal):
                self.error(g, 'nonlocal is not supported')
            for name in g.names:
                if name not in self.globals or name in self.functions:
                    self.error(g, f'global {name} must name a module-level value')
                if name in self.params:
                    self.error(g, f'{name} is a parameter and global')
            self.global_decls.update(g.names)
        self.locals = {x.id for x in stores} - self.params - self.global_decls
        if self.self_name in {x.id for x in stores}:
            self.error(n, 'Reassigning self is not supported')
        if (self.locals | self.params) & (BUILTINS | set(self.imports) | {'Behaviour'}):
            self.error(n, 'Local names cannot shadow builtins, imports or Behaviour in v1')
        # const only for single direct assignments before every read. Branch/loop
        # assignments stay function scoped with an unbound sentinel.
        self.consts = set()
        prior_reads = set()
        for stmt in n.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                name = stmt.targets[0].id
                rhs_reads = {x.id for x in ast.walk(stmt.value) if isinstance(x, ast.Name)}
                if name in self.locals and sum(x.id == name for x in stores) == 1 and name not in prior_reads | rhs_reads:
                    self.consts.add(name)
            prior_reads.update(x.id for x in ast.walk(stmt) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load))
        name = 'constructor' if method and n.name == '__init__' else json.dumps(n.name) if method else jsname(n.name)
        self.emit(f'{"" if method else "function "}{name}({", ".join(map(jsname, args))}) {{', n)
        self.indent += 1
        self.emit(f'if (arguments.length !== {len(args)}) throw new Error("TypeError: {n.name} expects {len(args)} arguments");')
        if self.locals - self.consts:
            self.emit('let ' + ', '.join(f'{jsname(x)} = $py.missing' for x in sorted(self.locals - self.consts)) + ';')
        for stmt in n.body:
            self.stmt(stmt)
        if n.name != '__init__' or not method:
            self.emit('return null;')
        self.indent -= 1
        self.emit('}')
        self.locals, self.params, self.consts, self.self_name = set(), set(), set(), None
        self.global_decls = set()

    def stmt(self, n):
        if self.docstring(n) or isinstance(n, (ast.Pass, ast.Global)):
            return
        if isinstance(n, ast.Assign):
            value = self.expr(n.value)
            if len(n.targets) > 1:
                t = self.temp()
                self.emit(f'const {t} = {value};', n)
                value = t
            for target in n.targets:
                self.assign(target, value, n)
        elif isinstance(n, ast.AugAssign):
            # Cache receivers and indexes before RHS: Python evaluates them once.
            if isinstance(n.target, ast.Name):
                old = self.name(n.target)
                self.assign(n.target, self.binop(n.op, old, self.expr(n.value), n), n)
            elif isinstance(n.target, (ast.Attribute, ast.Subscript)):
                t = self.temp()
                self.emit(f'const {t} = {self.expr(n.target.value)};', n)
                if isinstance(n.target, ast.Attribute):
                    k = json.dumps(n.target.attr)
                    self.check_attr(n.target)
                    self.emit(f'{t}[{k}] = {self.binop(n.op, f"$py.attr({t}, {k})", self.expr(n.value), n)};', n)
                else:
                    k = self.temp()
                    self.emit(f'const {k} = {self.expr(n.target.slice)};', n)
                    self.emit(f'$py.set({t}, {k}, {self.binop(n.op, f"$py.get({t}, {k})", self.expr(n.value), n)});', n)
            else:
                self.error(n, 'Unsupported augmented assignment target')
        elif isinstance(n, ast.Expr):
            self.emit(self.expr(n.value) + ';', n)
        elif isinstance(n, ast.Return):
            self.emit('return ' + (self.expr(n.value) if n.value else 'null') + ';', n)
        elif isinstance(n, ast.If):
            self.emit(f'if ($py.truth({self.expr(n.test)})) {{', n)
            self.block(n.body)
            if n.orelse:
                self.emit('} else {')
                self.block(n.orelse)
            self.emit('}')
        elif isinstance(n, (ast.For, ast.While)):
            if n.orelse:
                self.error(n, 'Loop else clauses are not supported')
            self.loop_depth += 1
            if isinstance(n, ast.For):
                t = self.temp()
                self.emit(f'for (const {t} of $py.iter({self.expr(n.iter)})) {{', n)
                self.indent += 1
                self.assign(n.target, t, n)
                for s in n.body:
                    self.stmt(s)
                self.indent -= 1
            else:
                self.emit(f'while ($py.truth({self.expr(n.test)})) {{', n)
                self.block(n.body)
            self.emit('}')
            self.loop_depth -= 1
        elif isinstance(n, (ast.Break, ast.Continue)):
            if not self.loop_depth:
                self.error(n, 'break/continue requires a loop')
            self.emit('break;' if isinstance(n, ast.Break) else 'continue;', n)
        else:
            self.error(n, f'Unsupported Python statement: {type(n).__name__}')

    def block(self, nodes):
        self.indent += 1
        for n in nodes:
            self.stmt(n)
        self.indent -= 1

    def check_attr(self, n):
        if n.attr.startswith('__') or n.attr in ('prototype', 'constructor'):
            self.error(n, f'Unsupported reflective attribute: {n.attr}')

    def assign(self, n, value, source):
        if isinstance(n, ast.Name):
            if n.id in self.global_decls:
                self.emit(f'$module[{json.dumps(n.id)}] = {value};', source)
                return
            if n.id not in self.locals | self.params:
                self.error(n, 'Assignment must target a local variable (use global NAME to change a module value)')
            prefix = 'const ' if n.id in self.consts else ''
            self.emit(f'{prefix}{jsname(n.id)} = {value};', source)
        elif isinstance(n, ast.Attribute):
            self.check_attr(n)
            # RHS must precede evaluation of the assignment target.
            t = self.temp()
            self.emit(f'const {t} = {value};', source)
            self.emit(f'{self.expr(n.value)}[{json.dumps(n.attr)}] = {t};')
        elif isinstance(n, ast.Subscript):
            t = self.temp()
            self.emit(f'const {t} = {value};', source)
            self.emit(f'$py.set({self.expr(n.value)}, {self.expr(n.slice)}, {t});')
        elif isinstance(n, (ast.Tuple, ast.List)):
            t = self.temp()
            self.emit(f'const {t} = $py.unpack({value}, {len(n.elts)});', source)
            for i, target in enumerate(n.elts):
                self.assign(target, f'{t}[{i}]', source)
        else:
            self.error(n, 'Unsupported assignment target')

    def name(self, n):
        member = self.viper_member(n)
        if member is not None:
            return self.viper_value(member)
        if n.id == self.self_name:
            return 'this'
        if n.id in self.params or n.id in self.consts:
            return jsname(n.id)
        if n.id in self.locals:
            return f'$py.read({jsname(n.id)}, {json.dumps(n.id)})'
        if n.id in self.functions:
            return jsname(n.id)
        if n.id in self.globals:
            return f'$module[{json.dumps(n.id)}]'
        value = self.imports.get(n.id, '')
        if value.startswith('module:'):
            return value[len('module:'):]
        if value.startswith('from:'):
            return jsname(n.id)
        if n.id in self.imports and MATH.get(value, False) is None:
            return self.math_value(value)
        if n.id in self.path_names or n.id == '__file__':
            self.error(n, f'{n.id} is only supported for sys.path setup at module scope on web')
        self.error(n, f'Unknown or unsupported name: {n.id}')

    @staticmethod
    def math_value(name):
        return {'pi': 'Math.PI', 'tau': '(2 * Math.PI)', 'e': 'Math.E'}[name]

    def math_member(self, n):
        if isinstance(n, ast.Name) and n.id not in self.locals | self.params:
            member = self.imports.get(n.id)
            return member if member == 'math' or member in MATH else None
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and self.imports.get(n.value.id) == 'math':
            if n.attr not in MATH:
                self.error(n, f'Unsupported math member: {n.attr}')
            return n.attr
        return None

    def expr(self, n):
        if isinstance(n, ast.Constant):
            v = n.value
            if v is None or isinstance(v, (str, bool)):
                return json.dumps(v, ensure_ascii=True)
            if isinstance(v, (int, float)):
                import math
                if not math.isfinite(v) or isinstance(v, int) and abs(v) > 2**53 - 1:
                    self.error(n, 'Numeric literal exceeds the finite JavaScript safe-number range')
                return repr(v)
            self.error(n, 'Only None, bool, string and numeric constants are supported')
        if isinstance(n, ast.Name):
            return self.name(n)
        if isinstance(n, ast.Attribute):
            self.check_attr(n)
            viper = self.viper_member(n)
            if viper is not None:
                return self.viper_value(viper)
            member = self.math_member(n)
            if member in MATH:
                if MATH[member] is not None:
                    self.error(n, 'Use approved math functions as direct calls')
                return self.math_value(member)
            return f'$py.attr({self.expr(n.value)}, {json.dumps(n.attr)})'
        if isinstance(n, ast.List):
            return '[' + ', '.join(self.expr(x) for x in n.elts) + ']'
        if isinstance(n, ast.Dict):
            if any(x is None for x in n.keys):
                self.error(n, 'Dictionary unpacking is not supported')
            return '$py.dict([' + ', '.join(f'[{self.expr(k)}, {self.expr(v)}]' for k, v in zip(n.keys, n.values)) + '])'
        if isinstance(n, ast.Subscript):
            return f'$py.get({self.expr(n.value)}, {self.expr(n.slice)})'
        if isinstance(n, ast.Slice):
            # Python slice a[start:stop:step]; omitted parts become None (null).
            parts = [self.expr(x) if x is not None else 'null' for x in (n.lower, n.upper, n.step)]
            return f'$py.slice({", ".join(parts)})'
        if isinstance(n, ast.BinOp):
            return self.binop(n.op, self.expr(n.left), self.expr(n.right), n)
        if isinstance(n, ast.UnaryOp):
            x = self.expr(n.operand)
            if isinstance(n.op, ast.Not):
                return f'(!$py.truth({x}))'
            if isinstance(n.op, (ast.UAdd, ast.USub)):
                return f'({"-" if isinstance(n.op, ast.USub) else "+"}$py.num({x}))'
            self.error(n, 'Bitwise operators are not supported')
        if isinstance(n, ast.BoolOp):
            out = self.expr(n.values[-1])
            for v in reversed(n.values[:-1]):
                t = self.temp()
                result = f'{out} : {t}' if isinstance(n.op, ast.And) else f'{t} : {out}'
                out = f'(() => {{ const {t} = {self.expr(v)}; return $py.truth({t}) ? {result}; }})()'
            return out
        if isinstance(n, ast.Compare):
            left = self.temp()
            parts = [f'let {left} = {self.expr(n.left)};']
            for op, other in zip(n.ops, n.comparators):
                right = self.temp()
                parts.append(f'const {right} = {self.expr(other)};')
                if isinstance(op, (ast.Eq, ast.NotEq)):
                    comparison = ('!' if isinstance(op, ast.NotEq) else '') + f'$py.eq({left}, {right})'
                elif isinstance(op, (ast.In, ast.NotIn)):
                    comparison = ('!' if isinstance(op, ast.NotIn) else '') + f'$py.has({right}, {left})'
                elif isinstance(op, (ast.Is, ast.IsNot)):
                    if not isinstance(other, ast.Constant) or other.value is not None:
                        self.error(n, 'Identity comparisons support only is None / is not None')
                    comparison = f'{left} {"!==" if isinstance(op, ast.IsNot) else "==="} {right}'
                else:
                    ops = {ast.Lt: '<', ast.LtE: '<=', ast.Gt: '>', ast.GtE: '>='}
                    if type(op) not in ops:
                        self.error(n, 'Unsupported comparison')
                    comparison = f'$py.order({json.dumps(ops[type(op)])}, {left}, {right})'
                parts.extend([f'if (!({comparison})) return false;', f'{left} = {right};'])
            return '(() => { ' + ' '.join(parts) + ' return true; })()'
        if isinstance(n, ast.IfExp):
            return f'($py.truth({self.expr(n.test)}) ? {self.expr(n.body)} : {self.expr(n.orelse)})'
        if isinstance(n, ast.Call):
            return self.call(n)
        self.error(n, f'Unsupported Python expression: {type(n).__name__}')

    def binop(self, op, a, b, n):
        functions = {ast.Add: 'add', ast.Mult: 'mul', ast.Div: 'div', ast.Mod: 'mod'}
        if type(op) in functions:
            return f'$py.{"iadd" if isinstance(n, ast.AugAssign) and isinstance(op, ast.Add) else "imul" if isinstance(n, ast.AugAssign) and isinstance(op, ast.Mult) else functions[type(op)]}({a}, {b})'
        if isinstance(op, ast.FloorDiv):
            return f'Math.floor($py.div({a}, {b}))'
        if isinstance(op, ast.Sub):
            return f'($py.num({a}) - $py.num({b}))'
        self.error(n, f'Unsupported operator: {type(op).__name__}')

    def call(self, n):
        if n.keywords or any(isinstance(x, ast.Starred) for x in n.args):
            self.error(n, 'Keyword arguments and argument unpacking are not supported')
        args = [self.expr(x) for x in n.args]
        joined = ', '.join(args)
        viper = self.viper_member(n.func)
        if viper is not None:
            if viper not in ('libviper.Vec2', 'libviper.set_runtime_mode'):
                self.error(n, f'{viper} is not callable in the supported web subset')
            if args:
                self.error(n, f'{viper} expects no arguments, matching ViperPython.cpp')
            return f'{self.viper_value(viper)}()'
        member = self.math_member(n.func)
        if member is not None:
            if member not in MATH or MATH[member] is None or len(args) != MATH[member]:
                self.error(n, f'Invalid approved math call: {member}')
            if member in ('radians', 'degrees'):
                return f'($py.num({args[0]}) * {"Math.PI / 180" if member == "radians" else "180 / Math.PI"})'
            method = 'abs' if member == 'fabs' else member
            # Domain failures are errors instead of propagating JS NaN.
            return f'(() => {{ const $r = Math.{method}({", ".join(f"$py.num({a})" for a in args)}); if (!Number.isFinite($r)) throw new Error("ValueError: math domain/range error"); return $r; }})()'
        if isinstance(n.func, ast.Name) and n.func.id in BUILTINS:
            name = n.func.id
            if name == 'range':
                if not 1 <= len(args) <= 3:
                    self.error(n, 'range requires 1 to 3 positional arguments')
                return f'$py.range({joined})'
            if name in ('min', 'max'):
                if not args:
                    self.error(n, f'{name} needs at least one argument')
                return f'$py.minmax({json.dumps(name)}, [{joined}])'
            if name == 'print':
                return f'(console.log({", ".join(f"$py.str({a})" for a in args)}), null)'
            if len(args) != 1:
                self.error(n, f'{name} requires one argument in v1')
            fn = {'len': '$py.length', 'abs': 'Math.abs', 'int': '$py.integer', 'float': '$py.float', 'bool': '$py.truth', 'str': '$py.str'}[name]
            return f'{fn}({"$py.num(" + joined + ")" if name == "abs" else joined})'
        if isinstance(n.func, ast.Attribute):
            self.check_attr(n.func)
            return f'$py.method({self.expr(n.func.value)}, {json.dumps(n.func.attr)})({joined})'
        return f'{self.expr(n.func)}({joined})'


def transpile(source, filename='<script>'):
    """Return an ES module exporting Behaviour; raise TranspileError on rejection."""
    return Compiler(source, filename).compile()
