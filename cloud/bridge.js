(() => {
  'use strict';
  const LOCAL = 'http://127.0.0.1:8879';
  const actions = {
    xhs: document.getElementById('choose-xhs'),
    chrome: document.getElementById('choose-chrome'),
    library: document.getElementById('open-library'),
  };
  const message = document.getElementById('message');
  let inProgress = false;
  let paired = false;

  const tell = (text, error = false) => {
    message.textContent = text;
    message.classList.toggle('error', error);
  };

  async function healthCheck() {
    const response = await fetch(`${LOCAL}/api/cloud-health`, {
      mode: 'cors', cache: 'no-store', credentials: 'omit', targetAddressSpace: 'loopback',
    });
    if (!response.ok || !(await response.json()).ready) throw new Error('本机拾集未就绪');
  }

  function waitForPair(popup) {
    return new Promise((resolve, reject) => {
      let ended = false;
      const close = () => {
        if (ended) return;
        ended = true;
        window.removeEventListener('message', onMessage);
        clearInterval(closedCheck);
        clearTimeout(timeout);
      };
      const onMessage = event => {
        if (event.source !== popup || event.origin !== LOCAL || event.data?.type !== 'shiji-cloud-paired') return;
        if (!/^[A-Za-z0-9_-]{40,100}$/.test(event.data.token || '')) return;
        close();
        resolve(event.data.token);
      };
      window.addEventListener('message', onMessage);
      const closedCheck = setInterval(() => {
        if (popup.closed) { close(); reject(new Error('连接窗口已关闭，请重新连接')); }
      }, 600);
      const timeout = setTimeout(() => { close(); reject(new Error('连接等待超时，请重新连接')); }, 10 * 60 * 1000);
    });
  }

  async function configureWorker(token) {
    if (!('serviceWorker' in navigator)) throw new Error('当前浏览器不支持本机连接，请使用最新版 Chrome');
    const registration = await navigator.serviceWorker.register('/sw.js', {scope: '/'});
    await navigator.serviceWorker.ready;
    const worker = registration.active;
    if (!worker) throw new Error('连接组件没有启动，请刷新后重试');
    const channel = new MessageChannel();
    const acknowledged = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('连接组件没有响应')), 10000);
      channel.port1.onmessage = event => {
        clearTimeout(timeout);
        if (event.data?.ok) resolve();
        else reject(new Error('连接组件未能保存本机授权'));
      };
    });
    worker.postMessage({type: 'shiji-pair', token}, [channel.port2]);
    await acknowledged;
  }

  async function hasStoredPairing() {
    const registration = await navigator.serviceWorker?.getRegistration('/');
    if (!registration?.active) return false;
    const channel = new MessageChannel();
    const answer = new Promise(resolve => {
      const timeout = setTimeout(() => resolve(false), 3000);
      channel.port1.onmessage = event => { clearTimeout(timeout); resolve(Boolean(event.data?.paired)); };
    });
    registration.active.postMessage({type: 'shiji-status'}, [channel.port2]);
    return answer;
  }

  async function authorizedStatus() {
    const response = await fetch('/api/status', {cache: 'no-store'});
    if (!response.ok || !response.headers.get('Content-Type')?.includes('application/json')) {
      throw new Error('本机授权已失效');
    }
    return response.json();
  }

  function destination(action, status) {
    if (action === 'xhs') return '/import?platform=xhs';
    if (action === 'chrome') return '/bookmarks.html';
    if (status.libraries?.liked?.visible) return '/index.html';
    if (status.libraries?.saved?.visible) return '/saved.html';
    if (status.following_count) return '/following.html';
    if (status.bookmarks_count) return '/bookmarks.html';
    if (status.products_count) return '/products.html';
    return '';
  }

  async function openAction(action) {
    const status = await authorizedStatus();
    const path = destination(action, status);
    if (!path) {
      tell('本机还没有已导入的资料。请先选择小红书或 Chrome 开始导入。');
      return;
    }
    location.assign(path);
  }

  async function handleAction(action) {
    if (inProgress) return;
    inProgress = true;
    for (const button of Object.values(actions)) button.disabled = true;
    if (paired) {
      try {
        tell('正在读取本机连接…');
        await healthCheck();
        await openAction(action);
      } catch (error) {
        paired = false;
        tell(`${error.message}。请再次点击并在本机确认。`, true);
      } finally {
        for (const button of Object.values(actions)) button.disabled = false;
        inProgress = false;
      }
      return;
    }
    tell('正在等待本机确认…');
    // Open synchronously from the user's click, so browsers do not block the popup.
    const popup = window.open(`${LOCAL}/cloud-pair?origin=${encodeURIComponent(location.origin)}`, 'shiji-cloud-pair', 'popup,width=470,height=570');
    if (!popup) {
      tell('浏览器阻止了本机确认窗口，请允许此站点打开弹窗后重试', true);
      for (const button of Object.values(actions)) button.disabled = false;
      inProgress = false;
      return;
    }
    try {
      const pairing = waitForPair(popup);
      // Health can fail before the user closes the popup. Keep the later
      // rejection handled while still surfacing it when we await pairing.
      pairing.catch(() => {});
      await healthCheck();
      const token = await pairing;
      tell('已授权，正在打开所选内容…');
      await configureWorker(token);
      paired = true;
      await openAction(action);
    } catch (error) {
      if (!popup.closed) popup.close();
      tell(`${error.message}。请确认本机服务已启动，并允许浏览器连接本机网络。`, true);
    } finally {
      for (const button of Object.values(actions)) button.disabled = false;
      inProgress = false;
    }
  }

  actions.xhs.addEventListener('click', () => handleAction('xhs'));
  actions.chrome.addEventListener('click', () => handleAction('chrome'));
  actions.library.addEventListener('click', () => handleAction('library'));

  if (new URL(location.href).searchParams.get('reason') === 'offline') {
    tell('本机拾集未连接或授权已过期，请重新连接。', true);
  } else if ('serviceWorker' in navigator) {
    hasStoredPairing().then(value => { paired = value; }).catch(() => {});
  }
})();
