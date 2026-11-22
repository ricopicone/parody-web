# Animated figures get play controls and frame stepping

Status: approved by Rico 2026-11-21 (parody task #974). Short design.

## Why

Robotics carries eight GIF figures (screw motions, Jacobian columns,
manipulability ellipsoids). Each prints its numbers as the motion runs — the
angle, $T(\theta)$ — and the point of several is a particular moment. Students
reading on their own, and Rico when he lectures, want to stop on a moment and
step through it a frame at a time. Today they cannot: the web renders each as a
plain `<img>`, and a browser offers no way to pause a GIF in an `<img>`. Each
loops forever, which also misses WCAG 2.2.2 (moving content needs a pause).

## What exists

- parody's filter.lua emits a GIF figure as
  `<img src="{% media '…gif' %}" class="figure-img" loading="lazy">` (only GIFs
  get `loading="lazy"`); parody-web's numbering wraps captioned ones in
  `<figure id="fig:…">` with a `<figcaption>`.
- Media is same-origin on every host (`/media/`, nginx proxies the bucket), so a
  page script can `fetch` the GIF's bytes. No CORS work.
- The eight GIFs: 60–80 frames, 4–5 s, 0.7–1.6 MB, 576–960 px wide, written by
  Pillow. Every frame after the first is a **delta** — a sub-rectangle with
  transparency drawn over the previous frame (disposal 0), with its own colour
  table. Frame k therefore depends on frames 0…k-1. Per-frame delays are 50 ms
  with 450/850 ms holds at the ends.

## Approaches

1. **Client-side player in parody-web (chosen).** A script finds each GIF figure,
   decodes the GIF itself, draws frames on a canvas and adds a control bar. No
   build, content or markup change; every existing GIF in every book gets it on
   the next parody-web deploy; with the script absent or failing the reader keeps
   today's looping GIF.
2. Build-time conversion to video. ~10× smaller files, native controls — but
   video cannot reliably step *backward* one frame (keyframe seeking, inexact
   frame times), and stepping is the point. Also touches parody's markup,
   media staging and goldens. Rejected.
3. Build-time frame sheets + JSON timing. More pipeline and bigger downloads, and
   it still needs the same player. Rejected.

Decoder: our own (~200 lines, LZW + compositing), not WebCodecs `ImageDecoder`:
Safari's support for it could not be confirmed and students use iPads. One code
path, unit-testable under `node --test`.

## Design

**What the reader sees** — the figure's canvas in place of the image, a slim bar
under it, the caption unchanged:

```
┌──────────────────────────────┐
│      (animation canvas)      │
└──────────────────────────────┘
 ⏮  ◀︎  ⏸  ▶︎  ━━━━●━━━━━━━  37 / 80  ⛶
Figure 3.4: The door opens to 100°…
```

- First frame, step back, play/pause, step forward, a frame scrubber, a
  "k / N" counter, fullscreen (lecture: one frame fills the projector).
- Click on the canvas toggles play/pause. With the player focused: Space or K
  plays/pauses, ← → step, Home/End first/last, F fullscreen. PageUp/PageDown
  step too, because presentation clickers send them.
- Stepping or scrubbing pauses playback.
- Each frame keeps its own GIF delay (the end holds still hold). A delay under
  20 ms plays at 100 ms, as browsers do.
- Autoplays and loops, as the GIF does today — except under
  `prefers-reduced-motion: reduce`, where it starts paused on frame 1.
- Pauses itself while scrolled out of view and resumes on return, unless the
  reader paused it.
- Fullscreen hides itself where the Fullscreen API is unavailable (iPhone).
- Accessible: canvas is `role="img"` with the image's alt; buttons are real
  `<button>`s with labels; the scrubber is a range input whose value text reads
  "Frame 37 of 80".

**How**

- `assets/gifplayer/decode.js` (pure): parse the GIF's block structure without
  decoding pixels; LZW-decode one frame on demand (interlace handled); a
  compositor that returns the composited RGBA of frame i, honouring disposal
  0/1/2/3 and transparency.
- Random access: the compositor keeps full-frame **snapshots** every K frames as
  it decodes forward, and reaches frame i by decoding forward from the nearest
  snapshot at or before it. K is chosen per GIF so snapshots stay within a fixed
  memory budget; snapshots are a cache, dropped when the figure is far off
  screen and refilled on the next forward pass. Budget and K set by measurement
  (target: a backward step under ~50 ms on a laptop for the largest GIF).
- `assets/gifplayer/controller.js` (pure): play/pause/step/seek state and the
  frame schedule against an injected clock — tested without a DOM.
- `assets/gifplayer/index.js`: DOM wiring. Enhances `img.figure-img` whose URL
  path ends `.gif`, after the image has loaded (so the `fetch` is served from
  the HTTP cache, not a second download). The `<img>` stays in the DOM, hidden,
  as the fallback; any failure leaves it shown and untouched.
- Bundled by esbuild to `parody_web/static/parody_web/js/gifplayer.js`
  (committed, as the other bundles are); added to `package-data` (a static file
  missing there is silently absent from the wheel). Loaded from `base.html` as a
  module — every book page, a no-op without GIFs. CSS in content.css: the canvas
  takes the image's figure rules (`--fig-scale` zoom, max-width, dark-mode
  panel).

## Non-goals

- Video figures (.mp4/.webm) on the web — none exist; print already handles them.
- Speed control, A–B loops, per-figure authoring attributes. Easy to add later.
- Any parody (build-side) change.

## Left to the builder

Icon drawing (24-grid, 1.6 stroke, matching `_icon.html`), exact bar styling,
the snapshot budget, and the loop rule for a GIF with no NETSCAPE loop block
(play once and stop on the last frame, as browsers do).
