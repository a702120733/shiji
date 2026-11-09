(() => {
  'use strict';
  const LOCAL = 'http://127.0.0.1:8879';
  const actions = {
    xhs: document.getElementById('choose-xhs'),
    chrome: document.getElementById('choose-chrome'),
    library: document.getElementById('open-library'),
  };
  const message = document.getElementById('message');
  const libraryDialog = document.getElementById('library-dialog');
  const libraryMessage = document.getElementById('library-status');
  const libraryProgress = document.getElementById('library-progress');
  const libraryResult = document.getElementById('library-result');
  const libraryPreview = document.getElementById('library-preview');
  const librarySource = document.getElementById('library-source');
  const libraryButtons = [document.getElementById('choose-folder'), document.getElementById('choose-package'),
    document.getElementById('confirm-library'), document.getElementById('open-configured')];
  let inProgress = false;
  let paired = false;
  let activePopup = null;
  let selection = '';
  let libraryTimer = null;

  const tell = (text, error = false) => {
    message.textContent = text;
    message.classList.toggle('error', error);
  };

  const report = (action, text, error = false) => {
    if (action !== 'library') return tell(text, error);
    libraryMessage.textContent = text;
    libraryMessage.classList.toggle('error', error);
    document.getElementById('retry-library').hidden = !error;
    if (error) libraryProgress.hidden = true;
  };

  const stages = ['connect', 'choose', 'inspect', 'open'];
  function setStage(stage, text, error = false) {
    report('library', text, error);
    const index = stages.indexOf(stage);
    libraryDialog.querySelectorAll('.library-steps li').forEach((item, position) => {
      item.classList.toggle('complete', position < index || stage === 'ready');
      item.classList.toggle('current', position === index && stage !== 'ready');
    });
  }

  function busyLibrary(value) {
    for (const button of libraryButtons) button.disabled = value;
  }

  function progress(processed, total) {
    libraryProgress.hidden = false;
    if (Number.isFinite(processed) && Number.isFinite(total) && total > 0) {
      libraryProgress.value = Math.min(100, Math.round(processed / total * 100));
    } else libraryProgress.removeAttribute('value');
  }

  async function localRequest(path, payload) {
    const response = await fetch(path, payload === undefined ? {cache: 'no-store'} : {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload), cache: 'no-store',
    });
    if (!response.headers.get('Content-Type')?.includes('application/json')) {
      throw new Error('本机服务版本较旧，请更新拾集本机服务后重试');
    }
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || `本机读取失败（${response.status}）`);
    return value;
  }

  function describe(value) {
    const names = (value.pages || []).map(page => page.label).filter(Boolean);
    const count = Number.isFinite(value.items) ? ` · ${value.items} 条内容` : '';
    return names.length ? `${names.join('、')}${count}` : `未找到可读取的资料页面${count}`;
  }

  function safeLocalUrl(value) {
    try {
      const url = new URL(value);
      if (url.protocol === 'http:' && url.hostname === '127.0.0.1' && /^\d+$/.test(url.port)) return url.href;
    } catch { /* Invalid local viewer address. */ }
    throw new Error('本机服务没有返回有效的资料页面');
  }

  function readyLibrary(value) {
    libraryProgress.hidden = true;
    libraryResult.href = safeLocalUrl(value.url);
    libraryResult.hidden = false;
    libraryPreview.hidden = true;
    setStage('ready', '资料已在本机就绪。点击下方按钮打开。');
    busyLibrary(false);
  }

  async function pollLibraryJob() {
    clearTimeout(libraryTimer);
    if (!libraryDialog.open) return;
    try {
      const value = await localRequest('/api/local-library/status');
      const job = value.job || {};
      if (job.state === 'ready') return readyLibrary(job);
      if (job.state === 'failed') throw new Error(job.error || '资料包读取失败');
      if (job.state === 'extracting') {
        setStage('open', job.phase || '正在本机解压资料包…');
        progress(job.processed, job.total);
        libraryTimer = setTimeout(pollLibraryJob, 700);
      }
    } catch (error) {
      libraryProgress.hidden = true;
      busyLibrary(false);
      setStage('open', error.message, true);
    }
  }

  async function showLibraryStatus() {
    const value = await localRequest('/api/local-library/status');
    const configured = value.configured || {};
    librarySource.hidden = false;
    document.getElementById('library-current-path').textContent = value.data_root || '未设置';
    document.getElementById('library-current-summary').textContent =
      `${value.demo_mode ? '隔离测试环境 · ' : ''}${describe(configured)}`;
    document.getElementById('open-configured').hidden = !(configured.pages || []).length;
    if (value.job?.state === 'extracting') {
      busyLibrary(true);
      setStage('open', value.job.phase || '正在本机解压资料包…');
      progress(value.job.processed, value.job.total);
      libraryTimer = setTimeout(pollLibraryJob, 700);
    } else if (value.job?.state === 'ready') readyLibrary(value.job);
    else if (value.job?.state === 'failed') {
      libraryProgress.hidden = true;
      busyLibrary(false);
      setStage('open', value.job.error || '上次读取失败，请重新选择资料。', true);
    }
    else {
      libraryProgress.hidden = true;
      busyLibrary(false);
      setStage('choose', '本机已连接。请选择已有资料文件夹或 ZIP 文件包。');
    }
  }

  async function chooseLibrary(kind) {
    if (!paired) return setStage('connect', '请先完成本机连接。', true);
    busyLibrary(true);
    libraryResult.hidden = true;
    libraryPreview.hidden = true;
    setStage('choose', `正在等待本机系统选择${kind === 'folder' ? '文件夹' : 'ZIP 文件包'}…`);
    progress();
    try {
      const value = await localRequest('/api/local-library/choose', {kind});
      selection = value.selection;
      document.getElementById('library-selected-path').textContent = value.path;
      document.getElementById('library-selected-summary').textContent = describe(value);
      libraryPreview.hidden = false;
      libraryProgress.hidden = true;
      setStage('inspect', kind === 'package'
        ? '已检查资料包。确认后会在本机解压并只读打开。'
        : '已检查资料内容。确认后将在本机只读打开。');
    } catch (error) {
      libraryProgress.hidden = true;
      setStage('choose', error.message, true);
    } finally { busyLibrary(false); }
  }

  async function openLibrary(payload) {
    busyLibrary(true);
    libraryResult.hidden = true;
    setStage('open', '正在准备本机资料…');
    progress();
    try {
      const value = await localRequest('/api/local-library/open', payload);
      if (value.state === 'ready') readyLibrary(value);
      else if (value.state === 'extracting') {
        setStage('open', '正在本机解压资料包…');
        libraryTimer = setTimeout(pollLibraryJob, 500);
      } else throw new Error('本机服务返回了未知的读取状态');
    } catch (error) {
      libraryProgress.hidden = true;
      busyLibrary(false);
      setStage('open', error.message, true);
    }
  }

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
    if (action === 'library') return showLibraryStatus();
    location.assign(destination(action, status));
  }

  async function handleAction(action) {
    if (inProgress) return;
    inProgress = true;
    for (const button of Object.values(actions)) button.disabled = true;
    if (paired) {
      try {
        report(action, '正在检查本机连接…');
        await healthCheck();
        await openAction(action);
      } catch (error) {
        paired = false;
        report(action, `${error.message}。请再次点击并在本机确认。`, true);
      } finally {
        for (const button of Object.values(actions)) button.disabled = false;
        inProgress = false;
      }
      return;
    }
    report(action, '正在等待本机确认…');
    // Open synchronously from the user's click, so browsers do not block the popup.
    const popup = window.open(`${LOCAL}/cloud-pair?origin=${encodeURIComponent(location.origin)}`, 'shiji-cloud-pair', 'popup,width=470,height=570');
    if (!popup) {
      report(action, '浏览器阻止了本机确认窗口，请允许此站点打开弹窗后重试', true);
      for (const button of Object.values(actions)) button.disabled = false;
      inProgress = false;
      return;
    }
    activePopup = popup;
    try {
      const pairing = waitForPair(popup);
      // Health can fail before the user closes the popup. Keep the later
      // rejection handled while still surfacing it when we await pairing.
      pairing.catch(() => {});
      await healthCheck();
      const token = await pairing;
      report(action, '已授权，正在读取本机资料…');
      await configureWorker(token);
      paired = true;
      await openAction(action);
    } catch (error) {
      if (!popup.closed) popup.close();
      report(action, `${error.message}。请确认本机服务已启动，并允许浏览器连接本机网络。`, true);
    } finally {
      activePopup = null;
      for (const button of Object.values(actions)) button.disabled = false;
      inProgress = false;
    }
  }

  actions.xhs.addEventListener('click', () => handleAction('xhs'));
  actions.chrome.addEventListener('click', () => handleAction('chrome'));
  actions.library.addEventListener('click', () => {
    libraryDialog.showModal();
    librarySource.hidden = true;
    libraryPreview.hidden = true;
    libraryResult.hidden = true;
    libraryProgress.hidden = true;
    busyLibrary(true);
    setStage('connect', '正在检查本机连接…');
    progress();
    handleAction('library');
  });
  document.getElementById('close-library').addEventListener('click', () => libraryDialog.close());
  document.getElementById('retry-library').addEventListener('click', () => handleAction('library'));
  libraryDialog.addEventListener('close', () => {
    clearTimeout(libraryTimer);
    if (activePopup && !activePopup.closed) activePopup.close();
  });
  document.getElementById('choose-folder').addEventListener('click', () => chooseLibrary('folder'));
  document.getElementById('choose-package').addEventListener('click', () => chooseLibrary('package'));
  document.getElementById('confirm-library').addEventListener('click', () => {
    if (selection) openLibrary({selection});
  });
  document.getElementById('open-configured').addEventListener('click', () => openLibrary({source: 'configured'}));

  if (new URL(location.href).searchParams.get('reason') === 'offline') {
    tell('本机拾集未连接或授权已过期，请重新连接。', true);
  } else if ('serviceWorker' in navigator) {
    hasStoredPairing().then(value => { paired = value; }).catch(() => {});
  }
})();
