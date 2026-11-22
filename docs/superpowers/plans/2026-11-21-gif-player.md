# GIF Player Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every GIF figure on a parody-web page plays on a canvas with play/pause, frame stepping, a scrubber, a frame counter and fullscreen.

**Architecture:** A pure GIF decoder/compositor (`decode.js`) and a pure playback controller (`controller.js`), both tested under `node --test`; a thin DOM layer (`index.js`) enhances `img.figure-img` GIFs. esbuild bundles them to a committed `parody_web/static/parody_web/js/gifplayer.js`, loaded by `base.html`.

**Tech Stack:** ES2020 modules, `node:test`, esbuild (existing `esbuild.config.js`), Django templates, Pillow (fixture generation only, via `uvx --with pillow`).

**Spec:** `docs/superpowers/specs/2026-11-21-gif-player-design.md`

## Global Constraints

- No parody (build-side) change; no change to the section markup parody emits.
- The `<img>` stays in the DOM; any failure leaves it shown and untouched (today's behaviour).
- Fetch the GIF only after the `<img>` has loaded (HTTP-cache hit, not a second download).
- Delay under 20 ms plays at 100 ms. No NETSCAPE loop block = play once, stop on the last frame.
- `prefers-reduced-motion: reduce` starts paused on frame 1.
- Bundle committed; `static/parody_web/js/*.js` in `[tool.setuptools.package-data] parody_web`.
- Icons on the 24-grid, stroke 1.6, round caps/joins (as `_icon.html`).
- Version bump commits `pyproject.toml` AND `uv.lock` together; re-derive the version against `origin/main` at merge time.

## Review Focus

1. **A GIF from another tool** (disposal 2 or 3, interlaced, global palette only, first frame not full-size) — composites identically to Pillow. Fixtures in Task 2 cover each.
2. **Stepping backward across a snapshot boundary and from frame 0 to the last frame** — the pixels equal a straight forward decode. Task 2 test `random access equals sequential`.
3. **The reader pauses, scrolls away and back** — it stays paused; one who did not pause sees it resume. Task 3 test `offscreen pause does not override the reader's pause`.
4. **A truncated or non-GIF response** (HTML error page, cut-off file) — the decoder throws, the `<img>` stays. Task 1 test `rejects non-GIF and truncated input`.
5. **Two players on one page with focus in one** — keys act only on the focused player and never scroll the page or steal keys from inputs elsewhere. Task 4 (keydown listener on the player element, not `window`; `preventDefault` only for handled keys).

---

### Task 1: GIF structure parser

**Files:**
- Create: `assets/gifplayer/decode.js`
- Create: `assets/gifplayer/fixtures/make_fixtures.py`, `assets/gifplayer/fixtures/*.gif`, `assets/gifplayer/fixtures/expected.json`
- Test: `assets/gifplayer/decode.test.js`

**Interfaces:**
- Produces: `parseGif(bytes: Uint8Array) -> Gif` where `Gif = {width, height, loop: number|null, frames: Frame[]}` and `Frame = {x, y, w, h, delay (ms, floored as spec), disposal (0-3), transparent: number|null, interlaced: bool, palette: Uint8Array (RGB triples), minCodeSize, data: Uint8Array[] (LZW sub-blocks, subarrays of bytes, no copies)}`. Throws `Error` on a non-GIF or truncated file.

- [ ] **Step 1: Fixtures.** `make_fixtures.py` (run `uvx --with pillow python assets/gifplayer/fixtures/make_fixtures.py`) writes small GIFs (≤ 32×24 px, ≤ 8 frames): `delta.gif` (Pillow default save, optimised deltas + transparency, loop=0), `dispose2.gif` (disposal=2), `dispose3.gif` (disposal=3), `interlaced.gif` (interlace=True, ≥ 16 px each side), `global-only.gif` (one shared palette, no local tables), `once.gif` (no `loop` argument → no NETSCAPE block), `fast.gif` (duration=10 ms). It writes `expected.json`: per file `{width, height, loop, delays, frames: [sha256 hex of RGBA]}` from Pillow's `seek(i); convert("RGBA")`, with every alpha-0 pixel normalised to `0,0,0,0`. Check the fixtures in; confirm with the block parser used in brainstorming that `dispose3.gif` really carries disposal 3 and `interlaced.gif` the interlace flag (Pillow may silently drop either — if it does, hand-patch the flag bytes in the script and recompute nothing, since Pillow's expectation is then generated from the patched file).
- [ ] **Step 2: Failing tests** in `decode.test.js`: for each fixture, `parseGif` returns `expected.json`'s width/height/loop/delays and frame count; `fast.gif` delays are 100; `once.gif` loop is `null`; `parseGif(new TextEncoder().encode('<!doctype html>'))` throws; a fixture cut to half its length throws.
- [ ] **Step 3: Run** `node --test assets/gifplayer/*.test.js` — FAIL (module missing).
- [ ] **Step 4: Implement `parseGif`.** Walk the blocks: header, logical screen + global table, then extension (0x21: GCE 0xF9 for delay/disposal/transparency, application `NETSCAPE2.0` for loop, skip others by sub-blocks) / image descriptor (0x2C) / trailer (0x3B). Delay is centiseconds × 10; < 20 ms → 100. A frame with no local table uses the global one.
- [ ] **Step 5: Run** — PASS.
- [ ] **Step 6: Commit** `feat(gifplayer): parse a GIF's frames without decoding them`.

### Task 2: LZW decode and compositor with snapshots

**Files:**
- Modify: `assets/gifplayer/decode.js`
- Test: `assets/gifplayer/decode.test.js`

**Interfaces:**
- Consumes: `parseGif`, `Gif`, `Frame` (Task 1).
- Produces: `decodeIndices(frame: Frame) -> Uint8Array` (w×h palette indices, de-interlaced); `class Compositor { constructor(gif: Gif, {budget = 16 * 2**20} = {}); frame(i: number) -> Uint8ClampedArray /* width*height*4, owned by the compositor, valid until the next call */; get interval(): number /* K */; dropCache(): void }`.

- [ ] **Step 1: Failing tests:** every fixture frame composited in order hashes (sha256 via `node:crypto`) to `expected.json`; `random access equals sequential` — for `delta.gif` with a tiny budget forcing K = 2, request frames in the order `[5, 1, 7, 0, 6, 6, 3]` and each hash matches; after `dropCache()` frame 4 still matches; `interval` is ≥ 1 and `ceil(n·W·H·4 / budget)`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** Standard variable-width LZW (clear/end codes, 12-bit max, the KwKwK case). Compositing per frame i: apply frame i-1's disposal (2: clear its rect to transparent; 3: restore the rect saved before drawing it), save the rect first if frame i has disposal 3, then draw non-transparent indices. Snapshots: after composing frame j where `j % K === 0`, store a copy; `frame(i)` starts from the current state if `current ≤ i` and no nearer snapshot exists, else from snapshot `floor(i/K)·K` (re-decoding forward if that snapshot was dropped, from the nearest earlier one or frame 0). A snapshot also has to carry the disposal-3 saved rect pending for the next frame.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Real-GIF check (not committed).** A scratch script composites all eight robotics GIFs (`git -C ~/mr-integrate show origin/main:figures/<name>.gif`) and compares every frame's normalised hash with Pillow's; reports the time per forward frame and the worst backward step at the default budget for `door-frames.gif` (960×640, 80 frames). Expected: all frames match; worst backward step < 50 ms. If not, lower K (raise the budget) and record the measured numbers in the commit message.
- [ ] **Step 6: Commit** `feat(gifplayer): decode and composite any frame, with bounded snapshots`.

### Task 3: Playback controller

**Files:**
- Create: `assets/gifplayer/controller.js`
- Test: `assets/gifplayer/controller.test.js`

**Interfaces:**
- Produces: `class Controller { constructor({count: number, delays: number[], loop: number|null, render: (i) => void, schedule: (fn, ms) => handle, cancel: (handle) => void, onChange: (state) => void}); state: {frame, playing, pausedByReader}; play(); pause(); toggle(); step(d: number /* ±1 */); seek(i: number); first(); last(); setVisible(v: bool) }`. Every frame change calls `render(i)` then `onChange(state)`.

- [ ] **Step 1: Failing tests** with a fake scheduler (a list of pending `{fn, ms}`; the test runs them): playing advances one frame per scheduled callback, each scheduled with that frame's delay; at the last frame it wraps to 0 when `loop !== null`, stops when `loop === null` (and `play()` from the last frame restarts at 0); `step(+1)`/`step(-1)` wrap at the ends and pause; `seek`, `first`, `last` pause and clamp; `toggle()` flips; `offscreen pause does not override the reader's pause` — `pause()`, `setVisible(false)`, `setVisible(true)` stays paused, while `play()`, `setVisible(false)` (cancels the timer), `setVisible(true)` resumes.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** (no DOM, no timers of its own).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(gifplayer): playback state and frame schedule`.

### Task 4: The player on the page

**Files:**
- Create: `assets/gifplayer/index.js`, `parody_web/static/parody_web/js/gifplayer.js` (built)
- Modify: `esbuild.config.js` (third entry), `package.json` (`test` script adds `assets/gifplayer/*.test.js`), `.github/workflows/ci.yml` (same glob), `pyproject.toml` package-data (`"static/parody_web/js/*.js"`), `parody_web/templates/parody_web/base.html` (`<script type="module" src="{% static 'parody_web/js/gifplayer.js' %}"></script>` after the stylesheets), `parody_web/static/parody_web/css/content.css`
- Test: `parody_web/tests_gifplayer.py`

**Interfaces:**
- Consumes: `parseGif`, `Compositor` (Tasks 1–2), `Controller` (Task 3).

- [ ] **Step 1: Failing Django tests** (`SimpleTestCase`): pyproject declares `static/parody_web/js/*.js` for `parody_web`; the bundle exists and is < 30 KB; `base.html` loads `parody_web/js/gifplayer.js` as `type="module"`; a rendered section page (reuse the fixture-book helpers in `parody_web/tests.py`) contains that script tag.
- [ ] **Step 2: Run** `uv run python runtests.py` — the four FAIL.
- [ ] **Step 3: Implement `index.js`.** On `DOMContentLoaded`, for each `img.figure-img` whose `new URL(img.src).pathname` ends `.gif` (case-insensitive): when loaded (`img.complete && img.naturalWidth` or the `load` event), `fetch(img.currentSrc || img.src, {cache: 'force-cache'})` → `parseGif` → build `<div class="gif-player" tabindex="0">` holding `<canvas role="img" aria-label=alt width=W height=H>` and `<div class="gif-bar">` (buttons First / Step back / Play·Pause / Step forward, `<input type="range" min=0 max=N-1>` with `aria-valuetext="Frame k of N"`, `<span class="gif-count">k / N</span>`, Fullscreen), insert it before the `<img>`, set `img.hidden = true`; any throw → `console.warn` and leave the `<img>`. `render(i)` → `putImageData`. Click on the canvas toggles. Keydown on the player: Space/K toggle, ←/PageUp step −1, →/PageDown step +1, Home/End, F fullscreen; `preventDefault` only for these, and ignore events whose target is the range input for ← → Home End (the input handles them natively and fires `input` → `seek`). `IntersectionObserver`: visible ↔ `setVisible`; more than two viewports away → `compositor.dropCache()`. Reduced motion → do not autoplay. Fullscreen button: `requestFullscreen` or `webkitRequestFullscreen` on the player, hidden when neither exists. Copy the `id` of a bare `<img id=…>` (a caption-less figure) to the player so cross-ref anchors still land.
- [ ] **Step 4: CSS** in content.css: `.gif-player canvas` takes the image's rules (same `zoom: var(--fig-scale); max-width: 100%; height: auto`, the `--paper-panel` background and the dark-mode padding in BOTH dark selectors); `.gif-bar` a single row of 32 px buttons using existing tokens (`--ink-muted`, `--rule`), wrapping on phones; `:fullscreen` / `:-webkit-full-screen` player: `--paper` background, canvas `zoom: 1; width: 100%; height: calc(100vh - bar); object-fit: contain`.
- [ ] **Step 5: Build and run.** `npm run build`; `uv run python runtests.py` — PASS; `npm test` — PASS.
- [ ] **Step 6: Browser check.** Serve a section with a robotics GIF (example_site with the robotics artifact, or a static page using the built bundle and a copied GIF). Screenshot light and dark, desktop and 390 px wide: the canvas shows the frame at the image's size, the bar sits under it, the caption below. Via `javascript_tool`, call the buttons' `click()` and read the counter (wiring only — the automated tab is hidden, so real input and timing stay unverified and are said so).
- [ ] **Step 7: Commit** `feat(gifplayer): GIF figures play, pause and step on the page` (bundle included).

### Task 5: Release

- [ ] Version bump (minor, `0.107.0` unless main moved), `uv lock`, commit `pyproject.toml` + `uv.lock`; push branch to `main` after re-checking it is a fast-forward; build the wheel and confirm `parody_web/static/parody_web/js/gifplayer.js` is inside it (`unzip -l`).
- [ ] PyPI upload (`uvx twine upload dist/parody_web-0.107.0*`) — if auto mode refuses, hand Rico the line.
- [ ] homepage-django repin of parody-web on a branch in a worktree; deploy push to main (hand Rico the line if refused); after deploy, fetch a robotics section as staff or confirm `/static/parody_web/js/gifplayer.<hash>.js` is served, and ask Rico to try the player in his browser.
