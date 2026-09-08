import { useEffect, useRef, useState } from 'react';
import { DeviceAccessClient, type Device, type DeviceEndpoint, type DeviceGrant, type Enrollment } from '../lib/deviceAccess';

const button = 'min-h-11 px-3 py-2 rounded-md border border-edge text-txt hover:bg-panel2 disabled:opacity-50';
const input = 'min-h-11 rounded-md border border-edge bg-bg text-txt px-3 py-2 w-full';
const grantLabels = {
  'endpoint.read': 'Endpoint metadata',
  'session.read': 'Session metadata',
  'session.events.read': 'Retained content/events',
} satisfies Record<DeviceGrant['operation'], string>;

export default function DeviceAccess() {
  const connection = useRef<DeviceAccessClient | null>(null);
  const secretFocus = useRef<HTMLButtonElement>(null);
  const labelFocus = useRef<HTMLInputElement>(null);
  const hadSecret = useRef(false);
  const refreshFocus = useRef<HTMLButtonElement>(null);
  const returnToRefresh = useRef(false);
  const [endpoint, setEndpoint] = useState<DeviceEndpoint | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [label, setLabel] = useState('');
  const [session, setSession] = useState('');
  const [grants, setGrants] = useState<DeviceGrant[]>([]);
  const [secret, setSecret] = useState<Enrollment | null>(null);
  const [shown, setShown] = useState(false);
  const [copyStatus, setCopyStatus] = useState('');
  const [uncertain, setUncertain] = useState(false);

  useEffect(() => {
    const client = new DeviceAccessClient();
    connection.current = client;
    void (async () => {
      try {
        const identity = await client.connect();
        if (connection.current !== client) return;
        setEndpoint(identity);
        if (identity.supported) {
          const list = await client.list();
          if (connection.current === client) setDevices(list);
        }
      } catch { if (connection.current === client) setError('Could not load device access. Close and reopen this panel to reconnect.'); }
      finally { if (connection.current === client) setBusy(false); }
    })();
    return () => { connection.current = null; client.close(); };
  }, []);
  useEffect(() => {
    if (secret) secretFocus.current?.focus();
    else if (hadSecret.current) labelFocus.current?.focus();
    hadSecret.current = secret !== null;
  }, [secret]);
  useEffect(() => {
    if (!busy && returnToRefresh.current) {
      returnToRefresh.current = false;
      refreshFocus.current?.focus();
    }
  }, [busy]);

  function toggle(grant: DeviceGrant) {
    setGrants(previous => previous.some(g => g.operation === grant.operation && g.resource_id === grant.resource_id)
      ? previous.filter(g => g.operation !== grant.operation || g.resource_id !== grant.resource_id) : [...previous, grant]);
  }
  async function refresh() {
    const client = connection.current;
    if (!client || busy) return;
    setBusy(true); setError('');
    try {
      const list = await client.list();
      if (connection.current === client) setDevices(list);
    } catch { if (connection.current === client) setError('Could not refresh devices. Close and reopen this panel if the backend changed.'); }
    finally { if (connection.current === client) setBusy(false); }
  }
  async function enroll() {
    const client = connection.current;
    if (!client || busy) return;
    setBusy(true); setError('');
    try {
      const result = await client.enroll(label, grants);
      if (connection.current !== client) return;
      setSecret(result); setShown(false); setCopyStatus('');
      setDevices(previous => [...previous, { device_id: result.device_id, label, grants: [...grants], created_at: Date.now() / 1000, revoked_at: null, grants_revision: 1 }]);
      setLabel(''); setGrants([]); setSession('');
    } catch {
      if (connection.current === client) {
        setUncertain(true);
        setError('Enrollment outcome is unknown. Refresh the list before trying again. A new device may need to be revoked if its one-time credential was not received.');
      }
    } finally { if (connection.current === client) setBusy(false); }
  }
  async function revoke(id: string, restoreFocus: boolean) {
    const client = connection.current;
    if (!client || busy) return;
    setBusy(true); setError('');
    try {
      await client.revoke(id);
      if (connection.current !== client) return;
      returnToRefresh.current = restoreFocus;
      setDevices(previous => previous.map(d => d.device_id === id ? { ...d, revoked_at: d.revoked_at ?? Date.now() / 1000, grants_revision: d.revoked_at === null ? d.grants_revision + 1 : d.grants_revision } : d));
      if (secret?.device_id === id) { setSecret(null); setShown(false); setCopyStatus(''); }
    } catch { if (connection.current === client) setError('Revocation could not be confirmed. Refresh the list and retry revoking if it is still active.'); }
    finally { if (connection.current === client) setBusy(false); }
  }
  async function copy() {
    if (!secret) return;
    const client = connection.current;
    try {
      await navigator.clipboard.writeText(secret.credential);
      if (connection.current === client) setCopyStatus('Copied. Keep it somewhere private.');
    } catch { if (connection.current === client) setCopyStatus('Copy unavailable. Use Show credential and copy it manually.'); }
  }
  const enabled = endpoint?.supported === true;
  return <section aria-label="Device access" className="space-y-3 text-sm text-muted">
    <p>Give a device read-only access to explicitly selected information on this endpoint. This does not allow commands, files, or live remote execution.</p>
    {busy && <p role="status">Loading device access…</p>}
    {error && <p role="alert">{error}</p>}
    {endpoint && <details><summary className="cursor-pointer text-txt">Connection details</summary><p className="break-all">Endpoint: {endpoint.endpoint_id}<br />Backend boot: {endpoint.boot_id}</p></details>}
    {endpoint && !enabled && <p>Device access is disabled or unsupported on this platform. No enrollment or access changes are available.</p>}
    {enabled && <>
      <button type="button" ref={refreshFocus} className={button} disabled={busy} onClick={() => void refresh()}>Refresh devices</button>
      {secret && <div className="space-y-2 rounded-md border border-edge p-3" aria-label="One-time credential">
        <p>Device enrolled: <span className="break-all">{secret.device_id}</span>. This credential is available only now. Dismissing it or closing Settings clears it from this panel.</p>
        <button type="button" ref={secretFocus} className={button} onClick={() => setShown(v => !v)}>{shown ? 'Hide credential' : 'Show credential'}</button>{' '}
        <button type="button" className={button} onClick={() => void copy()}>Copy credential</button>{' '}
        <button type="button" className={button} onClick={() => { setSecret(null); setShown(false); setCopyStatus(''); }}>Dismiss credential</button>
        {shown && <pre className="whitespace-pre-wrap break-all select-all">{secret.credential}</pre>}
        {copyStatus && <p role="status">{copyStatus}</p>}
      </div>}
      <form className="space-y-3" onSubmit={event => { event.preventDefault(); void enroll(); }}>
        <fieldset disabled={busy || secret !== null || uncertain} className="space-y-3">
          <legend className="text-txt font-medium">Enroll a device</legend>
          <label className="block">Device label<input ref={labelFocus} className={input} value={label} maxLength={100} onChange={event => setLabel(event.target.value)} /></label>
          <label className="flex items-center gap-2 min-h-11"><input type="checkbox" checked={grants.some(g => g.operation === 'endpoint.read')} onChange={() => toggle({ operation: 'endpoint.read', resource_id: endpoint.endpoint_id })} />Read endpoint metadata</label>
          <label className="block">Exact session ID<input className={input} value={session} maxLength={200} onChange={event => setSession(event.target.value)} /></label>
          <p>Session metadata includes its title and workspace identity. Retained session content/events may contain prompts, replies, and tool output. Events are retained snapshots, not a live stream. Each permission applies only to the exact session ID you add.</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={button} disabled={!session.trim() || session !== session.trim() || grants.length >= 64} onClick={() => { if (!grants.some(g => g.operation === 'session.read' && g.resource_id === session)) toggle({ operation: 'session.read', resource_id: session }); }}>Add session metadata</button>
            <button type="button" className={button} disabled={!session.trim() || session !== session.trim() || grants.length >= 64} onClick={() => { if (!grants.some(g => g.operation === 'session.events.read' && g.resource_id === session)) toggle({ operation: 'session.events.read', resource_id: session }); }}>Add retained content/events</button>
          </div>
          <ul className="space-y-2">{grants.map(g => <li key={`${g.operation}:${g.resource_id}`} className="break-all">{grantLabels[g.operation]}: {g.resource_id}{' '}<button type="button" className={button} onClick={() => toggle(g)} aria-label={`Remove ${grantLabels[g.operation]} for ${g.resource_id}`}>Remove</button></li>)}</ul>
          <button className={button} type="submit" disabled={!label.trim() || grants.length === 0 || grants.length > 64}>Enroll device</button>
        </fieldset>
      </form>
      {uncertain && <p>After reviewing the refreshed list and revoking any unwanted device, close and reopen this panel to begin a new enrollment. Your draft remains here until then.</p>}
      <h4 className="font-medium text-txt">Enrolled devices</h4>
      {!devices.length && !busy && <p>No devices enrolled.</p>}
      <ul className="space-y-3">{devices.map(device => <li key={device.device_id} className="space-y-2 border border-edge rounded-md p-3">
        <p className="text-txt break-all">{device.label} — {device.revoked_at === null ? 'Active' : 'Revoked'}</p>
        <p className="break-all">Device ID: {device.device_id}</p>
        <p>Grant revision: {device.grants_revision}</p>
        <ul>{device.grants.map(g => <li className="break-all" key={`${g.operation}:${g.resource_id}`}>{grantLabels[g.operation]}: {g.resource_id}</li>)}</ul>
        <button type="button" className={button} disabled={busy || device.revoked_at !== null} onClick={event => void revoke(device.device_id, document.activeElement === event.currentTarget)} aria-label={`Revoke ${device.label}`}>{device.revoked_at === null ? 'Revoke device' : 'Revoked'}</button>
      </li>)}</ul>
    </>}
  </section>;
}
