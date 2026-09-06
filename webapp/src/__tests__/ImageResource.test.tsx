import { StrictMode } from 'react';
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ImageResource } from '../components/conversation/ImageResource';
import { endpointDescriptor } from './endpointFixture';

beforeEach(() => {
  let count = 0;
  vi.spyOn(URL, 'createObjectURL').mockImplementation(() => `blob:resource-${++count}`);
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  vi.stubGlobal('fetch', vi.fn(async path => path === '/api/endpoint' ? Response.json(endpointDescriptor) : new Response('pixels', {headers:{'Content-Type':'image/png'}})));
  vi.stubGlobal('Image', class { onload: (() => void) | null = null; onerror = null; set src(value: string) { if (value) queueMicrotask(() => this.onload?.()); } });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('receipt and lightbox mounts own independent URLs and strict-mode cleanup cannot revoke another mount', async () => {
  const receipt = render(<StrictMode><ImageResource src="/api/image?path=input%3As%3Asha" alt="receipt" /></StrictMode>);
  const lightbox = render(<ImageResource src="/api/image?path=input%3As%3Asha" alt="lightbox" />);
  await act(async () => { await Promise.resolve(); });
  const receiptUrl = screen.getByAltText('receipt').getAttribute('src');
  const lightboxUrl = screen.getByAltText('lightbox').getAttribute('src');
  expect(receiptUrl).toMatch(/^blob:/);
  expect(lightboxUrl).toMatch(/^blob:/);
  expect(receiptUrl).not.toBe(lightboxUrl);
  receipt.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith(receiptUrl);
  expect(URL.revokeObjectURL).not.toHaveBeenCalledWith(lightboxUrl);
  lightbox.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith(lightboxUrl);
});

it('wrong-origin API lookalikes never enter a raw img source or authenticated fetch', async () => {
  vi.useFakeTimers();
  render(<ImageResource src="https://evil.example/api/image?path=x" alt="refused" />);
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.getByAltText('refused')).not.toHaveAttribute('src');
});

it('hanging loads exhaust a finite timeout budget without a retry loop', async () => {
  vi.useFakeTimers();
  const signals: AbortSignal[] = [];
  vi.mocked(fetch).mockImplementation(async (path, init) => {
    if (path === '/api/endpoint') return Response.json(endpointDescriptor);
    if (init?.signal) signals.push(init.signal);
    return new Promise<Response>((_resolve, reject) => init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once:true}));
  });
  render(<ImageResource src="/api/image?path=hanging" alt="hanging" />);
  await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
  expect(signals).toHaveLength(5);
  expect(signals.every(signal => signal.aborted)).toBe(true);
  expect(screen.getByAltText('hanging')).toHaveAttribute('data-image-state', 'error');
});
