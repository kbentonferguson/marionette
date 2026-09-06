import { describe, it, expect } from 'vitest';
import { EndpointSessionClient } from '../lib/endpointSession';
const identity = (boot = 'a') => ({ok:true, protocol_version:1, endpoint_id:'endpoint', boot_id:boot, capabilities:['endpoint_fence_v1','session_replay_fence_v1']});
const reply = (status: number, body: unknown) => ({kind:'response' as const, status, text:JSON.stringify(body), correlationId:''});
describe('endpoint session identity', () => {
  it('deduplicates discovery and captures immutable pins', async () => {
    const client = new EndpointSessionClient();
    let calls = 0;
    const discover = async () => { calls++; return reply(200, identity()); };
    const [a,b] = await Promise.all([client.connect(discover),client.connect(discover)]);
    expect(calls).toBe(1); expect(a).toBe(b);
    expect(client.headers(a)['X-Harness-Boot']).toBe('a');
  });
  it('only explicit 404 permits legacy', async () => {
    expect((await new EndpointSessionClient().connect(async()=>reply(404,{}))).kind).toBe('legacy');
    for (const status of [401,403,500,426]) await expect(new EndpointSessionClient().connect(async()=>reply(status,{}))).rejects.toThrow();
    await expect(new EndpointSessionClient().connect(async()=>reply(200,{...identity(),protocol_version:2}))).rejects.toThrow();
  });
  it('an old failure cannot invalidate new pins or accept old replies', async () => {
    const client = new EndpointSessionClient();
    const a = await client.connect(async()=>reply(200,identity()));
    client.invalidate(a);
    const b = await client.connect(async()=>reply(200,identity('b')));
    client.invalidate(a);
    expect(client.isCurrent(b)).toBe(true); expect(client.isCurrent(a)).toBe(false);
  });
  it('scopes opaque stream cursors to endpoint boot and explicit session', async () => {
    const client = new EndpointSessionClient();
    const a = await client.connect(async()=>reply(200,identity()));
    const first = client.prepare('/api/session/events?session=s&since=99&generation=5',a);
    expect(first.path).not.toContain('generation'); expect(first.path).toContain('since=0');
    client.accept(first,{session_id:'s',stream_id:'opaque',cursor:4,events:[]});
    expect(client.prepare('/api/session/events?session=s&since=4',a).path).toContain('stream_id=opaque');
    expect(client.prepare('/api/session/events?session=other&since=4',a).path).toContain('since=0');
    expect(()=>client.prepare('/api/session/events',a)).toThrow(/session/i);
    client.invalidate(a);
    const b = await client.connect(async()=>reply(200,identity('b')));
    expect(client.prepare('/api/session/events?session=s&since=4',b).path).toContain('since=0');
    expect(()=>client.accept(first,{session_id:'s',stream_id:'old'})).toThrow();
  });
});

it('rejects late same-session responses and wrong-session envelopes', async () => {
  const client = new EndpointSessionClient();
  const pin = await client.connect(async()=>reply(200,identity()));
  const old = client.prepare('/api/session/events?session=s',pin);
  const current = client.prepare('/api/session/events?session=s',pin);
  client.accept(current,{session_id:'s',stream_id:'new',events:[]});
  expect(()=>client.accept(old,{session_id:'s',stream_id:'old',events:[]})).toThrow();
  expect(()=>client.accept(client.prepare('/api/session/events?session=s',pin),{session_id:'other',stream_id:'new'})).toThrow();
  expect(client.prepare('/api/session/events?session=s&since=3',pin).path).toContain('stream_id=new');
});

it('resets ring cursors per boot and session without inventing a ring stream token', async () => {
  const client = new EndpointSessionClient();
  const a=await client.connect(async()=>reply(200,identity()));
  const first=client.prepare('/api/chat/events?session=s&since=12&generation=4&watch=1',a);
  expect(first.ringReset).toBe(true); expect(first.path).toContain('since=0');
  expect(first.path).not.toContain('generation'); expect(first.path).not.toContain('stream_id');
  expect(client.prepare('/api/chat/events?session=s&since=12',a).ringReset).toBe(false);
  client.invalidate(a);
  const b=await client.connect(async()=>reply(200,identity('b')));
  expect(client.prepare('/api/chat/events?session=s&since=12',b).ringReset).toBe(true);
});
