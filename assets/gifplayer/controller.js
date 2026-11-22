/**
 * Playback state for one animated figure: which frame shows, whether the
 * reader has it playing, and when the next frame is due. No DOM and no clock
 * of its own: the page passes in `render`, `schedule`, `cancel` and `now`, so
 * the tests can turn the clock by hand.
 *
 * `playing` is the reader's choice, the state the play/pause button shows.
 * Scrolling the figure out of view stops the timer but not `playing`, so a
 * figure the reader paused stays paused when it comes back, and one they left
 * running picks up again.
 *
 * `loop` is the GIF's NETSCAPE count: null (no such block) plays once, 0
 * loops forever, and N plays N more times after the first, as browsers read
 * it. A GIF that stops, stops on its last frame.
 */
export class Controller {
  constructor({
    count, delays, loop, render, schedule, cancel,
    now = () => performance.now(), onChange = () => {},
  }) {
    this.count = count;
    this.delays = delays;
    this.loop = loop;
    // plays in all, and how many have run to their last frame and wrapped
    this.plays = loop === null ? 1 : loop === 0 ? Infinity : loop + 1;
    this.played = 0;
    this.render = render;
    this.schedule = schedule;
    this.cancel = cancel;
    this.now = now;
    this.onChange = onChange;
    this.frame = 0;
    this.playing = false;
    this.visible = true;
    this.timer = null;
    this.due = null; // when the next frame is due, while the timer runs
  }

  get state() {
    return { frame: this.frame, playing: this.playing };
  }

  play() {
    if (this.finished()) { this.frame = 0; this.played = 0; }
    this.playing = true;
    this.render(this.frame);
    this.onChange(this.state);
    this.arm();
  }

  pause() {
    this.disarm();
    this.playing = false;
    this.onChange(this.state);
  }

  toggle() {
    if (this.playing) this.pause();
    else this.play();
  }

  /** One frame forward (+1) or back (-1), wrapping; pauses. */
  step(d) {
    this.show((this.frame + d + this.count) % this.count);
  }

  /** Go to frame i (clamped; a string from a range input is fine); pauses. */
  seek(i) {
    const n = Math.round(Number(i));
    this.show(Math.min(this.count - 1, Math.max(0, Number.isFinite(n) ? n : 0)));
  }

  first() { this.seek(0); }

  last() { this.seek(this.count - 1); }

  setVisible(v) {
    this.visible = v;
    if (v) this.arm();
    else this.disarm();
  }

  show(i) {
    this.disarm();
    this.playing = false;
    this.frame = i;
    this.render(i);
    this.onChange(this.state);
  }

  /** Start the timer for the frame on show. From tick(), `due` still holds
   * when this frame was due, and the next is due a delay after that: the time
   * spent drawing and a timer's lateness come out of the wait instead of
   * adding up (waiting a whole delay after drawing ran 8% slow). A deadline
   * already gone by (a busy page, a background tab) is dropped, so the frames
   * never come in a burst to catch up. */
  arm() {
    if (!this.playing || !this.visible || this.timer) return;
    const t = this.now();
    const d = this.delays[this.frame];
    this.due = this.due === null || this.due + d < t ? t + d : this.due + d;
    this.timer = this.schedule(() => this.tick(), this.due - t);
  }

  disarm() {
    if (this.timer) this.cancel(this.timer);
    this.timer = null;
    this.due = null;
  }

  /** On the last frame of the last play: where a GIF that stops, stops. */
  finished() {
    return this.frame === this.count - 1 && this.played >= this.plays - 1;
  }

  tick() {
    this.timer = null;
    if (this.frame === this.count - 1) {
      this.frame = 0;
      this.played++;
    } else {
      this.frame++;
    }
    this.render(this.frame);
    if (this.finished()) { this.playing = false; this.due = null; }
    this.onChange(this.state);
    this.arm();
  }
}
