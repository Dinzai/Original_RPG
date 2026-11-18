// Private per-module Python compatibility prelude embedded by compiler.py.
// This is NOT the engine runtime.js. No browser or engine globals required.
const $py = (() => {
  const missing = Symbol('unbound');
  const ranges = new WeakSet();
  const fail = message => { throw new Error(message); };
  const read = (v, name) => v === missing ? fail(`UnboundLocalError: ${name}`) : v;
  const num = x => typeof x === 'boolean' ? Number(x) : typeof x === 'number' ? x : fail('TypeError: expected number');
  const truth = x => x == null ? false : Array.isArray(x) || typeof x === 'string' ? x.length !== 0 : x instanceof Map ? x.size !== 0 : Boolean(x);
  const eq = (a, b) => {
    if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => eq(v, b[i]));
    if (a instanceof Map && b instanceof Map) return a.size === b.size && [...a].every(([k, v]) => has(b, k) && eq(v, get(b, k)));
    if (['number', 'boolean'].includes(typeof a) && ['number', 'boolean'].includes(typeof b)) return num(a) === num(b);
    return a === b;
  };
  const key = k => { if (k !== null && !['string', 'number', 'boolean'].includes(typeof k)) fail('TypeError: dictionary keys must be scalar'); return typeof k === 'boolean' ? Number(k) : k; };
  const dict = entries => { const d = new Map(); for (const [k, v] of entries) d.set(key(k), v); return d; };
  const has = (obj, k) => obj instanceof Map ? obj.has(key(k)) : Array.isArray(obj) ? obj.some(v => eq(v, k)) : typeof obj === 'string' && typeof k === 'string' ? obj.includes(k) : fail('TypeError: unsupported membership');
  const index = (obj, k) => { if (typeof k === 'boolean') k = Number(k); if (!Number.isInteger(k)) fail('TypeError: index must be an integer'); const n = k < 0 ? obj.length + k : k; if (n < 0 || n >= obj.length) fail('IndexError: index out of range'); return n; };
  // Python slices: obj[start:stop:step] for strings and lists (negatives, omitted bounds, any step).
  const slices = new WeakSet();
  const slice = (start, stop, step) => { const s = Object.freeze({start, stop, step}); slices.add(s); return s; };
  const sliceIndex = v => { if (v === null || v === undefined) return null; if (typeof v === 'boolean') v = Number(v); if (!Number.isInteger(v)) fail('TypeError: slice indices must be integers or None'); return v; };
  const sliceRange = (s, len) => {
    let step = sliceIndex(s.step); if (step === null) step = 1; if (step === 0) fail('ValueError: slice step cannot be zero');
    const adjust = (v, fallback) => { v = sliceIndex(v); if (v === null) return fallback; if (v < 0) { v += len; if (v < 0) v = step < 0 ? -1 : 0; } else if (v >= len) v = step < 0 ? len - 1 : len; return v; };
    const start = adjust(s.start, step < 0 ? len - 1 : 0), stop = adjust(s.stop, step < 0 ? -1 : len);
    const out = []; for (let i = start; step > 0 ? i < stop : i > stop; i += step) out.push(i);
    return {start, stop, step, indices: out};
  };
  const getSlice = (obj, s) => {
    const a = typeof obj === 'string' ? [...obj] : obj;
    const {start, stop, step, indices} = sliceRange(s, a.length);
    const picked = step === 1 ? a.slice(start, Math.max(start, stop)) : indices.map(i => a[i]);
    return typeof obj === 'string' ? picked.join('') : picked;
  };
  const setSlice = (obj, s, v) => {
    const values = [...iter(v)];
    const {start, stop, step, indices} = sliceRange(s, obj.length);
    if (step === 1) { obj.splice(start, Math.max(0, stop - start), ...values); return v; }
    if (values.length !== indices.length) fail(`ValueError: attempt to assign sequence of size ${values.length} to extended slice of size ${indices.length}`);
    indices.forEach((i, n) => { obj[i] = values[n]; });
    return v;
  };
  const get = (obj, k) => { if (slices.has(k)) return Array.isArray(obj) || typeof obj === 'string' ? getSlice(obj, k) : fail('TypeError: unsupported slicing'); if (obj instanceof Map) { k = key(k); return obj.has(k) ? obj.get(k) : fail(`KeyError: ${k}`); } if (Array.isArray(obj) || typeof obj === 'string') { const a = typeof obj === 'string' ? [...obj] : obj; return a[index(a, k)]; } return fail('TypeError: unsupported subscription'); };
  const set = (obj, k, v) => { if (slices.has(k)) return Array.isArray(obj) ? setSlice(obj, k, v) : fail('TypeError: unsupported slice assignment'); if (obj instanceof Map) obj.set(key(k), v); else if (Array.isArray(obj)) obj[index(obj, k)] = v; else fail('TypeError: unsupported item assignment'); return v; };
  const iter = x => ranges.has(x) ? x[Symbol.iterator]() : x instanceof Map ? x.keys() : Array.isArray(x) || typeof x === 'string' ? x[Symbol.iterator]() : fail('TypeError: unsupported iterable');
  const length = x => x instanceof Map ? x.size : Array.isArray(x) ? x.length : typeof x === 'string' ? [...x].length : fail('TypeError: len expects list, dict or string');
  const add = (a, b) => Array.isArray(a) && Array.isArray(b) ? [...a, ...b] : typeof a === 'string' && typeof b === 'string' ? a + b : num(a) + num(b);
  const iadd = (a, b) => { if (Array.isArray(a)) { a.push(...iter(b)); return a; } return add(a, b); };
  const mul = (a, b) => {
    if ((Array.isArray(b) || typeof b === 'string') && ['number', 'boolean'].includes(typeof a) && Number.isInteger(num(a))) [a, b] = [b, num(a)];
    if (Array.isArray(a) || typeof a === 'string') { if (typeof b === 'boolean') b = num(b); if (!Number.isInteger(b)) fail('TypeError: repetition requires integer'); return typeof a === 'string' ? a.repeat(Math.max(0, b)) : Array.from({length: Math.max(0, b)}, () => a).flat(); }
    return num(a) * num(b);
  };
  const imul = (a, b) => { const r = mul(a, b); if (Array.isArray(a)) { a.splice(0, a.length, ...r); return a; } return r; };
  const div = (a, b) => { a = num(a); b = num(b); if (!b) fail('ZeroDivisionError'); return a / b; };
  const mod = (a, b) => { a = num(a); b = num(b); if (!b) fail('ZeroDivisionError'); return a - Math.floor(a / b) * b; };
  const order = (op, a, b) => {
    if (Array.isArray(a) && Array.isArray(b)) { let i = 0; while (i < Math.min(a.length, b.length) && eq(a[i], b[i])) i++; return order(op, i < Math.min(a.length, b.length) ? a[i] : a.length, i < Math.min(a.length, b.length) ? b[i] : b.length); }
    if (!(typeof a === 'string' && typeof b === 'string')) { a = num(a); b = num(b); }
    return op === '<' ? a < b : op === '<=' ? a <= b : op === '>' ? a > b : a >= b;
  };
  const range = (...args) => {
    if (args.length < 1 || args.length > 3) fail('TypeError: range expects one to three arguments');
    args = args.map(x => typeof x === 'boolean' ? Number(x) : x);
    let [start, stop, step] = args.length === 1 ? [0, args[0], 1] : [args[0], args[1], args.length === 3 ? args[2] : 1];
    if (![start, stop, step].every(Number.isSafeInteger) || !step) fail('ValueError: range requires safe integers and nonzero step');
    const result = { [Symbol.iterator]: function* () { for (let i = start; step > 0 ? i < stop : i > stop; i += step) yield i; } };
    ranges.add(result); return result;
  };
  // Resolve a Python bound method even if the web API uses numeric Vec2 fields.
  // Keeping the adaptation here preserves JavaScript's numeric .x/.y API.
  const attr = (obj, name) => {
    if (Array.isArray(obj)) {
      if (name === 'append') return v => { obj.push(v); return null; };
      if (name === 'extend') return v => { obj.push(...iter(v)); return null; };
      if (name === 'pop') return (i = -1) => obj.splice(index(obj, i), 1)[0];
      if (name === 'clear') return () => { obj.length = 0; return null; };
      fail(`Unsupported list method: ${name}`);
    }
    if (obj instanceof Map) {
      if (name === 'get') return (k, fallback = null) => obj.has(key(k)) ? obj.get(key(k)) : fallback;
      if (name === 'keys') return () => [...obj.keys()];
      if (name === 'values') return () => [...obj.values()];
      if (name === 'items') return () => [...obj.entries()];
      if (name === 'clear') return () => { obj.clear(); return null; };
      fail(`Unsupported dictionary method: ${name}`);
    }
    if (typeof obj === 'string') fail(`Unsupported string method: ${name}`);
    if (obj == null || !(name in Object(obj))) fail(`AttributeError: ${name}`);
    const value = obj[name];
    if ((name === 'x' || name === 'y') && typeof value === 'number' && typeof obj.x === 'number' && typeof obj.y === 'number') {
      return (...args) => { if (args.length) fail(`TypeError: Vec2.${name} expects no arguments`); return obj[name]; };
    }
    // Python void calls return None, including methods extracted via attr().
    return typeof value === 'function' ? (...args) => { const result = value.apply(obj, args); return result === undefined ? null : result; } : value;
  };
  const method = (obj, name) => {
    const f = attr(obj, name);
    return (...args) => {
      if ((name === 'x' || name === 'y') && typeof f === 'number' && args.length === 0) return f;
      if (typeof f !== 'function') fail(`TypeError: ${name} is not callable`);
      const result = f(...args); return result === undefined ? null : result;
    };
  };
  const unpack = (x, n) => { const a = [...iter(x)]; if (a.length !== n) fail('ValueError: unpack length mismatch'); return a; };
  // Lists and dicts print like Python, e.g. ['enemy', 2] (get_tags, find_by_tag results).
  const repr = x => typeof x === 'string' ? `'${x.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'` : str(x);
  const str = x => x === null ? 'None' : x === true ? 'True' : x === false ? 'False' : typeof x === 'string' || typeof x === 'number' ? String(x)
    : Array.isArray(x) ? `[${x.map(repr).join(', ')}]`
    : x instanceof Map ? `{${[...x].map(([k, v]) => `${repr(k)}: ${repr(v)}`).join(', ')}}`
    : fail('TypeError: str supports scalars, lists and dicts only');
  const integer = x => { if (typeof x === 'string' && !/^[+-]?\d+$/.test(x.trim())) fail('ValueError: invalid int'); const n = typeof x === 'string' ? Number(x) : num(x); if (!Number.isFinite(n)) fail('ValueError: invalid int'); return Math.trunc(n); };
  const float = x => { if (typeof x === 'string' && !/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(x.trim())) fail('ValueError: invalid float'); return typeof x === 'string' ? Number(x) : num(x); };
  const minmax = (kind, args) => { const a = args.length === 1 ? [...iter(args[0])] : args; if (!a.length) fail('ValueError: empty min/max'); return a.reduce((x, y) => order(kind === 'min' ? '<' : '>', y, x) ? y : x); };
  const noArgs = (name, args) => { if (args.length) fail(`TypeError: ${name} expects no arguments`); };
  const viper = Object.freeze({
    AIMode: Object.freeze({ EMPTY: 'EMPTY', BASIC: 'BASIC', RANDOM: 'RANDOM', CHASE: 'CHASE' }),
    Vec2: (...args) => { noArgs('Vec2', args); return { x: 0, y: 0 }; },
    set_runtime_mode: (...args) => { noArgs('set_runtime_mode', args); return null; }
  });
  return {viper, missing, read, num, truth, eq, dict, has, get, set, slice, iter, length, add, iadd, mul, imul, div, mod, order, range, attr, method, unpack, str, integer, float, minmax};
})();
