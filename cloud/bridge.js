(() => {
  'use strict';
  const LOCAL = 'http://127.0.0.1:8879';
  const button = document.getElementById('connect');
  const message = document.getElementById('message');
  let inProgress = false;

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

  button.addEventListener('click', async () => {
    if (inProgress) return;
    inProgress = true;
    button.disabled = true;
    if (button.dataset.paired === 'true') {
      try {
        tell('正在打开本机资料库…');
        await healthCheck();
        location.assign('/import');
      } catch {
        button.dataset.paired = 'false';
        button.innerHTML = '连接本机资料库 <span aria-hidden="true">↗</span>';
        tell('本机连接已失效，请再次点击并在本机确认。', true);
      } finally { button.disabled = false; inProgress = false; }
      return;
    }
    tell('正在等待本机确认…');
    // Open synchronously from the user's click, so browsers do not block the popup.
    const popup = window.open(`${LOCAL}/cloud-pair?origin=${encodeURIComponent(location.origin)}`, 'shiji-cloud-pair', 'popup,width=470,height=570');
    if (!popup) {
      tell('浏览器阻止了本机确认窗口，请允许此站点打开弹窗后重试', true);
      button.disabled = false;
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
      tell('已授权，正在打开资料库…');
      await configureWorker(token);
      location.assign('/import');
    } catch (error) {
      tell(`${error.message}。请确认本机服务已启动，并允许浏览器连接本机网络。`, true);
    } finally {
      button.disabled = false;
      inProgress = false;
    }
  });

  if (new URL(location.href).searchParams.get('reason') === 'offline') {
    tell('本机拾集未连接或授权已过期，请重新连接。', true);
  } else if ('serviceWorker' in navigator) {
    hasStoredPairing().then(paired => {
      if (!paired) return;
      button.dataset.paired = 'true';
      button.innerHTML = '打开我的资料库 <span aria-hidden="true">↗</span>';
    }).catch(() => {});
  }
})();
