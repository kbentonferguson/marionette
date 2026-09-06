import { act, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { TranscriptImage } from '../components/conversation/TranscriptImage';
import { endpointDescriptor } from './endpointFixture';

afterEach(() => { vi.unstubAllGlobals(); Reflect.deleteProperty(window, '__HARNESS_TOKEN__'); });
it('mounted retained-original thumbnail fetches authenticated bytes instead of assigning a protected URL', async () => {
  Reflect.set(window, '__HARNESS_TOKEN__', 'browser-test-token');
  vi.stubGlobal('fetch', vi.fn(async (path, init) => {
    if (path === '/api/endpoint') return Response.json(endpointDescriptor);
    expect(init.headers['X-Harness-Token']).toBe('browser-test-token');
    expect(init.headers['X-Harness-Endpoint']).toBe('fixture-endpoint');
    expect(init.headers['X-Harness-Boot']).toBe('fixture-boot');
    expect(path).toBe('/api/image?path=input%3Asession%3Asha');
    return new Response('pixels', {headers: {'Content-Type': 'image/png'}});
  }));
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:authenticated');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  vi.stubGlobal('Image', class { onload: (() => void) | null = null; onerror = null; set src(value: string) { if (value) queueMicrotask(() => this.onload?.()); } });
  render(<TranscriptImage path="input:session:sha" name="original.png" />);
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(fetch).toHaveBeenCalled();
  expect(screen.getByAltText('original.png')).toHaveAttribute('src', 'blob:authenticated');
});
