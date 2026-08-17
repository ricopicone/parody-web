# Read-along: TTS-paced reading with fill-in-the-blank clozes

**Task:** parody #606. Origin: ME 345 #605 (flipped vs. traditional).
**Status:** design agreed in brainstorming; not yet implemented.

## What it is

A reading mode that reads a section aloud at lecture pace over the section's
**PDF**, highlighting each word as it is spoken. At marked terms the page
carries a typeset blank. The answer is spoken, and shown briefly above the
blank; the student writes it into the blank with the existing pen, then
continues. The filled-in blanks are the pre-class submission.

Three things it buys that assigned reading does not: it paces the student at
~150 wpm instead of letting them skim; it produces an accountability artifact
they were going to produce anyway; and that artifact doubles as a defect
report on which passages of the notes are weak.

At ~10 students the instructor eyeballs the canvases before class. **There is
no grading and no handwriting recognition.** The act of writing is the point.

## Why the PDF, not the HTML

The task description assumed the HTML reading surface. It is the PDF, because
the annotation tool students write with already exists there
(`parody_web_annotate`, shipped 0.44.1, now 0.49.0) and writing by hand is the
whole mechanism.

That inverts what the task description recorded as a hard constraint. It said
the fade and the writing space must not coincide, because the annotation
canvas covers the prose. On the PDF that is backwards: a canvas covering the
page is exactly what you want, because the page has a hole in it. The blank
*is* the writing space.

Corrections to the task description, all verified in code:

- The PDF annotator is **Konva + perfect-freehand + pdf.js**, not Fabric.js.
  Fabric is homepage-django's *HTML* `_section_overlay.html` — a different
  surface. The task's decision 5 was written about the wrong one.
- **Decision 1 is overturned.** This ships in parody-web, not homepage-django.
  The client overlay has to live in the same bundle as the viewer it draws on,
  and the server side reuses `slice_key`, the print archive, and the access
  policy that `parody_web_annotate` already established. Splitting one feature
  across two repos to keep Polly credentials host-side is not worth it.
- **Decision 6 is already built.** parody ships cloze end to end:
  `[answer]{.cloze}` → `\cloze{}`, `\clozeblank{}`, `\clozelines{}`,
  `clozeblock`, on a `--clozes blank|key|full` axis
  (`parody/filters/print.lua:126`, `profiles/print/parody-print.sty:53`).
- **Decision 2's SRE plan needs a carrier.** SRE consumes LaTeX or MathML; a
  PDF carries neither. See "Math" below — the artifact HTML turns out to carry
  exactly what SRE wants, so no new build artifact is needed for math.

## Decisions taken in brainstorming

**1. The blank is typeset, not masked at runtime.** Serve a `--clozes blank`
build. `\cloze` measures its rule with `\settowidth` to the hidden answer, so
the blank is exactly as wide as the word that belongs in it — which is also
exactly the width of the text we reveal. No runtime masking, no geometry to
maintain, and nothing to go wrong under zoom or the dark-mode filter.

**2. Karaoke word highlight** marks the reader's place, word by word, driven by
Polly word timings against a per-page overlay. Rejected: highlighting only the
live blank (too weak a pacing cue — pacing is the point), and a line band
(coarser, and its only real advantage was hiding per-word error we do not
expect to have).

**3. The answer is revealed, not withheld.** It is spoken, and shown as text.
Withholding it would be pedagogically stronger in the abstract, but this is a
reading-pacing tool with an engagement artifact, not an assessment. Revealing
makes the interaction forgiving and the failure modes benign.

**4. Persistence is copy-length, not recall-length.** The reveal holds long
enough to copy, and playback resumes on the student's explicit continue. The
model is the board in class: it stays up while you write it down. This applies
to text and figure clozes alike — one rhythm, one control.

**5. It ships as a third app**, `parody_web_readaloud`, beside `parody_web` and
`parody_web_annotate` in the parody-web distribution.

## Architecture

Three pieces, split by where the knowledge already lives.

### parody (build side) — no change at all

The published artifact is built `--clozes blank` and must stay exactly as it
is. `filter.lua:737` states the invariant plainly:

> In `blank` the hidden text is NEVER written into the HTML: anything this
> filter emits is fetchable by the reader, so the answer is replaced here at
> build time, not hidden with CSS. […] Only the referenced file is staged into
> media/, so in `blank` mode the complete artwork is never published.

An earlier draft of this spec proposed adding a `clozes` list carrying the
answers to that artifact. **That was wrong** — it breaches the invariant for
every reader of the ordinary web book, not just this mode, and it would not
have solved figures anyway, since blank mode never stages the complete
artwork.

The right source is a **second artifact built `--clozes key`**, generated at
build time and never published. That mode already gives all three things:

- answers present and *explicitly marked*, as `<span class="cloze-key">`
  (`filter.lua:775`; math clozes get `\class{cloze-key}{…}` at :853)
- complete figure artwork rendered and staged, because `cloze_variant_src`
  returns `nil` for any mode that is not `blank` (`filter.lua:795`)
- math as `\(…\)` / `\[…\]`, as in any build

So the build emits two artifacts: `blank` (published, unchanged) and `key`
(build-time input to read-along, never served). `parody build --clozes key`
already exists (`cli.py:319`). The extra cost is one pandoc pass — no LaTeX
compile. Answers reach a client only through the gated read-along payload.

This is what makes the marker question disappear: read-along never has to
guess which words were clozed, because `key` mode tells it.

### parody_web_readaloud (server side)

Generation runs at import or on instructor trigger. **Never on request** — see
"Cost and access" below.

For each section:

1. Take the section's HTML from the **`key` artifact**. This is the text
   source: clean prose, correct reading order, no running heads, no folios, no
   hyphenation, no page breaks. Every one of those is an artifact of reading
   text out of a PDF, and none of them exist here. It also carries the marked
   answers and the complete figure artwork for the reveals.
2. Take the served section PDF (`printing.section_pdf_path`) for geometry.
   Extract words with boxes per page (PyMuPDF, the approach in wolfgang's
   `readaloud/services.py:13 extract_pdf_words`).
3. **Align the two streams** (see below), producing a word list where each
   spoken word carries a page and a box.
4. Locate each blank. The rules are vector strokes, so `page.get_drawings()`
   finds the horizontal rules directly and exactly; the alignment gap between
   the words either side of a blank is the fallback.
5. Synthesise the whole section, answers included, and cache the audio.

Keyed by **`slice_key`** — the per-version PDF key `InkLayer` already uses
(`printing.slice_key_for`, a hash of the section's own page content streams).
Ink and audio then invalidate together instead of drifting apart, and the
cache-invalidation worry in the task's decision 4 is answered by machinery that
already exists.

### The client

A read-along layer per page, a third sibling in `entry.el` beside the pdf.js
canvas and the Konva ink layer, created and released on
`onPageReady`/`onPageGone`. Boxes are PDF points scaled through
`entry.viewport`. It ships in the existing esbuild bundle.

## The alignment

The join between clean text and page geometry is a diff-style sequence
alignment, not an identity.

Both streams derive from the same source in the same order, so they agree
almost everywhere, and the disagreements **self-classify**:

- a PDF token matching nothing → page furniture (running head, folio, crop
  mark)
- two PDF tokens matching one HTML token → a hyphenated line break

These stop being hand-written heuristics and become fallout of one algorithm.
Anchor on long unique token runs so local noise cannot derail it.

**Clozes are the one place the streams disagree by design**, and both sides
mark it. The `key` HTML has the answer wrapped in `<span class="cloze-key">`;
the `blank` PDF has a vector rule where those words would have been. So a
clozed answer shows up as a run of HTML tokens matching nothing, *and* as a
rule found by `get_drawings()` at that position. Two independent signals for
the same thing: the span says what the answer is and that one belongs here, the
rule says exactly where on the page it goes. A gap with no corresponding rule
is alignment noise, not a cloze — which is how the aligner tells the two apart.

The spoken stream is therefore the whole `key` text, answers included, and the
blanks are the subset of it the page declines to print.

**Known limit: float reordering.** LaTeX moves figures and tables to page
tops, so a caption sits at a different point in PDF reading order than in the
HTML. Alignment handles insertions and deletions cleanly; a transposition is
harder. The out is that captions are not read aloud, so they can simply stay
unmatched, in the same bucket as running heads — prose order is untouched.
Enforcing `[H]` placement book-wide was offered and **declined**: it is a real
typographic cost across the whole house style for a risk we can absorb. Revisit
only if the prototype shows the aligner slipping.

## The interaction

One cloze, from the top:

1. The karaoke highlight advances word by word, driven by Polly timings.
2. It reaches a blank. The answer appears on a paper-coloured plate **above**
   the blank, and is spoken.
3. The plate holds. Playback is paused.
4. The student writes the answer into the blank with the pen.
5. They continue (space, or tap). The plate fades and playback resumes.

**Above, not in.** The blank is where the student writes; the reveal cannot
occupy it. Above rather than below because a stylus hand rests below the line
being written, so a plate below is the one that ends up under the palm — and
because reading up then writing down matches the movement you want. The plate
occludes a line of prose while visible, which is acceptable: it is transient,
and the student is listening rather than reading ahead.

**Figure clozes** reveal into the **margin pad** instead — half a page wide,
immediately adjacent, and unable to cover the incomplete figure being drawn
into. They have nothing to speak, so audio simply stops. One caution: the pad
is itself an ink surface whose strokes are glued on at export, so the reveal
must be a transient overlay that the exporter cannot mistake for pad content.

**Skip-ahead** seeks to the end of the current math region, for when an
expression is long and the student wants to move on. Each expression is
already a first-class timed region, so this composes.

## Math

The artifact HTML carries math as `<span class="math inline">\(…\)</span>` and
`<span class="math display">\[…\]</span>` — measured at 2,426 and 335
respectively in rtc. That is precisely SRE's input format, already isolated in
tagged spans. **So no sidecar and no new build artifact are needed.** SRE runs
on the HTML directly and its output is spliced into the spoken text as a timed
region.

Inline math must be spoken. It is woven mid-sentence — on a math-heavy page
most text lines carry a symbol or two, e.g. *"the Fourier transform of the
sampling function 𝑝(𝑡) is an infinite train of…"* — so dropping it leaves
sentences without their subjects.

**Fallback if SRE output proves unusable on dense expressions:** skip display
math (the eye carries it, and unlike in HTML the student is looking at properly
typeset math) while keeping inline math spoken. Decided in advance so the
prototype does not stall on it.

## Cost and access

**No new access tier.** The book's existing policy (public / `authenticated` /
`owner`) governs who reaches a section, and the mode inherits it via the same
`can_download_section_pdf` question `parody_web_annotate` asks. Safe because
cached audio makes cost constant in the number of listeners.

**The audio endpoint is serve-only.** Generate at import or on instructor
trigger; 404 rather than synthesise on a miss. Lazy synthesis is the one path
where an anonymous visitor to a public book could mint new audio, and the only
way cost starts tracking requests instead of content. This is a design
constraint, not a gate.

Polly neural is ~$16/1M characters (standard ~$4/1M; verify current pricing).
Cost scales with content × voices × re-synthesis. The real exposure is the
weekly chapter refresh busting the cache — mitigated by caching per section
rather than per chapter, and by drafting on the standard engine and switching
to neural at a freeze. Count characters in the Primer and chapters 1–4 before
committing.

Because the answers are spoken, the audio is simply the section read straight
through, so it does not depend on cloze placement at all. Changing which terms
are blanked rebuilds the PDF but never re-synthesises. Prototype freely.

## Naming

The mode is **Read-along** in the UI; the app is `parody_web_readaloud`.

Task #606 is still titled "Live reading mode: TTS-paced sections with fading
cloze items", which described an earlier design in which a word printed on the
page dissolved. Nothing on the page fades now — a reveal fades in and out
*above* the blank. Retitle the task to match the mode.

## Measured: does the alignment actually work?

Tested against real content before building the rest — 10 sections of rtc
(120 in the artifact, those over 120 words), aligning each section's artifact
HTML against the pages of the typeset PDF that hold it:

| | placed |
|---|---|
| median | 99.9% |
| mean | 98.4% |
| worst | 93.9% |

"Placed" means a speakable token (prose or math) that came away with a box.

This is a harder test than production will be. The PDF is the *ancestor's*
LaTeX build rather than parody's, and the harness over-grabs page ranges, so
page words outnumber script words roughly 3:1 — every one of those extras is
furniture the aligner had to reject. It still placed essentially everything.

Worth stating precisely: this measures placement *rate*, not placement
*correctness*. It shows the aligner is not dropping the stream on real prose;
it does not prove every box is the right one. That needs eyes on a rendered
page, which is the first thing to check once a track exists.

## Risks

- **Float reordering** derailing the aligner. Absorbed as unmatched captions;
  `[H]` placement held in reserve.
- **pdf.js holds only ~3 page canvases** (`windowAround(…, 1)` in `pages.js`).
  Audio can outrun a released page, so playback must drive scroll and await
  the render rather than assume a layer exists.
- **Dark mode inverts the page canvas via a CSS filter.** The highlight and the
  reveal plate must sit deliberately inside or outside that filter, or they
  come out the wrong colour.
- **Auto-scroll fighting the reader**, who is also scrolling and drawing.
- **SRE output length** on dense expressions; fallback decided above.

## v1 cut

In: text and figure clozes, karaoke highlight, reveal-and-continue, inline
math via SRE, serve-only cached audio, one voice.

Out: display-math speech if SRE disappoints, grading or handwriting
recognition (never), multiple voices, cross-encounter clozing (a term met three
times coming up blank the fourth), and any automatic selection of what to
blank — cloze targets are hand-marked during the chapter refresh, which is
nearly free when you are already editing the prose.

## Scope guard

ME 345 starts imminently. Week one runs on notes-as-pre-work with a manual
pre-class submission (task #605). This mode replaces that submission around
week 3–4 if it ships. **It must not gate the format decision.**

## Related

`docs/superpowers/specs/2026-08-16-pdf-annotation-design.md` (the surface this
draws on), `docs/host-integration.md` (the seams), and the project memories
`pdf-annotation-app-and-versioning`, `print-pdf-text-extraction-facts`,
`cloze-rendering-three-mode-axis`.
