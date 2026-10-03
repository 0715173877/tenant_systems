// Headless-Chrome PWA diagnostic via the DevTools Protocol (no npm deps).
// Usage: node /tmp/pwa_check.mjs [url]
const { spawn } = require("node:child_process");
const fs = require("node:fs");

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9333;
const TARGET_URL = process.argv[2] || "http://127.0.0.1:8000/accounts/login/";
const PROFILE = "/tmp/chrome-pwa-profile-" + Date.now();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const chrome = spawn(
    CHROME,
    [
      "--headless=new",
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${PROFILE}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-gpu",
      "about:blank",
    ],
    { stdio: "ignore" }
  );

  let version;
  for (let i = 0; i < 60; i++) {
    try {
      version = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
      break;
    } catch {
      await sleep(250);
    }
  }
  if (!version) {
    console.log("ERROR: Chrome did not expose a debugging port");
    chrome.kill();
    process.exit(1);
  }
  console.log("Chrome:", version.Browser);

  // Open a new tab target.
  const tab = await (
    await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent("about:blank")}`, {
      method: "PUT",
    })
  ).json();

  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = rej;
  });

  let id = 0;
  const pending = new Map();
  const consoleMsgs = [];
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    } else if (msg.method === "Runtime.consoleAPICalled") {
      consoleMsgs.push(
        `[console.${msg.params.type}] ` +
          msg.params.args.map((a) => a.value ?? a.description ?? a.type).join(" ")
      );
    } else if (msg.method === "Log.entryAdded") {
      consoleMsgs.push(`[log.${msg.params.entry.level}] ${msg.params.entry.text}`);
    } else if (msg.method === "Runtime.exceptionThrown") {
      consoleMsgs.push(
        `[exception] ${msg.params.exceptionDetails.text} ${
          msg.params.exceptionDetails.exception?.description || ""
        }`
      );
    }
  };
  const send = (method, params = {}) =>
    new Promise((res) => {
      const mid = ++id;
      pending.set(mid, res);
      ws.send(JSON.stringify({ id: mid, method, params }));
    });

  await send("Runtime.enable");
  await send("Log.enable");
  await send("Page.enable");
  await send("Page.navigate", { url: TARGET_URL });

  await sleep(6000); // let load + SW registration happen

  const expr = `(async () => {
    const out = {};
    out.url = location.href;
    out.isSecureContext = window.isSecureContext;
    out.hasServiceWorkerAPI = 'serviceWorker' in navigator;
    try {
      const regs = await navigator.serviceWorker.getRegistrations();
      out.registrations = regs.map(r => ({ scope: r.scope, active: !!(r.active), installing: !!(r.installing), waiting: !!(r.waiting), activeScript: r.active ? r.active.scriptURL : null }));
    } catch (e) { out.registrationsErr = String(e); }
    out.controller = navigator.serviceWorker.controller ? navigator.serviceWorker.controller.scriptURL : null;
    const link = document.querySelector('link[rel="manifest"]');
    out.manifestHref = link ? link.href : null;
    out.pwaScriptTag = !!document.querySelector('script[src*="pwa.js"]');
    out.installButtons = Array.from(document.querySelectorAll('.pwa-install-btn')).map(function (b) {
      return { text: b.textContent.trim(), hasDnoneClass: b.classList.contains('d-none'), display: getComputedStyle(b).display };
    });
    out.standalone = (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true);
    if (link) {
      try {
        const r = await fetch(link.href);
        out.manifestStatus = r.status;
        out.manifestContentType = r.headers.get('content-type');
        const m = await r.json();
        out.manifestName = m.name; out.manifestShortName = m.short_name;
        out.manifestStartUrl = m.start_url; out.manifestDisplay = m.display;
        out.manifestIconSizes = (m.icons || []).map(i => i.sizes);
      } catch (e) { out.manifestErr = String(e); }
    }
    return JSON.stringify(out);
  })()`;

  const res = await send("Runtime.evaluate", {
    expression: expr,
    awaitPromise: true,
    returnByValue: true,
  });

  console.log("\n=== RESULT ===");
  console.log(res.result?.result?.value || JSON.stringify(res));
  console.log("\n=== CONSOLE / LOG ===");
  console.log(consoleMsgs.length ? consoleMsgs.join("\n") : "(none)");

  ws.close();
  chrome.kill();
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {}
  process.exit(0);
})();
