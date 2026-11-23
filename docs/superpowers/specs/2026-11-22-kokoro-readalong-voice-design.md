# Read-along voiced by Kokoro, rendered on the laptop

Task 981 (parody project). Decided with Rico on 2026-11-22.

## Intent

Read-along is voiced by Amazon Polly today (`PollySynth`, voice Matthew, engine
`neural`). Polly bills the word-timing ("speech marks") request at the same rate
as the audio, so read-along pays **$32 per million characters**. The voiced
corpus is growing, and a partial re-voice was recently estimated at $20 or more.

Rico listened to Kokoro-82M (Apache-2.0, open weights) against the live Polly
tracks and likes it. **Voice: `am_puck`.** Kokoro is free to run, and its word
timings are exact by construction: the model's duration predictor sets how long
each phoneme lasts, and the audio is built from those same durations
(`KModel.forward_with_tokens` returns `pred_dur`, which `KPipeline.join_timestamps`
sums per token).

**Measured locally (M5 Pro, kokoro 0.9.4):**
- The text was rebuilt with parody-web 0.107.4 and its `text_key` matched the
  live S3 object, so the comparison used byte-identical text.
- 540/540 words got a timing, in order.
- About 10–11× faster than real time.
- Across electronics, system-dynamics and modern-robotics (435k spoken words),
  0.8% of words fall to espeak's guess. The frequent errors are fixable with
  phoneme overrides (see the correction table below).

## Goals

- Every released section of **electronics** and **modern-robotics** (the books
  whose `content-manifest.json` declares `readalong`) gets an `am_puck` track,
  and the reader plays it by default.
- **The production box never runs Kokoro.** It is a t4g.small: 2 burstable ARM
  vCPUs and 2 GB of RAM, shared with the site.
- **The box stays the single source of truth for the spoken text** and its
  `text_key`. The laptop voices exactly what the box asked for, so parody-web or
  SRE version skew between the two machines cannot produce audio for the wrong
  words.
- **A correction table** fixes known mispronunciations, and editing it re-voices
  only the sections that contain the changed words.
- **No reader loses audio during the cutover:** a section keeps playing its
  Matthew track until its Puck track exists.
- **The Polly path keeps working** (engine `neural`), unchanged and unmigrated.

## Amendments after approval (Rico, 2026-11-22)

- **System Dynamics gets read-along too.** homepage-django's
  `content-manifest.json` sets `features.readalong: true` for
  `system-dynamics`; its key artifact is already fetched for `map_clozes`. So
  the books are **electronics, modern-robotics and system-dynamics**.
- **The builder extends the correction table** from the measured hard-word
  report, and Rico reviews it by ear afterwards.
- **Audio lands as soon as it's voiced, with no deploy needed.** Rico doesn't
  want audio tied to the deploy. homepage-django gets a local script,
  `scripts/voice_readalong.sh`, that:
  1. runs the parody-web worker;
  2. sends one SSM command to the box, run as **`ubuntu`** (never root, see
     Constraints), that runs `generate_readalong <slug> --key-artifact …` for
     each book that had entries voiced.

  That run is the pickup in §3. parody-web's worker stays host-agnostic; the
  SSM step belongs to the host.
- **Rico authorized** the PyPI upload and the homepage-django `main` push for
  this work.
- **Out of scope here, its own project next:** streamlining the whole content
  release (local LaTeX and translation builds, landing in parallel as each
  finishes). This design's queue already lets audio land independently.

## Non-goals

- A custom voice in Rico's own voice: task 983.
- Rendering in CI. That's a later step, and the worker below is designed so CI
  can run it unchanged.
- Deleting the Matthew tracks or their audio.
- Per-book correction tables. A host setting can extend the shared table, but no
  book format changes.
- Tuning speed. Kokoro reads slower than Polly by default (212 s against 165 s on
  one section), and readers have a speed control.

## Anti-goals (failures even if it technically works)

- torch, Kokoro or a model download on the box.
- Audio whose words differ from the text its timings index.
- A deploy that fails, or reports a feature missing, because audio is still
  waiting to be voiced.
- The cutover leaving a section without audio while its Matthew track still
  exists. The fallback in §5 matches by section and slice, never by
  `text_key`, so the subscript change in §6 cannot break it. Matthew rows keep
  referring to their audio, so prune keeps that audio.
- A queued section silently serving nothing when a Matthew track exists.

## Constraints

- **The deploy** (`homepage-django/scripts/deploy_ec2.sh`) runs
  `check_book_features --heal` as root. That calls `generate_readalong <slug>
  --key-artifact …` with no voice or engine arguments, so the defaults are what
  production uses. `verify()` checks artifacts, not tracks.
- **Audio lives in S3** under the `readalong/` prefix of the media bucket
  (`AWS_STORAGE_BUCKET_NAME`, via the instance role). `prune_readalong_audio`
  runs weekly. It deletes objects under that prefix that no track's
  `audio_name` refers to, after a 7-day hold-back.
- **Box commands run by hand** must run as `ubuntu`, not root, or they poison
  the print cache.
- **The track view** picks a row by `section_key`, the current `slice_key` and
  `voice_id`. The voice is `?voice=` or the module constant
  `DEFAULT_VOICE = "Matthew"`, and the client sends no voice.
- **The laptop:** Python 3.14 is the default, but kokoro needs ≤3.12 (a uv venv
  works). On macOS, the espeak-ng bundled in `espeakng-loader` 0.2.x ignores the
  data path it is given and kills the process, so the worker must use Homebrew's
  espeak-ng (`brew install espeak-ng`). misaki uses espeak only for
  out-of-vocabulary words.
- **Shared repos:** parody-web is worked on by several sessions at once. Work
  in this worktree, and re-derive the version number at merge time.
- **Rico's go is needed** for the PyPI upload and for pushes to homepage-django
  `main`, which deploy.

## Approaches considered

1. **The box queues the exact text; the laptop voices the queue (CHOSEN).**
   The box stays as it is, version skew is impossible by construction, and a
   full re-voice takes about 2 hours on the M5. The cost is a manual step after
   a content release: new or changed sections have no read-along until the
   worker runs and the box picks the audio up.
2. **Kokoro on the box.** The smallest code change, but it needs torch and the
   model in 2 GB of RAM next to the site, at about real-time speed on burstable
   CPU, so a full re-voice would take most of a day on production. It would
   need a bigger, pricier instance. Rejected.
3. **A hosted Kokoro API from the box** (about $1 for everything). There's no
   laptop step, but whether word timings and phoneme overrides survive the
   host's API is unverified, and it adds a third-party dependency and an API
   key. Rejected for now.

## Design

### 1. Voice and engine are settings

- **New settings:** `PARODY_WEB_READALOUD_VOICE` (default `"Matthew"`) and
  `PARODY_WEB_READALOUD_ENGINE` (default `"neural"`).
- **`generate_readalong`:** `--voice` and `--engine` default to the settings,
  and `--engine` gains `kokoro`.
- **The track view:** reads the setting instead of the `DEFAULT_VOICE` constant.
- **homepage-django** sets `am_puck` and `kokoro`.

### 2. The correction table

- **Where it lives:** shipped in parody-web as data: `{word: misaki phonemes}`,
  used for the kokoro engine only. A host setting
  (`PARODY_WEB_READALOUD_PRONUNCIATIONS`, a dict) can add entries or override
  them.
- **How it's applied:** `spoken_form(text, engine)` wraps each whole-word match
  as `[word](/phonemes/)`, which misaki reads as an override. The match ignores
  surrounding punctuation like `(`, `,`, `;`, `:`, `.` and quotes, but tries the
  word with its trailing `.` first, so `e.g.` matches. Override tokens keep the
  word itself as their text, so timings still map onto the original text.
- **Other engines:** for `neural` and `standard`, `spoken_form` returns the text
  unchanged, **so every existing Polly `text_key` is unchanged.**
- **How it changes the key:** `_one` computes `text_key = text_key_for(spoken,
  voice, engine)`, where `spoken` is the annotated text. Editing the table
  therefore changes the key, and triggers a re-voice, only for sections
  containing the edited words. The marks still index `prep.text`, the
  un-annotated text, which is what `synthesise` maps byte offsets against.
- **Initial contents,** curated from the measured hard-word report and checked
  by ear on the `hard-*.mp3` samples:
  - Laplace, Kirchhoff/Kirchhoff's, Thévenin/Thévenin's.
  - The SRE ordinals: n-th, m-th, i-th, j-th, k-th, theta-th.
  - e.g. and i.e. read as "for example" and "that is".
  - The units mA, mH, mV, mW, pF, nF, kN.
  - ROS, SCARA, MIMO, SISO, MATLAB/matlab.
  - The 13 overrides already tested, plus whatever else the report shows to be
    both frequent and wrong.

### 3. The box side: a queued synth

`QueuedSynth(voice, engine, queue_store)` implements the existing synth seam,
`synth(text) -> (audio_bytes, marks)`:

- **If a voiced result exists**: when `done/<text_key>.mp3` and
  `done/<text_key>.marks.json` are in the queue store, it returns them. The marks
  are Polly-shaped: `{"time": ms, "type": "word", "start": BYTE offset into
  text, "value": word}`.
- **Otherwise it queues the text**: it writes `todo/<text_key>.json` (unless the
  file already exists) and raises `NotVoicedYet`. The entry carries `text`,
  `spoken`, `voice`, `engine`, `text_key`, `book`, `section` and `queued_at`,
  where `text` is `prep.text` and `spoken` is the annotated form.
- **What `_one` does with that:** catches `NotVoicedYet`, prints `queued
  <section>`, writes no row and returns a new outcome, `queued`. The summary line
  counts it. It is not an error, so the deploy passes.
- **Ordinary flow after that:** once the track row is written, the audio goes
  through `write_audio` under the usual name `f"{text_key}-{voice}.mp3"`, so
  prune and the audio view work as they do today. Then the two `done/` objects
  are deleted.
- **The queue store:** S3, under a separate prefix `readalong-queue/` in the
  same bucket, so prune never sees it. It's a directory under the cache root when
  no bucket is configured, for development and tests.
- **Wiring:** `generate_readalong` uses `QueuedSynth` when the engine is
  `kokoro`. It never imports kokoro or torch.

### 3b. A changed table or pronunciation rule re-voices on the next deploy

This is the builder's call, settled after the review. `_one`'s cheap exit
returns `have` whenever a row exists at the current `slice_key` with a
`text_key`, and it does so without preparing the text. The deploy's heal never
passes `--respeak`. So without a change here, editing the correction table or
the §6 subscript rule would queue nothing, and the old pronunciation would keep
playing with no error anywhere.

- **The row records a fingerprint.** `ReadAlongTrack.engine` stores an engine
  *id*: `kokoro@<fp>`, where `fp` is the first 12 hex characters of a sha256
  over the effective correction table (sorted JSON, including the host setting)
  and a `SPEECH_VERSION` constant in `speech.py`. That's 19 characters, which
  fits the existing `max_length=20`, so **no migration is needed**.
  `SPEECH_VERSION` is bumped whenever `build_speech` or `tidy_math_speech`
  changes what is said; the §6 rule is the first bump. Polly rows keep
  `neural` and behave exactly as today.
- **`text_key` hashes the engine family, `kokoro`, never the fingerprint.**
  Otherwise a one-word table edit would re-key, and so re-voice, every section.
- **The cheap exit also requires `exact.engine == current engine id`.** Past
  the exit, the ordinary logic already does the right thing:
  - **Unchanged spoken text** finds its prior by `text_key`. The row is
    re-stamped with the new engine id, with no audio work and no queueing.
    Extend the existing "text key recorded" branch to stamp the engine id too.
  - **Changed spoken text** finds no prior, so `QueuedSynth` queues it. The row
    keeps its old id, so every run until pickup passes the exit, re-finds the
    `done/` pair, and makes the track.
- **The cost:** after an edit, the first heal prepares every released section
  once (SRE plus a PDF parse, about a second each on the box). After that the
  cheap exit holds again.

### 4. The laptop side: the worker

The worker is `python -m parody_web_readaloud.voice_queue` (plus a console
script). It needs **no Django and no database**, only the bucket.

- **Options:** `--bucket` (default `$AWS_STORAGE_BUCKET_NAME`), `--region`,
  `--limit N`, `--dry-run` (list the queue, with characters and estimated
  minutes), and `--queue-dir` for a local queue.
- **Each `todo/` entry:**
  1. Render `spoken` with Kokoro, using `entry.voice`.
  2. Build the marks against `entry.text`.
  3. Encode the MP3.
  4. Upload `done/<key>.mp3` and `done/<key>.marks.json`.
  5. Delete `todo/<key>.json`.
- **Safe to stop and resume.** An entry whose `done/` pair already exists is
  just cleared.
- **The worker never applies the table itself.** It voices `spoken` exactly as
  the box wrote it, which is what rules out version skew.
- **Building the marks:** Kokoro's token `start_ts` values are relative to each
  generated chunk, so they're offset by the running audio length. Each
  whitespace word of `text` takes the start of its first token, found by a
  forward cursor search. A word that gets no token time is given an
  interpolated time between its neighbours, and the worker logs how many were
  interpolated. This needs a test: the prototype lost 2 of 114 words' times
  next to an override. Times must never decrease.
- **Packaging:** a `parody-web[kokoro]` extra pins kokoro 0.9.4, `misaki[en]`
  and an encoder, and documents Python ≤3.12.
- **The espeak bug:** at startup on macOS, the worker points phonemizer at
  Homebrew's espeak-ng after `import misaki.espeak`. If it isn't installed, it
  stops with the `brew install espeak-ng` instruction instead of crashing in C.
- **The model:** downloaded from Hugging Face on first use (`hexgrad/Kokoro-82M`).

### 5. The view falls back during the cutover

If there's no track for the configured voice at the current `slice_key`, the
track view serves the newest track of **any** voice for the same section and
slice. That's the Matthew track during the cutover. The JSON already carries
`voice_id`, and `audio_url` keeps `?voice=<row.voice_id>`, so the audio endpoint
serves the matching file. The audio endpoint needs the same fallback.

### 6. Subscripts are read without "sub" (Rico, 2026-11-22)

Rico wants `v_1` read as "vee one", not "v sub 1". **SRE's output never marks
where a subscript ends** (measured with parody-web 0.107.4's SRE):

| LaTeX | SRE says today |
|---|---|
| `v_{1} i_{1} = -v_2 i_2` | v sub 1 i sub 1 equals negative v sub 2 i sub 2 |
| `x_{k+1} = x_k + 1` | x sub k plus 1 equals x sub k plus 1 (both sides identical) |
| `a_{n-1}` | a sub n minus 1 |
| `q_{\text{in}}`, `V_{CC}`, `\mathbf{T}_{sb}` | q sub in, V sub C C, bold T sub s b |
| `\sum_{k=0}^{n} a_k` | the sum from k equals 0 to n of a sub k |

So the rule works per expression, using the LaTeX that `build_speech` already
holds for each maths token. This is the builder's call, open to Rico's override:

- **When every subscript is simple, drop every "sub".** A subscript is simple
  when it holds no operator, relation, comma, fraction, nested script or
  parenthesis. Digits, letters, one Greek letter, and `\text{…}`, `\mathrm{…}`
  or `\mathbf{…}` words all count as simple.
- **When any subscript is compound, the expression keeps every "sub",** because
  there "sub" is the only cue that a subscript started. Dropping it from
  `a_{n-1}` would make it sound like a·n − 1.
- **Where:** a pure-Python step in `speech.py`, next to `tidy_math_speech`, run
  on SRE's output. It does NOT touch `speak.mjs`, so the hand-installed copy on
  the box (`/srv/parody/sre/speak.mjs`) needs no update.
- **Scope:** it applies to every engine. It changes the spoken text, so it
  changes the `text_key` of every section with subscripted maths. That's free
  under Kokoro, since everything is being re-voiced anyway. Polly hosts pick it
  up only when they next re-voice.
- **Superscripts are unchanged:** "x 1 squared".

### 7. Rollout

0. **Precondition (builder's call, settled after the review): do steps 2–4 in
   one sitting, with no content release for electronics or modern-robotics in
   between.** The §5 fallback only matches the current `slice_key`, and after
   the flip nothing re-boxes Matthew rows. A reflow inside the window would
   leave every section not yet picked up with no audio, and §6 changes
   Matthew's `text_key` too, so `--realign` can't rescue it. Before starting:
   - check homepage-django `origin/main` for repins not yet deployed, since the
     deploy ships whatever is on main;
   - check `gh run list` for deploys in progress;
   - ask other sessions not to release either book until step 4 is done.

   The window is about 2–3 hours. A code path that makes Matthew survive a
   reflow was rejected as more machinery than a few-hours freeze warrants.
1. **Release parody-web** with a minor version bump, after Rico's go for PyPI.
2. **homepage-django:** repin, set `PARODY_WEB_READALOUD_VOICE=am_puck` and
   `PARODY_WEB_READALOUD_ENGINE=kokoro`, then deploy, after Rico's go. The
   deploy's heal queues every released section and serves Matthew meanwhile.
3. **Laptop:** run the worker. The first full run is about 2 hours, less
   because only released sections are queued.
4. **The box:** run `generate_readalong` for both books as `ubuntu` over SSM (or
   just deploy again). It reports `made` for each section.
5. **Verify:**
   - Count `am_puck` tracks against released sections in Postgres.
   - Load one section in the reader and confirm the audio is Puck and the
     highlight follows the voice.
   - Confirm the `todo/` queue is empty.
6. **From then on,** after a content release: deploy (queues), then worker, then
   re-run the box step.

## Left to the builder

- The MP3 encoder: `soundfile` with MPEG support, `lameenc`, or ffmpeg. Prefer
  pure Python if it encodes 24 kHz mono reliably.
- Exact CLI and console-script names.
- Queue JSON details beyond the fields listed.
- Test structure. There must be tests for:
  - unchanged Polly keys;
  - annotation with punctuation;
  - the marks builder, including interpolation and monotonicity;
  - the `QueuedSynth` hit, miss and idempotent re-queue;
  - `_one`'s `queued` outcome writing no row;
  - the view fallback.
- How to fake Kokoro in tests: tests must not download the model.
