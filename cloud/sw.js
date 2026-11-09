/* The cloud serves code only. Private responses are forwarded directly from loopback
   to the browser and are never written to CacheStorage or the hosting provider. */
'use strict';
const LOCAL = 'http://127.0.0.1:8879';
const DB = 'shiji-cloud-bridge';
const STORE = 'session';
const KEY = 'token';
const EXPIRES_IN = 12 * 60 * 60 * 1000;
let session = null;

function database() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function saveSession(value) {
  const db = await database();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put(value, KEY);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  } finally { db.close(); }
}

async function readSession() {
  if (session && session.expires > Date.now()) return session;
  const db = await database();
  try {
    const value = await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const request = tx.objectStore(STORE).get(KEY);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    session = value?.expires > Date.now() ? value : null;
    return session;
  } finally { db.close(); }
}

self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('message', event => {
  if (event.data?.type === 'shiji-status') {
    event.waitUntil(readSession().then(value => event.ports[0]?.postMessage({paired: Boolean(value)}))
      .catch(() => event.ports[0]?.postMessage({paired: false})));
    return;
  }
  if (event.data?.type !== 'shiji-pair' || !/^[A-Za-z0-9_-]{40,100}$/.test(event.data.token || '')) return;
  event.waitUntil((async () => {
    session = {token: event.data.token, expires: Date.now() + EXPIRES_IN};
    try { await saveSession(session); event.ports[0]?.postMessage({ok: true}); }
    catch { event.ports[0]?.postMessage({ok: false}); }
  })());
});

async function fromLocal(request) {
  let access;
  try { access = await readSession(); } catch { access = null; }
  if (!access) {
    return request.mode === 'navigate' ? Response.redirect('/', 302) : new Response('', {status: 401});
  }
  const path = new URL(request.url);
  const headers = new Headers();
  headers.set('X-Shiji-Token', access.token);
  for (const name of ['Content-Type', 'Range']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const options = {
    method: request.method,
    headers,
    mode: 'cors',
    credentials: 'omit',
    cache: 'no-store',
    redirect: 'follow',
    targetAddressSpace: 'loopback',
  };
  if (request.method !== 'GET' && request.method !== 'HEAD') options.body = await request.clone().arrayBuffer();
  try {
    const response = await fetch(LOCAL + path.pathname + path.search, options);
    if (response.status === 403 && request.mode === 'navigate') return Response.redirect('/?reason=offline', 302);
    // Synthesize a response for the hosted origin. Do not let the loopback
    // response URL become the navigation's effective URL or cache private data.
    return new Response(response.status === 204 || response.status === 304 ? null : response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  } catch {
    return request.mode === 'navigate'
      ? Response.redirect('/?reason=offline', 302)
      : new Response(JSON.stringify({error: '本机拾集未连接，请返回首页重新连接'}), {
        status: 503, headers: {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store'},
      });
  }
}

const PUBLIC_UI = new Map([
  ['/import', '/ui/import.html'],
  ['/import.html', '/ui/import.html'],
  ['/import.css', '/ui/import.css'],
  ['/import.js', '/ui/import.js'],
  ['/bookmarks.html', '/ui/bookmarks.html'],
  ['/products.html', '/ui/products.html'],
  ['/local.css', '/ui/local.css'],
  ['/local.js', '/ui/local.js'],
]);

async function fromPublicUI(request, file) {
  if (request.mode === 'navigate') {
    let access;
    try { access = await readSession(); } catch { access = null; }
    if (!access) return Response.redirect('/', 302);
  }
  const response = await fetch(file, {cache: 'no-store'});
  return new Response(response.body, {status: response.status, statusText: response.statusText, headers: response.headers});
}

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname === '/' || ['/sw.js', '/bridge.js', '/cloud.css', '/favicon.svg', '/platform-assets/xhs.png', '/platform-assets/douyin.png'].includes(url.pathname)) return;
  const publicFile = PUBLIC_UI.get(url.pathname);
  if (publicFile) { event.respondWith(fromPublicUI(event.request, publicFile)); return; }
  if (event.request.mode === 'navigate') {
    if (url.pathname === '/index.html') { event.respondWith(Response.redirect('/liked/index.html', 302)); return; }
    if (url.pathname === '/saved.html') { event.respondWith(Response.redirect('/saved/index.html', 302)); return; }
    if (/^\/open-(?:saved-)?note\/[0-9a-f]{24}$/i.test(url.pathname)) {
      event.respondWith(Response.redirect(LOCAL + url.pathname, 302));
      return;
    }
  }
  event.respondWith(fromLocal(event.request));
});
