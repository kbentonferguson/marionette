"use strict";

const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { isDeepStrictEqual } = require('node:util');

function parseReceipt(receipt) {
  if (!receipt || receipt.schema !== 1 || receipt.owner !== 'external'
      || !Number.isInteger(receipt.port) || receipt.port < 1 || receipt.port > 65535
      || !Number.isInteger(receipt.pid) || receipt.pid < 1
      || ['endpoint_id', 'boot_id', 'launch_id', 'repo_root', 'token_file'].some(k =>
        typeof receipt[k] !== 'string' || !receipt[k])
      || !receipt.environment || !receipt.environment.source_sha || !receipt.environment.source_digest) {
    throw new Error('Invalid external backend receipt');
  }
  return receipt;
}

function validateReceipt(expected, live) {
  for (const key of ['schema', 'owner', 'port', 'pid', 'endpoint_id', 'boot_id', 'launch_id', 'repo_root', 'token_file']) {
    if (expected[key] !== live[key]) throw new Error('Backend identity changed; work may be interrupted. Reattach explicitly.');
  }
  if (!isDeepStrictEqual(expected.environment, live.environment)) {
    throw new Error('Backend environment changed; operator restart required.');
  }
}

function probe(receipt, token) {
  return new Promise((resolve, reject) => {
    const req = http.get({host:'127.0.0.1', port:receipt.port, path:'/api/backend/lifetime',
      headers:{'X-Harness-Token':token, 'X-Harness-Protocol':'1',
        'X-Harness-Endpoint':receipt.endpoint_id, 'X-Harness-Boot':receipt.boot_id}, timeout:2000}, res => {
      let raw = '';
      res.setEncoding('utf8');
      res.on('data', chunk => {
        raw += chunk;
        if (raw.length > 65536) req.destroy(new Error('Backend receipt response too large'));
      });
      res.on('error', reject);
      res.on('aborted', () => reject(new Error('Backend interrupted during attachment')));
      res.on('end', () => {
        if (res.statusCode !== 200) return reject(new Error(`Backend attachment refused (HTTP ${res.statusCode}); interruption or readiness drift requires operator attention.`));
        try { resolve(JSON.parse(raw)); } catch { reject(new Error('Invalid backend readiness response')); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('Backend attachment timed out; work may be interrupted.')));
    req.on('error', reject);
  });
}

// Cache the first receipt: replacing the file must not silently change this client's boot.
const receipts = new Map();
async function attachBackend(receiptPath, repoRoot) {
  const key = path.resolve(receiptPath);
  if (!receipts.has(key)) receipts.set(key, parseReceipt(JSON.parse(fs.readFileSync(key, 'utf8'))));
  const receipt = receipts.get(key);
  if (path.resolve(receipt.repo_root) !== path.resolve(repoRoot)) throw new Error('Backend checkout differs from client checkout');
  const token = fs.readFileSync(receipt.token_file, 'utf8').trim();
  if (!token) throw new Error('Backend token unavailable');
  const live = await probe(receipt, token);
  validateReceipt(receipt, live);
  return {receipt, token};
}

module.exports = {attachBackend, validateReceipt};
