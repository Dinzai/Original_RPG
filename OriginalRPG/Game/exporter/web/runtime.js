import { GameAudio } from "./audio.js";
// Standalone Viper web runtime v2. No TGUI, CDN, Python, or external game loop.
const finite = (v, name) => {
  if (!Number.isFinite(v)) throw new TypeError(`${name} must be finite`);
  return v;
};
const normalized = (x, y) => {
  const n = Math.hypot(x, y);
  return n ? { x: x / n, y: y / n } : { x: 0, y: 0 };
};
const overlaps = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
const contains = (a, p) => p.x >= a.x && p.x < a.x + a.w && p.y >= a.y && p.y < a.y + a.h;
// Player.define_key names -> KeyboardEvent.code ("M" -> KeyM, "1" -> Digit1).
const keyCode = name => {
  if (typeof name !== 'string' || !name) throw new TypeError('Key name must be a nonempty string');
  const n = name.trim();
  if (/^[a-z]$/i.test(n)) return `Key${n.toUpperCase()}`;
  if (/^[0-9]$/.test(n)) return `Digit${n}`;
  const named = { space: 'Space', enter: 'Enter', return: 'Enter', escape: 'Escape', esc: 'Escape', tab: 'Tab', shift: 'ShiftLeft', up: 'ArrowUp', down: 'ArrowDown', left: 'ArrowLeft', right: 'ArrowRight' };
  const code = named[n.toLowerCase()];
  if (!code) throw new Error(`Unknown key for define_key: ${name}`);
  return code;
};
const directions = [{ x: 0, y: -1 }, { x: 1, y: 0 }, { x: 0, y: 1 }, { x: -1, y: 0 }];

// One asset bank per game, matching Loop::GetAsset and Assets::Add.
export const AIMode = Object.freeze({ EMPTY: 'EMPTY', BASIC: 'BASIC', RANDOM: 'RANDOM', CHASE: 'CHASE' });
// Plain numeric coordinates preserve existing JavaScript scripts. The $py helper
// adapts Python's Vec2.x()/y() and extracted bound methods without callable numbers.
export const vector = (x = 0, y = 0) => ({ x: finite(x, 'x'), y: finite(y, 'y') });
export function set_runtime_mode() { /* Web exports always run outside the editor. */ }
const bounds = e => typeof e.get_bounds === 'function' ? e.get_bounds() : e;
// Loop::CollisionBetweenGenerics box: frame size * scale from position - origin * scale (rotation ignored).
const aabb = (e, scale = e.scale) => {
  const x = e.x - e.origin.x * scale.x, y = e.y - e.origin.y * scale.y;
  return { x, y, w: e.w * scale.x, h: e.h * scale.y };
};
const overlapsAABB = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
// [r, g, b] or [r, g, b, a] with 0-255 channels, as on desktop.
const colour = (value, fallback) => {
  if (value == null) return fallback;
  const c = Array.isArray(value) ? value.map(Number) : null;
  if (!c || (c.length !== 3 && c.length !== 4) || !c.every(Number.isFinite)) throw new TypeError('Colours are [r, g, b] or [r, g, b, a] with values 0-255');
  const [r, g, b, a = 255] = c.map(v => Math.max(0, Math.min(255, Math.trunc(v))));
  return `rgba(${r}, ${g}, ${b}, ${a / 255})`;
};
// "world" -> Scenes/world.json; a name ending in .json is used as given (Loop::ScenePath).
export const scenePath = name => {
  if (typeof name !== 'string' || !name) throw new TypeError('Scene name must be a nonempty string');
  const path = name.endsWith('.json') && name.length > 5 ? name : `Scenes/${name}.json`;
  if (path.startsWith('/') || path.split('/').includes('..')) throw new Error(`Scene must be project-relative: ${name}`);
  return path;
};
// Store values are plain data so they survive scene changes and save slots.
// Python dicts compile to Map; they are kept as Map when read back.
const storeEncode = value => {
  if (value === null || value === undefined) return null;
  if (['boolean', 'string'].includes(typeof value)) return value;
  if (typeof value === 'number') { if (!Number.isFinite(value)) throw new TypeError('Store numbers must be finite'); return value; }
  if (Array.isArray(value)) return value.map(storeEncode);
  const entries = value instanceof Map ? [...value] : Object.getPrototypeOf(value) === Object.prototype ? Object.entries(value) : null;
  if (!entries) throw new TypeError('Store values must be None, bool, int, float, str, list or dict');
  const out = {};
  for (const [k, v] of entries) { if (typeof k !== 'string') throw new TypeError('Store dictionary keys must be strings'); out[k] = storeEncode(v); }
  return { $dict: out };
};
const storeDecode = value => {
  if (Array.isArray(value)) return value.map(storeDecode);
  if (value && typeof value === 'object') return new Map(Object.entries(value.$dict).map(([k, v]) => [k, storeDecode(v)]));
  return value;
};

export class Assets {
  constructor(game) {
    this.game = game;
    this.textures = new Map();
    this.pending = [];
  }
  import_image(type, path) {
    if (typeof type !== 'string' || !type.trim()) throw new TypeError('Asset type must be a nonempty string');
    if (typeof path !== 'string' || !path.trim()) throw new TypeError('Image path must be a nonempty string');
    const entry = { path, image: null, error: null };
    if (!this.textures.has(type)) this.textures.set(type, []);
    this.textures.get(type).push(entry);
    // Native import_image returns void. Track browser loading internally so
    // on_start/on_update/on_click remain synchronous and need no await.
    entry.ready = this.game.image(path).then(image => {
      entry.image = image;
    }).catch(error => {
      entry.error = error;
      this.game.report(error);
    });
    this.pending.push(entry);
  }
  texture(type) {
    // Native PassTexture returns the first registered image of this type.
    const entry = this.textures.get(type)?.[0];
    if (!entry) throw new Error(`Unknown image asset: ${type}; call get_asset().import_image(type, path) first`);
    if (entry.error) throw entry.error;
    return entry;
  }
  async prepare() {
    while (this.pending.length) {
      const batch = this.pending.splice(0);
      await Promise.all(batch.map(entry => entry.ready));
      const failed = batch.find(entry => entry.error);
      if (failed) throw failed.error;
    }
  }
}

export class Entity {
  constructor(game, data, image) {
    this.game = game;
    this.sounds = game.audio.bank(data.audio?.sfx ?? []);
    this.data = data;
    this.id = data.id;
    this.type = data.type;
    this.x = data.position.x;
    this.y = data.position.y;
    this.name = typeof data.name === 'string' ? data.name : data.type;
    this.tags = Array.isArray(data.tags) ? [...new Set(data.tags.filter(t => typeof t === 'string' && t))] : [];
    this.columns = data.sprite.xFrame;
    this.rows = data.sprite.yFrame;
    if (![this.columns, this.rows].every(n => Number.isInteger(n) && n > 0)) throw new RangeError('Frame counts must be positive integers');
    this.image = null;
    this.w = 0;
    this.h = 0;
    // Spawned entities may still be loading their image; they stay hidden until then.
    if (image) this.installImage(image);
    else this.pendingFrameCount = this.columns * this.rows;
    // Sprite-local pivot and scale; frame dimensions stay unscaled.
    this.origin = { x: 0, y: 0 };
    this.scale = { x: 1, y: 1 };
    this.rotation = 0;
    this.speed = data.sprite.speed ?? 0;
    this.direction = { x: 0, y: 0 };
    this.lastDirection = { x: 0, y: 1 };
    this.alive = true;
    this.style = data.style ?? 'TOPDOWN';
    this.mode = data.ai?.mode ?? 'EMPTY';
    this.frame = 0;
    this.frameDirection = 1;
    this.animTimer = 0;
    this.animRange = [0, 0];
    this.manualAnimation = false;
    this.movementFrames = [0, 0, 0, 0, 0, 0, 0, 0];
    if (data.movementFrames != null) {
      // Saved editor defaults may refer to a larger sheet (including on
      // static sprites). Recover each invalid direction at load time only.
      const frames = data.movementFrames;
      if (Array.isArray(frames) && frames.length === 8) {
        for (let i = 0; i < 8; i += 2) {
          try {
            this.checkRange(frames[i], frames[i + 1]);
            this.movementFrames[i] = frames[i];
            this.movementFrames[i + 1] = frames[i + 1];
          } catch (error) {
            console.warn(`${error.message}; saved movement pair ${i / 2} reset to [0, 0]`);
          }
        }
      } else {
        console.warn(`Invalid saved movementFrames for ${data.sprite.file} (id ${this.id}); using frame 0`);
      }
    }
    this.collisionEnabled = true;
    this.spriteRevision = 0;
    this.script = null;
    this.clickCallback = null;
    this.actionCallback = null;
    // Player::DefineKey: key name -> callback, run once per key press.
    this.keyCallbacks = new Map();
    this.lastRayTarget = null;
    this.aiIndex = 1;
    if (this.mode !== 'EMPTY') this.direction = { ...directions[this.aiIndex] };
    // Trigger zone state, as in Generic::LoadEdit. The exporter sets eventTile.
    const trigger = data.trigger ?? {};
    this.eventTile = this.type === 'Generic' && (data.eventTile === true || trigger.enabled === true);
    this.triggerActive = trigger.active !== false;
    this.zone = { w: data.shape?.width ?? 20, h: data.shape?.height ?? 20 };
    this.zoneColour = data.shape?.colour ?? [210, 210, 210, 255];
    this.insideIds = new Set();
    this.triggerObjectId = -1;
    this.triggerCallbacks = null;
    // Fakedeath (ViperUnit::FakeDestroy): bullets hide objects that allow it
    // (game.spawn ones do), then on_death runs at the end of the frame.
    this.canBeFakeDestroyed = false;
    this.dead = false;
    this.deathPending = false;
    this.deathCallback = null;
    // Possession (Player::Posses): the player draws with a generic's sprite while the
    // generic is hidden from rendering; both keep updating and colliding as before.
    this.possessed = null;
    this.possessView = null;
    this.hiddenByPossession = false;
  }
  get script_path() { return this.data.script_path ?? this.data.script ?? ''; }
  installImage(image) {
    if (image.width % this.columns || image.height % this.rows) throw new Error(`Invalid sprite frame dimensions: ${this.data.sprite.file}`);
    this.image = image;
    this.w = image.width / this.columns;
    this.h = image.height / this.rows;
    this.pendingFrameCount = null;
  }
  get_id() { return this.id; }
  is_alive() { return this.alive; }
  get_name() { return this.name; }
  set_name(name) { if (typeof name !== 'string') throw new TypeError('Name must be a string'); this.name = name; }
  add_tag(tag) { if (typeof tag !== 'string') throw new TypeError('Tag must be a string'); if (tag && !this.tags.includes(tag)) this.tags.push(tag); }
  remove_tag(tag) { this.tags = this.tags.filter(t => t !== tag); }
  has_tag(tag) { return this.tags.includes(tag); }
  get_tags() { return [...this.tags]; }
  get_scale() { return { ...this.scale }; }
  // Killed objects stay "alive" (as on desktop) but are hidden, skipped by lookups and stop updating.
  get live() { return this.alive && !this.dead; }
  kill() {
    if (!this.alive || this.dead) return;
    this.dead = true;
    this.deathPending = true;
    this.resetTriggers();
  }
  set_death_callback(callback) {
    if (callback !== null && typeof callback !== 'function') throw new TypeError('death callbacks must be callable, e.g. self.on_death');
    this.deathCallback = callback;
  }
  on_death() { if (this.deathCallback) this.deathCallback(); }
  should_destroy(enabled) { this.canBeFakeDestroyed = Boolean(enabled); }
  // ---- Trigger zones (Generic event tiles) ----
  get is_event_tile() { return this.eventTile; }
  set_event_tile(enabled) { this.eventTile = Boolean(enabled); this.resetTriggers(); }
  set_trigger_active(enabled) { this.triggerActive = Boolean(enabled); if (!this.triggerActive) this.resetTriggers(); }
  set_size(w, h) {
    if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) throw new RangeError('Zone size must be finite and positive');
    this.zone = { w, h };
  }
  set_colour(r, g, b, a) { this.zoneColour = [r, g, b, a].map(v => finite(v, 'colour')); }
  get_trigger_object_id() { return this.triggerObjectId; }
  set_trigger_callbacks(enter, stay, exit) {
    for (const callback of [enter, stay, exit]) if (callback != null && typeof callback !== 'function') throw new TypeError('Trigger callbacks must be callable or None');
    this.triggerCallbacks = { enter, stay, exit };
  }
  bind_trigger_script(behaviour) {
    const call = name => () => { const method = behaviour?.[name]; if (typeof method === 'function') method.call(behaviour); };
    this.triggerCallbacks = { enter: call('on_trigger_enter'), stay: call('on_trigger_stay'), exit: call('on_trigger_exit') };
  }
  resetTriggers() { this.insideIds.clear(); this.triggerObjectId = -1; }
  // A zone with a sprite uses the sprite's bounds; without one, its centred shape.
  zoneBounds() {
    if (this.image) return this.get_bounds();
    return { x: this.x - this.zone.w / 2, y: this.y - this.zone.h / 2, w: this.zone.w, h: this.zone.h };
  }
  checkTriggers(objects) {
    if (!this.live || !this.eventTile || !this.triggerActive || this.pendingFrameCount) { this.resetTriggers(); return; }
    const zone = this.zoneBounds(), now = new Set();
    for (const other of objects) if (other !== this && overlaps(zone, bounds(other))) now.add(other.id);
    // Commit first: callbacks may destroy, kill, move or spawn objects (Generic::CheckTriggers).
    const previous = this.insideIds;
    this.insideIds = now;
    const dispatch = (id, phase) => {
      if (!this.live || !this.eventTile || !this.triggerActive) return;
      this.triggerObjectId = id;
      const callback = this.triggerCallbacks?.[phase];
      if (!callback) return;
      try { callback(); }
      catch (error) { this.game.report(new Error(`on_trigger_${phase}: ${error.message}`), this); }
    };
    for (const id of now) dispatch(id, previous.has(id) ? 'stay' : 'enter');
    for (const id of previous) if (!now.has(id)) dispatch(id, 'exit');
    this.triggerObjectId = -1;
  }
  get_bounds() {
    const c = Math.cos(-this.rotation), s = Math.sin(-this.rotation);
    const points = [[0, 0], [this.w, 0], [0, this.h], [this.w, this.h]].map(([x, y]) => {
      x = (x - this.origin.x) * this.scale.x;
      y = (y - this.origin.y) * this.scale.y;
      return { x: this.x + c * x - s * y, y: this.y + s * x + c * y };
    });
    const xs = points.map(p => p.x), ys = points.map(p => p.y);
    const x = Math.min(...xs), y = Math.min(...ys);
    return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
  }
  contains_point(p) {
    if (!this.scale.x || !this.scale.y) return false;
    const dx = p.x - this.x, dy = p.y - this.y;
    const c = Math.cos(this.rotation), s = Math.sin(this.rotation);
    const x = (c * dx - s * dy) / this.scale.x + this.origin.x;
    const y = (s * dx + c * dy) / this.scale.y + this.origin.y;
    return x >= 0 && y >= 0 && x < this.w && y < this.h;
  }
  init_with_frames(asset, type, fileLocation, xFrame, yFrame, animTime, x, y) {
    if (!(asset instanceof Assets) || asset.game !== this.game) throw new TypeError('Expected this game.get_asset()');
    if (![xFrame, yFrame].every(n => Number.isInteger(n) && n > 0)) throw new RangeError('Frame counts must be positive integers');
    if (finite(animTime, 'animTime') < 0) throw new RangeError('animTime must be nonnegative');
    const position = vector(x, y);
    asset.import_image(type, fileLocation);
    const entry = asset.texture(type), revision = ++this.spriteRevision;
    this.pendingFrameCount = xFrame * yFrame;
    this.frame = 0; this.animRange = [0, 0]; this.animTimer = 0; this.frameDirection = 1;
    this.manualAnimation = false;
    if (this.movementFrames.some(f => f >= this.pendingFrameCount)) this.movementFrames = [0, 0, 0, 0, 0, 0, 0, 0];
    // Keep the old sprite valid while the browser loads the new one. prepare()
    // waits for this installation too, including imports made during on_start.
    const install = () => {
      if (revision !== this.spriteRevision || !this.alive) return;
      if (entry.error) throw entry.error;
      const image = entry.image;
      if (image.width % xFrame || image.height % yFrame) throw new Error(`Invalid sprite frame dimensions: ${fileLocation}`);
      this.image = image; this.columns = xFrame; this.rows = yFrame;
      this.w = image.width / xFrame; this.h = image.height / yFrame;
      this.data.sprite = { ...this.data.sprite, type, file: entry.path, xFrame, yFrame, animTime };
      this.pendingFrameCount = null;
    };
    this.set_position(position.x, position.y);
    if (entry.image) install();
    else {
      const pending = { error: null };
      pending.ready = entry.ready.then(install).catch(error => { pending.error = error; this.game.report(error, this); });
      asset.pending.push(pending);
    }
  }
  play_sfx(name) { return this.alive && this.sounds.play(name); }
  stop_sfx(name) { return this.sounds.stop(name); }
  get_audio_error() { return this.sounds.error; }
  get_position() { return { x: this.x, y: this.y }; }
  set_position(x, y) { this.x = finite(x, 'x'); this.y = finite(y, 'y'); }
  set_speed(speed) { if (finite(speed, 'speed') < 0) throw new RangeError('speed must be nonnegative'); this.speed = speed; }
  // Player::SetSpeedDebug: the editor's fast debug speed (debugSpeed = 500).
  set_debug_speed() { this.speed = 500; }
  set_direction(x, y) { this.direction = normalized(finite(x, 'x'), finite(y, 'y')); }
  get_direction() { return { ...this.lastDirection }; }


  set_origin(x, y) {
    this.origin = {
      x: finite(x, 'x'),
      y: finite(y, 'y')
    };
    if (this.possessView) this.possessView.origin = { ...this.origin };
  }

  set_scale(x, y) {
    this.scale = {
      x: finite(x, 'x'),
      y: finite(y, 'y')
    };
    if (this.possessView) this.possessView.scale = { ...this.scale };
  }

  get_image_size() {
    return {
      x: this.w,
      y: this.h
    };
  }

  look_at(lhs, rhs) {
    if (!lhs || !rhs) {
      throw new TypeError('look_at requires lhs and rhs positions');
    }

    const lhsX = finite(lhs.x, 'lhs.x');
    const lhsY = finite(lhs.y, 'lhs.y');
    const rhsX = finite(rhs.x, 'rhs.x');
    const rhsY = finite(rhs.y, 'rhs.y');

    // Native Generic::LookAt stores radians with an upward-facing sprite offset.
    // drawEntity converts this native sign to the Canvas rotation convention.
    this.rotation = -(Math.atan2(rhsY - lhsY, rhsX - lhsX) + Math.PI / 2);
  }


  set_style(style) {
    if (!['TOPDOWN', 'ARCADE'].includes(style)) throw new Error('Web supports TOPDOWN and ARCADE');
    this.style = style;
  }
  set_movement_frames(...frames) {
    if (frames.length !== 8) throw new Error('Expected eight movement frame indices');
    for (let i = 0; i < 8; i += 2) this.checkRange(frames[i], frames[i + 1]);
    this.movementFrames = frames;
  }
  checkRange(start, end) {
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end < start || end >= (this.pendingFrameCount ?? this.columns * this.rows)) throw new RangeError(`Invalid animation range [${start}, ${end}] for ${this.data.sprite.file} (id ${this.id}); valid indices: 0..${(this.pendingFrameCount ?? this.columns * this.rows) - 1}`);
  }
  play_anim(start, end) { this.checkRange(start, end); this.manualAnimation = true; this.range(start, end); }
  end_anim() { this.manualAnimation = false; this.range(0, 0); }
  range(start, end) {
    if (this.animRange[0] !== start || this.animRange[1] !== end) {
      this.animRange = [start, end]; this.frame = start; this.frameDirection = 1; this.animTimer = 0;
    }
  }
  set_click_callback(callback) {
    if (callback !== null && typeof callback !== 'function') throw new TypeError('Click callback must be a function or null');
    this.clickCallback = callback;
  }
  set_action_callback(callback) {
    if (callback !== null && typeof callback !== 'function') throw new TypeError('Action callback must be a function or null');
    this.actionCallback = callback;
  }
  on_click() { this.game.invoke(this, 'on_click', this.clickCallback); }
  define_key(name, callback) {
    if (typeof callback !== 'function') throw new TypeError('define_key needs a callback, e.g. self.open_menu');
    this.keyCallbacks.set(keyCode(name), callback);
  }
  // Player::UserDefinedKey
  on_key(code) { const callback = this.keyCallbacks.get(code); if (callback) this.game.invoke(this, 'on_key', callback); }
  on_action() { this.game.invoke(this, 'on_action', this.actionCallback); }
  AI(mode) {
    if (!['EMPTY', 'BASIC', 'RANDOM', 'CHASE'].includes(mode)) throw new Error(`Unknown AI: ${mode}`);
    this.mode = mode; this.aiIndex = 1; this.direction = mode === 'EMPTY' ? { x: 0, y: 0 } : { ...directions[1] };
  }
  set_gravity(maximum) { if (maximum !== 0) throw new Error('Gravity requires the future PLATFORMER runtime'); }
  raycast(enabled = true) {
    this.lastRayTarget = enabled ? this.game.raycast(this) : null;
    if (this.lastRayTarget) this.lastRayTarget.on_action();
    return this.lastRayTarget;
  }
  destroy() {
    // Match Player::DestroyThat: player destroys its last raycast target.
    if (this.type === 'Player') { if (this.lastRayTarget) this.lastRayTarget.alive = false; }
    else this.alive = false;
  }
  animate(dt) {
    if (this.pendingFrameCount) return;
    if (!this.manualAnimation && ['Player', 'Generic'].includes(this.type)) {
      const d = this.lastDirection;
      const index = d.y > 0 ? 0 : d.y < 0 ? 2 : d.x < 0 ? 4 : 6;
      const start = this.movementFrames[index], end = this.movementFrames[index + 1];
      if (this.direction.x || this.direction.y) this.range(start, end);
      else this.range(Math.max(start, end - 1), Math.max(start, end - 1));
    }
    const interval = this.data.sprite.animTime > 0 ? this.data.sprite.animTime : 1 / 60;
    this.animTimer += dt;
    const [a, b] = this.animRange;
    while (this.animTimer >= interval) {
      this.animTimer -= interval;
      if (a === b) { this.frame = a; continue; }
      this.frame += this.frameDirection;
      if (this.frame >= b) { this.frame = b; this.frameDirection = -1; }
      if (this.frame <= a) { this.frame = a; this.frameDirection = 1; }
    }
  }
}

export class Game {
  constructor(canvas, scene, baseURL, status) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { alpha: false });
    if (!this.ctx) throw new Error('Canvas 2D is unavailable');
    this.scene = scene;
    this.baseURL = baseURL;
    this.status = status;
    // Logical view = the desktop window. The canvas backing store is sized in
    // device pixels by fitCanvas, so the browser never resamples the pixel art.
    this.viewW = scene.settings.width;
    this.viewH = scene.settings.height;
    this.pixelScale = 1;
    this.canvas.width = this.viewW;
    this.canvas.height = this.viewH;
    this.zoom = scene.settings.zoom;
    // Loop::UserSetZoom (game.set_camera_zoom). null = the engine's default camera scale.
    this.userCameraScale = null;
    // Desktop cameras are centred on a world point (Camera::GetViewMatrix).
    this.cameraCenter = { x: 0, y: 0 };
    this.step = scene.settings.fixedStep;
    this.images = new Map();
    this.assets = new Assets(this);
    this.entities = [];
    this.player = null;
    this.maps = [];
    this.solids = [];
    this.bullets = [];
    this.keys = new Set();
    this.pressedKeys = [];
    this.clicks = [];
    this.actions = 0;
    this.mouse = { x: 0, y: 0 };
    this.mouseHeld = false;
    this.mouseClicked = false;
    this.camera = { x: 0, y: 0 };
    this.errors = [];
    this.running = false;
    this.tickCount = 0;
    this.listeners = [];
    this.audio = new GameAudio(this);
    this.music = this.audio.bank(scene.audio?.music ?? [], true);
    // game.add_sound effects: global, so they survive scene changes (Loop::globalSounds).
    this.globalSounds = this.audio.bank([], false);
    this.accumulator = 0;
    this.previous = null;
    // Script API state. The store and fonts outlive scene changes.
    this.fonts = new Map();
    this.currentFont = '';
    this.texts = [];
    this.ui = [];
    this.nextUIId = 1;
    this.store = new Map();
    this.modules = new Map();
    this.pendingStart = [];
    this.pendingScene = null;
    this.switching = false;
    this.loadedImages = new Map();
    // Every exported scene, keyed by project path; scene.json is the start scene.
    this.scenes = new Map(Object.entries(scene.scenes ?? {}));
    this.scenes.set('scene.json', scene);
    this.sceneName = 'scene.json';
    const ids = [...this.scenes.values()].flatMap(d => [d.player, ...(d.generics ?? [])]).filter(Boolean).map(d => d.id);
    this.nextEntityId = Math.max(0, ...ids) + 1;
  }
  url(path) {
    // Encode filename characters; # and ? are legal filesystem characters.
    return new URL(path.split('/').map(encodeURIComponent).join('/'), this.baseURL).href;
  }
  async image(path) {
    if (!this.images.has(path)) this.images.set(path, new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => { this.loadedImages.set(path, img); resolve(img); };
      img.onerror = () => reject(new Error(`Could not load image: ${path}`));
      img.src = this.url(path);
    }));
    return this.images.get(path);
  }
  async load() {
    // Import every exported script once, so spawn() can attach any of them synchronously.
    const scripts = new Set(Object.values(this.scene.scripts ?? {}));
    for (const d of this.scenes.values()) for (const e of [d.player, ...(d.generics ?? [])]) if (e?.script) scripts.add(e.script);
    for (const path of scripts) {
      const module = await import(this.url(path));
      const Behaviour = module.Behaviour ?? module.default;
      if (typeof Behaviour !== 'function') throw new Error(`${path}: export class Behaviour`);
      this.modules.set(path, Behaviour);
    }
    await this.loadScene(this.scene);
    // The game is running: hide the loading line so the canvas has the window to itself.
    if (!this.errors.length) { this.status.textContent = ''; this.status.hidden = true; }
    this.bindInput();
    this.render();
  }
  async loadScene(sceneData) {
    const data = [sceneData.player, ...(sceneData.generics ?? [])].filter(Boolean);
    for (const obj of data) {
      const e = new Entity(this, obj, await this.image(obj.sprite.file));
      this.entities.push(e);
      if (obj.type === 'Player') this.player = e;
    }
    for (const map of sceneData.maps ?? []) {
      const image = await this.image(map.image), size = map.tileSize;
      if (image.width % size || image.height % size) throw new Error(`Invalid tile atlas: ${map.image}`);
      const columns = image.width / size, count = columns * image.height / size;
      for (const layer of ['ground', 'grass', 'collision', 'above']) {
        for (const t of map[layer]) {
          if (t.frame < 0 || t.frame >= count) throw new Error(`Tile frame ${t.frame} exceeds ${map.image}`);
          if (layer === 'collision') this.solids.push({ ...t, w: size, h: size });
        }
      }
      this.maps.push({ ...map, image, columns });
    }
    await this.audio.prepare();
    // Attach all owners before any callback runs, allowing scripts to find each other.
    for (const e of this.entities) this.attach(e);
    this.pendingStart.length = 0;
    for (const e of this.entities) if (e.script) e.script.started = true;
    this.audio.autoplay();
    this.audioStarted = true;
    await this.assets.prepare();
    // Snapshot: objects spawned inside on_start start next frame, from pendingStart.
    for (const e of [...this.entities]) this.invoke(e, 'on_start');
    await this.assets.prepare();
    // Decode sounds registered with add_sound in on_start before the first frame.
    await this.audio.prepare();
    this.followCamera();
  }
  attach(e) {
    if (!e.data.script) return;
    const Behaviour = this.modules.get(e.data.script);
    if (!Behaviour) throw new Error(`Script was not exported: ${e.data.script}`);
    const behaviour = new Behaviour(e, this);
    for (const name of ['on_start', 'on_update', 'on_click', 'on_action', 'on_death']) {
      if (behaviour[name] !== undefined && typeof behaviour[name] !== 'function') throw new Error(`${e.data.script}: ${name} must be callable`);
      if (behaviour[name]?.constructor.name === 'AsyncFunction') throw new Error(`${e.data.script}: ${name} must be synchronous`);
    }
    // Desktop attaches spawned scripts between frames: on_start runs before the first on_update.
    e.script = { behaviour, enabled: true, started: false };
    // The launcher binds on_death, like main.cpp; set_death_callback can replace it.
    if (typeof behaviour.on_death === 'function') e.deathCallback = () => { if (e.script?.enabled) behaviour.on_death(); };
    this.pendingStart.push(e);
  }
  report(error, owner) {
    const message = `${owner?.data.script ?? 'Runtime'}: ${error.message}`;
    this.errors.push(message);
    this.status.dataset.error = 'true';
    this.status.hidden = false;
    this.status.textContent = message;
    console.error(message);
  }
  invoke(owner, name, callback = null, ...args) {
    if (!owner.alive || (owner.script && !owner.script.enabled)) return;
    try {
      const result = callback ? callback(...args) : owner.script?.behaviour[name]?.(...args);
      if (result && typeof result.then === 'function') {
        Promise.resolve(result).catch(() => { });
        throw new Error(`${name} must be synchronous`);
      }
    } catch (error) {
      if (owner.script) owner.script.enabled = false;
      owner.clickCallback = null; owner.actionCallback = null;
      this.report(error, owner);
    }
  }
  listen(target, event, callback) { target.addEventListener(event, callback); this.listeners.push([target, event, callback]); }
  bindInput() {
    const controlled = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space']);
    this.listen(window, 'keydown', event => {
      if (document.activeElement !== this.canvas) return;
      const defined = this.player?.keyCallbacks.has(event.code);
      if (!controlled.has(event.code) && !defined) return;
      this.audio.unlock();
      event.preventDefault();
      if (event.code === 'Space' && !event.repeat) this.actions++;
      if (defined && !event.repeat) this.pressedKeys.push(event.code);
      this.keys.add(event.code);
    });
    this.listen(window, 'keyup', event => { this.keys.delete(event.code); });
    const reset = () => { this.keys.clear(); this.pressedKeys.length = 0; this.mouseHeld = false; this.clicks.length = 0; this.actions = 0; this.accumulator = 0; this.previous = null; };
    this.listen(window, 'blur', () => { reset(); this.audio.suspend(); });
    this.listen(this.canvas, 'blur', reset);
    this.listen(document, 'visibilitychange', () => { reset(); if (document.hidden) this.audio.suspend(); });
    const position = event => {
      const r = this.canvas.getBoundingClientRect();
      this.mouse = { x: (event.clientX - r.left) * this.viewW / r.width, y: (event.clientY - r.top) * this.viewH / r.height };
    };
    this.listen(this.canvas, 'pointermove', position);
    this.listen(this.canvas, 'pointerdown', event => {
      if (event.button !== 0) return;
      this.audio.unlock();
      this.canvas.focus(); position(event);
      // A press on screen UI never becomes a world hold (matches desktop).
      this.mouseHeld = !this.uiAt(this.mouse);
      this.clicks.push({ world: this.get_mouse_pos(), screen: { ...this.mouse } });
    });
    this.listen(window, 'pointerup', event => { if (event.button === 0) this.mouseHeld = false; });
    this.listen(window, 'pointercancel', reset);
    this.listen(window, 'resize', () => this.fitCanvas());
    this.fitCanvas();
  }
  // Size the canvas in device pixels: a whole-number multiple of the desktop
  // window when it fits (every art pixel becomes an equal square block), else
  // the largest size that fits. CSS size = backing size / devicePixelRatio.
  fitCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const reserved = (this.status?.offsetHeight ?? 0) + 16;
    const availW = Math.max(1, document.documentElement.clientWidth || window.innerWidth) * dpr;
    const availH = Math.max(1, window.innerHeight - reserved) * dpr;
    const fit = Math.min(availW / this.viewW, availH / this.viewH);
    let scale = fit;
    if (fit >= 1) {
      // Whole steps keep every art pixel the same size. Fall back to half steps
      // (still even at zoom 2) when a whole step would leave the game much smaller.
      scale = Math.floor(fit);
      if (scale / fit < 0.75) scale = Math.floor(fit * 2) / 2;
    }
    const w = Math.max(1, Math.round(this.viewW * scale)), h = Math.max(1, Math.round(this.viewH * scale));
    if (this.canvas.width !== w) this.canvas.width = w;
    if (this.canvas.height !== h) this.canvas.height = h;
    this.canvas.style.width = `${w / dpr}px`;
    this.canvas.style.height = `${h / dpr}px`;
    this.pixelScale = w / this.viewW;
    if (!this.running) this.render();
  }
  // ---------------------------------------------------------------------------
  // Script API: text. Mirrors Loop::QueueText and the Raylib renderer.
  // ---------------------------------------------------------------------------
  load_font(name, path) {
    if (typeof name !== 'string' || !name) throw new TypeError('Font name must be a nonempty string');
    if (typeof path !== 'string' || !path || path.startsWith('/') || path.split('/').includes('..')) throw new Error('load_font: use a project-relative path, e.g. Assets/Fonts/main.ttf');
    const family = `viper-font-${name}`;
    // Loads in the background; text uses the fallback font until it is ready.
    const face = new FontFace(family, `url("${this.url(path)}")`);
    this.fonts.set(name, family);
    face.load().then(loaded => document.fonts.add(loaded)).catch(() => this.report(new Error(`Could not load font: ${path}`)));
    return true;
  }
  set_font(name) { this.currentFont = typeof name === 'string' ? name : ''; }
  cssFont(font, size) {
    const family = this.fonts.get(font);
    return `${size}px ${family ? `"${family}", ` : ''}monospace`;
  }
  queueText(text, x, y, size, rgba, world) {
    this.texts.push({ text: String(text), x: finite(x, 'x'), y: finite(y, 'y'), size: Math.max(1, finite(size, 'size')), colour: colour(rgba, 'rgba(255, 255, 255, 1)'), font: this.currentFont, world });
  }
  draw_text(text, x, y, size = 20, rgba = null) { this.queueText(text, x, y, size, rgba, false); }
  draw_text_world(text, x, y, size = 20, rgba = null) { this.queueText(text, x, y, size, rgba, true); }
  measure_text(text, size = 20) {
    this.ctx.font = this.cssFont(this.currentFont, size);
    return { x: this.ctx.measureText(String(text)).width, y: size };
  }
  get_screen_size() { return { x: this.viewW, y: this.viewH }; }

  // ---------------------------------------------------------------------------
  // Script API: screen-space UI. Mirrors Loop::UIPanel/UIImage/UIButton.
  // ---------------------------------------------------------------------------
  addUI(kind, x, y, w, h, extra) {
    const element = {
      id: this.nextUIId++, kind, x: finite(x, 'x'), y: finite(y, 'y'), w: finite(w, 'w'), h: finite(h, 'h'),
      colour: 'rgba(40, 44, 52, 0.863)', textColour: 'rgba(255, 255, 255, 1)', text: '', image: null, imageElement: null,
      font: this.currentFont, textSize: 20, order: 0, visible: true, hovered: false, callback: null, ...extra
    };
    this.ui.push(element);
    this.sortUI();
    return element.id;
  }
  sortUI() { this.ui.sort((a, b) => a.order - b.order || a.id - b.id); }
  callbackArg(callback) {
    if (callback == null) return null;
    if (typeof callback !== 'function') throw new TypeError('UI callbacks must be callable, e.g. self.on_play');
    return callback;
  }
  ui_panel(x, y, w, h, rgba = null) { return this.addUI('panel', x, y, w, h, { colour: colour(rgba, 'rgba(40, 44, 52, 0.863)') }); }
  ui_image(x, y, w, h, path) {
    const id = this.addUI('image', x, y, w, h, { colour: 'rgba(255, 255, 255, 1)' });
    this.ui_set_image(id, path);
    return id;
  }
  ui_button(x, y, w, h, text, callback = null) {
    return this.addUI('button', x, y, w, h, { colour: 'rgba(60, 70, 90, 1)', text: String(text), callback: this.callbackArg(callback) });
  }
  requireUI(id) {
    const element = this.ui.find(e => e.id === id);
    if (!element) throw new RangeError(`No UI element with id ${id}`);
    return element;
  }
  ui_set_text(id, text) { this.requireUI(id).text = String(text); }
  ui_set_text_size(id, size) { this.requireUI(id).textSize = Math.max(1, finite(size, 'size')); }
  ui_set_text_colour(id, rgba) { const e = this.requireUI(id); e.textColour = colour(rgba, e.textColour); }
  ui_set_colour(id, rgba) { const e = this.requireUI(id); e.colour = colour(rgba, e.colour); }
  ui_set_image(id, path) {
    if (typeof path !== 'string' || !path || path.startsWith('/') || path.split('/').includes('..')) throw new Error('ui_set_image: use a project-relative image path');
    const element = this.requireUI(id);
    element.image = path;
    element.imageElement = this.loadedImages.get(path) ?? null;
    const size = img => { if (element.w <= 0) element.w = img.width; if (element.h <= 0) element.h = img.height; };
    if (element.imageElement) size(element.imageElement);
    else this.image(path).then(img => { if (element.image === path) { element.imageElement = img; size(img); } }).catch(error => this.report(error));
  }
  ui_set_position(id, x, y) { const e = this.requireUI(id); e.x = finite(x, 'x'); e.y = finite(y, 'y'); }
  ui_set_size(id, w, h) { const e = this.requireUI(id); e.w = finite(w, 'w'); e.h = finite(h, 'h'); }
  ui_set_visible(id, visible) { this.requireUI(id).visible = Boolean(visible); }
  ui_set_order(id, order) { this.requireUI(id).order = Math.trunc(finite(order, 'order')); this.sortUI(); }
  ui_set_callback(id, callback) { this.requireUI(id).callback = this.callbackArg(callback); }
  ui_remove(id) { const before = this.ui.length; this.ui = this.ui.filter(e => e.id !== id); return this.ui.length !== before; }
  ui_exists(id) { return this.ui.some(e => e.id === id); }
  ui_clear() { this.ui = []; }
  uiAt(point) {
    for (let i = this.ui.length - 1; i >= 0; i--) {
      const e = this.ui[i];
      if (e.visible && point.x >= e.x && point.x <= e.x + e.w && point.y >= e.y && point.y <= e.y + e.h) return e;
    }
    return null;
  }
  is_mouse_over_ui() { return this.uiAt(this.mouse) !== null; }
  invokeUI(element) {
    try {
      const result = element.callback();
      if (result && typeof result.then === 'function') throw new Error('UI callbacks must be synchronous');
    } catch (error) {
      element.callback = null;
      this.report(new Error(`UI callback disabled (element ${element.id}): ${error.message}`));
    }
  }
  renderScriptLayer() {
    const ctx = this.ctx;
    ctx.save();
    try {
      // Screen UI and text use logical (desktop window) coordinates.
      ctx.setTransform(this.pixelScale, 0, 0, this.pixelScale, 0, 0);
      ctx.imageSmoothingEnabled = false;
      ctx.textBaseline = 'top';
      const text = t => { ctx.font = this.cssFont(t.font, t.size); ctx.fillStyle = t.colour; ctx.fillText(t.text, t.x, t.y); };
      for (const t of this.texts) {
        if (!t.world) continue;
        // World text moves and scales with the camera, like sprites.
        ctx.save();
        ctx.translate(-this.camera.x * this.zoom, -this.camera.y * this.zoom);
        ctx.scale(this.zoom, this.zoom);
        text(t);
        ctx.restore();
      }
      const hovered = this.uiAt(this.mouse);
      for (const e of this.ui) {
        if (!e.visible) continue;
        if (e.kind === 'image') {
          if (e.imageElement) ctx.drawImage(e.imageElement, e.x, e.y, e.w > 0 ? e.w : e.imageElement.width, e.h > 0 ? e.h : e.imageElement.height);
        } else {
          ctx.fillStyle = e.colour;
          ctx.fillRect(e.x, e.y, e.w, e.h);
          if (e.kind === 'button') {
            if (e === hovered) { ctx.fillStyle = 'rgba(255, 255, 255, 0.14)'; ctx.fillRect(e.x, e.y, e.w, e.h); }
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.28)'; ctx.lineWidth = 2;
            ctx.strokeRect(e.x + 1, e.y + 1, e.w - 2, e.h - 2);
          }
        }
        if (e.text) {
          // Element text is centred, as on desktop.
          ctx.font = this.cssFont(e.font, e.textSize);
          ctx.fillStyle = e.textColour;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(e.text, e.x + e.w / 2, e.y + e.h / 2);
          ctx.textAlign = 'start';
          ctx.textBaseline = 'top';
        }
      }
      for (const t of this.texts) if (!t.world) text(t);
    } finally {
      ctx.restore();
    }
  }

  // ---------------------------------------------------------------------------
  // Script API: spawning and lookup. Mirrors Loop::Spawn/SpawnCopy/FindByTag.
  // ---------------------------------------------------------------------------
  scriptModule(script) {
    if (!script) return '';
    const path = this.scene.scripts?.[script] ?? (this.modules.has(script) ? script : null);
    if (!path) throw new Error(`spawn: script ${script} was not exported; keep spawnable scripts in Scripts/`);
    return path;
  }
  spawnEntity(data) {
    const cached = this.loadedImages.get(data.sprite.file) ?? null;
    const e = new Entity(this, data, cached);
    if (!cached) {
      this.image(data.sprite.file).then(img => { if (e.alive) e.installImage(img); }).catch(error => { e.alive = false; this.report(error); });
    }
    this.entities.push(e);
    this.attach(e);
    return e;
  }
  spawn(image, x, y, columns = 1, rows = 1, script = '') {
    if (typeof image !== 'string' || !image || image.startsWith('/') || image.split('/').includes('..')) throw new Error('spawn: use a project-relative image path');
    if (![columns, rows].every(n => Number.isInteger(n) && n > 0)) throw new RangeError('spawn: columns and rows must be at least 1');
    const e = this.spawnEntity({
      id: this.nextEntityId++, type: 'Generic', name: 'Generic', tags: [],
      position: { x: finite(x, 'x'), y: finite(y, 'y') },
      sprite: { type: image, file: image, xFrame: columns, yFrame: rows, animTime: 0.18, speed: 0 },
      ai: { mode: 'EMPTY' }, audio: { sfx: [] }, script: this.scriptModule(script)
    });
    // Loop::SpawnTempGeneric: bullets can fakedeath spawned objects.
    e.canBeFakeDestroyed = true;
    return e;
  }
  spawn_copy(template, x, y) {
    if (!(template instanceof Entity) || template.game !== this || !template.alive) throw new Error('spawn_copy: the template entity no longer exists');
    const data = JSON.parse(JSON.stringify(template.data));
    Object.assign(data, { id: this.nextEntityId++, type: 'Generic', name: template.name, tags: [...template.tags], position: { x: finite(x, 'x'), y: finite(y, 'y') } });
    data.sprite = { ...data.sprite, speed: template.speed };
    data.ai = { mode: template.mode };
    data.movementFrames = [...template.movementFrames];
    const e = this.spawnEntity(data);
    // Keep the template's pivot, scale and rotation.
    e.origin = { ...template.origin }; e.scale = { ...template.scale }; e.rotation = template.rotation;
    return e;
  }
  destroy(entity) {
    if (entity == null) return;
    if (!(entity instanceof Entity) || entity.type !== 'Generic') throw new TypeError('destroy expects an entity from spawn, get_entity or find_by_tag');
    entity.alive = false;
  }
  take_spawned() { return []; }
  // Lookups skip killed objects, as on desktop.
  find_by_tag(tag) { return this.entities.filter(e => e.live && e.tags.includes(tag)); }
  find_by_name(name) { return this.entities.find(e => e.live && e.name === name) ?? null; }
  find_nearest(tag, x, y, maxDistance = 0) {
    finite(x, 'x'); finite(y, 'y');
    let nearest = null, best = finite(maxDistance, 'max_distance') > 0 ? maxDistance * maxDistance : Infinity;
    for (const e of this.find_by_tag(tag)) {
      const distance = (e.x - x) ** 2 + (e.y - y) ** 2;
      if (distance <= best) { best = distance; nearest = e; }
    }
    return nearest;
  }

  // ---------------------------------------------------------------------------
  // Script API: global sound effects. Mirrors Loop::AddGlobalSound and friends.
  // ---------------------------------------------------------------------------
  add_sound(name, path, volume = 1) {
    if (typeof name !== 'string' || !name || name.length > 128) throw new Error('Sound name must contain 1 to 128 characters.');
    if (typeof path !== 'string' || !path || path.startsWith('/') || path.includes('\\') || path.split('/').includes('..')) throw new Error(`add_sound: audio file not found: ${path}`);
    if (!/\.(wav|mp3|flac)$/i.test(path)) throw new Error('Choose WAV, MP3, or FLAC audio.');
    if (!Number.isFinite(volume) || volume < 0 || volume > 1) throw new RangeError('Volume must be between 0 and 1.');
    const bank = this.globalSounds, old = bank.clips.get(name);
    if (old && old.file === path && old.volume === volume) return;
    if (!old && bank.clips.size >= 128) throw new Error('At most 128 sounds can be registered.');
    bank.stop(name);
    bank.clips.set(name, { name, file: path, volume, loop: false, autoplay: false });
    // Decodes in the background; loadScene also waits for it after on_start.
    this.audio.load(path);
  }
  play_sound(name) { return this.globalSounds.play(name); }
  stop_sound(name) { return this.globalSounds.stop(name); }
  has_sound(name) { return this.globalSounds.clips.has(name); }
  remove_sound(name) { if (!this.globalSounds.clips.has(name)) return false; this.globalSounds.stop(name); this.globalSounds.clips.delete(name); return true; }
  get_sound_error() { return this.globalSounds.error; }

  // ---------------------------------------------------------------------------
  // Script API: scenes and the persistent store
  // ---------------------------------------------------------------------------
  load_scene(name) {
    const path = scenePath(name);
    if (!this.scenes.has(path)) throw new Error(`Scene not found: ${path}`);
    // Applied between frames so no script is running while objects disappear.
    this.pendingScene = path;
  }
  reload_scene() { this.pendingScene = this.sceneName; }
  get_scene() { return this.sceneName; }
  has_pending_scene() { return this.pendingScene !== null; }
  apply_scene_change() { /* The web runtime applies scene changes itself between frames. */ }
  async switchScene() {
    const path = this.pendingScene;
    this.pendingScene = null;
    this.switching = true;
    try {
      for (const e of this.entities) { e.sounds.dispose(); e.alive = false; e.clickCallback = null; e.actionCallback = null; e.script = null; }
      this.music.dispose();
      this.globalSounds.stopAll();
      this.music = this.audio.bank(this.scenes.get(path).audio?.music ?? [], true);
      this.entities = []; this.player = null; this.maps = []; this.solids = []; this.bullets = [];
      this.ui = []; this.texts = []; this.pendingStart = []; this.clicks.length = 0; this.mouseHeld = false;
      this.camera = { x: 0, y: 0 };
      // Loop::ApplySceneChange: a scene without a player opens centred on the origin.
      this.cameraCenter = { x: 0, y: 0 };
      this.pressedKeys.length = 0;
      this.sceneName = path;
      await this.loadScene(this.scenes.get(path));
    } catch (error) {
      this.report(error);
      this.stop();
    } finally {
      this.switching = false;
      this.previous = null;
      this.accumulator = 0;
    }
  }
  store_set(key, value) { if (typeof key !== 'string') throw new TypeError('Store keys must be strings'); this.store.set(key, storeEncode(value)); }
  store_get(key, fallback = null) { return this.store.has(key) ? storeDecode(this.store.get(key)) : fallback; }
  store_has(key) { return this.store.has(key); }
  store_remove(key) { return this.store.delete(key); }
  store_clear() { this.store.clear(); }
  store_keys() { return [...this.store.keys()]; }
  slotKey(slot) {
    if (typeof slot !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(slot)) throw new Error('Save slots use letters, numbers, _ and - only');
    return `viper:${this.scene.settings.title}:${slot}`;
  }
  save_store(slot) {
    try { localStorage.setItem(this.slotKey(slot), JSON.stringify(Object.fromEntries(this.store))); return true; }
    catch (error) { if (error.message.startsWith('Save slots')) throw error; return false; }
  }
  load_store(slot) {
    const key = this.slotKey(slot);
    try {
      const text = localStorage.getItem(key);
      if (text === null) return false;
      const data = JSON.parse(text);
      if (!data || typeof data !== 'object' || Array.isArray(data)) return false;
      this.store = new Map(Object.entries(data));
      return true;
    } catch { return false; }
  }
  quit() {
    this.stop();
    this.status.hidden = false;
    this.status.textContent = 'Game ended.';
  }
  clear_script_callbacks() { for (const e of this.ui) e.callback = null; }
  show_frame_rate() { /* Desktop editor FPS counter; nothing to show on web. */ }
  // V::Random: rand() % int(max - min) + min, truncated to an int; 0 when min == max.
  get_random_num(min, max) {
    const span = Math.trunc(finite(max, 'max') - finite(min, 'min'));
    if (max === min) return 0;
    if (span === 0) return Math.trunc(min);
    return Math.trunc(Math.floor(Math.random() * Math.abs(span)) + min);
  }
  remove_player_collision() { if (this.player) this.player.collisionEnabled = false; }
  play_music(name) { return this.music.play(name); }
  stop_music(name) { return this.music.stop(name); }
  can_edit() { return false; }
  // Loop::UserSetZoom: sets the camera scale. 1 = normal, 0.5 = twice as close,
  // 2 = see twice as much. It stays until changed again, across scenes.
  set_camera_zoom(amount) {
    if (finite(amount, 'zoom') <= 0) throw new RangeError('Camera zoom must be above 0');
    this.userCameraScale = amount;
    this.followCamera();
  }
  vector(x = 0, y = 0) { return vector(x, y); }
  remove_collision(entity) {
    if (!(entity instanceof Entity) || entity.game !== this) throw new TypeError('Expected an entity belonging to this game');
    entity.collisionEnabled = false;
  }
  get_asset() { return this.assets; }
  get_player() { return this.player?.alive ? this.player : null; }
  get_all_generics() { return this.entities.filter(e => e.live && e.type === 'Generic'); }
  get_mouse_pos() { return { x: this.mouse.x / this.zoom + this.camera.x, y: this.mouse.y / this.zoom + this.camera.y }; }
  get_mouse_down() { return this.mouseHeld; }
  get_mouse_click() { return this.mouseClicked; }
  get_magnitude(a, b) { return Math.hypot(b.x - a.x, b.y - a.y); }
  get_angle(a, b) { return Math.atan2(b.y - a.y, b.x - a.x); }
  get_entity(id) { return this.entities.find(e => e.alive && e.id === id) ?? null; }

  // ---------------------------------------------------------------------------
  // Script API: manual AABB checks and possession. Mirrors Loop::CollisionBetween*
  // and Loop::PossesGeneric/ReleaseGeneric.
  // ---------------------------------------------------------------------------
  requireEntity(entity, name) {
    if (!(entity instanceof Entity) || entity.game !== this) throw new TypeError(`${name} expects an entity belonging to this game`);
    return entity;
  }
  requirePlayer(name) {
    if (!this.player?.alive) throw new Error(`${name}: the scene has no player`);
    return this.player;
  }
  // True while one of the two was stopped by the other on its latest move: what desktop
  // reports as an overlap in the frame before its collision pass pushes them apart.
  pushingTogether(a, b) {
    return a.live && b.live && (a.blockedBy?.has(b) || b.blockedBy?.has(a)) === true;
  }
  collision_aabb_g_g(lhs, rhs) {
    const a = this.requireEntity(lhs, 'collision_aabb_g_g'), b = this.requireEntity(rhs, 'collision_aabb_g_g');
    return overlapsAABB(aabb(a), aabb(b)) || this.pushingTogether(a, b);
  }
  collision_aabb_p_g(generic) {
    const player = this.requirePlayer('collision_aabb_p_g');
    const g = this.requireEntity(generic, 'collision_aabb_p_g');
    // Desktop reads the player's own frame size and origin, and the scale of its newest view.
    return overlapsAABB(aabb(player, player.possessView?.scale ?? player.scale), aabb(g)) || this.pushingTogether(player, g);
  }
  posses(generic) {
    const player = this.requirePlayer('posses');
    this.requireEntity(generic, 'posses');
    if (generic.pendingFrameCount || !generic.image) throw new Error('posses: the generic\'s image has not loaded yet');
    generic.hiddenByPossession = true;
    player.possessed = generic;
    // A fresh view of the generic's sheet: origin 0, scale 1, animated with the player's frames.
    player.possessView = { image: generic.image, columns: generic.columns, rows: generic.rows, w: generic.w, h: generic.h, origin: { x: 0, y: 0 }, scale: { x: 1, y: 1 } };
  }
  release(generic) {
    const player = this.requirePlayer('release');
    this.requireEntity(generic, 'release').hiddenByPossession = false;
    player.possessed = null;
    player.possessView = null;
  }
  spawn_bullet(position, ...args) {
    if (!position) throw new TypeError('Bullet position is required');
    const x = finite(position.x, 'x'), y = finite(position.y, 'y');
    const sprite = typeof args[0] === 'string';
    if (sprite ? args.length !== 6 && args.length !== 7 : args.length !== 3) {
      throw new TypeError('Expected spawn_bullet(position, angle, speed, radius) or spawn_bullet(position, type, angle, speed, xFrame, yFrame, animTime, radius)');
    }
    let angle, speed, radius, asset = null, columns = 1, rows = 1, animTime = 0, size = 1;
    if (sprite) {
      const type = args[0];
      [angle, speed, columns, rows, animTime] = args.slice(1);
      // Loop::SpawnBullet scales sprite bullets by radius / 2 (the old 7-argument form had none).
      if (args.length === 7) {
        if (finite(args[6], 'radius') <= 0) throw new RangeError('Bullet radius must be positive');
        size = args[6] / 2;
      }
      if (!Number.isInteger(columns) || columns <= 0 || !Number.isInteger(rows) || rows <= 0) throw new RangeError('Bullet frame counts must be positive integers');
      if (finite(animTime, 'animTime') < 0) throw new RangeError('Bullet animTime must be nonnegative');
      asset = this.assets.texture(type);
    } else {
      [angle, speed, radius] = args;
      if (finite(radius, 'radius') <= 0) throw new RangeError('Bullet radius must be positive');
    }
    finite(angle, 'angle');
    if (finite(speed, 'speed') < 0) throw new RangeError('Bullet speed must be nonnegative');
    const b = {
      id: this.nextEntityId++, startX: x, startY: y, ignore: null,
      x, y, dx: Math.cos(angle), dy: Math.sin(angle), speed, radius,
      age: 0, alive: true, asset, columns, rows, animTime,
      frame: 0, frameDirection: 1, animTimer: 0, image: null,
      w: sprite ? 0 : radius * 2, h: sprite ? 0 : radius * 2,
      origin: { x: 0, y: 0 }, scale: { x: size, y: size }, rotation: angle + Math.PI / 2,
      get_bounds() { const w = this.w * this.scale.x, h = this.h * this.scale.y; return { x: this.x - w / 2, y: this.y - h / 2, w, h }; }
    };
    if (asset?.image) this.prepareBullet(b);
    this.bullets.push(b);
    return b;
  }
  prepareBullet(b) {
    if (!b.asset || b.image) return true;
    if (b.asset.error) { b.alive = false; return false; }
    const image = b.asset.image;
    if (!image) return false; // An image imported during play is still loading.
    if (image.width % b.columns || image.height % b.rows) {
      throw new Error(`Invalid bullet sprite frame dimensions: ${b.asset.path}`);
    }
    b.image = image;
    b.w = image.width / b.columns;
    b.h = image.height / b.rows;
    // Keep the existing web projectile position at its center.
    b.origin = { x: b.w / 2, y: b.h / 2 };
    return true;
  }
  raycast(owner) {
    const d = owner.lastDirection;
    const box = bounds(owner);
    const ray = { x: box.x + box.w / 2, y: box.y + box.h / 2, w: 5, h: 5 };
    if (d.x) { ray.x += d.x > 0 ? box.w / 2 : -box.w / 2 - 20; ray.w = 20; ray.y -= 2.5; }
    else { ray.y += d.y > 0 ? box.h / 2 : -box.h / 2 - 20; ray.h = 20; ray.x -= 2.5; }
    return this.entities.find(e => e !== owner && e.live && e.collisionEnabled !== false && overlaps(bounds(e), ray)) ?? null;
  }
  inputDirection() {
    const has = (...codes) => codes.some(c => this.keys.has(c));
    // Match desktop cardinal key priority: D > A > S > W.
    if (has('KeyD', 'ArrowRight')) return { x: 1, y: 0 };
    if (has('KeyA', 'ArrowLeft')) return { x: -1, y: 0 };
    if (has('KeyS', 'ArrowDown')) return { x: 0, y: 1 };
    if (has('KeyW', 'ArrowUp')) return { x: 0, y: -1 };
    return this.player?.style === 'ARCADE' ? { ...this.player.lastDirection } : { x: 0, y: 0 };
  }
  move(e, dt, obstacles) {
    let hit = false;
    // Objects that stopped this move, kept until e's next move. Desktop lets a mover
    // overlap what it hit for a frame before snapping back, and scripts see that overlap
    // in collision_aabb_*; here the sweep stops flush, so the AABB checks read this instead.
    e.blockedBy = new Set();
    // Axis sweep clips travel against walls even at high speed; no tunnelling.
    for (const axis of ['x', 'y']) {
      const size = axis === 'x' ? 'w' : 'h', other = axis === 'x' ? 'y' : 'x', otherSize = axis === 'x' ? 'h' : 'w';
      const wanted = e.direction[axis] * e.speed * dt;
      let amount = wanted;
      const box = bounds(e);
      for (const obstacle of obstacles) {
        if (obstacle === e || obstacle.alive === false || obstacle.dead || obstacle.collisionEnabled === false || e.collisionEnabled === false) continue;
        const o = bounds(obstacle);
        if (box.w <= 0 || box.h <= 0 || o.w <= 0 || o.h <= 0 || box[other] >= o[other] + o[otherSize] || box[other] + box[otherSize] <= o[other]) continue;
        let limit = wanted;
        if (wanted > 0 && box[axis] + box[size] <= o[axis]) limit = o[axis] - box[axis] - box[size];
        if (wanted < 0 && box[axis] >= o[axis] + o[size]) limit = o[axis] + o[size] - box[axis];
        if (Math.abs(limit) < Math.abs(wanted) - 1e-8) e.blockedBy.add(obstacle);
        amount = wanted > 0 ? Math.min(amount, limit) : Math.max(amount, limit);
      }
      if (Math.abs(amount - wanted) > 1e-8) hit = true;
      e[axis] += amount;
    }
    return hit;
  }
  update(dt) {
    this.tickCount++;
    // draw_text is per frame: only the latest update's text is drawn.
    this.texts.length = 0;
    // Spawned entities start before their first update, as on desktop.
    for (const e of this.pendingStart.splice(0)) {
      if (e.script) e.script.started = true;
      if (e.live) this.invoke(e, 'on_start');
    }
    // Screen UI takes clicks first; a click on any element never reaches the world.
    const worldClicks = [];
    for (const click of this.clicks.splice(0)) {
      const element = this.uiAt(click.screen);
      if (!element) { worldClicks.push(click.world); continue; }
      if (element.callback) this.invokeUI(element);
    }
    this.clicks.push(...worldClicks);
    if (this.player?.live) {
      this.player.direction = this.inputDirection();
      if (this.player.direction.x || this.player.direction.y) this.player.lastDirection = { ...this.player.direction };
    }
    this.mouseClicked = this.clicks.length > 0;
    for (const p of this.clicks.splice(0)) {
      // Player click is global, as in Player::OnInput. Generic click requires hit.
      if (this.player?.live) this.player.on_click();
      const hit = [...this.entities].reverse().find(e => e.type === 'Generic' && e.live && !e.pendingFrameCount && e.contains_point(p));
      if (hit) hit.on_click();
    }
    for (const code of this.pressedKeys.splice(0)) if (this.player?.live) this.player.on_key(code);
    while (this.actions > 0) {
      this.actions--;
      if (this.player?.live) { this.player.on_action(); this.player.raycast(); }
    }
    for (const e of [...this.entities]) {
      if (!e.live) continue;
      if (e.mode === 'CHASE' && this.player?.live) e.direction = normalized(this.player.x - e.x, this.player.y - e.y);
      // Spawned this frame: its on_start (and first on_update) run next frame.
      if (!e.script || e.script.started) this.invoke(e, 'on_update', null, dt);
      if (!e.live) continue;
      const hit = this.move(e, dt, [...this.solids, ...this.entities]);
      if (hit && ['BASIC', 'RANDOM', 'CHASE'].includes(e.mode)) {
        e.aiIndex = e.mode === 'RANDOM' ? Math.floor(Math.random() * 4) : (e.aiIndex + 1) % 4;
        e.direction = { ...directions[e.aiIndex] };
      }
      if (e.direction.x || e.direction.y) e.lastDirection = { ...e.direction };
      e.animate(dt);
    }
    for (const b of this.bullets) {
      if (!b.alive || !this.prepareBullet(b)) continue;
      if (b.image && b.animTime > 0) {
        b.animTimer += dt;
        const count = b.columns * b.rows;
        while (b.animTimer >= b.animTime) {
          b.animTimer -= b.animTime;
          if (count === 1) continue;
          b.frame += b.frameDirection;
          if (b.frame >= count - 1) { b.frame = count - 1; b.frameDirection = -1; }
          if (b.frame <= 0) { b.frame = 0; b.frameDirection = 1; }
        }
      }
      // A projectile ignores whatever it was fired from until it leaves it.
      if (!b.ignore) b.ignore = new Set(this.entities.filter(e => e.live && overlaps(bounds(b), bounds(e))));
      // Short steps, so a fast bullet cannot pass through a small target.
      const travel = b.speed * dt, steps = Math.max(1, Math.ceil(travel / Math.max(1, Math.min(b.w, b.h) / 2)));
      for (let i = 0; i < steps && b.alive; i++) {
        b.x += b.dx * travel / steps; b.y += b.dy * travel / steps;
        this.bulletHit(b);
      }
      b.age += dt;
      // Bullet::Update: gone once it is half a desktop window (1200x800) from where it started.
      if (Math.abs(b.x - b.startX) > 600 || Math.abs(b.y - b.startY) > 400) b.alive = false;
    }
    this.bullets = this.bullets.filter(b => b.alive);
    this.updateTriggers();
    this.dispatchDeaths();
    for (const e of this.entities) if (!e.alive) e.sounds.dispose();
    this.entities = this.entities.filter(e => e.alive);
    this.followCamera();
  }
  // Bullet::DetectHit: stops at anything collidable and fakedeaths objects that allow it.
  bulletHit(b) {
    const box = bounds(b);
    for (const e of b.ignore) if (!e.live || !overlaps(box, bounds(e))) b.ignore.delete(e);
    const target = this.entities.find(e => e.live && e.collisionEnabled && !e.pendingFrameCount && !b.ignore.has(e) && overlaps(box, bounds(e)));
    if (target) {
      if (target.canBeFakeDestroyed) target.kill();
      b.alive = false;
    } else if (this.solids.some(s => overlaps(box, s))) b.alive = false;
  }
  // Loop::UpdateEventTiles: zones see the player, other generics and bullets (spawned ones too).
  updateTriggers() {
    const candidates = [...this.entities.filter(e => e.live && !e.eventTile && !e.pendingFrameCount), ...this.bullets.filter(b => b.alive && b.w > 0)];
    for (const zone of [...this.entities]) if (zone.eventTile || zone.insideIds.size) zone.checkTriggers(candidates);
  }
  // Loop::DispatchDeaths: on_death runs after collisions and triggers, so it may spawn or play sounds.
  dispatchDeaths() {
    for (const e of this.entities.filter(e => e.deathPending)) {
      e.deathPending = false;
      if (!e.alive) continue;
      try { e.on_death(); }
      catch (error) { this.report(new Error(`on_death failed: ${error.message}`), e); }
    }
  }
  followCamera() {
    // Loop::MoveCamera: ARCADE uses camera scale 0.75 (world drawn 4/3 larger),
    // otherwise 1. A zoom set with game.set_camera_zoom always wins.
    const arcade = this.player?.alive && this.player.style === 'ARCADE';
    const cameraScale = this.userCameraScale ?? (arcade ? 0.75 : 1);
    this.zoom = this.scene.settings.zoom / cameraScale;
    if (this.player?.alive && this.player.style === 'TOPDOWN') {
      const box = bounds(this.player);
      this.cameraCenter = { x: box.x + box.w / 2, y: box.y + box.h / 2 };
    } else if (this.player?.style === 'ARCADE') {
      this.cameraCenter = { x: 200, y: 200 };
    }
    // No player: the camera stays where it was (the origin after a scene load).
    this.camera.x = this.cameraCenter.x - this.viewW / (2 * this.zoom);
    this.camera.y = this.cameraCenter.y - this.viewH / (2 * this.zoom);
  }
  draw(image, frame, columns, w, h, x, y) {
    // Round both edges, not just each origin: adjacent tiles share an exact edge.
    // Device pixels: world zoom times the canvas pixel scale.
    const k = this.zoom * this.pixelScale;
    const left = Math.round((x - this.camera.x) * k), top = Math.round((y - this.camera.y) * k);
    const right = Math.round((x + w - this.camera.x) * k), bottom = Math.round((y + h - this.camera.y) * k);
    if (right < 0 || bottom < 0 || left >= this.canvas.width || top >= this.canvas.height) return;
    this.ctx.drawImage(image, (frame % columns) * w, Math.floor(frame / columns) * h, w, h, left, top, right - left, bottom - top);
  }
  drawEntity(entity) {
    if (entity.pendingFrameCount) return;
    const { image, frame, columns, w, h, x, y, origin, scale, rotation } = entity;
    if (scale.x === 0 || scale.y === 0) return;

    // Preserve the existing pixel-aligned path for untransformed sprites.
    if (rotation === 0 && scale.x === 1 && scale.y === 1) {
      this.draw(image, frame, columns, w, h, x - origin.x, y - origin.y);
      return;
    }

    const ctx = this.ctx, k = this.zoom * this.pixelScale;
    const sx = (frame % columns) * w, sy = Math.floor(frame / columns) * h;
    if (rotation === 0) {
      // Scaled (or mirrored) but not rotated: snap both edges to whole device
      // pixels, like draw(), so scaled pixel art stays sharp and even.
      const xa = x - origin.x * scale.x, xb = x + (w - origin.x) * scale.x;
      const ya = y - origin.y * scale.y, yb = y + (h - origin.y) * scale.y;
      const left = Math.round((Math.min(xa, xb) - this.camera.x) * k), right = Math.round((Math.max(xa, xb) - this.camera.x) * k);
      const top = Math.round((Math.min(ya, yb) - this.camera.y) * k), bottom = Math.round((Math.max(ya, yb) - this.camera.y) * k);
      if (right <= left || bottom <= top || right < 0 || bottom < 0 || left >= this.canvas.width || top >= this.canvas.height) return;
      ctx.save();
      try {
        // A negative scale mirrors the frame in place.
        ctx.setTransform(scale.x < 0 ? -1 : 1, 0, 0, scale.y < 0 ? -1 : 1, scale.x < 0 ? left + right : 0, scale.y < 0 ? top + bottom : 0);
        ctx.drawImage(image, sx, sy, w, h, left, top, right - left, bottom - top);
      } finally {
        ctx.restore();
      }
      return;
    }
    ctx.save();
    try {
      ctx.translate((x - this.camera.x) * k, (y - this.camera.y) * k);
      // Native rotation is the negative of the screen-space Canvas angle.
      ctx.rotate(-rotation);
      ctx.scale(scale.x * k, scale.y * k);
      ctx.drawImage(image, sx, sy, w, h, -origin.x, -origin.y, w, h);
    } finally {
      ctx.restore();
    }
  }

  render() {
    // World drawing works in device pixels; the script layer scales up from the logical view.
    this.ctx.setTransform(1, 0, 0, 1, 0, 0);
    this.ctx.imageSmoothingEnabled = false;
    this.ctx.fillStyle = '#101719'; this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    const layer = name => {
      for (const m of this.maps) for (const t of m[name]) this.draw(m.image, t.frame, m.columns, m.tileSize, m.tileSize, t.x, t.y);
    };
    layer('ground'); layer('grass'); layer('collision');
    // Desktop Scene::RenderAll draws by layer: generics (MidGround), then the
    // player, then bullets (both Entity), so the player sits above other objects.
    for (const e of this.entities) if (e.live && e !== this.player && !e.hiddenByPossession) this.drawEntity(e);
    if (this.player?.live) {
      const view = this.player.possessView;
      if (!view) this.drawEntity(this.player);
      else {
        // The player's animation frames run on the possessed sheet; out-of-range frames show frame 0.
        const frame = this.player.frame < view.columns * view.rows ? this.player.frame : 0;
        this.drawEntity({ ...view, frame, x: this.player.x, y: this.player.y, rotation: 0 });
      }
    }
    for (const b of this.bullets) {
      if (!b.alive || !this.prepareBullet(b)) continue;
      if (b.image) { this.drawEntity(b); continue; }
      this.ctx.fillStyle = '#64d264'; this.ctx.beginPath();
      const k = this.zoom * this.pixelScale;
      this.ctx.arc((b.x - this.camera.x) * k, (b.y - this.camera.y) * k, b.radius * k, 0, Math.PI * 2); this.ctx.fill();
    }
    layer('above');
    this.renderScriptLayer();
  }
  advance(milliseconds) {
    if (this.switching) return;
    if (document.hidden) { this.previous = null; this.accumulator = 0; return; }
    if (this.previous !== null) this.accumulator += Math.max(0, Math.min(0.25, (milliseconds - this.previous) / 1000));
    this.previous = milliseconds;
    let ticks = 0;
    while (this.accumulator >= this.step && ticks++ < 15 && !this.pendingScene) { this.update(this.step); this.accumulator -= this.step; }
    if (ticks >= 15) this.accumulator = 0;
    if (this.pendingScene) { this.switchScene(); return; }
    this.render();
  }
  start() {
    if (this.running) return;
    this.running = true;
    if (!this.audioStarted) { this.audio.autoplay(); this.audioStarted = true; }
    this.previous = null;
    const frame = time => {
      if (!this.running) return;
      try { this.advance(time); }
      catch (error) { this.report(error); this.stop(); return; }
      this.request = requestAnimationFrame(frame);
    };
    this.request = requestAnimationFrame(frame);
  }
  stop() { this.audio.stopAll(); this.audioStarted = false; this.running = false; cancelAnimationFrame(this.request); this.previous = null; this.keys.clear(); }
  dispose() {
    this.stop();
    this.audio.dispose();
    for (const [target, event, callback] of this.listeners) target.removeEventListener(event, callback);
    this.listeners.length = 0;
    for (const e of this.entities) { e.clickCallback = null; e.actionCallback = null; e.script = null; }
  }
}
