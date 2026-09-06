import { renderHook, waitFor, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearSWRCache, useStaleWhileRevalidate, writeSWRCache } from "../lib/useStaleWhileRevalidate";

describe("useStaleWhileRevalidate", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    clearSWRCache();
    sessionStorage.clear();
  });

  it("keeps stale data visible while a new key revalidates", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(["a"])
      .mockImplementationOnce(
        () => new Promise((resolve) => setTimeout(() => resolve(["b"]), 50)),
      );

    const { result, rerender } = renderHook(
      ({ key }) => useStaleWhileRevalidate<string[]>(key, fetcher),
      { initialProps: { key: "one" } },
    );

    await waitFor(() => expect(result.current.data).toEqual(["a"]));
    expect(result.current.isShowingStale).toBe(false);

    rerender({ key: "two" });

    expect(result.current.data).toEqual(["a"]);
    expect(result.current.isValidating).toBe(true);
    expect(result.current.isShowingStale).toBe(true);

    await waitFor(() => expect(result.current.data).toEqual(["b"]));
    expect(result.current.isShowingStale).toBe(false);
    expect(result.current.isValidating).toBe(false);
  });

  it("coalesces simultaneous same-key refreshes and keeps current data stable", async () => {
    let finish: (value: string) => void = () => {};
    const pending = new Promise<string>((resolve) => { finish = resolve; });
    const fetcher = vi.fn().mockResolvedValueOnce("initial").mockReturnValueOnce(pending);
    const { result } = renderHook(() => useStaleWhileRevalidate("key", fetcher));
    await waitFor(() => expect(result.current.data).toBe("initial"));
    let first: Promise<unknown>;
    let second: Promise<unknown>;
    act(() => {
      first = result.current.revalidate();
      second = result.current.revalidate();
    });
    expect(result.current.data).toBe("initial");
    expect(result.current.isTransitioning).toBe(false);
    await act(async () => {
      finish("fresh");
      await Promise.all([first, second]);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(result.current.data).toBe("fresh");
  });

  it("ignores old-key responses even when the fetcher ignores abort", async () => {
    let finish: (value: string) => void = () => {};
    const pending = new Promise<string>((resolve) => { finish = resolve; });
    const fetcher = vi.fn().mockReturnValueOnce(pending).mockResolvedValueOnce("new");
    const { result, rerender } = renderHook(
      ({ key }) => useStaleWhileRevalidate(key, fetcher),
      { initialProps: { key: "old" } },
    );
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    rerender({ key: "new" });
    await waitFor(() => expect(result.current.data).toBe("new"));
    await act(async () => { finish("old"); await pending; });
    expect(result.current.data).toBe("new");
  });

  it("forces a post-mutation read without accepting an older response", async () => {
    let finish: (value: string) => void = () => {};
    const pending = new Promise<string>((resolve) => { finish = resolve; });
    const fetcher = vi.fn().mockReturnValueOnce(pending).mockResolvedValueOnce("cancelled");
    const { result } = renderHook(() => useStaleWhileRevalidate("mutation", fetcher));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    await act(async () => { await result.current.revalidate(true); });
    await act(async () => { finish("running"); await pending; });
    expect(result.current.data).toBe("cancelled");
  });

  it("does not fetch while disabled and refreshes on activation", async () => {
    const fetcher = vi.fn().mockResolvedValue([]);
    const { result, rerender } = renderHook(
      ({ enabled }) => useStaleWhileRevalidate("disabled", fetcher, { enabled }),
      { initialProps: { enabled: false } },
    );
    await act(async () => { await result.current.revalidate(); });
    expect(fetcher).not.toHaveBeenCalled();
    rerender({ enabled: true });
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    expect(result.current.isTransitioning).toBe(false);
  });

  it("rehydrates swarm keys from sessionStorage after cache clear", async () => {
    writeSWRCache("swarm:/tmp/proj", { session: { tokens_used: 1, est_cost_usd: 0 }, jobs: [] });
    clearSWRCache();
    // clearSWRCache wipes sessionStorage too -- seed persist directly.
    sessionStorage.setItem(
      "swr.persist.v1:swarm:/tmp/proj",
      JSON.stringify({ session: { tokens_used: 9, est_cost_usd: 0.1 }, jobs: [{ id: "j1" }] }),
    );

    const fetcher = vi.fn().mockImplementation(
      () => new Promise(() => {}), // never resolves -- stay on persisted seed
    );
    const { result } = renderHook(() =>
      useStaleWhileRevalidate("swarm:/tmp/proj", fetcher),
    );

    expect(result.current.data).toEqual({
      session: { tokens_used: 9, est_cost_usd: 0.1 },
      jobs: [{ id: "j1" }],
    });
  });
});
