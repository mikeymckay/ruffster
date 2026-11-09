import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { access, appendFile, mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import axe from 'axe-core';
import WebSocket from 'ws';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const site = path.join(root, 'docs');
const parentAssets = path.join(root, 'family_activity', 'parent_assets');
const pages = ['index.html', 'install.html', 'progress.html', 'faq.html'];
const viewports = [
  { name: 'desktop', width: 1440, height: 1000, mobile: false },
  { name: 'mobile', width: 390, height: 844, mobile: true },
];
const mimeTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
};

async function writeStepSummary(lines) {
  const summaryPath = process.env.GITHUB_STEP_SUMMARY;
  if (summaryPath) await appendFile(summaryPath, `${lines.join('\n')}\n`, 'utf8');
}

function annotateGitHubFailure(title, message) {
  if (process.env.GITHUB_ACTIONS !== 'true') return;
  const safeTitle = title.replace(/[\r\n:]/g, ' ');
  const safeMessage = String(message)
    .replace(/%/g, '%25')
    .replace(/\r/g, '%0D')
    .replace(/\n/g, '%0A');
  console.log(`::error title=${safeTitle}::${safeMessage}`);
}

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

function sampleReport() {
  const now = new Date().toISOString();
  const appRows = [['Safari', 3540], ['Pages', 1080]];
  const siteRows = [['example.edu', 1800], ['wikipedia.org', 900]];
  const trafficRows = [['en0', 125000000, 14000000]];
  const empty = [];
  const byContext = rows => ({ school: rows, home: rows, school_network: rows, other_network: empty, schedule_uncertain: false });
  const byPeriod = rows => ({ today: rows, week: rows });
  return {
    incomplete: false,
    devices: [{ device_id: 'sample1234', label: 'Sample computer', last_seen: now }],
    selected_device: 'sample1234',
    apps: byPeriod(appRows), sites: byPeriod(siteRows),
    website_observations: { count: 12, latest_at: now },
    site_categories: byPeriod([['Learning', 1800], ['Reference', 900]]),
    category_contexts: { school: appRows, home: appRows, school_network: appRows, other_network: empty },
    gaps: [[now, now]], sessions: [[now, now, null]],
    agent_runtime: { seconds: 21600, sessions: 3, gaps: 1, restarts: 1, days: 7 },
    traffic: [[now, 'en0', 125000000, 14000000]],
    traffic_usage: byPeriod(trafficRows), traffic_contexts: byContext(trafficRows),
    process_traffic: { status: 'enabled', status_at: now, today: [['Safari', 86000000, 8000000]], week: [['Safari', 86000000, 8000000]] },
    networks: [{ identifier: 'sample-router-identifier', last_seen: now, label: 'home' }],
    network_settings: { sampled_at: now, dns_observed: true, proxy_indicator: false, vpn_indicator: false },
    contexts: { apps: byContext(appRows), sites: byContext(siteRows), schedule_configured: true },
    recorded_through: now, generated_at: now, report_timezone: 'Europe/Vienna',
    conversation_prompts: ['What was useful about this activity?', 'Is there anything you would like help with?'],
  };
}

function createParentServer({ populated = false } = {}) {
  const assets = {
    '/': 'index.html',
    '/app.css': 'app.css',
    '/app.js': 'app.js',
    '/ruffster-mascot.webp': 'ruffster-mascot.webp',
  };
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
    if (pathname === '/api/status') {
      const body = Buffer.from(JSON.stringify({
        has_key: populated, unlocked: populated, has_report: populated, backup_confirmed: populated,
      }));
      response.writeHead(200, {
        'Content-Type': 'application/json; charset=utf-8',
        'Content-Length': body.length,
        'Cache-Control': 'no-store',
      });
      response.end(request.method === 'HEAD' ? undefined : body);
      return;
    }
    if (populated && pathname === '/api/settings') {
      response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
      response.end(JSON.stringify({ retention_days: 30 }));
      return;
    }
    if (populated && pathname === '/api/schedule') {
      response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
      response.end(JSON.stringify({ schedule: { timezone: 'Europe/Vienna', start: '08:30', end: '15:00', days: [1, 2, 3, 4, 5] } }));
      return;
    }
    if (populated && new URL(request.url || '/', 'http://localhost').pathname === '/api/report') {
      response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
      response.end(JSON.stringify(sampleReport()));
      return;
    }
    const relative = assets[pathname];
    if (!relative) {
      response.writeHead(404).end();
      return;
    }
    try {
      const body = await readFile(path.join(parentAssets, relative));
      response.writeHead(200, {
        'Content-Type': mimeTypes[path.extname(relative).toLowerCase()] || 'application/octet-stream',
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
    const { resolve, reject, timer } = pending.get(response.id);
    clearTimeout(timer);
    pending.delete(response.id);
    if (response.error) reject(new Error(response.error.message));
    else resolve(response.result);
  });
  const rejectPending = (error) => {
    for (const { reject, timer } of pending.values()) {
      clearTimeout(timer);
      reject(error);
    }
    pending.clear();
  };
  socket.on('close', () => rejectPending(new Error('Chrome closed the DevTools connection.')));
  socket.on('error', (error) => rejectPending(error));
  const opened = new Promise((resolve, reject) => {
    socket.once('open', resolve);
    socket.once('error', reject);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Chrome DevTools command timed out: ${method}`));
    }, 10000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }), (error) => {
      if (!error) return;
      clearTimeout(timer);
      pending.delete(id);
      reject(error);
    });
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

async function waitForPageReady(send, page, expectedPath = `/${page}`) {
  const deadline = Date.now() + 10000;
  await new Promise((resolve) => setTimeout(resolve, 150));
  while (Date.now() < deadline) {
    const state = await evaluate(send, '({ pathname: location.pathname, ready: document.readyState })');
    if (state.pathname === expectedPath && state.ready === 'complete') {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Page ${page} did not finish loading before the accessibility scan.`);
}

async function main() {
  const chrome = await findChrome();
  const chromeVersion = spawnSync(chrome, ['--version'], { encoding: 'utf8' }).stdout?.trim() || 'unknown';
  const profile = await mkdtemp(path.join(tmpdir(), 'family-pages-axe-'));
  const server = createStaticServer();
  const parentServer = createParentServer();
  const parentReportServer = createParentServer({ populated: true });
  let browser;
  let socket;
  try {
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', resolve);
    });
    await new Promise((resolve, reject) => {
      parentServer.once('error', reject);
      parentServer.listen(0, '127.0.0.1', resolve);
    });
    await new Promise((resolve, reject) => {
      parentReportServer.once('error', reject);
      parentReportServer.listen(0, '127.0.0.1', resolve);
    });
    const address = server.address();
    const parentAddress = parentServer.address();
    const reportAddress = parentReportServer.address();
    const browserArgs = [
      '--headless=new', '--disable-gpu', '--no-first-run', '--disable-background-networking',
      '--remote-debugging-port=0', '--remote-allow-origins=*', `--user-data-dir=${profile}`,
      'about:blank',
    ];
    if (process.platform === 'linux') browserArgs.unshift('--no-sandbox');
    browser = spawn(chrome, browserArgs, {
      detached: process.platform !== 'win32',
      stdio: 'ignore',
    });
    const target = await waitForDebugger(profile, browser);
    const debuggerConnection = connectDebugger(target.webSocketDebuggerUrl);
    socket = debuggerConnection.socket;
    await debuggerConnection.opened;
    const { send } = debuggerConnection;
    await send('Page.enable');
    await send('Runtime.enable');

    const failures = [];
    const targets = [
      ...pages.map((page) => ({ name: page, url: `http://127.0.0.1:${address.port}/${page}`, path: `/${page}` })),
      { name: 'parent dashboard setup', url: `http://127.0.0.1:${parentAddress.port}/`, path: '/' },
      { name: 'parent dashboard report', url: `http://127.0.0.1:${reportAddress.port}/`, path: '/' },
    ];
    for (const viewport of viewports) {
      await send('Emulation.setDeviceMetricsOverride', {
        width: viewport.width,
        height: viewport.height,
        deviceScaleFactor: 1,
        mobile: viewport.mobile,
      });
      for (const target of targets) {
        await send('Page.navigate', { url: target.url });
        await waitForPageReady(send, target.name, target.path);
        if (target.name === 'parent dashboard setup') {
          const deadline = Date.now() + 5000;
          let ready = false;
          while (Date.now() < deadline) {
            ready = await evaluate(send,
              'document.querySelector("#setup-progress li[aria-current=step]") !== null');
            if (ready) break;
            await new Promise((resolve) => setTimeout(resolve, 50));
          }
          if (!ready) throw new Error('The parent setup screen did not reach its initial state.');
        }
        if (target.name === 'parent dashboard report') {
          const deadline = Date.now() + 5000;
          let ready = false;
          while (Date.now() < deadline) {
            ready = await evaluate(send,
              'document.querySelector("#report").hidden === false && document.querySelector("#apps li")?.textContent.includes("Safari")');
            if (ready) break;
            await new Promise((resolve) => setTimeout(resolve, 50));
          }
          if (!ready) throw new Error('The populated parent report did not render its sample data.');
        }
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
        console.log(`${target.name} @ ${viewport.name}: ${result.violations.length} Axe violations${overflow ? ', horizontal overflow' : ''}`);
        if (result.violations.length || overflow) {
          failures.push({ page: target.name, viewport: viewport.name, ...result, overflow });
        }
      }
    }
    if (failures.length) {
      console.error(JSON.stringify(failures, null, 2));
      const findings = failures.map((failure) => {
        const rules = failure.violations.map((violation) => `${violation.id} (${violation.impact})`).join(', ');
        return `${failure.page} at ${failure.viewport}: ${rules || 'no Axe violations'}${failure.overflow ? `; width ${failure.documentWidth}px exceeds ${failure.viewportWidth}px` : ''}`;
      }).join('; ');
      annotateGitHubFailure('Pages accessibility findings', findings);
      process.exitCode = 1;
    }
    const summary = [
      '## Ruffster website and parent dashboard accessibility scan',
      `Runtime: Node ${process.version}; ${chromeVersion}`,
      '',
      '| Page | Viewport | Axe violations | Horizontal overflow |',
      '| --- | --- | ---: | --- |',
      ...targets.flatMap((target) => viewports.map((viewport) => {
        const failure = failures.find((entry) => entry.page === target.name && entry.viewport === viewport.name);
        const count = failure?.violations.length ?? 0;
        return `| ${target.name} | ${viewport.name} | ${count} | ${failure?.overflow ? 'Yes' : 'No'} |`;
      })),
    ];
    if (failures.length) {
      summary.push('', '### Findings');
      for (const failure of failures) {
        for (const violation of failure.violations) {
          const targets = violation.nodes.map((node) => node.target.join(' ')).join(', ');
          summary.push(`- **${failure.page} / ${failure.viewport}**: \`${violation.id}\` (${violation.impact}) — ${violation.help}; targets: ${targets}`);
        }
        if (failure.overflow) {
          summary.push(`- **${failure.page} / ${failure.viewport}**: document width ${failure.documentWidth}px exceeds viewport ${failure.viewportWidth}px.`);
        }
      }
    }
    await writeStepSummary(summary);
  } finally {
    socket?.close();
    if (browser && browser.exitCode === null) {
      const signalBrowser = (signal) => {
        if (process.platform !== 'win32' && browser.pid) {
          try {
            process.kill(-browser.pid, signal);
            return;
          } catch (error) {
            if (error.code !== 'ESRCH') throw error;
          }
        }
        browser.kill(signal);
      };
      signalBrowser('SIGTERM');
      await Promise.race([
        new Promise((resolve) => browser.once('exit', resolve)),
        new Promise((resolve) => setTimeout(resolve, 3000)),
      ]);
      if (browser.exitCode === null) {
        signalBrowser('SIGKILL');
        await Promise.race([
          new Promise((resolve) => browser.once('exit', resolve)),
          new Promise((resolve) => setTimeout(resolve, 3000)),
        ]);
      }
    }
    await new Promise((resolve) => server.close(resolve));
    await new Promise((resolve) => parentServer.close(resolve));
    await new Promise((resolve) => parentReportServer.close(resolve));
    await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
}

main().catch(async (error) => {
  console.error(error);
  annotateGitHubFailure('Ruffster accessibility scan could not finish', error?.stack || error);
  try {
    await writeStepSummary([
      '## Ruffster accessibility scan failed before completion',
      `Runtime: Node ${process.version}`,
      '',
      `Error: ${error?.stack || error}`,
    ]);
  } catch (summaryError) {
    console.error('Could not write the GitHub Actions step summary:', summaryError);
  }
  process.exitCode = 1;
});
