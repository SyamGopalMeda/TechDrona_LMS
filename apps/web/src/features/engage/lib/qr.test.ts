import { describe, expect, it } from "vitest";
import {
  addEccAndInterleave,
  alignmentPositions,
  byteCapacity,
  dataCodewords,
  dataModuleOrder,
  encodeQr,
  formatBits,
  functionModules,
  maskApplies,
  qrPath,
  rsDivisor,
  rsRemainder,
  totalCodewords,
  versionBits,
  type EccLevel,
  type QrMatrix,
} from "./qr";

/** Independent reader: format bits → unmask → zigzag → de-interleave → RS check → byte segment. */
function decode(m: QrMatrix): { text: string; ecc: EccLevel; mask: number } {
  const size = m.size;
  const at = (x: number, y: number) => m.modules[y]![x]!;
  // first copy of the format information (bit i at the positions the spec assigns)
  const coords: [number, number][] = [];
  for (let i = 0; i <= 5; i++) coords.push([8, i]);
  coords.push([8, 7], [8, 8], [7, 8]);
  for (let i = 9; i < 15; i++) coords.push([14 - i, 8]);
  let fmt = 0;
  coords.forEach(([x, y], i) => {
    if (at(x, y)) fmt |= 1 << i;
  });
  // second copy must agree
  let fmt2 = 0;
  for (let i = 0; i < 8; i++) if (at(size - 1 - i, 8)) fmt2 |= 1 << i;
  for (let i = 8; i < 15; i++) if (at(8, size - 15 + i)) fmt2 |= 1 << i;
  expect(fmt2).toBe(fmt);
  let found: { ecc: EccLevel; mask: number } | null = null;
  for (const ecc of ["L", "M"] as EccLevel[])
    for (let mask = 0; mask < 8; mask++) if (formatBits(ecc, mask) === fmt) found = { ecc, mask };
  expect(found).not.toBeNull();
  const { ecc, mask } = found!;
  const ver = (size - 17) / 4;
  const fn = functionModules(ver);
  const order = dataModuleOrder(size, (x, y) => fn[y]![x]!);
  const total = totalCodewords(ver);
  const raw: number[] = [];
  for (let i = 0; i < total * 8; i++) {
    const [x, y] = order[i]!;
    const b = at(x, y) !== maskApplies(mask, x, y);
    if (i % 8 === 0) raw.push(0);
    raw[raw.length - 1] = (raw[raw.length - 1]! << 1) | (b ? 1 : 0);
  }
  // de-interleave: rebuild blocks the same way the spec lays them out
  const nData = dataCodewords(ver, ecc);
  const eccTotal = total - nData;
  const blocksCount = { L: [0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4], M: [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5] }[ecc][ver]!;
  const eccLen = eccTotal / blocksCount;
  const numShort = blocksCount - (total % blocksCount);
  const shortData = Math.floor(total / blocksCount) - eccLen;
  const lens = Array.from({ length: blocksCount }, (_, i) => shortData + (i < numShort ? 0 : 1));
  const blocks: number[][] = lens.map(() => []);
  let k = 0;
  for (let i = 0; i < shortData + 1; i++)
    for (let j = 0; j < blocksCount; j++) if (i < lens[j]!) blocks[j]!.push(raw[k++]!);
  const eccBlocks: number[][] = lens.map(() => []);
  for (let i = 0; i < eccLen; i++) for (let j = 0; j < blocksCount; j++) eccBlocks[j]!.push(raw[k++]!);
  const div = rsDivisor(eccLen);
  blocks.forEach((b, j) => expect(rsRemainder(b, div)).toEqual(eccBlocks[j]));
  const data = blocks.flat();
  // byte-mode segment
  const bits = data.flatMap((b) => Array.from({ length: 8 }, (_, i) => (b >> (7 - i)) & 1));
  const read = (pos: number, len: number) => bits.slice(pos, pos + len).reduce((a, b) => (a << 1) | b, 0);
  expect(read(0, 4)).toBe(0b0100);
  const cc = ver <= 9 ? 8 : 16;
  const n = read(4, cc);
  const bytes = Array.from({ length: n }, (_, i) => read(4 + cc + i * 8, 8));
  return { text: new TextDecoder().decode(new Uint8Array(bytes)), ecc, mask };
}

function finderAt(m: QrMatrix, x0: number, y0: number) {
  for (let dy = 0; dy < 7; dy++)
    for (let dx = 0; dx < 7; dx++) {
      const d = Math.max(Math.abs(dx - 3), Math.abs(dy - 3));
      expect(m.modules[y0 + dy]![x0 + dx]).toBe(d !== 2);
    }
}

describe("QR encoder", () => {
  it("Reed–Solomon matches the published HELLO WORLD 1-M example", () => {
    // ISO 18004 / thonky.com worked example (alphanumeric data codewords, 10 EC codewords)
    const data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17];
    expect(rsRemainder(data, rsDivisor(10))).toEqual([196, 35, 39, 119, 235, 215, 231, 226, 93, 23]);
  });

  it("produces the standard format and version information words", () => {
    expect(formatBits("M", 0).toString(2).padStart(15, "0")).toBe("101010000010010");
    expect(formatBits("M", 5).toString(2).padStart(15, "0")).toBe("100000011001110");
    expect(formatBits("L", 0).toString(2).padStart(15, "0")).toBe("111011111000100");
    expect(formatBits("L", 7).toString(2).padStart(15, "0")).toBe("110100101110110");
    expect(versionBits(7)).toBe(0x07c94);
  });

  it("uses the standard capacities and alignment positions", () => {
    expect(totalCodewords(1)).toBe(26);
    expect(dataCodewords(1, "M")).toBe(16);
    expect(dataCodewords(5, "M")).toBe(86);
    expect(dataCodewords(10, "M")).toBe(216);
    expect(byteCapacity(1, "M")).toBe(14);
    expect(byteCapacity(1, "L")).toBe(17);
    expect(byteCapacity(10, "M")).toBe(213);
    expect(alignmentPositions(1)).toEqual([]);
    expect(alignmentPositions(2)).toEqual([6, 18]);
    expect(alignmentPositions(7)).toEqual([6, 22, 38]);
    expect(alignmentPositions(10)).toEqual([6, 28, 50]);
  });

  it("encodes a short string at version 1 with finder patterns and timing", () => {
    const m = encodeQr("HELLO WORLD");
    expect(m.version).toBe(1);
    expect(m.size).toBe(21);
    expect(m.modules).toHaveLength(21);
    finderAt(m, 0, 0);
    finderAt(m, 14, 0);
    finderAt(m, 0, 14);
    for (let i = 8; i < 13; i++) {
      expect(m.modules[6]![i]).toBe(i % 2 === 0);
      expect(m.modules[i]![6]).toBe(i % 2 === 0);
    }
    expect(m.modules[13]![8]).toBe(true); // dark module (8, size-8)
    expect(decode(m)).toEqual({ text: "HELLO WORLD", ecc: "M", mask: m.mask });
  });

  it("round-trips join URLs across versions, levels and every mask", () => {
    const urls = [
      "https://techdrona.in/app/engage/join/ABCD2345",
      "http://localhost:3000/app/engage/join/XYZW7788",
      `https://example.org/${"a".repeat(120)}`,
      `https://example.org/${"é".repeat(90)}`,
    ];
    for (const url of urls) {
      for (const ecc of ["L", "M"] as EccLevel[]) {
        const m = encodeQr(url, { ecc });
        expect(m.size).toBe(m.version * 4 + 17);
        expect(decode(m).text).toBe(url);
      }
    }
    for (let mask = 0; mask < 8; mask++) {
      const m = encodeQr("https://techdrona.in/app/engage/join/ABCD2345", { mask });
      expect(decode(m)).toMatchObject({ mask, text: "https://techdrona.in/app/engage/join/ABCD2345" });
    }
    expect(encodeQr(`https://example.org/${"a".repeat(120)}`).version).toBeGreaterThanOrEqual(7);
  });

  it("interleaves multi-block versions in the standard order", () => {
    // version 5-M: 2 blocks of 43 data codewords, 24 EC each
    const data = Array.from({ length: 86 }, (_, i) => i);
    const out = addEccAndInterleave(data, 5, "M");
    expect(out).toHaveLength(134);
    expect(out.slice(0, 4)).toEqual([0, 43, 1, 44]);
    expect(out.slice(84, 86)).toEqual([42, 85]);
  });

  it("is deterministic and renders an SVG path", () => {
    const a = encodeQr("https://techdrona.in/x");
    const b = encodeQr("https://techdrona.in/x");
    expect(a).toEqual(b);
    const d = qrPath(a);
    expect(d.startsWith("M4 4h1v1h-1z")).toBe(true); // top-left finder corner after the quiet zone
    expect(d.split("z").length - 1).toBe(a.modules.flat().filter(Boolean).length);
  });

  it("rejects payloads beyond version 10", () => {
    expect(() => encodeQr("x".repeat(400))).toThrow(/too long/);
  });
});
