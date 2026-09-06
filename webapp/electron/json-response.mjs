/** Plain HTTP response data is safe across Electron invoke and contextBridge. */
export function parseJSONResponse(response, path, soft = false) {
  if (response.kind === 'connection-error') {
    throw Object.assign(new Error(response.message), { code: response.code });
  }
  const { status, text, correlationId } = response;
  const ok = status >= 200 && status < 300;
  let body;
  let malformed = false;
  try {
    body = text === '' && (status === 204 || status === 205) ? null : JSON.parse(text);
  } catch {
    malformed = true;
    body = soft ? {} : text;
  }
  const fallback = `${path} -> ${status}`;
  if (soft) {
    if (!ok) {
      if (body && typeof body === 'object') {
        return 'ok' in body ? body : { ok: false, error: body.error || fallback, ...body };
      }
      return { ok: false, error: fallback };
    }
    return body;
  }
  if (!ok || malformed) {
    const fields = body && typeof body === 'object' && !Array.isArray(body) ? body : {};
    const message = !ok ? String(fields.error || fallback) : `Invalid JSON response: ${fallback}`;
    const error = new Error(message);
    // Preserve backend detail fields used by lease-capacity callers, but never
    // let a response overwrite Error identity or authoritative transport data.
    for (const [key, value] of Object.entries(fields)) {
      if (!['__proto__', 'constructor', 'prototype', 'name', 'message', 'stack'].includes(key)) {
        Object.defineProperty(error, key, { value, enumerable: true, configurable: true, writable: true });
      }
    }
    Object.assign(error, { message, status, body, correlationId });
    if (ok && malformed) error.code = 'INVALID_JSON_RESPONSE';
    throw error;
  }
  return body;
}
