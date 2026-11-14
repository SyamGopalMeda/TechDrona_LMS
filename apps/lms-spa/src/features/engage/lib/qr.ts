/**
 * Minimal, dependency-free QR Code encoder (ISO/IEC 18004) for join links.
 *
 * Byte mode only (UTF-8), error correction level L or M, versions 1–10 (up to 213 bytes at M,
 * 271 at L). Reed–Solomon over GF(256) with the 0x11D polynomial; the mask is chosen by the
 * standard penalty score. Pure functions, no DOM: `encodeQr(text)` returns the module matrix.
 */

export type EccLevel = "L" | "M";

export interface QrMatrix {
  version: number;
  size: number;
  ecc: EccLevel;
  mask: number;
  /** modules[y][x] — true = dark. */
  modules: boolean[][];
}

const MAX_VERSION = 10;

/** Error correction codewords per block, index = version. */
const ECC_PER_BLOCK: Record<EccLevel, number[]> = {
  L: [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18],
  M: [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26],
};

/** Number of error correction blocks, index = version. */
const NUM_BLOCKS: Record<EccLevel, number[]> = {
  L: [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4],
  M: [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5],
};

/** Format-info ECC level bits (L = 01, M = 00). */
const ECC_FORMAT_BITS: Record<EccLevel, number> = { L: 1, M: 0 };

/* ------------------------------------------------------------------ GF(256) / Reed–Solomon */

export function gfMul(x: number, y: number): number {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z & 0xff;
}

/** Generator polynomial coefficients (highest degree term omitted, which is always 1). */
export function rsDivisor(degree: number): number[] {
  const result = new Array<number>(degree).fill(0);
  result[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < result.length; j++) {
      result[j] = gfMul(result[j]!, root);
      if (j + 1 < result.length) result[j]! ^= result[j + 1]!;
    }
    root = gfMul(root, 0x02);
  }
  return result;
}

/** Remainder of data(x)·x^n divided by the generator: the n error correction codewords. */
export function rsRemainder(data: readonly number[], divisor: readonly number[]): number[] {
  const result = new Array<number>(divisor.length).fill(0);
  for (const b of data) {
    const factor = b ^ result.shift()!;
    result.push(0);
    for (let i = 0; i < divisor.length; i++) result[i]! ^= gfMul(divisor[i]!, factor);
  }
  return result;
}

/* ------------------------------------------------------------------ capacity */

function rawDataModules(ver: number): number {
  let result = (16 * ver + 128) * ver + 64;
  if (ver >= 2) {
    const numAlign = Math.floor(ver / 7) + 2;
    result -= (25 * numAlign - 10) * numAlign - 55;
    if (ver >= 7) result -= 36;
  }
  return result;
}

export function totalCodewords(ver: number): number {
  return Math.floor(rawDataModules(ver) / 8);
}

export function dataCodewords(ver: number, ecc: EccLevel): number {
  return totalCodewords(ver) - ECC_PER_BLOCK[ecc][ver]! * NUM_BLOCKS[ecc][ver]!;
}

function charCountBits(ver: number): number {
  return ver <= 9 ? 8 : 16;
}

/** Bytes that fit in byte mode at this version / level. */
export function byteCapacity(ver: number, ecc: EccLevel): number {
  return Math.floor((dataCodewords(ver, ecc) * 8 - 4 - charCountBits(ver)) / 8);
}

/* ------------------------------------------------------------------ data codewords */

function utf8(text: string): number[] {
  return Array.from(new TextEncoder().encode(text));
}

/** Mode + count + payload, terminator, byte padding and 0xEC/0x11 pad codewords. */
export function encodeDataCodewords(bytes: readonly number[], ver: number, ecc: EccLevel): number[] {
  const bits: number[] = [];
  const push = (val: number, len: number) => {
    for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1);
  };
  push(0b0100, 4);
  push(bytes.length, charCountBits(ver));
  for (const b of bytes) push(b, 8);
  const capacity = dataCodewords(ver, ecc) * 8;
  if (bits.length > capacity) throw new Error("data too long for version");
  push(0, Math.min(4, capacity - bits.length));
  push(0, (8 - (bits.length % 8)) % 8);
  for (let pad = 0xec; bits.length < capacity; pad ^= 0xec ^ 0x11) push(pad, 8);
  const out: number[] = [];
  for (let i = 0; i < bits.length; i += 8) {
    let byte = 0;
    for (let j = 0; j < 8; j++) byte = (byte << 1) | bits[i + j]!;
    out.push(byte);
  }
  return out;
}

/** Split into blocks, append RS codewords, interleave. */
export function addEccAndInterleave(data: readonly number[], ver: number, ecc: EccLevel): number[] {
  const numBlocks = NUM_BLOCKS[ecc][ver]!;
  const eccLen = ECC_PER_BLOCK[ecc][ver]!;
  const total = totalCodewords(ver);
  const numShort = numBlocks - (total % numBlocks);
  const shortLen = Math.floor(total / numBlocks);
  const divisor = rsDivisor(eccLen);
  const blocks: number[][] = [];
  let k = 0;
  for (let i = 0; i < numBlocks; i++) {
    const len = shortLen - eccLen + (i < numShort ? 0 : 1);
    const dat = data.slice(k, k + len);
    k += len;
    const block = [...dat];
    if (i < numShort) block.push(-1); // placeholder so all blocks align when interleaving
    blocks.push([...block, ...rsRemainder(dat, divisor)]);
  }
  const out: number[] = [];
  for (let i = 0; i < blocks[0]!.length; i++) {
    for (let j = 0; j < blocks.length; j++) {
      // skip the short-block placeholder
      if (i !== shortLen - eccLen || j >= numShort) out.push(blocks[j]![i]!);
    }
  }
  return out;
}

/* ------------------------------------------------------------------ matrix */

export function alignmentPositions(ver: number): number[] {
  if (ver === 1) return [];
  const numAlign = Math.floor(ver / 7) + 2;
  const step = Math.ceil((ver * 4 + 4) / (numAlign * 2 - 2)) * 2;
  const size = ver * 4 + 17;
  const result = [6];
  for (let pos = size - 7; result.length < numAlign; pos -= step) result.splice(1, 0, pos);
  return result;
}

/** 15-bit format information (ECC level + mask, BCH code, XOR 0x5412). */
export function formatBits(ecc: EccLevel, mask: number): number {
  const data = (ECC_FORMAT_BITS[ecc] << 3) | mask;
  let rem = data;
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
  return ((data << 10) | rem) ^ 0x5412;
}

/** 18-bit version information (versions ≥ 7). */
export function versionBits(ver: number): number {
  let rem = ver;
  for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
  return (ver << 12) | rem;
}

const bit = (x: number, i: number) => ((x >>> i) & 1) !== 0;

class Grid {
  readonly modules: boolean[][];
  readonly fn: boolean[][];
  constructor(readonly size: number) {
    this.modules = Array.from({ length: size }, () => new Array<boolean>(size).fill(false));
    this.fn = Array.from({ length: size }, () => new Array<boolean>(size).fill(false));
  }
  setFn(x: number, y: number, dark: boolean) {
    this.modules[y]![x] = dark;
    this.fn[y]![x] = true;
  }
}

function drawFunctionPatterns(g: Grid, ver: number) {
  const size = g.size;
  for (let i = 0; i < size; i++) {
    g.setFn(6, i, i % 2 === 0);
    g.setFn(i, 6, i % 2 === 0);
  }
  const finder = (cx: number, cy: number) => {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const dist = Math.max(Math.abs(dx), Math.abs(dy));
        const x = cx + dx;
        const y = cy + dy;
        if (x >= 0 && x < size && y >= 0 && y < size) g.setFn(x, y, dist !== 2 && dist !== 4);
      }
    }
  };
  finder(3, 3);
  finder(size - 4, 3);
  finder(3, size - 4);
  const align = alignmentPositions(ver);
  const n = align.length;
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      if ((i === 0 && j === 0) || (i === 0 && j === n - 1) || (i === n - 1 && j === 0)) continue;
      for (let dy = -2; dy <= 2; dy++) {
        for (let dx = -2; dx <= 2; dx++) {
          g.setFn(align[i]! + dx, align[j]! + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
        }
      }
    }
  }
  drawFormat(g, "M", 0); // reserve the areas; real bits are drawn after masking
  if (ver >= 7) {
    const bits = versionBits(ver);
    for (let i = 0; i < 18; i++) {
      const a = size - 11 + (i % 3);
      const b = Math.floor(i / 3);
      g.setFn(a, b, bit(bits, i));
      g.setFn(b, a, bit(bits, i));
    }
  }
}

function drawFormat(g: Grid, ecc: EccLevel, mask: number) {
  const bits = formatBits(ecc, mask);
  const size = g.size;
  for (let i = 0; i <= 5; i++) g.setFn(8, i, bit(bits, i));
  g.setFn(8, 7, bit(bits, 6));
  g.setFn(8, 8, bit(bits, 7));
  g.setFn(7, 8, bit(bits, 8));
  for (let i = 9; i < 15; i++) g.setFn(14 - i, 8, bit(bits, i));
  for (let i = 0; i < 8; i++) g.setFn(size - 1 - i, 8, bit(bits, i));
  for (let i = 8; i < 15; i++) g.setFn(8, size - 15 + i, bit(bits, i));
  g.setFn(8, size - 8, true); // dark module
}

/** Function-pattern map (finders, timing, alignment, format/version areas) for a version. */
export function functionModules(ver: number): boolean[][] {
  const g = new Grid(ver * 4 + 17);
  drawFunctionPatterns(g, ver);
  return g.fn;
}

/** Data module coordinates in placement order (two-column zigzag from the bottom right). */
export function dataModuleOrder(size: number, isFn: (x: number, y: number) => boolean): [number, number][] {
  const out: [number, number][] = [];
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < size; vert++) {
      for (let j = 0; j < 2; j++) {
        const x = right - j;
        const upward = ((right + 1) & 2) === 0;
        const y = upward ? size - 1 - vert : vert;
        if (!isFn(x, y)) out.push([x, y]);
      }
    }
  }
  return out;
}

export function maskApplies(mask: number, x: number, y: number): boolean {
  switch (mask) {
    case 0:
      return (x + y) % 2 === 0;
    case 1:
      return y % 2 === 0;
    case 2:
      return x % 3 === 0;
    case 3:
      return (x + y) % 3 === 0;
    case 4:
      return (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0;
    case 5:
      return ((x * y) % 2) + ((x * y) % 3) === 0;
    case 6:
      return (((x * y) % 2) + ((x * y) % 3)) % 2 === 0;
    default:
      return (((x + y) % 2) + ((x * y) % 3)) % 2 === 0;
  }
}

function applyMask(g: Grid, mask: number) {
  for (let y = 0; y < g.size; y++) {
    for (let x = 0; x < g.size; x++) {
      if (!g.fn[y]![x] && maskApplies(mask, x, y)) g.modules[y]![x] = !g.modules[y]![x];
    }
  }
}

/** Penalty score (N1 runs, N2 blocks, N3 finder-like patterns, N4 balance). */
export function penalty(m: boolean[][]): number {
  const size = m.length;
  let score = 0;
  const lines: boolean[][] = [];
  for (let y = 0; y < size; y++) lines.push(m[y]!);
  for (let x = 0; x < size; x++) lines.push(m.map((row) => row[x]!));
  const pattern = [true, false, true, true, true, false, true];
  for (const line of lines) {
    let run = 1;
    for (let i = 1; i <= size; i++) {
      if (i < size && line[i] === line[i - 1]) run++;
      else {
        if (run >= 5) score += 3 + (run - 5);
        run = 1;
      }
    }
    for (let i = 0; i + 7 <= size; i++) {
      if (!pattern.every((p, k) => line[i + k] === p)) continue;
      const lightBefore = [1, 2, 3, 4].every((k) => i - k < 0 || !line[i - k]);
      const lightAfter = [0, 1, 2, 3].every((k) => i + 7 + k >= size || !line[i + 7 + k]);
      if (lightBefore || lightAfter) score += 40;
    }
  }
  let dark = 0;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (m[y]![x]) dark++;
      if (x + 1 < size && y + 1 < size) {
        const c = m[y]![x];
        if (c === m[y]![x + 1] && c === m[y + 1]![x] && c === m[y + 1]![x + 1]) score += 3;
      }
    }
  }
  const total = size * size;
  const k = Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1;
  return score + Math.max(0, k) * 10;
}

/** Smallest version (1..10) whose byte capacity fits the payload at the given level. */
export function chooseVersion(byteLength: number, ecc: EccLevel): number {
  for (let v = 1; v <= MAX_VERSION; v++) if (byteCapacity(v, ecc) >= byteLength) return v;
  throw new Error("QR payload too long");
}

export function encodeQr(text: string, opts: { ecc?: EccLevel; mask?: number } = {}): QrMatrix {
  const ecc = opts.ecc ?? "M";
  const bytes = utf8(text);
  const version = chooseVersion(bytes.length, ecc);
  const size = version * 4 + 17;
  const codewords = addEccAndInterleave(encodeDataCodewords(bytes, version, ecc), version, ecc);

  const base = new Grid(size);
  drawFunctionPatterns(base, version);
  const order = dataModuleOrder(size, (x, y) => base.fn[y]![x]!);
  order.forEach(([x, y], i) => {
    if (i < codewords.length * 8) base.modules[y]![x] = bit(codewords[i >>> 3]!, 7 - (i & 7));
  });

  const build = (mask: number) => {
    const g = new Grid(size);
    for (let y = 0; y < size; y++) {
      g.modules[y] = [...base.modules[y]!];
      g.fn[y] = [...base.fn[y]!];
    }
    applyMask(g, mask);
    drawFormat(g, ecc, mask);
    return g;
  };

  let mask = opts.mask ?? -1;
  let best: Grid | null = null;
  if (mask >= 0 && mask <= 7) best = build(mask);
  else {
    let bestScore = Infinity;
    for (let m = 0; m < 8; m++) {
      const g = build(m);
      const s = penalty(g.modules);
      if (s < bestScore) {
        bestScore = s;
        best = g;
        mask = m;
      }
    }
  }
  return { version, size, ecc, mask, modules: best!.modules };
}

/** SVG path data (one unit per module, offset by the quiet zone). */
export function qrPath(m: QrMatrix, quiet = 4): string {
  const parts: string[] = [];
  for (let y = 0; y < m.size; y++) {
    for (let x = 0; x < m.size; x++) {
      if (m.modules[y]![x]) parts.push(`M${x + quiet} ${y + quiet}h1v1h-1z`);
    }
  }
  return parts.join("");
}
