const http = require('node:http');
const MAX_IMAGE_BYTES = 32 * 1024 * 1024;
const IMAGE_TIMEOUT_MS = 15000;
const failure = code => ({kind: 'image-error', code});

function imageRequest(path, identity, backend) {
  if (typeof path !== 'string' || path.length > 16384 || !path.startsWith('/api/image?')
    || /[\x00-\x20\x7f\\#]/.test(path)) throw new Error('invalid');
  const url = new URL(path, 'http://127.0.0.1');
  if (url.pathname !== '/api/image' || url.pathname + url.search !== path
    || [...url.searchParams.keys()].some(key => key !== 'path' && key !== '_r')
    || url.searchParams.getAll('path').length !== 1 || url.searchParams.getAll('_r').length > 1
    || !url.searchParams.get('path')?.trim() || /[\x00-\x1f\x7f]/.test(url.searchParams.get('path'))
    || /%(?![a-f\d]{2})/i.test(path)) throw new Error('invalid');
  if (!Number.isInteger(backend.port) || backend.port < 1 || backend.port > 65535
    || typeof backend.token !== 'string' || !backend.token) throw new Error('invalid');
  const headers = {'X-Harness-Token': backend.token};
  for (const name of ['X-Harness-Protocol', 'X-Harness-Endpoint', 'X-Harness-Boot']) {
    const value = identity?.[name];
    if (typeof value !== 'string' || !/^[\x21-\x7e]{1,256}$/.test(value)) throw new Error('invalid');
    headers[name] = value;
  }
  if (headers['X-Harness-Protocol'] !== '1') throw new Error('invalid');
  return {host: '127.0.0.1', port: backend.port, path, method: 'GET', headers};
}

/** A single bounded request; all failures are fixed codes, never backend text. */
function startImageRequest({path, identity, backend, request = http.request, timeoutMs = IMAGE_TIMEOUT_MS}) {
  let req, res, timer, settled = false;
  let finish;
  const promise = new Promise(resolve => {
    finish = value => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
      res?.destroy();
      req?.destroy();
    };
    try {
      const options = imageRequest(path, identity, backend);
      timer = setTimeout(() => finish(failure('timeout')), timeoutMs);
      req = request(options, response => {
        if (settled) { response.destroy(); return; }
        res = response;
        res.on('error', () => finish(failure('connection')));
        res.on('aborted', () => finish(failure('connection')));
        const status = res.statusCode;
        if (!Number.isInteger(status)) { finish(failure('response')); return; }
        if (status < 200 || status >= 300) {
          finish({kind:'image-response', status, mime:'', bytes:new Uint8Array(0), port:backend.port});
          return;
        }
        const mime = String(res.headers['content-type'] || '').split(';', 1)[0].trim().toLowerCase();
        if (!/^image\/[a-z0-9.+-]+$/.test(mime)) { finish(failure('mime')); return; }
        const declared = res.headers['content-length'];
        if (declared !== undefined && (!/^\d+$/.test(String(declared)) || Number(declared) > MAX_IMAGE_BYTES)) {
          finish(failure('size')); return;
        }
        let size = 0;
        const chunks = [];
        res.on('data', chunk => {
          if (settled) return;
          size += chunk.length;
          if (size > MAX_IMAGE_BYTES) { finish(failure('size')); return; }
          chunks.push(chunk);
        });
        res.on('end', () => {
          if (settled) return;
          if (!size || (declared !== undefined && Number(declared) !== size)) { finish(failure('size')); return; }
          finish({kind:'image-response', status, mime, bytes:new Uint8Array(Buffer.concat(chunks, size)), port:backend.port});
        });
      });
      req.on('error', () => finish(failure('connection')));
      req.end();
    } catch { finish(failure('request')); }
  });
  return {promise, cancel: () => finish(failure('aborted'))};
}

function registerImageBridge(ipcMain, {getBackend, isAllowedSender, start = startImageRequest}) {
  const owners = new Map();
  ipcMain.handle('harness:requestImage', async (event, id, path, identity, expectedPort) => {
    if (!isAllowedSender(event) || typeof id !== 'string' || !/^image-\d+$/.test(id) || id.length > 40) return failure('request');
    const sender = event.sender;
    const backend = getBackend();
    if (backend.port !== expectedPort) return failure('stale');
    let owner = owners.get(sender);
    if (!owner) {
      owner = {requests:new Map(), destroy:() => {
        owners.delete(sender);
        for (const handle of owner.requests.values()) handle.cancel();
        owner.requests.clear();
      }};
      owners.set(sender, owner);
      sender.once('destroyed', owner.destroy);
    }
    if (owner.requests.has(id) || owner.requests.size >= 64) return failure('request');
    const handle = start({path, identity, backend});
    owner.requests.set(id, handle);
    try {
      const result = await handle.promise;
      if (sender.isDestroyed() || !isAllowedSender(event)) return failure('aborted');
      const now = getBackend();
      if (now.port !== backend.port || now.token !== backend.token) return failure('stale');
      return result;
    } finally {
      owner.requests.delete(id);
      if (!owner.requests.size) {
        sender.removeListener('destroyed', owner.destroy);
        if (owners.get(sender) === owner) owners.delete(sender);
      }
    }
  });
  ipcMain.on('harness:cancelImage', (event, id) => {
    if (isAllowedSender(event)) owners.get(event.sender)?.requests.get(id)?.cancel();
  });
}
module.exports = {MAX_IMAGE_BYTES, IMAGE_TIMEOUT_MS, startImageRequest, registerImageBridge};
