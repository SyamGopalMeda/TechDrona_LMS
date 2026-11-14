/**
 * Video analytics (analytics-event-schema §2.2 and `page.heartbeat.media`, §3.9).
 *
 * The lesson player (VdoCipher) maps its player API events onto `VideoEvents`. Each call emits
 * one `video.*` event with the documented payload and keeps `media_playing` in the engagement
 * meter in step. While playing, the media ranges actually played are collected and attached to
 * the next engaged heartbeat as `media.played_ranges` (input for unique coverage).
 *
 * All positions are media seconds (≥ 0). Rates are clamped to the schema range 0.25–2.0.
 */

export type VideoEventType =
  | "video.play"
  | "video.pause"
  | "video.seek"
  | "video.rate_change"
  | "video.ended"
  | "video.buffering"
  | "video.error";

/** Public API the player calls. Every method is a no-op once the page instance is closed. */
export interface VideoEvents {
  play(positionS: number, rate?: number): void;
  pause(positionS: number): void;
  seek(fromS: number, toS: number): void;
  rateChange(fromRate: number, toRate: number, positionS: number): void;
  ended(positionS: number, durationS: number): void;
  /** Buffering started (stall). Nothing is emitted until `bufferingEnd`. */
  bufferingStart(positionS: number): void;
  /** Buffering finished: emits `video.buffering` with the measured `buffer_ms`. */
  bufferingEnd(positionS: number, bitrateKbps?: number): void;
  /** Player error code only — never messages or URLs. */
  error(code: string | number, positionS: number): void;
  /** Position update while playing (call at least every few seconds, e.g. on `timeupdate`). */
  timeUpdate(positionS: number): void;
}

export interface MediaHeartbeat {
  lesson_asset_id?: string;
  position_s: number;
  rate: number;
  played_ranges?: [number, number][];
}

/** Sink the tracker provides to the video session. */
export interface VideoSink {
  emit(eventType: VideoEventType, payload: Record<string, unknown>): void;
  setMediaPlaying(playing: boolean): void;
  /** Monotonic ms. */
  mono(): number;
}

export const MAX_PLAYED_RANGES = 8;
const MIN_RATE = 0.25;
const MAX_RATE = 2.0;
/** A forward timeupdate jump larger than this × rate (media s) is treated as an implicit seek. */
const JUMP_TOLERANCE_S = 10;

export const clampRate = (r: number): number => (Number.isFinite(r) ? Math.min(MAX_RATE, Math.max(MIN_RATE, r)) : 1);
export const pos = (s: number): number => (Number.isFinite(s) && s > 0 ? Math.round(s * 10) / 10 : 0);

/** Player error code as accepted by ingest: `[A-Za-z0-9_.-]{1,32}` (never messages or URLs). */
export function errorCode(code: string | number): string {
  const c = String(code).replace(/[^A-Za-z0-9_.-]/g, "_").slice(0, 32);
  return c || "unknown";
}

/** Merge overlapping/adjacent ranges and keep at most `max` (merging the closest gaps first). */
export function normalizeRanges(ranges: [number, number][], max = MAX_PLAYED_RANGES): [number, number][] {
  const sorted = ranges
    .filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b) && b > a)
    .map(([a, b]) => [pos(a), pos(b)] as [number, number])
    .filter(([a, b]) => b > a)
    .sort((x, y) => x[0] - y[0]);
  const out: [number, number][] = [];
  for (const r of sorted) {
    const last = out[out.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else out.push([r[0], r[1]]);
  }
  while (out.length > max) {
    // Merge the pair with the smallest gap (over-reports coverage by at most that gap).
    let best = 0;
    for (let i = 1; i < out.length - 1; i++) {
      if (out[i + 1]![0] - out[i]![1] < out[best + 1]![0] - out[best]![1]) best = i;
    }
    out.splice(best, 2, [out[best]![0], out[best + 1]![1]]);
  }
  return out;
}

export class VideoSession implements VideoEvents {
  private playing = false;
  private rate = 1;
  private position = 0;
  private rangeStart: number | null = null;
  private ranges: [number, number][] = [];
  private bufferStartedAt: number | null = null;
  private touched = false;

  constructor(
    private readonly sink: VideoSink,
    private readonly lessonAssetId?: string,
    private readonly isClosed: () => boolean = () => false,
  ) {}

  play(positionS: number, rate = this.rate): void {
    if (this.isClosed()) return;
    this.touched = true;
    this.rate = clampRate(rate);
    this.position = pos(positionS);
    this.playing = true;
    this.rangeStart = this.position;
    this.sink.emit("video.play", { position_s: this.position, rate: this.rate });
    this.sink.setMediaPlaying(true);
  }

  pause(positionS: number): void {
    if (this.isClosed()) return;
    this.stopAt(positionS);
    this.sink.emit("video.pause", { position_s: this.position });
  }

  seek(fromS: number, toS: number): void {
    if (this.isClosed()) return;
    this.touched = true;
    const from = pos(fromS);
    const to = pos(toS);
    this.closeRange(from);
    this.position = to;
    if (this.playing) this.rangeStart = to;
    this.sink.emit("video.seek", { from_s: from, to_s: to });
  }

  rateChange(fromRate: number, toRate: number, positionS: number): void {
    if (this.isClosed()) return;
    this.touched = true;
    this.timeUpdate(positionS);
    this.rate = clampRate(toRate);
    this.sink.emit("video.rate_change", { from_rate: clampRate(fromRate), to_rate: this.rate, position_s: this.position });
  }

  ended(positionS: number, durationS: number): void {
    if (this.isClosed()) return;
    this.stopAt(positionS);
    // duration_s must be > 0 on the wire; fall back to the end position when the player has no duration.
    const duration = pos(durationS) || this.position;
    if (duration <= 0) return;
    this.sink.emit("video.ended", { position_s: this.position, duration_s: duration });
  }

  bufferingStart(positionS: number): void {
    if (this.isClosed()) return;
    this.timeUpdate(positionS);
    this.bufferStartedAt = this.sink.mono();
  }

  bufferingEnd(positionS: number, bitrateKbps?: number): void {
    if (this.isClosed() || this.bufferStartedAt === null) return;
    const bufferMs = Math.max(0, Math.round(this.sink.mono() - this.bufferStartedAt));
    this.bufferStartedAt = null;
    this.position = pos(positionS);
    this.sink.emit("video.buffering", {
      position_s: this.position,
      buffer_ms: bufferMs,
      ...(bitrateKbps !== undefined && Number.isFinite(bitrateKbps) ? { bitrate_kbps: Math.max(0, Math.round(bitrateKbps)) } : {}),
    });
  }

  error(code: string | number, positionS: number): void {
    if (this.isClosed()) return;
    this.stopAt(positionS);
    this.sink.emit("video.error", { code: errorCode(code), position_s: this.position });
  }

  timeUpdate(positionS: number): void {
    if (this.isClosed()) return;
    const p = pos(positionS);
    if (this.playing && this.rangeStart !== null && (p < this.position || p - this.position > JUMP_TOLERANCE_S * Math.max(1, this.rate))) {
      // Discontinuity without a seek callback: close the old range and start a new one.
      this.closeRange(this.position);
      this.rangeStart = p;
    }
    this.position = p;
  }

  /**
   * Media block for the next heartbeat; drains the played ranges collected since the previous
   * sample. Returns undefined if the player was never used on this page instance.
   */
  takeHeartbeat(): MediaHeartbeat | undefined {
    if (!this.touched) return undefined;
    if (this.playing && this.rangeStart !== null) {
      this.closeRange(this.position);
      this.rangeStart = this.position;
    }
    const ranges = normalizeRanges(this.ranges);
    this.ranges = [];
    return {
      ...(this.lessonAssetId ? { lesson_asset_id: this.lessonAssetId } : {}),
      position_s: this.position,
      rate: this.rate,
      ...(ranges.length ? { played_ranges: ranges } : {}),
    };
  }

  /** True when played media time is waiting for a heartbeat. */
  get hasPendingRanges(): boolean {
    return this.ranges.length > 0 || (this.playing && this.rangeStart !== null && this.position > this.rangeStart);
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  private stopAt(positionS: number): void {
    this.touched = true;
    this.position = pos(positionS);
    this.closeRange(this.position);
    if (this.playing) {
      this.playing = false;
      this.sink.setMediaPlaying(false);
    }
    this.bufferStartedAt = null;
  }

  private closeRange(end: number): void {
    if (this.rangeStart !== null && end > this.rangeStart) this.ranges.push([this.rangeStart, end]);
    this.rangeStart = null;
    if (this.ranges.length > MAX_PLAYED_RANGES * 4) this.ranges = normalizeRanges(this.ranges);
  }
}
