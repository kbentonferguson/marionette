// Run from webapp: node scripts/check-chrome-accessibility.cjs --contrast-only
// Browser gate: ./node_modules/.bin/electron scripts/check-chrome-accessibility.cjs
// Uses an isolated temporary profile and static controls; never loads the app/backend.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '..');
const read = (name) => fs.readFileSync(path.join(root, name), 'utf8');
const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
const luminance = (color) => color.map((x) => x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4)
  .reduce((sum, x, i) => sum + x * [.2126, .7152, .0722][i], 0);
function contrast(fg, bg, alpha = 1) {
  const back = rgb(bg);
  const front = rgb(fg).map((x, i) => alpha * x + (1 - alpha) * back[i]);
  const values = [luminance(front), luminance(back)].sort((a, b) => a - b);
  return (values[1] + .05) / (values[0] + .05);
}
async function config() { return (await import(pathToFileURL(path.join(root, 'tailwind.config.js')))).default; }
function measure(colors) {
  const rows = [];
  for (const bg of [colors.bg, '#13161a', colors.panel, colors.panel2]) {
    for (const alpha of [1, .8, .7, .65, .5]) {
      const ratio = contrast(colors.faint, bg, alpha);
      rows.push({ foreground: colors.faint, background: bg, alpha, ratio: +ratio.toFixed(3) });
      if (alpha === 1) assert.ok(ratio >= 4.5, `Opaque faint on ${bg}: ${ratio}`);
    }
    assert.ok(contrast(colors.accent, bg) >= 3, `Focus on ${bg}`);
  }
  console.log(JSON.stringify(rows, null, 2));
}
if (process.argv.includes('--contrast-only')) {
  config().then((c) => measure(c.theme.extend.colors)).catch((e) => { console.error(e); process.exitCode = 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'chrome-a11y-'));
  app.setPath('userData', path.join(tmp, 'profile'));
  app.on('will-quit', () => fs.rmSync(tmp, { recursive: true, force: true }));
  app.whenReady().then(async () => {
    const cfg = await config();
    measure(cfg.theme.extend.colors);
    // Consume current production class strings so styling changes reach the fixture.
    const errorButtons = [...read('src/components/ErrorBoundary.tsx').matchAll(/<button\b[\s\S]*?className="([^"]+)"/g)].map((m) => m[1]);
    const closeButton = read('src/components/PluginInstallModal.tsx').match(/title="Close"[\s\S]*?className="([^"]+)"/)[1];
    assert.equal(errorButtons.length, 3);
    const controls = [
      ['bare', 'right-pane-icon-btn', 'Chrome action'],
      ['suppressed', 'focus:outline-none', 'Retry'],
      ['ring', 'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent/70', 'Component ring'],
      ['outline', 'focus:outline-none focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent', 'Component outline'],
      ...errorButtons.map((c, i) => [`error-${i}`, c, 'Try again / reload']),
      ['ring-color-only', 'focus:ring-accent', 'Ring color only'],
    ];
    const html = `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="fixture.css"></head>
      <body><main class="bg-panel p-4 flex gap-4">${controls.map(([id, c, label]) => `<button id="${id}" class="${c}">${label}</button>`).join('')}</main>
      <dialog class="bg-panel text-txt"><button id="close" class="${closeButton}">Close</button><input id="field" class="focus:outline-none" aria-label="Source"></dialog></body></html>`;
    const css = await require('postcss')([require('tailwindcss')({ ...cfg, content: [{ raw: html, extension: 'html' }] })]).process(read('src/index.css'), { from: path.join(root, 'src/index.css') });
    fs.writeFileSync(path.join(tmp, 'fixture.css'), css.css);
    fs.writeFileSync(path.join(tmp, 'fixture.html'), html);
    const win = new BrowserWindow({ width: 1100, height: 500, webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false } });
    win.webContents.session.webRequest.onBeforeRequest((details, cb) => cb({ cancel: !details.url.startsWith('file:') }));
    await win.loadFile(path.join(tmp, 'fixture.html'));
    const evaluate = (script) => win.webContents.executeJavaScript(script);
    async function tab(expected, mode = 'fallback') {
      win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Tab' });
      win.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Tab' });
      await new Promise((resolve) => setTimeout(resolve, 50));
      const s = await evaluate(`(() => {const el=document.activeElement,c=getComputedStyle(el);return {id:el.id,visible:el.matches(':focus-visible'),style:c.outlineStyle,width:c.outlineWidth,color:c.outlineColor,shadow:c.boxShadow,offset:c.outlineOffset};})()`);
      assert.equal(s.id, expected);
      assert.equal(s.visible, true);
      if (mode === 'ring') {
        assert.notEqual(s.shadow, 'none');
        assert.equal(s.color, 'rgba(0, 0, 0, 0)', 'No extra outline around component ring');
      } else {
        assert.equal(s.style, 'solid');
        assert.equal(s.width, mode === 'outline' ? '1px' : '2px');
        assert.notEqual(s.color, 'rgba(0, 0, 0, 0)');
        if (mode === 'fallback') assert.equal(s.offset, '-2px');
        if (expected === 'error-0' || expected === 'error-1') {
          assert.equal(s.color, 'rgb(15, 17, 19)', 'Accent-filled retry needs a contrasting inset outline');
        }
      }
      console.log('PASS', expected, JSON.stringify(s));
    }
    for (const [id] of controls) await tab(id, id === 'ring' ? 'ring' : id === 'outline' ? 'outline' : 'fallback');
    await evaluate(`document.querySelector('dialog').showModal(); document.getElementById('field').focus()`);
    await tab('close');
    await tab('field');
    win.webContents.debugger.attach('1.3');
    await win.webContents.debugger.sendCommand('Emulation.setEmulatedMedia', { features: [{ name: 'forced-colors', value: 'active' }, { name: 'prefers-reduced-motion', value: 'reduce' }] });
    await tab('close');
    assert.equal(await evaluate(`matchMedia('(forced-colors: active)').matches && matchMedia('(prefers-reduced-motion: reduce)').matches`), true);
    await evaluate(`document.querySelector('dialog').close(); document.getElementById('suppressed').focus()`);
    await tab('ring'); // Shadow-only rings must acquire a system outline in forced colors.
    win.webContents.debugger.detach();
    win.destroy();
    app.quit();
  }).catch((e) => {
    console.error(e);
    fs.rmSync(tmp, { recursive: true, force: true });
    app.exit(1);
  });
}
