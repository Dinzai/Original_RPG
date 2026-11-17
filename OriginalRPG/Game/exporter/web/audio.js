// Same named-bank contract as native VIPER_AUDIO::Bank. No external libraries.
export class AudioBank {
  constructor(system, clips = [], music = false) {
    this.system = system;
    this.clips = new Map(clips.map(c => [c.name, c]));
    this.music = music;
    this.voices = new Map();
    this.pending = new Set();
    this.error = '';
  }
  play(name) {
    const clip = this.clips.get(name);
    if (!clip) { this.error = `Unknown sound: ${name}`; return false; }
    if (!this.system.context || !this.system.buffers.has(clip.file)) {
      this.error = `Audio unavailable: ${clip.file}`; return false;
    }
    if (this.music) this.stopAll(); else this.stop(name);
    if (this.system.context.state !== 'running') { this.pending.add(name); return true; }
    try {
      const ctx = this.system.context;
      const source = ctx.createBufferSource(), gain = ctx.createGain();
      source.buffer = this.system.buffers.get(clip.file);
      source.loop = clip.loop ?? false;
      gain.gain.value = clip.volume ?? 1;
      source.connect(gain); gain.connect(this.system.master);
      const voice = {source, gain};
      this.voices.set(name, voice);
      source.onended = () => {
        source.disconnect(); gain.disconnect();
        if (this.voices.get(name) === voice) this.voices.delete(name);
      };
      source.start();
      return true;
    } catch (error) { this.stop(name); this.error = error.message; this.system.report(error); return false; }
  }
  stop(name) {
    this.pending.delete(name);
    const voice = this.voices.get(name);
    if (voice) {
      this.voices.delete(name); voice.source.onended = null;
      try { voice.source.stop(); } catch {}
      voice.source.disconnect(); voice.gain.disconnect();
    }
    return this.clips.has(name);
  }
  stopAll() { this.pending.clear(); for (const name of [...this.voices.keys()]) this.stop(name); }
  autoplay() { for (const c of this.clips.values()) if (c.autoplay) { this.play(c.name); if (this.music) break; } }
  flush() { const names = [...this.pending]; this.pending.clear(); for (const name of names) this.play(name); }
  dispose() { this.stopAll(); this.system.banks.delete(this); }
}

export class GameAudio {
  constructor(game) {
    this.game = game;
    this.context = null; this.master = null;
    this.buffers = new Map(); this.banks = new Set();
    this.loading = new Map();
    this.disposed = false;
  }
  report(error) { this.game.report(new Error(`Audio: ${error.message}`)); }
  bank(clips, music = false) { const bank = new AudioBank(this, clips, music); this.banks.add(bank); return bank; }
  async prepare() {
    const paths = new Set();
    for (const bank of this.banks) for (const c of bank.clips.values()) paths.add(c.file);
    // Later scenes reuse the context and decode only files not seen before.
    for (const path of this.buffers.keys()) paths.delete(path);
    // Serialized decoding bounds peak temporary memory. Music is decoded too,
    // unlike native streamed tracks: prefer compressed files of moderate length.
    for (const path of paths) await this.load(path);
  }
  async createContext() {
    if (this.context) return true;
    if (this.disposed) return false;
    try {
      const Context = globalThis.AudioContext || globalThis.webkitAudioContext;
      if (!Context) throw new Error('This browser does not support Web Audio');
      this.context = new Context();
      // Consistent opt-in even when autoplay is permitted. Not awaited: WebKit can
      // leave suspend() pending until audio output starts, which stalled loading.
      if (this.context.state === 'running') this.context.suspend().catch(error => this.report(error));
      this.master = this.context.createGain(); this.master.connect(this.context.destination);
      return true;
    } catch (error) { this.context = null; this.report(error); return false; }
  }
  // Decode one file once; game.add_sound calls this while the game runs.
  load(path) {
    if (this.buffers.has(path)) return Promise.resolve();
    if (!this.loading.has(path)) {
      this.loading.set(path, (async () => {
        try {
          if (!(await this.createContext())) return;
          const response = await fetch(this.game.url(path));
          if (!response.ok) throw new Error(`Cannot fetch ${path}: ${response.status}`);
          const buffer = await this.context.decodeAudioData(await response.arrayBuffer());
          if (!this.disposed) this.buffers.set(path, buffer);
        } catch (error) { this.report(new Error(`${path}: ${error.message}`)); }
        finally { this.loading.delete(path); }
      })());
    }
    return this.loading.get(path);
  }
  unlock() {
    if (!this.context || this.disposed) return;
    // Called directly inside a trusted pointer/key handler, before awaiting.
    const result = this.context.resume();
    Promise.resolve(result).then(() => {
      if (!this.disposed && this.context.state === 'running') for (const bank of this.banks) bank.flush();
    }).catch(error => this.report(error));
  }
  autoplay() { for (const bank of this.banks) bank.autoplay(); }
  stopAll() { for (const bank of this.banks) bank.stopAll(); }
  suspend() {
    if (this.context && this.context.state === 'running') this.context.suspend().catch(error => this.report(error));
  }
  dispose() {
    this.disposed = true; this.stopAll(); this.banks.clear(); this.buffers.clear();
    if (this.context) this.context.close().catch(() => {});
  }
}
