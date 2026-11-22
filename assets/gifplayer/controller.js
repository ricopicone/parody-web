/**
 * Playback state for one animated figure: which frame shows, whether the
 * reader has it playing, and when the next frame is due. No DOM and no clock
 * of its own: the page passes in `render`, `schedule` and `cancel`, so the
 * tests can turn the clock by hand.
 *
 * `playing` is the reader's choice, the state the play/pause button shows.
 * Scrolling the figure out of view stops the timer but not `playing`, so a
 * figure the reader paused stays paused when it comes back, and one they left
 * running picks up again.
 */
export class Controller {
  constructor({ count, delays, loop, render, schedule, cancel, onChange = () => {} }) {
    this.count = count;
    this.delays = delays;
    this.loop = loop;
    this.render = render;
    this.schedule = schedule;
    this.cancel = cancel;
    this.onChange = onChange;
    this.frame = 0;
    this.playing = false;
    this.visible = true;
    this.timer = null;
  }

  get state() {
    return { frame: this.frame, playing: this.playing };
  }

  play() {
    if (this.loop === null && this.frame === this.count - 1) this.frame = 0;
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

  arm() {
    if (!this.playing || !this.visible || this.timer) return;
    this.timer = this.schedule(() => this.tick(), this.delays[this.frame]);
  }

  disarm() {
    if (this.timer) this.cancel(this.timer);
    this.timer = null;
  }

  tick() {
    this.timer = null;
    const last = this.frame === this.count - 1;
    this.frame = last ? 0 : this.frame + 1;
    this.render(this.frame);
    if (this.loop === null && this.frame === this.count - 1) this.playing = false;
    this.onChange(this.state);
    this.arm();
  }
}
