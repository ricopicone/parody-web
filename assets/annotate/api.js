/** Talking to the ink endpoints. */
import { maybeGzip, Downgrade } from './compress.js';

function csrf() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

/** The wire form of a reader's marks. One definition, used by both saves. */
export function _body({ sliceKey, bookSha, pages, strokes, pads }) {
  return {
    slice_key: sliceKey,
    book_sha256: bookSha,
    pages,
    strokes: strokes || {},
    pads: pads || {},
  };
}

/** What a `keepalive` fetch is allowed to carry, per the fetch spec. */
export const KEEPALIVE_MAX_BYTES = 64 * 1024;

export class InkApi {
  constructor(base) {
    this.base = base;            // e.g. /one/alpha/
    // Shared across every save on this page, so one rejection switches
    // compression off for the session rather than per request.
    this.downgrade = new Downgrade();
  }

  async load(version) {
    const url = new URL(`${this.base}ink/`, window.location.origin);
    if (version) url.searchParams.set('v', version);
    const resp = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!resp.ok) return null;
    return resp.json();
  }

  /**
   * Replace this reader's marks for one version.
   *
   * The body is built from one place — `_body` — rather than listed at each
   * call site. Listing them twice is how the scratch pad came to be saved as
   * nothing: the payload carried it and this method quietly dropped it.
   */
  async save(state) {
    const { body, encoding } = await maybeGzip(JSON.stringify(_body(state)),
                                               { downgrade: this.downgrade });
    const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() };
    if (encoding) headers['Content-Encoding'] = encoding;
    const resp = await fetch(`${this.base}ink/`, { method: 'PUT', headers, body });
    if (!resp.ok && encoding) {
      // The server could not read what we sent. Remember that, then send this
      // save again as plain bytes rather than making the reader wait for a
      // retry loop that would fail the same way.
      this.downgrade.note(resp.status);
      if (this.downgrade.off) return this.save(state);
    }
    return resp.ok;
  }

  /**
   * Last-gasp save when the page is going away.
   *
   * `keepalive` rather than sendBeacon: a plain fetch is cancelled on unload,
   * but sendBeacon cannot set the CSRF header and would need its own endpoint
   * that reads the token out of the body. keepalive keeps one route and one
   * code path.
   *
   * Its 64 KB payload limit was once described here as one a page of ink is
   * "nowhere near". That was wrong by two orders of magnitude: a save carries
   * the whole section, and a densely marked one measures several megabytes.
   * Over the limit the browser rejects the request outright, so this reports
   * whether it even tried — a section too big to leave this way is one the
   * reader must be held on the page for instead (see the beforeunload guard in
   * index.js).
   */
  saveOnExit(state) {
    const body = JSON.stringify(_body(state));
    if (body.length > KEEPALIVE_MAX_BYTES) return false;
    try {
      fetch(`${this.base}ink/`, {
        method: 'PUT',
        keepalive: true,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
        body,
      });
      return true;
    } catch (err) {
      return false;                 // the page is going away regardless
    }
  }

  async carryForward(from, to) {
    const resp = await fetch(`${this.base}ink/carry-forward/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify({ from, to }),
    });
    return { ok: resp.ok, status: resp.status };
  }
}
