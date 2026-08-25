/**
 * Getting the reader's ink to the server, and admitting when it hasn't got
 * there.
 *
 * A save carries the whole section, so it is both large and idempotent: the
 * last one to land wins, and any earlier one is redundant. That shapes
 * everything here — requests never overlap, a request made mid-flight is
 * collapsed into one more round afterwards, and a retry re-reads the ink
 * rather than replaying the body that failed.
 *
 * The reporting half is the reason this module exists. Saving used to be
 * `if (await api.save(payload())) delete root.dataset.dirty;` — a failure left
 * the flag set and said nothing, so a reader past the request-body ceiling
 * kept annotating while every stroke was discarded (task #667).
 */

export const OK = 'ok';
export const SAVING = 'saving';
export const FAILED = 'failed';

const RETRY_MS = 15000;

export class Saver {
  constructor(api, { onState, retryMs = RETRY_MS,
                     setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
    this.api = api;
    this.onState = onState || (() => {});
    this.retryMs = retryMs;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;

    this.inFlight = null;
    this.again = null;     // a payload source that arrived mid-flight
    this.timer = null;
    /** True while the reader has marks the server has not acknowledged. */
    this.pending = false;
  }

  _state(state) {
    this.state = state;
    this.onState(state);
  }

  /**
   * Save whatever `payload()` returns now.
   *
   * Takes a function, not a body: by the time this actually goes out the
   * reader may have drawn more, and what they want saved is the ink as it
   * stands, not as it was when the timer fired.
   */
  async save(payload) {
    if (this.inFlight) {
      this.again = payload;
      return this.inFlight;
    }
    if (this.timer !== null) {
      this.clearTimer(this.timer);
      this.timer = null;
    }
    this.pending = true;
    this._state(SAVING);
    this.inFlight = (async () => {
      let ok = false;
      try {
        ok = await this.api.save(payload());
      } catch (err) {
        ok = false;                       // offline, or the request was cut
      }
      this.inFlight = null;
      if (ok) {
        this.pending = false;
        this._state(OK);
      } else {
        this._state(FAILED);
        this._scheduleRetry(payload);
      }
      const next = this.again;
      this.again = null;
      if (next) await this.save(next);
      return ok;
    })();
    return this.inFlight;
  }

  /**
   * Keep trying on the reader's behalf.
   *
   * Without this a reader who stops drawing after a failure never gets another
   * attempt: the only other trigger is the next stroke.
   */
  _scheduleRetry(payload) {
    if (this.timer !== null) this.clearTimer(this.timer);
    this.timer = this.setTimer(() => {
      this.timer = null;
      return this.save(payload);
    }, this.retryMs);
  }
}
