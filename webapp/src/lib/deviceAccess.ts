import { getHarnessIpc } from './transport';
import { desktopBridgeMissing } from './operationalDiagnostic';
import type { JSONResponse } from '../../electron/json-response.mjs';

export type DeviceOperation = 'endpoint.read' | 'session.read' | 'session.events.read';
export type DeviceGrant = { operation: DeviceOperation; resource_id: string };
export type Device = { device_id: string; label: string; created_at: number; revoked_at: number | null; grants_revision: number; grants: DeviceGrant[] };
export type DeviceEndpoint = { endpoint_id: string; boot_id: string; supported: boolean };
export type Enrollment = { device_id: string; credential: string };
type Bridge = { endpointHeaders: true; requestJSON: (method: string, path: string, body: unknown, correlation: string, headers: Record<string, string>) => Promise<JSONResponse> };
function isBridge(value: unknown): value is Bridge {
  return record(value) && value.endpointHeaders === true && typeof value.requestJSON === 'function';
}
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function ownerToken(): string {
  return '__HARNESS_TOKEN__' in window && typeof window.__HARNESS_TOKEN__ === 'string' ? window.__HARNESS_TOKEN__ : '';
}
function isGrant(value: unknown): value is DeviceGrant {
  return record(value) && ['endpoint.read', 'session.read', 'session.events.read'].includes(String(value.operation)) && typeof value.resource_id === 'string';
}
function isDevice(value: unknown): value is Device {
  return record(value) && typeof value.device_id === 'string' && typeof value.label === 'string'
    && typeof value.created_at === 'number' && (value.revoked_at === null || typeof value.revoked_at === 'number')
    && typeof value.grants_revision === 'number' && Array.isArray(value.grants) && value.grants.every(isGrant);
}

/** A panel-scoped connection: never rediscover or replay a mutation automatically. */
export class DeviceAccessClient {
  private readonly bridge: unknown = getHarnessIpc();
  private readonly token = ownerToken();
  private readonly origin = window.location.origin;
  private endpoint: DeviceEndpoint | null = null;
  private closed = false;
  close(): void { this.closed = true; }
  private current(): void {
    if (this.closed || getHarnessIpc() !== this.bridge || ownerToken() !== this.token || window.location.origin !== this.origin) {
      throw new Error('Connection changed. Close and reopen Device access.');
    }
  }
  private async request(method: 'GET' | 'POST', path: string, body?: unknown): Promise<unknown> {
    this.current();
    const headers: Record<string, string> = { 'X-Harness-Protocol': '1' };
    if (this.endpoint) {
      headers['X-Harness-Endpoint'] = this.endpoint.endpoint_id;
      headers['X-Harness-Boot'] = this.endpoint.boot_id;
    }
    let response: JSONResponse;
    if (this.bridge) {
      if (!isBridge(this.bridge)) throw new Error('Update and reopen the desktop app.');
      response = await this.bridge.requestJSON(method, path, body, '', headers);
    } else {
      if (desktopBridgeMissing()) throw new Error('Desktop connection unavailable. Reopen the app.');
      const result = await fetch(path, {
        method, cache: 'no-store', headers: { ...headers, 'X-Harness-Token': this.token, 'Content-Type': 'application/json' },
        ...(method === 'POST' ? { body: JSON.stringify(body) } : {}),
      });
      response = { kind: 'response', status: result.status, text: await result.text(), correlationId: '' };
    }
    this.current();
    if (response.kind !== 'response' || response.status < 200 || response.status >= 300) {
      if (response.kind === 'response' && response.status === 409) this.closed = true;
      throw new Error('Device request failed. Check the connection; close and reopen this panel if the backend changed.');
    }
    const value: unknown = JSON.parse(response.text);
    if (!record(value) || value.ok !== true) throw new Error('Invalid device response.');
    return value;
  }
  async connect(): Promise<DeviceEndpoint> {
    const value = await this.request('GET', '/api/endpoint');
    if (!record(value) || value.protocol_version !== 1 || typeof value.endpoint_id !== 'string' || !value.endpoint_id
      || typeof value.boot_id !== 'string' || !value.boot_id || !Array.isArray(value.capabilities) || !value.capabilities.includes('endpoint_fence_v1')) {
      throw new Error('Device access requires a compatible backend.');
    }
    this.endpoint = { endpoint_id: value.endpoint_id, boot_id: value.boot_id, supported: value.device_auth === 'bounded_read_v1' };
    return this.endpoint;
  }
  private supported(): void {
    if (!this.endpoint?.supported) throw new Error('Device access is unavailable on this backend.');
  }
  async list(): Promise<Device[]> {
    this.supported();
    const value = await this.request('GET', '/api/devices');
    if (!record(value) || !Array.isArray(value.devices) || !value.devices.every(isDevice)) throw new Error('Invalid device list.');
    return value.devices;
  }
  async enroll(label: string, grants: DeviceGrant[]): Promise<Enrollment> {
    this.supported();
    if (!label.trim() || label.length > 100 || grants.length < 1 || grants.length > 64) throw new Error('Enter a label and select 1–64 grants.');
    const value = await this.request('POST', '/api/devices/enroll', { label, grants });
    if (!record(value) || typeof value.device_id !== 'string' || typeof value.credential !== 'string' || !value.credential) throw new Error('Enrollment response unavailable.');
    return { device_id: value.device_id, credential: value.credential };
  }
  async revoke(id: string): Promise<void> {
    this.supported();
    await this.request('POST', `/api/devices/${encodeURIComponent(id)}/revoke`, {});
  }
}
