import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { endpointDescriptor } from "./endpointFixture";
import { TranscriptImage } from "../components/conversation/TranscriptImage";
import {
  adoptTranscriptPreviewBlob,
  ownedTranscriptPreviewBlobCount,
  peekOwnedTranscriptPreviewBlob,
  releaseAllTranscriptPreviewBlobs,
  releaseTranscriptPreviewBlob,
  resetTranscriptPreviewBlobsForTests,
} from "../components/conversation/transcriptImageBlobs";
import {
  delayAfterDurableFailure,
  MAX_DURABLE_IMAGE_RETRIES,
  shouldRetryDurableImage,
} from "../components/conversation/transcriptImageRetry";

type ProbeImage = {
  src: string;
  onload: ((ev?: Event) => void) | null;
  onerror: ((ev?: Event) => void) | null;
};

let urlCount = 0;
const probes: ProbeImage[] = [];
const revokeSpy = vi.fn();

function lastProbe(): ProbeImage {
  return probes[probes.length - 1];
}

function mockHarnessPort(port: number | string | undefined) {
  const w = window as any;
  if (port === undefined) delete w.__HARNESS_PORT__;
  else w.__HARNESS_PORT__ = port;
}

function mockBackendRespawn(subscribe: ((cb: () => void) => () => void) | null) {
  const w = window as any;
  if (!subscribe) {
    delete w.harnessIPC;
    return;
  }
  w.harnessIPC = { onBackendRespawned: subscribe };
}

beforeEach(() => {
  resetTranscriptPreviewBlobsForTests();
  probes.length = 0;
  revokeSpy.mockReset();
  mockHarnessPort(undefined);
  vi.stubGlobal("fetch", vi.fn(async path => path === "/api/endpoint" ? Response.json(endpointDescriptor) : new Response("pixels", {headers:{"Content-Type":"image/png"}})));
  mockBackendRespawn(null);
  vi.stubGlobal(
    "Image",
    class {
      src = "";
      onload: ((ev?: Event) => void) | null = null;
      onerror: ((ev?: Event) => void) | null = null;
      constructor() {
        probes.push(this);
      }
    },
  );
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = (_blob: Blob) => `blob:fetched-${++urlCount}`;
    static revokeObjectURL = (url: string) => {
      revokeSpy(url);
    };
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  resetTranscriptPreviewBlobsForTests();
  mockHarnessPort(undefined);
  mockBackendRespawn(null);
});

describe("transcriptImageRetry helpers", () => {
  it("bounds durable retries and backoff", () => {
    expect(shouldRetryDurableImage({ durablePath: "uploads/a.png", failureCount: 0 })).toBe(true);
    expect(shouldRetryDurableImage({ durablePath: "uploads/a.png", failureCount: MAX_DURABLE_IMAGE_RETRIES - 1 })).toBe(true);
    expect(shouldRetryDurableImage({ durablePath: "uploads/a.png", failureCount: MAX_DURABLE_IMAGE_RETRIES })).toBe(false);
    expect(shouldRetryDurableImage({ durablePath: "blob:x", failureCount: 1 })).toBe(false);
    expect(shouldRetryDurableImage({ durablePath: "https://cdn.example/x.png", failureCount: 1 })).toBe(false);
    expect(delayAfterDurableFailure(1)).toBe(200);
    expect(delayAfterDurableFailure(MAX_DURABLE_IMAGE_RETRIES)).toBe(4000);
    expect(delayAfterDurableFailure(MAX_DURABLE_IMAGE_RETRIES + 1)).toBeNull();
  });
});

describe("transcriptImageBlobs ownership", () => {
  it("revokes on explicit release, not merely by forgetting a mount", () => {
    adoptTranscriptPreviewBlob("uploads/a.png", "blob:owned-1");
    expect(peekOwnedTranscriptPreviewBlob("uploads/a.png")).toBe("blob:owned-1");
    expect(ownedTranscriptPreviewBlobCount()).toBe(1);
    // "unmount" does nothing to the registry
    expect(peekOwnedTranscriptPreviewBlob("uploads/a.png")).toBe("blob:owned-1");
    releaseTranscriptPreviewBlob("uploads/a.png");
    expect(revokeSpy).toHaveBeenCalledWith("blob:owned-1");
    expect(ownedTranscriptPreviewBlobCount()).toBe(0);
  });

  it("releaseAll clears session-discarded blobs", () => {
    adoptTranscriptPreviewBlob("uploads/a.png", "blob:a");
    adoptTranscriptPreviewBlob("uploads/b.png", "blob:b");
    releaseAllTranscriptPreviewBlobs();
    expect(ownedTranscriptPreviewBlobCount()).toBe(0);
    expect(revokeSpy).toHaveBeenCalledWith("blob:a");
    expect(revokeSpy).toHaveBeenCalledWith("blob:b");
  });
});

async function flush() { await act(async () => { await Promise.resolve(); }); }
async function decode() { await flush(); await act(async () => { lastProbe().onload?.(); }); }

describe("TranscriptImage resilient surface", () => {
  it("keeps composer fallback across offscreen unmount and late remount", async () => {
    const view = render(<TranscriptImage path="uploads/shot.png" name="shot.png" previewUrl="blob:preview" />);
    await flush();
    expect(screen.getByAltText("shot.png")).toHaveAttribute("src", "blob:preview");
    view.unmount();
    expect(revokeSpy).not.toHaveBeenCalledWith("blob:preview");
    expect(peekOwnedTranscriptPreviewBlob("uploads/shot.png")).toBe("blob:preview");
    render(<TranscriptImage path="uploads/shot.png" name="shot.png" previewUrl="blob:preview" />);
    expect(screen.getByAltText("shot.png")).toHaveAttribute("src", "blob:preview");
  });

  it("recovers from a failed authenticated request with bounded backoff", async () => {
    vi.useFakeTimers();
    let requests = 0;
    vi.mocked(fetch).mockImplementation(async path => {
      if (path === "/api/endpoint") return Response.json(endpointDescriptor);
      requests++;
      return requests === 1 ? new Response("busy", {status:503}) : new Response("pixels", {headers:{"Content-Type":"image/png"}});
    });
    render(<TranscriptImage path="uploads/reload.png" name="reload.png" />);
    await flush();
    expect(screen.getByAltText("reload.png")).not.toHaveAttribute("src");
    expect(screen.getByAltText("reload.png")).toHaveAttribute("data-failure-count", "1");
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    await decode();
    expect(requests).toBe(2);
    expect(screen.getByAltText("reload.png")).toHaveAttribute("data-durable-loaded", "1");
    expect(screen.getByAltText("reload.png").getAttribute("src")).toMatch(/^blob:fetched-/);
  });

  it("refreshes native port on respawn while keeping preview until decode", async () => {
    let respawn: (() => void) | undefined;
    const requestImage = vi.fn((_path: string, _identity: Record<string, string>, port: number, done: (value: unknown) => void) => {
      done({kind:"image-response", status:200, mime:"image/png", bytes:new Uint8Array([1, 2]), port});
      return () => {};
    });
    mockHarnessPort(7788);
    Reflect.set(window, "harnessIPC", {
      endpointHeaders:true,
      requestImage,
      requestJSON: async () => ({kind:"response", status:200, text:JSON.stringify(endpointDescriptor), correlationId:""}),
      onBackendRespawned: (callback: () => void) => {respawn = callback; return () => {respawn = undefined;};},
    });
    render(<TranscriptImage path="uploads/port.png" name="port.png" previewUrl="blob:port" />);
    await flush();
    const oldProbe = lastProbe();
    mockHarnessPort(7799);
    await act(async () => { respawn?.(); });
    expect(requestImage.mock.calls.map(call => call[2])).toEqual([7788, 7799]);
    expect(requestImage.mock.calls.at(-1)?.[0]).toContain("/api/image?");
    expect(fetch).not.toHaveBeenCalled();
    expect(oldProbe.onload).toBeNull();
    expect(screen.getByAltText("port.png")).toHaveAttribute("src", "blob:port");
    await decode();
    expect(revokeSpy).toHaveBeenCalledWith("blob:port");
    expect(screen.getByAltText("port.png")).toHaveAttribute("data-durable-loaded", "1");
  });

  it("revokes preview only after decode and fetched URL on unmount; remount fetches anew", async () => {
    const view = render(<TranscriptImage path="uploads/ok.png" name="ok.png" previewUrl="blob:preview-ok" />);
    await flush();
    expect(revokeSpy).not.toHaveBeenCalledWith("blob:preview-ok");
    await decode();
    const url = screen.getByAltText("ok.png").getAttribute("src");
    expect(revokeSpy).toHaveBeenCalledWith("blob:preview-ok");
    expect(ownedTranscriptPreviewBlobCount()).toBe(0);
    view.unmount();
    expect(revokeSpy).toHaveBeenCalledWith(url);
    render(<TranscriptImage path="uploads/ok.png" name="ok.png" previewUrl="blob:preview-ok" />);
    expect(screen.getByAltText("ok.png")).not.toHaveAttribute("src");
    expect(ownedTranscriptPreviewBlobCount()).toBe(0);
    await decode();
    expect(screen.getByAltText("ok.png").getAttribute("src")).not.toBe(url);
  });

  it("passes durable identity to lightbox so it owns a separate resource lifetime", async () => {
    const onClick = vi.fn();
    render(<TranscriptImage path="input:session:sha" name="click.png" previewUrl="blob:preview-click" onImageClick={onClick} />);
    fireEvent.click(screen.getByAltText("click.png"));
    expect(onClick).toHaveBeenLastCalledWith("/api/image?path=input%3Asession%3Asha");
    await decode();
    fireEvent.click(screen.getByAltText("click.png"));
    expect(onClick).toHaveBeenLastCalledWith("/api/image?path=input%3Asession%3Asha");
  });

  it("caps requests after repeated decode failures", async () => {
    vi.useFakeTimers();
    render(<TranscriptImage path="uploads/fail.png" name="fail.png" />);
    for (let i = 1; i <= MAX_DURABLE_IMAGE_RETRIES; i++) {
      await flush();
      await act(async () => { lastProbe().onerror?.(); });
      await act(async () => { await vi.advanceTimersByTimeAsync(delayAfterDurableFailure(i) || 0); });
    }
    const count = vi.mocked(fetch).mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(fetch).toHaveBeenCalledTimes(count);
    expect(probes).toHaveLength(MAX_DURABLE_IMAGE_RETRIES);
    expect(screen.getByAltText("fail.png")).toHaveAttribute("data-failure-count", String(MAX_DURABLE_IMAGE_RETRIES));
  });

  it("suppresses an old session's response and never flashes its URL on prop replacement", async () => {
    let finishOld: ((response: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation(async path => {
      if (path === "/api/endpoint") return Response.json(endpointDescriptor);
      if (String(path).includes("old")) return new Promise<Response>(resolve => {finishOld = resolve;});
      return new Response("new", {headers:{"Content-Type":"image/png"}});
    });
    const view = render(<TranscriptImage path="input:old:sha" name="old.png" />);
    await flush();
    const signal = vi.mocked(fetch).mock.calls.at(-1)?.[1]?.signal;
    view.rerender(<TranscriptImage path="input:new:sha" name="new.png" />);
    expect(signal?.aborted).toBe(true);
    expect(screen.getByAltText("new.png")).not.toHaveAttribute("src");
    await decode();
    const url = screen.getByAltText("new.png").getAttribute("src");
    await act(async () => { finishOld?.(new Response("old", {headers:{"Content-Type":"image/png"}})); });
    expect(screen.getByAltText("new.png")).toHaveAttribute("src", url);
    expect(probes).toHaveLength(1);
  });

  it("cancels a stale decode and revokes its object URL on path replacement", async () => {
    const view = render(<TranscriptImage path="input:old:sha" name="old.png" />);
    await flush();
    const old = lastProbe(); const staleLoad = old.onload; const oldUrl = old.src;
    view.rerender(<TranscriptImage path="input:new:sha" name="new.png" />);
    expect(revokeSpy).toHaveBeenCalledWith(oldUrl);
    await act(async () => { staleLoad?.(); });
    expect(screen.getByAltText("new.png")).not.toHaveAttribute("src");
    await decode();
    expect(screen.getByAltText("new.png").getAttribute("src")).not.toBe(oldUrl);
  });

  it("does not authenticate or retry external images", async () => {
    vi.useFakeTimers();
    render(<TranscriptImage path="https://cdn.example/x.png" name="ext.png" />);
    fireEvent.error(screen.getByAltText("ext.png"));
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.getByAltText("ext.png")).toHaveAttribute("src", "https://cdn.example/x.png");
    expect(probes).toHaveLength(0);
  });
});
