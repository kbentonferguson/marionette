import { useEffect, useState } from "react";
import { fetchImage, getHarnessIpc } from "./transport";
import { delayAfterDurableFailure, MAX_DURABLE_IMAGE_RETRIES } from "../components/conversation/transcriptImageRetry";

type ImageState = { source: string; url: string | undefined; failures: number; loaded: boolean };

/** Mount-owned authenticated bytes. No shared or persistent browser cache. */
export function useImageResource(source: string, backend: boolean) {
  const [state, setState] = useState<ImageState>({source, url: undefined, failures: 0, loaded: false});
  useEffect(() => {
    if (!backend) return;
    let closed = false;
    let generation = 0;
    let attempts = 0;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    let release: (() => void) | undefined;
    let loaded = false;
    const clearAttempt = () => {
      controller?.abort();
      clearTimeout(timeout);
      release?.();
      release = undefined;
    };
    const attempt = async () => {
      if (closed || loaded || attempts >= MAX_DURABLE_IMAGE_RETRIES) return;
      clearTimeout(timer);
      clearAttempt();
      const gen = ++generation;
      attempts++;
      controller = new AbortController();
      const signal = controller.signal;
      timeout = setTimeout(() => controller?.abort(), 15_000);
      setState({source, url: undefined, failures, loaded: false});
      try {
        const resource = await fetchImage(source, signal);
        if (closed || gen !== generation || signal.aborted) return;
        resource.assertCurrent();
        const url = URL.createObjectURL(resource.blob);
        const probe = new Image();
        release = () => {
          probe.onload = null;
          probe.onerror = null;
          probe.src = "";
          URL.revokeObjectURL(url);
        };
        await new Promise<void>((resolve, reject) => {
          const abort = () => reject(new DOMException("Image load aborted", "AbortError"));
          signal.addEventListener("abort", abort, {once: true});
          probe.onload = () => { signal.removeEventListener("abort", abort); resolve(); };
          probe.onerror = () => { signal.removeEventListener("abort", abort); reject(new Error("Image decode failed")); };
          probe.src = url;
        });
        if (closed || gen !== generation || signal.aborted) return;
        resource.assertCurrent();
        clearTimeout(timeout);
        loaded = true;
        setState({source, url, failures, loaded: true});
      } catch {
        if (closed || gen !== generation) return;
        clearAttempt();
        failures++;
        setState({source, url: undefined, failures, loaded: false});
        const delay = delayAfterDurableFailure(failures);
        if (attempts < MAX_DURABLE_IMAGE_RETRIES && delay !== null) timer = setTimeout(() => { void attempt(); }, delay);
      }
    };
    void attempt();
    const ipc = getHarnessIpc();
    const unsubscribe = typeof ipc?.onBackendRespawned === "function"
      ? ipc.onBackendRespawned(() => { void attempt(); }) : undefined;
    return () => {
      closed = true;
      generation++;
      clearTimeout(timer);
      clearAttempt();
      unsubscribe?.();
    };
  }, [source, backend]);
  if (!backend) return {url: source || undefined, loaded: false, failures: 0};
  return state.source === source ? state : {url: undefined, loaded: false, failures: 0};
}
