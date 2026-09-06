import type { JSONResponse } from '../../electron/json-response.mjs';

export const endpointDescriptor = {
  ok: true,
  protocol_version: 1,
  endpoint_id: 'fixture-endpoint',
  boot_id: 'fixture-boot',
  capabilities: ['endpoint_fence_v1', 'session_replay_fence_v1'],
};

/** Keep discovery separate from operation responses, including held requests. */
export function withEndpointDiscovery(operation: typeof fetch): typeof fetch {
  return (input, init) => input === '/api/endpoint'
    ? Promise.resolve(Response.json(endpointDescriptor))
    : operation(input, init);
}

type DesktopRequest = (
  method: 'GET' | 'POST', path: string, body?: unknown,
  correlationId?: string, headers?: Record<string, string>,
) => Promise<JSONResponse>;

export function withDesktopEndpointDiscovery(operation: DesktopRequest): DesktopRequest {
  return (method, path, body, correlationId, headers) => path === '/api/endpoint'
    ? Promise.resolve({ kind: 'response', status: 200, text: JSON.stringify(endpointDescriptor), correlationId: '' })
    : operation(method, path, body, correlationId, headers);
}
