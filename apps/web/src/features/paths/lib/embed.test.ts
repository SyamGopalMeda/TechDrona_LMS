import { describe, expect, it } from "vitest";
import { EMBED_HOSTS, embeddableUrl, googleEmbedUrl } from "./embed";
import { EMBED_FRAME_ORIGINS } from "@/lib/security/csp";

describe("SEC-08 / D9 embed allow-list", () => {
  it("normalises Google Docs, Sheets, Slides and Drive links to preview URLs", () => {
    expect(googleEmbedUrl("https://docs.google.com/document/d/1AbCdEfGhIjKlMnOp/edit?usp=sharing")).toBe("https://docs.google.com/document/d/1AbCdEfGhIjKlMnOp/preview");
    expect(googleEmbedUrl("https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOp/edit#gid=0")).toBe("https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOp/preview");
    expect(googleEmbedUrl("https://docs.google.com/presentation/d/e/2PACX-1vAbCdEfGhIj/pub?start=false")).toBe("https://docs.google.com/presentation/d/e/2PACX-1vAbCdEfGhIj/pub?embedded=true");
    expect(googleEmbedUrl("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view")).toBe("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/preview");
  });

  it("rejects forms, folders, http, odd ports and look-alike hosts", () => {
    expect(googleEmbedUrl("https://docs.google.com/forms/d/1AbCdEfGhIjKlMnOp/viewform")).toBeNull();
    expect(googleEmbedUrl("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp")).toBeNull();
    expect(googleEmbedUrl("http://docs.google.com/document/d/1AbCdEfGhIjKlMnOp/edit")).toBeNull();
    expect(googleEmbedUrl("https://docs.google.com:8443/document/d/1AbCdEfGhIjKlMnOp/edit")).toBeNull();
    expect(googleEmbedUrl("https://docs.google.com.evil.example/document/d/1AbCdEfGhIjKlMnOp/edit")).toBeNull();
  });

  it("frames only allow-listed players and viewers; everything else is a new-tab link", () => {
    expect(embeddableUrl("https://www.youtube.com/watch?v=dQw4w9WgXcQ")).toBe("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ");
    expect(embeddableUrl("https://vimeo.com/123456789")).toBe("https://player.vimeo.com/video/123456789");
    expect(embeddableUrl("https://example.com/article")).toBeNull();
    expect(embeddableUrl("https://techdrona.in/uploads/x.html")).toBeNull();
    expect(embeddableUrl("javascript:alert(1)")).toBeNull();
  });

  it("matches the CSP frame-src allow-list", () => {
    expect(EMBED_FRAME_ORIGINS.map((o) => new URL(o).hostname).sort()).toEqual([...EMBED_HOSTS].sort());
  });
});
