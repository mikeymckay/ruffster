import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { access, mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import axe from 'axe-core';
import WebSocket from 'ws';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const site = path.join(root, 'docs');
const pages = ['index.html', 'install.html', 'faq.html'];
const viewports = [
  { name: 'desktop', width: 1440, height: 1000, mobile: false },
  { name: 'mobile', width: 390, height: 844, mobile: true },
];
const mimeTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
};

function chromeCandidates() {
  if (process.env.CHROME_BIN) return [process.env.CHROME_BIN];
  if (process.platform === 'darwin') return [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
  ];
  if (process.platform === 'win32') return [
    path.join(process.env.PROGRAMFILES || 'C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  ];
  return ['google-chrome', 'chromium', 'chromium-browser'];
}

async function findChrome() {
  for (const candidate of chromeCandidates()) {
    if (candidate.includes(path.sep)) {
      try {
        await access(candidate);
        return candidate;
      } catch {
        continue;
      }
    }
    const check = spawnSync(candidate, ['--version'], { stdio: 'ignore' });
    if (!check.error && check.status === 0) return candidate;
  }
  throw new Error('Chrome or Chromium was not found. Set CHROME_BIN to its executable path.');
}

function createStaticServer() {
  return createServer(async (request, response) => {
    if (!['GET', 'HEAD'].includes(request.method || '')) {
      response.writeHead(405).end();
      return;
    }
    let pathname;
    try {
      pathname = decodeURIComponent(new URL(request.url || '/', 'http://localhost').pathname);
    } catch {
      response.writeHead(400).end();
      return;
    }
    const relative = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
    const filename = path.resolve(site, relative);
    if (filename !== site && !filename.startsWith(site + path.sep)) {
      response.writeHead(403).end();
      return;
    }
    try {
      const body = await readFile(filename);
      response.writeHead(200, {
        'Content-Type': mimeTypes[path.extname(filename).toLowerCase()] || 'application/octet-stream',
        'Content-Length': body.length,
        'Cache-Control': 'no-store',
      });
      response.end(request.method === 'HEAD' ? undefined : body);
    } catch {
      response.writeHead(404).end();
    }
  });
}

async function waitForDebugger(profile, browser) {
  const marker = path.join(profile, 'DevToolsActivePort');
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (browser.exitCode !== null) throw new Error(`Chrome exited with status ${browser.exitCode}`);
    try {
      const [port] = (await readFile(marker, 'utf8')).trim().split(/\r?\n/);
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      if (response.ok) {
        const targets = await response.json();
        const page = targets.find((target) => target.type === 'page');
        if (page?.webSocketDebuggerUrl) return page;
      }
    } catch {
      // Chrome is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('Chrome did not expose its local DevTools endpoint.');
}

function connectDebugger(url) {
  const socket = new WebSocket(url, { origin: 'http://localhost' });
  const pending = new Map();
  let nextId = 0;
  socket.on('message', (message) => {
    const response = JSON.parse(message.toString());
    if (!response.id || !pending.has(response.id)) return;
    const { resolve, reject } = pending.get(response.id);
    pending.delete(response.id);
    if (response.error) reject(new Error(response.error.message));
    else resolve(response.result);
  });
  const opened = new Promise((resolve, reject) => {
    socket.once('open', resolve);
    socket.once('error', reject);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
  return { socket, opened, send };
}

async function evaluate(send, expression) {
  const response = await send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (response.exceptionDetails) {
    throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
  }
  return response.result?.value;
}

async function main() {
  const chrome = await findChrome();
  const profile = await mkdtemp(path.join(tmpdir(), 'family-pages-axe-'));
  const server = createStaticServer();
  let browser;
  let socket;
  try {
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', resolve);
    });
    const address = server.address();
    const browserArgs = [
      '--headless=new', '--disable-gpu', '--no-first-run', '--disable-background-networking',
      '--remote-debugging-port=0', '--remote-allow-origins=*', `--user-data-dir=${profile}`,
      'about:blank',
    ];
    if (process.platform === 'linux') browserArgs.unshift('--no-sandbox');
    browser = spawn(chrome, browserArgs, { stdio: 'ignore' });
    const target = await waitForDebugger(profile, browser);
    const debuggerConnection = connectDebugger(target.webSocketDebuggerUrl);
    socket = debuggerConnection.socket;
    await debuggerConnection.opened;
    const { send } = debuggerConnection;
    await send('Page.enable');
    await send('Runtime.enable');

    const failures = [];
    for (const viewport of viewports) {
      await send('Emulation.setDeviceMetricsOverride', {
        width: viewport.width,
        height: viewport.height,
        deviceScaleFactor: 1,
        mobile: viewport.mobile,
      });
      for (const page of pages) {
        await send('Page.navigate', { url: `http://127.0.0.1:${address.port}/${page}` });
        await new Promise((resolve) => setTimeout(resolve, 250));
        const axeSource = JSON.stringify(axe.source);
        const result = await evaluate(send, `(() => {
          const script = document.createElement('script');
          script.textContent = ${axeSource};
          document.head.appendChild(script);
          return axe.run(document, { runOnly: { type: 'tag', values: [
            'wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'
          ] } }).then((scan) => ({
            violations: scan.violations.map((rule) => ({
              id: rule.id,
              impact: rule.impact,
              help: rule.help,
              nodes: rule.nodes.map((node) => ({ target: node.target, summary: node.failureSummary }))
            })),
            viewportWidth: window.innerWidth,
            documentWidth: document.documentElement.scrollWidth
          }));
        })()`);
        const overflow = result.documentWidth > result.viewportWidth;
        console.log(`${page} @ ${viewport.name}: ${result.violations.length} Axe violations${overflow ? ', horizontal overflow' : ''}`);
        if (result.violations.length || overflow) {
          failures.push({ page, viewport: viewport.name, ...result, overflow });
        }
      }
    }
    if (failures.length) {
      console.error(JSON.stringify(failures, null, 2));
      process.exitCode = 1;
    }
  } finally {
    socket?.close();
    if (browser && browser.exitCode === null) {
      browser.kill('SIGTERM');
      await Promise.race([
        new Promise((resolve) => browser.once('exit', resolve)),
        new Promise((resolve) => setTimeout(resolve, 3000)),
      ]);
      if (browser.exitCode === null) browser.kill('SIGKILL');
    }
    await new Promise((resolve) => server.close(resolve));
    await rm(profile, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
