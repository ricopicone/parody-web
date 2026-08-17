/** Talking to the ink endpoints. */

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

export class InkApi {
  constructor(base) {
    this.base = base;            // e.g. /one/alpha/
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
    const resp = await fetch(`${this.base}ink/`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify(_body(state)),
    });
    return resp.ok;
  }

  /**
   * Last-gasp save when the page is going away.
   *
   * `keepalive` rather than sendBeacon: a plain fetch is cancelled on unload,
   * but sendBeacon cannot set the CSRF header and would need its own endpoint
   * that reads the token out of the body. keepalive keeps one route and one
   * code path. Its payload limit is 64 KB, which a page of ink is nowhere
   * near.
   */
  saveOnExit(state) {
    try {
      fetch(`${this.base}ink/`, {
        method: 'PUT',
        keepalive: true,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
        body: JSON.stringify(_body(state)),
      });
    } catch (err) {
      /* the page is going away regardless */
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
