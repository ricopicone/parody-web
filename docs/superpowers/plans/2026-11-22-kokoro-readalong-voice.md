# Kokoro Read-along Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Voice read-along with Kokoro (`am_puck`) on a laptop worker. The box
queues the exact text and picks up the result. It also adds a correction table,
subscripts read without "sub", and a fallback to Matthew during the cutover.
The first real run is System Dynamics chapters 1–4.

**Architecture:**
- `generate_readalong` under engine `kokoro` uses a `QueuedSynth`. It writes
  `todo-<text_key>.json` into an S3 queue prefix, or returns the
  `done-<text_key>.mp3`/`.marks.json` pair a worker left there.
- A Django-free worker (`parody-voice-queue`) renders the queue with Kokoro.
- homepage-django flips its settings, enables read-along for System Dynamics,
  and gets a local script that runs the worker and then triggers the box pickup
  over SSM.

**Tech Stack:** Django 5 (parody-web), kokoro 0.9.4 + misaki[en] 0.9.4 (Python
≤3.12, laptop only), soundfile, boto3, AWS SSM.

**Spec:** `docs/superpowers/specs/2026-11-22-kokoro-readalong-voice-design.md`
(approved, with the amendments section).

## Global Constraints

- **Voice and engine:** voice `am_puck`, engine `kokoro`. Polly (`neural`,
  voice `Matthew`) keeps working unchanged.
- **Never on the box:** kokoro, misaki, torch or soundfile, and nothing the box
  imports may import them. Only `kokoro_worker.py` touches them, lazily.
- **Neural keys must not move:** for `neural`/`standard`, `text_key` is
  byte-identical to today's (`spoken_form` returns the text unchanged).
- **The `text_key` input:** `text_key_for(spoken, voice, "kokoro")` hashes
  `spoken`, the annotated text, and the engine family `kokoro`, never the
  fingerprint.
- **The row's `engine`:** stores the engine id `kokoro@<12 hex>`, which must
  fit `max_length=20` (no migration).
- **Queue names:** `safe_name` rejects `/`, so queue objects use flat names
  under prefix `readalong-queue/`: `todo-<key>.json`, `done-<key>.mp3`,
  `done-<key>.marks.json`.
- **Mark shape:** `{"time": ms, "type": "word", "start": BYTE offset into text,
  "value": word}`, with times non-decreasing.
- **Box commands:** run as `ubuntu`, from `/srv/homepage-django`, with `.env`
  sourced, using `.venv/bin/python manage.py …`. Instance
  `i-0ed702541a200396d`, region `us-west-2`.
- **Packaging:** every new data file goes in `[tool.setuptools.package-data]`.
- **Version bumps:** commit `uv.lock` with the bump, and re-derive the version
  against `origin/main` at merge time. Never `git add -A`.
- **Tests:** `uv run python runtests.py` from the worktree. Tests must not
  import kokoro or download a model.

## Review Focus

1. **A section whose text changes between queue and pickup.** The new text
   gets a new key, so the old `done-` pair is never used. It must not be
   consumed for the wrong text; the prune-free queue just keeps it, which is
   harmless. Test: `test_pickup_ignores_done_pair_for_other_text` (Task 5).
2. **A word with no Kokoro token time,** which happens next to overrides and
   with punctuation-only tokens. It gets an interpolated time, never a missing
   mark or a decreasing time. Test: `test_interpolates_untimed_words` (Task 6).
3. **Explicit `?voice=` against the configured default.** The audio endpoint
   must serve the row the track JSON named, even when it's the fallback voice.
   Test: `test_audio_follows_fallback_voice` (Task 4).
4. **Big-operator limits** (`\sum_{k=0}^{n} a_k`) must not count as compound
   subscripts, so "sub" still drops from `a_k`. Test:
   `test_big_operator_limits_are_not_subscripts` (Task 1).
5. **Re-running the box step before the worker has finished** must re-queue
   idempotently: same JSON, `queued_at` unchanged, no row written. Test:
   `test_requeue_is_idempotent` (Task 3).

---

### Task 1: Subscripts without "sub", and SPEECH_VERSION

**Files:**
- Modify: `parody_web_readaloud/speech.py` (new functions, `build_speech`)
- Test: `parody_web_readaloud/tests_speech.py`

**Interfaces:**
- Produces:
  - `SPEECH_VERSION: str = "2"`.
  - `subscripts_are_simple(latex: str) -> bool`.
  - `terse_subscripts(said: str, latex: str) -> str`.
  - `build_speech` applies `terse_subscripts` to every spoken maths item (the
    `math` tokens and `cloze` tokens with latex) using that token's `latex`.

- [ ] **Step 1: Write failing tests** in `TerseSubscriptTests`:
  - `test_simple_subscripts_drop_sub`: `terse_subscripts("v sub 1 i sub 1
    equals negative v sub 2 i sub 2", r"v_{1} i_{1} = -v_2 i_2") == "v 1 i 1
    equals negative v 2 i 2"`.
  - `test_compound_subscript_keeps_every_sub`:
    `terse_subscripts("x sub k plus 1 equals x sub k plus 1", r"x_{k+1} = x_k
    + 1")` is unchanged.
  - `test_word_subscripts_are_simple`: `subscripts_are_simple(r"q_{\text{in}}
    + \tau_{\mathrm{max}} + V_{CC} + \mathbf{T}_{sb} + \theta_1")` is True.
  - `test_compound_forms`: each of `a_{n-1}`, `x_{i,j}`, `x_{(k)}`,
    `y_{\frac{1}{2}}` and `z_{a_b}` gives False.
  - `test_big_operator_limits_are_not_subscripts`: `terse_subscripts("the sum
    from k equals 0 to n of a sub k", r"\sum_{k=0}^{n} a_k") == "the sum from
    k equals 0 to n of a k"`. The same holds for `\prod`, `\int`, `\lim`,
    `\max` and `\min`, with or without `\limits`.
  - `test_escaped_underscore_is_not_a_subscript`:
    `subscripts_are_simple(r"\text{max\_speed}")` is True.
  - `test_only_whole_word_sub`: `terse_subscripts("x sub 1 subtract", "x_1")
    == "x 1 subtract"`.
  - `test_build_speech_applies_rule`: with a fake math whose `speak_all`
    returns `["v sub 1"]` for latex `v_1`, `build_speech` gives text `"v 1"`,
    and `owners` has the same length as `text.split()`.
- [ ] **Step 2: Run them and confirm they fail:** `uv run python runtests.py`
  (or the module label `parody_web_readaloud.tests_speech`).
- [ ] **Step 3: Implement.**
  - **Scanning:** walk the latex for unescaped `_`. The argument is the next
    char, a balanced `{…}` group, or a `\command` (taking its `{…}` argument
    when it's one of `\text \mathrm \mathbf \mathit \mathsf \operatorname`).
    Skip a `_` whose base, ignoring `\limits`/`\nolimits`, is one of `\sum
    \prod \int \oint \lim \max \min \sup \inf \bigcup \bigcap`.
  - **Simple:** after unwrapping one such wrapper, the content matches
    `^\s*(?:[A-Za-z0-9]+|\\[A-Za-z]+)\s*$`.
  - **Dropping:** `terse_subscripts` drops the whole word `sub` only when every
    subscript is simple.
  - **The docstring** must say this changes the spoken text, and so every
    affected section's `text_key`.
- [ ] **Step 4: Run them and confirm they pass.** Run the full suite too, since
  the existing speech tests may assert "sub" and need updating.
- [ ] **Step 5: Commit** `feat(readalong): read simple subscripts without "sub"`.

### Task 2: The correction table, spoken_form and engine_id

**Files:**
- Create: `parody_web_readaloud/pronunciations.json`, `parody_web_readaloud/pronounce.py`
- Modify: `pyproject.toml` (package-data: `parody_web_readaloud = [..., "pronunciations.json"]`)
- Test: `parody_web_readaloud/tests_pronounce.py`,
  `parody_web_readaloud/tests_packaging.py`

**Interfaces:**
- Consumes: `speech.SPEECH_VERSION` (Task 1).
- Produces (`pronounce.py`):
  - `KOKORO = "kokoro"`.
  - `KOKORO_VOCAB: frozenset[str]`: the 114 symbols of Kokoro-82M's
    `config.json` vocab, copied as a literal.
  - `load_table() -> dict[str, str]`: the packaged JSON, updated with
    `settings.PARODY_WEB_READALOUD_PRONUNCIATIONS` when that's set.
  - `spoken_form(text: str, engine: str, table: dict | None = None) -> str`.
  - `engine_id(engine: str, table: dict | None = None) -> str`.
  - `engine_family(engine_id: str) -> str`, which returns the part before `@`.

- [ ] **Step 1: Seed `pronunciations.json`** with the 13 tested entries,
  exactly:

```json
{"e.g.": "fɔɹ ɪɡzˈæmpəl", "i.e.": "ðˈæt ɪz", "Kirchhoff's": "kˈɪɹkɔfs",
 "Thévenin": "tˈAvənˌɪn", "Laplace": "ləplˈɑs", "mA": "mˈɪliˌæmps",
 "mH": "mˈɪlɪhˌɛnɹiz", "n-th": "ˈɛnθ", "ROS": "ɹˈɑs", "SCARA": "skˈɑɹə",
 "MIMO": "mˈImO", "SISO": "sˈIsO"}
```

  (Task 7 extends it.)
- [ ] **Step 2: Write failing tests:**
  - `test_neural_text_is_untouched`: `spoken_form(t, "neural") is t` for a
    text containing table words.
  - `test_kokoro_wraps_whole_words_with_punctuation`: the input `"see (e.g.
    Laplace, 10 mH."` gives `"see ([e.g.](/fɔɹ ɪɡzˈæmpəl/) [Laplace](/ləplˈɑs/),
    10 [mH](/mˈɪlɪhˌɛnɹiz/)."`.
  - `test_annotations_strip_back_to_text`: `re.sub(r"\[([^\]]+)\]\(/[^)]*/\)",
    r"\1", spoken) == text`.
  - `test_non_table_words_untouched`: "Laplacian" stays as it is.
  - `test_engine_id_neural_unchanged`: `engine_id("neural") == "neural"`.
  - `test_engine_id_kokoro_shape`: the id matches `^kokoro@[0-9a-f]{12}$` and
    is ≤20 characters.
  - `test_engine_id_moves_with_table_and_speech_version`: patching the table,
    or `speech.SPEECH_VERSION`, changes the id.
  - `test_host_setting_extends_table`: under
    `override_settings(PARODY_WEB_READALOUD_PRONUNCIATIONS={"Bode": "bˈOdi"})`,
    `load_table()["Bode"] == "bˈOdi"` and the packaged entries are still there.
  - `test_phonemes_use_kokoro_vocab`: every character of every value in
    `load_table()` is in `KOKORO_VOCAB` or is a space.
  - In `tests_packaging.py`, `test_pronunciations_are_shipped`: the
    `parody_web_readaloud` package-data includes `"pronunciations.json"`, and
    the file parses as a non-empty dict.
- [ ] **Step 3: Run them and confirm they fail.**
- [ ] **Step 4: Implement.**
  - **`spoken_form`:** for each whitespace word, try the core with `(),;:"“”`
    stripped from both ends; if that isn't in the table, try it with `.`
    stripped too. Replace the core in place with `[core](/ph/)`. Join with
    single spaces. That's the prototype's `annotate` in scratchpad
    `kokoro/render.py`.
  - **`engine_id`:** `f"kokoro@{sha256(json.dumps(table, sort_keys=True,
    ensure_ascii=False) + "\0" + SPEECH_VERSION).hexdigest()[:12]}"`.
- [ ] **Step 5: Run them and confirm they pass.**
- [ ] **Step 6: Commit** `feat(readalong): Kokoro correction table and engine fingerprint`.

### Task 3: The queue store and QueuedSynth

**Files:**
- Modify: `parody_web_readaloud/storage.py`
- Create: `parody_web_readaloud/queued.py`
- Test: `parody_web_readaloud/tests_queued.py`

**Interfaces:**
- Consumes: `pronounce.spoken_form`, `pronounce.engine_family`, `generate.text_key_for`.
- Produces:
  - **In `storage.py`:**
    - `QUEUE_PREFIX = "readalong-queue/"`.
    - `DiskAudio(root: Path | None = None)`, which defaults to `cache_root()`.
    - `read(name) -> bytes` on both stores.
    - `write(name, data, content_type=AUDIO_CONTENT_TYPE)` on both stores.
    - `queue_backend()`: S3 with `prefix=QUEUE_PREFIX` and the same
      bucket/region/sse as `backend()`, or else `DiskAudio(cache_root() /
      "queue")`.
  - **In `queued.py`:**
    - `class NotVoicedYet(Exception)`, with `.text_key`.
    - `class QueuedSynth(voice: str, engine: str, store, table: dict | None =
      None)`.
    - Its `.context: dict`, set by the caller: book, chapter, section.
    - `__call__(text: str) -> tuple[bytes, list[dict]]`.
    - `finish(text_key: str) -> None`, which deletes the done pair.
    - `key_for(text: str) -> tuple[str, str]`, which returns `(spoken,
      text_key)`.
  - **The todo JSON** has these fields: `text`, `spoken`, `voice`, `engine`
    (the family), `text_key`, `book`, `chapter`, `section`, `queued_at` (ISO
    UTC).

- [ ] **Step 1: Write failing tests,** using `DiskAudio(tmpdir)` as the store:
  - `test_miss_queues_and_raises`: calling it raises `NotVoicedYet`, and
    `todo-<key>.json` holds every field, with `text` equal to the input and
    `spoken == spoken_form(text, "kokoro")`.
  - `test_requeue_is_idempotent`: a second miss leaves the JSON byte-identical.
  - `test_hit_returns_done_pair`: with `done-<key>.mp3` (`b"ID3x"`) and
    `done-<key>.marks.json` written, the call returns `(b"ID3x", marks)`.
  - `test_finish_deletes_done_pair`.
  - `test_key_matches_text_key_for_spoken`: `key_for(t)[1] ==
    text_key_for(spoken_form(t, "kokoro"), "am_puck", "kokoro")`.
  - `test_disk_queue_root_is_separate`: `queue_backend()` under a cache-only
    setting writes beneath `<cache>/queue`, not into the audio root.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.** The S3 `read` is `get_object(...)["Body"].read()`.
  JSON is written with `content_type="application/json"`.
- [ ] **Step 4: Run them and confirm they pass,** and that the existing storage
  tests still pass.
- [ ] **Step 5: Commit** `feat(readalong): queue store and QueuedSynth`.

### Task 4: The view reads the configured voice and falls back during the cutover

**Files:**
- Modify: `parody_web_readaloud/views.py`
- Test: `parody_web_readaloud/tests_views.py`

**Interfaces:**
- Produces: `default_voice() -> str` (the setting `PARODY_WEB_READALOUD_VOICE`,
  default `"Matthew"`). `DEFAULT_VOICE` stays as an alias for `"Matthew"`, for
  importers.

- [ ] **Step 1: Write failing tests,** with `override_settings(PARODY_WEB_READALOUD_VOICE="am_puck")`:
  - `test_falls_back_to_other_voice`: with only a Matthew row at the current
    slice, the track JSON has `voice_id == "Matthew"` and `audio_url` ends with
    `?voice=Matthew`.
  - `test_prefers_configured_voice`: with both rows, it's `am_puck`.
  - `test_explicit_voice_is_exact`: `?voice=am_puck` with only Matthew gives 404.
  - `test_audio_follows_fallback_voice`: the audio endpoint with `?voice=Matthew`
    serves the Matthew file.
  - `test_fallback_ignores_other_slices`: a Matthew row at a stale slice only
    gives 404.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** in `_track_or_404`. An explicit `voice` param means
  an exact match. Otherwise use the configured voice, then the newest row of
  any voice for the same book, edition, section and slice.
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Commit** `feat(readalong): configured voice with cutover fallback`.

### Task 5: generate_readalong under engine kokoro

**Files:**
- Modify: `parody_web_readaloud/management/commands/generate_readalong.py`
- Test: `parody_web_readaloud/tests_command.py` (new `KokoroQueueTests`; reuse
  the existing fixtures/helpers of `RepaginationTests` for a book with a
  section PDF)

**Interfaces:**
- Consumes: `QueuedSynth`, `NotVoicedYet`, `queue_backend`, `spoken_form`,
  `engine_id`.
- Produces:
  - Outcome `queued`, and the summary line `"{made} made, {moved} moved,
    {queued} queued, {skipped} skipped"`.
  - `--voice` and `--engine` default to the settings
    `PARODY_WEB_READALOUD_VOICE` and `PARODY_WEB_READALOUD_ENGINE` (falling
    back to `Matthew` and `neural`), and `--engine` accepts `kokoro`.

- [ ] **Step 1: Write failing tests,** with engine `kokoro`, voice `am_puck`,
  and a cache-only store in a tmpdir:
  - `test_first_run_queues_and_writes_no_row`: it prints `queued <key>`,
    leaves 0 rows, and writes one `todo-` file.
  - `test_pickup_makes_track`:
    - Write a done pair for the queued key, with marks from the fake synth in
      `tests_generate.fake_synth`.
    - The run reports `made`.
    - The row's `engine` matches `^kokoro@`.
    - The audio is stored as `f"{text_key}-am_puck.mp3"`.
    - The done pair is deleted.
  - `test_third_run_is_have`: it prints `have <key>` with no new queue file.
  - `test_table_edit_absent_word_restamps`: patch `load_table` to add a word
    the section lacks. The run prints `(text key recorded)`, the row's engine
    id updates, and nothing is queued.
  - `test_table_edit_present_word_requeues`: patch the table to change a word
    the section contains. The run queues a new key, and the row keeps its old
    engine id.
  - `test_pickup_ignores_done_pair_for_other_text`: a done pair under some
    other key is left untouched, and the section is queued under its own key.
  - `test_neural_keys_unchanged`: under engine `neural` with a fake Polly
    synth, the stored `text_key == text_key_for(prep.text, "Matthew",
    "neural")`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement in `_one`.**
  - `eid = engine_id(engine)`.
  - `text_key = text_key_for(spoken_form(prep.text, engine), voice, engine)`.
  - **The cheap exit** also requires `exact.engine == eid`.
  - **The stamp branch:** when `exact.text_key in ("", text_key)`, stamp
    `text_key`, `token_count` and `engine=eid`, then return `skipped` with
    `(text key recorded)`. Otherwise fall through.
  - **Before `synthesise`:** if the synth has a `context` attribute, set
    `synth.context = {...}`.
  - **`except NotVoicedYet`:** print `queued {key}` and return `"queued"`.
  - **Writing the row:** `defaults["engine"] = eid`.
  - **After writing a newly synthesised row:** call `synth.finish(text_key)`
    if the synth has it.
  - **In `handle`:** build `QueuedSynth(voice, "kokoro", queue_backend())`
    for kokoro (`--no-audio` still uses `EstimatedSynth`), and count `queued`.
- [ ] **Step 4: Run the whole suite and confirm it passes.** This includes the
  existing `GenerateReadalongTests`, `RepaginationTests` and `DraftChapterTests`
  unchanged.
- [ ] **Step 5: Commit** `feat(readalong): generate_readalong queues for Kokoro and picks up`.

### Task 6: The Kokoro worker

**Files:**
- Create: `parody_web_readaloud/kokoro_worker.py`
- Modify: `pyproject.toml`
  - extra `kokoro = ["kokoro==0.9.4; python_version < '3.13'", "misaki[en]==0.9.4; python_version < '3.13'", "soundfile>=0.12", "boto3>=1.34"]`
  - `[project.scripts] parody-voice-queue = "parody_web_readaloud.kokoro_worker:main"`
- Test: `parody_web_readaloud/tests_kokoro_worker.py`

**Interfaces:**
- Consumes: the todo JSON schema (Task 3) and the queue name scheme. It does
  NOT import Django, `storage.py` or `queued.py`; the module must import with
  no Django settings configured.
- Produces:
  - `marks_from_tokens(text: str, timed: list[tuple[str, float | None]]) ->
    tuple[list[dict], int]`, which returns the marks and the number of
    interpolated words.
  - `class DirQueue(root: Path)` and `class S3Queue(bucket: str, prefix: str,
    region: str)`, each with `todo() -> list[str]`, `read(name) -> bytes`,
    `write(name, data: bytes, content_type: str)`, `exists(name) -> bool` and
    `delete(name)`.
  - `class KokoroVoice(pipeline_factory=None)`, whose `.render(spoken: str,
    voice: str)` returns `tuple[numpy.ndarray, list[tuple[str, float |
    None]]]` at 24 kHz, with token times absolute (offset by the preceding
    chunks).
  - `encode_mp3(samples, rate: int = 24000) -> bytes`.
  - `process(queue, voicer, *, book=None, chapters=(), limit=None,
    dry_run=False, log=print) -> dict`, which returns `{"voiced": n,
    "cleared": n, "books": sorted list, "interpolated": n}`.
  - `main(argv=None) -> int`.
  - The flags: `--bucket` (default `$PARODY_WEB_READALOUD_BUCKET`, else
    `$AWS_STORAGE_BUCKET_NAME`), `--prefix` (default `readalong-queue/`),
    `--region` (default `us-west-2`), `--queue-dir`, `--book`, `--chapter`
    (repeatable), `--limit` and `--dry-run`.
  - **The last stdout line** is the summary as JSON; the host script parses it.

- [ ] **Step 1: Write failing tests** with a fake `voicer` whose `render`
  returns `(np.zeros(2400), [(tok, i*0.1) ...])`. They must not import kokoro.
  - `test_marks_are_byte_offsets`: in `alpha “beta” gamma`, `gamma`'s mark has
    `start == 17`.
  - `test_interpolates_untimed_words`: with `timed=[("a",0.0),("b",None),
    ("c",1.0)]` and text `"a b c"`, the marks have times `[0, 500, 1000]` and
    `interpolated == 1`.
  - `test_times_never_decrease`: with out-of-order token times, the mark times
    still never decrease.
  - `test_punctuation_tokens_are_ignored`: a token `"("` doesn't consume a word.
  - `test_process_voices_and_clears`: with a `DirQueue` and one todo, it
    writes `done-<k>.mp3` and `done-<k>.marks.json`, deletes `todo-<k>.json`,
    and the summary has `voiced == 1` and `books == ["system-dynamics"]`.
  - `test_existing_done_pair_just_clears`.
  - `test_filters_book_and_chapter`: only matching entries are voiced.
  - `test_dry_run_writes_nothing`.
  - `test_module_imports_without_django`: run `subprocess([sys.executable,
    "-I", "-c", "import parody_web_readaloud.kokoro_worker"])` with
    `DJANGO_SETTINGS_MODULE` unset and check it exits 0.
  - `test_encode_mp3`: skipped unless `soundfile` can write MP3. The bytes
    start with `ID3` or an MPEG sync (0xFFE).
  - In `tests_packaging.py`, `test_kokoro_extra_and_script`: the extra names
    kokoro, misaki and soundfile, and the script entry exists.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**
  - **`KokoroVoice`:** on first render, set up espeak on macOS. If
    `/opt/homebrew/opt/espeak-ng/lib/libespeak-ng.dylib` exists, call
    `EspeakWrapper.set_library` / `set_data_path` with the Homebrew paths
    after `import misaki.espeak`. Otherwise raise `SystemExit("brew install
    espeak-ng")`. Then build `KPipeline(lang_code="a",
    repo_id="hexgrad/Kokoro-82M")`.
  - **`marks_from_tokens`:** follows the prototype in scratchpad
    `kokoro/render.py`. Each whitespace word of `text` takes the time of the
    first non-blank token found by a forward cursor search. Untimed words are
    interpolated linearly between their timed neighbours, a leading untimed
    word gets 0, and a trailing one gets the previous time.
  - **`encode_mp3`:** `soundfile.write(buf, samples, rate, format="MP3")`,
    mono.
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Live check on the laptop** (not CI):

  ```
  uv run --python 3.12 --with-editable '.[kokoro]' parody-voice-queue --queue-dir /tmp/qtest --dry-run
  ```

  Then voice one hand-written todo built from scratchpad
  `kokoro/out-electronics/ai.txt`. Check: every word has a mark, the times
  don't decrease, and the MP3 plays (`ffprobe` reports about 200 s).
- [ ] **Step 6: Commit** `feat(readalong): parody-voice-queue, the laptop Kokoro worker`.

### Task 7: Extend the correction table

**Files:**
- Modify: `parody_web_readaloud/pronunciations.json`
- Test: covered by `test_phonemes_use_kokoro_vocab` (Task 2).

- [ ] **Step 1: Pick the entries** from scratchpad `kokoro/hard_words.txt`
  (the measured report across all three books). Take every word that is
  **frequent (≥5 occurrences) or a proper name, AND whose current phonemes are
  wrong**. That means, at least:
  - the remaining SRE ordinals: m-th, i-th, j-th, k-th, theta-th;
  - Kirchhoff, Thévenin's;
  - the units mV, mW, pF, nF, kN and kg;
  - MATLAB, Matlab, matlab and Matlab's;
  - todo; Hz;
  - ROS-adjacent names: rospy, roscore;
  - SymPy, sympy and numpy;
  - Euler's (check: espeak already says "OY-ler");
  - Grübler's, Rodrigues', Pfaffian, holonomic, pseudoinverse, Lagrangian and
    eigendecomposition, after checking each one's current phonemes.

  Leave single-letter variables and correctly spelled acronyms (KVL, KCL,
  LTI, DFT, PWM) alone.
- [ ] **Step 2: Get phonemes** from misaki for a respelling, e.g.
  `g2p("milli volts")`, and paste them in. Don't hand-type IPA.
- [ ] **Step 3: Run the suite and confirm the vocab test passes.**
- [ ] **Step 4: Render a review clip** of the hard passage with the full
  table (scratchpad `kokoro/hard.txt`, voice `am_puck`) for Rico to check by
  ear.
- [ ] **Step 5: Commit** `feat(readalong): extend the Kokoro correction table`.

### Task 8: Docs, version and the parody-web release

**Files:**
- Modify: `docs/host-integration.md` (a read-along section covering engine
  `kokoro`, the queue, `parody-voice-queue`, the pickup, the settings and
  espeak on macOS), `pyproject.toml` (version), `uv.lock`

- [ ] **Step 1: Rebase on `origin/main`** (`git fetch origin && git rebase
  origin/main`) and resolve. Other sessions are active in read-along
  (tasks 979/980).
- [ ] **Step 2: Set the version** to the next minor above `origin/main`'s
  (0.108.0 if main is still 0.107.4), then run `uv lock`.
- [ ] **Step 3: Run the full suite** (`uv run python runtests.py`) and confirm
  it shows 0 failures.
- [ ] **Step 4: Check the wheel.** `uv build`, then confirm the wheel contains
  `parody_web_readaloud/pronunciations.json` and `kokoro_worker.py`:
  `unzip -l dist/*.whl | grep -E "pronunciations|kokoro_worker"`.
- [ ] **Step 5: Commit** (`0.108.0: read-along voiced by Kokoro on a laptop
  worker`), then `git push origin HEAD:main`. Wait for CI green with `gh run
  watch`.
- [ ] **Step 6: Upload to PyPI** with `uv publish` (or twine) for the exact
  dist files (Rico authorized this). Check the PyPI JSON shows the version.

### Task 9: homepage-django, the first run (System Dynamics chapters 1–4), and verification

**Files** (in a homepage-django worktree from `origin/main`, outside the repo):
- `requirements.txt`: pin `parody-web[print,readalong]==<version>`, with a
  changelog comment line in the house style.
- `config/settings.py`: `PARODY_WEB_READALOUD_VOICE = "am_puck"`,
  `PARODY_WEB_READALOUD_ENGINE = "kokoro"`.
- `teaching/content-manifest.json`: `system-dynamics.features.readalong: true`.
- Create `scripts/voice_readalong.sh`:
  1. Run `uv run --python 3.12 --with 'parody-web[kokoro]==<version>'
     parody-voice-queue --bucket "$AWS_STORAGE_BUCKET_NAME" "$@"`, with the
     bucket read from `.env`.
  2. Parse the last JSON line.
  3. For each book in `books`, send one SSM command, built with the base64
     recipe, that runs as `ubuntu`:

     ```
     cd /srv/homepage-django && sudo -u ubuntu bash -c 'set -a; . ./.env; set +a; .venv/bin/python manage.py generate_readalong <slug> --key-artifact teaching/notebooks_data/<slug>-key.json'
     ```
  4. Wait for it and print its tail.

- [ ] **Step 1: Check the preconditions.**
  - `git log origin/main` must show no undeployed repins that aren't ours.
  - `gh run list -R <homepage repo> -L 5` must show no deploy in progress.
  - Check that the PyPI version is installable on the box: `pip download
    parody-web==<version> --no-deps` over SSM, as ubuntu.
- [ ] **Step 2: Commit and push** to `main` (authorized). Watch the deploy
  workflow until it succeeds. Its log should show `queued` lines for all three
  books and no failure.
- [ ] **Step 3: Run the first real run:**

  ```
  scripts/voice_readalong.sh --book system-dynamics --chapter introduction --chapter linear-graph-models --chapter state-space-models --chapter electromechanical-systems
  ```

  Expected: about 38 sections voiced, then the SSM pickup reports about 38
  `made`.
- [ ] **Step 4: Verify on the box** with the read-only probe (scratchpad
  `ssm/probe.py`, extended to count by voice). The System Dynamics chapter 1–4
  sections have an `am_puck` track at the current slice, and electronics and
  modern-robotics still serve Matthew.
- [ ] **Step 5: Verify in the browser.** Open one System Dynamics chapter-2
  section's read-along on systems.ricopic.one:
  - the track JSON's `voice_id` is `am_puck`;
  - the audio plays;
  - the word mark advances. Check by counting the mark's position changes,
    since the automated tab may be hidden.
- [ ] **Step 6: Report to Rico, then run the remaining queue** (the rest of
  System Dynamics, electronics, robotics) with `scripts/voice_readalong.sh`,
  and verify all three books the same way.
