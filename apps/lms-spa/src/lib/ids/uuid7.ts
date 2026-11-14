/**
 * UUIDv7 (RFC 9562) generator with a monotonic counter inside the same millisecond
 * (analytics-event-schema §5.4: "Generate UUIDv7 with a monotonic counter within the same ms").
 *
 * Layout: 48-bit unix ms | ver(4)=7 | rand_a(12) | var(2)=0b10 | rand_b(62).
 * rand_a holds a 12-bit counter seeded randomly each new ms and incremented within the
 * same ms; on overflow the timestamp is advanced by 1 ms so ordering stays monotonic.
 * Works in browsers, Node and the Edge runtime (uses globalThis.crypto only).
 */

type RandomFill = (bytes: Uint8Array) => Uint8Array;

const defaultRandom: RandomFill = (bytes) => globalThis.crypto.getRandomValues(bytes);

export interface Uuid7Generator {
  (): string;
}

export function createUuid7Generator(
  now: () => number = Date.now,
  random: RandomFill = defaultRandom,
): Uuid7Generator {
  let lastMs = -1;
  let counter = 0;

  return function uuid7(): string {
    let ms = Math.max(now(), lastMs);
    if (ms === lastMs) {
      counter += 1;
      if (counter > 0xfff) {
        ms = lastMs + 1;
        counter = random(new Uint8Array(2)).reduce((a, b) => (a << 8) | b, 0) & 0x7ff;
      }
    } else {
      // Seed in the lower half of the range so many ids fit before overflow.
      counter = random(new Uint8Array(2)).reduce((a, b) => (a << 8) | b, 0) & 0x7ff;
    }
    lastMs = ms;

    const bytes = new Uint8Array(16);
    // 48-bit big-endian timestamp. Use division for the high bits (no 64-bit bitwise ops).
    const high = Math.floor(ms / 2 ** 32);
    const low = ms >>> 0;
    bytes[0] = (high >>> 8) & 0xff;
    bytes[1] = high & 0xff;
    bytes[2] = (low >>> 24) & 0xff;
    bytes[3] = (low >>> 16) & 0xff;
    bytes[4] = (low >>> 8) & 0xff;
    bytes[5] = low & 0xff;
    bytes[6] = 0x70 | ((counter >>> 8) & 0x0f);
    bytes[7] = counter & 0xff;
    const rand = random(new Uint8Array(8));
    bytes.set(rand, 8);
    bytes[8] = 0x80 | ((bytes[8] ?? 0) & 0x3f);

    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  };
}

/** Shared process/page-wide generator. */
export const uuid7: Uuid7Generator = createUuid7Generator();

/** Milliseconds since the Unix epoch encoded in a UUIDv7. */
export function uuid7Timestamp(id: string): number {
  const hex = id.replace(/-/g, "").slice(0, 12);
  return Number.parseInt(hex, 16);
}

export const UUID7_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** RFC 4122 v4 (used for tab_id / page_instance_id). */
export function uuid4(): string {
  return globalThis.crypto.randomUUID();
}
