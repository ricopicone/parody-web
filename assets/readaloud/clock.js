/**
 * A stand-in for the audio element, for tracks that have timings but no voice.
 *
 * Presents exactly the slice of HTMLAudioElement read-along uses —
 * `currentTime`, `paused`, `play()`, `pause()`, and an `ended` event — so
 * nothing downstream needs to know which one it is holding. That keeps the
 * preview honest: the pacing you judge is driven by the same loop, the same
 * timings and the same holds as the real thing.
 */
export class Clock {
  constructor(durationMs = 0) {
    this.durationMs = durationMs;
    this._elapsed = 0;
    this._startedAt = null;
    this._listeners = {};
  }

  get paused() {
    return this._startedAt === null;
  }

  get currentTime() {
    const running = this._startedAt === null
      ? 0
      : now() - this._startedAt;
    return (this._elapsed + running) / 1000;
  }

  set currentTime(seconds) {
    this._elapsed = seconds * 1000;
    if (this._startedAt !== null) this._startedAt = now();
  }

  play() {
    if (this._startedAt === null) this._startedAt = now();
    return Promise.resolve();
  }

  pause() {
    if (this._startedAt === null) return;
    this._elapsed += now() - this._startedAt;
    this._startedAt = null;
  }

  addEventListener(name, fn) {
    (this._listeners[name] = this._listeners[name] || []).push(fn);
  }

  dispatch(name) {
    (this._listeners[name] || []).forEach((fn) => fn());
  }
}

function now() {
  return (typeof performance !== 'undefined' && performance.now)
    ? performance.now()
    : Date.now();
}
