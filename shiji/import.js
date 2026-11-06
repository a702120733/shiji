(() => {
  const $ = id => document.getElementById(id);
  const names = {liked: '点赞笔记', saved: '收藏笔记', following: '关注账号'};
  const stages = ['settings', 'connect', 'progress', 'done'];
  let status = null;
  let current = 'settings';
  let timer = null;

  async function request(path, payload) {
    const response = await fetch(path, {
      method: payload === undefined ? 'GET' : 'POST',
      headers: payload === undefined ? {} : {'Content-Type': 'application/json'},
      body: payload === undefined ? undefined : JSON.stringify(payload),
      cache: 'no-store',
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || `请求失败 (${response.status})`);
    return value;
  }

  function notice(message) {
    $('notice').hidden = !message;
    $('notice').textContent = message || '';
  }

  function selectedSources() {
    return [...document.querySelectorAll('input[name="source"]:checked')].map(input => input.value);
  }

  function selectionChanged() {
    const chosen = selectedSources();
    $('selection-note').textContent = `已选择 ${chosen.length} 项内容 · 下一步将在小红书网页完成登录`;
    $('permission-list').replaceChildren(...chosen.map(source => {
      const row = document.createElement('div');
      row.className = 'permission';
      row.textContent = names[source];
      const check = document.createElement('span');
      check.textContent = '✓';
      row.append(check);
      return row;
    }));
  }

  function show(stage) {
    current = stage;
    for (const name of stages) {
      $(name + '-stage').hidden = name !== stage;
      const step = document.querySelector(`[data-step="${name}"]`);
      step.classList.toggle('active', name === stage);
      step.classList.toggle('complete', stages.indexOf(name) < stages.indexOf(stage));
    }
    const heading = {
      settings: ['YOUR PERSONAL INSPIRATION ARCHIVE', '让喜欢过的内容，成为你的资料库。', '选择要导入的内容，再连接你已登录的小红书。'],
      connect: ['CONNECT YOUR INSPIRATION', '连接你的小红书', '在小红书官方网页完成登录，无需向拾集提供账号密码。'],
      progress: ['COLLECTING THE THINGS YOU LOVE', '你的灵感，正在归位', '正在读取可访问内容并保存到这台设备。'],
      done: ['YOUR PERSONAL INSPIRATION ARCHIVE', '整理完成，随时回来。', '资料保留在本机，可继续增量导入。'],
    }[stage];
    $('eyebrow').textContent = heading[0];
    $('page-title').textContent = heading[1];
    $('page-description').textContent = heading[2];
    if (stage === 'progress') startPolling();
    else if (timer) { clearInterval(timer); timer = null; }
  }

  function syncSettings(config) {
    document.querySelectorAll('input[name="source"]').forEach(input => {
      input.checked = config.sources.includes(input.value);
    });
    $('limit').value = config.limit;
    $('auto-analyze').checked = config.auto_analyze !== false;
    $('profile-label').textContent = config.profile_id ? `已验证账号 ${config.profile_id.slice(0, 8)}…` : '等待连接小红书';
    selectionChanged();
  }

  function updateNavigation(value) {
    const amounts = {
      liked: value.libraries?.liked?.visible || 0,
      saved: value.libraries?.saved?.visible || 0,
      following: value.following_count || 0,
      bookmarks: value.bookmarks_count || 0,
      products: value.products_count || 0,
    };
    amounts.notes = amounts.liked + amounts.saved;
    document.querySelector('[data-library-link="notes"]').href = amounts.liked ? '/index.html' : '/saved.html';
    document.querySelectorAll('[data-library-link]').forEach(link => {
      link.hidden = !amounts[link.dataset.libraryLink];
    });
    document.querySelector('[data-nav-gap]').hidden = ![amounts.notes, amounts.following].some(Boolean);
    document.querySelector('[data-chrome-gap]').hidden = !(amounts.bookmarks || amounts.products);
    document.querySelectorAll('[data-result-source]').forEach(link => {
      link.hidden = !amounts[link.dataset.resultSource];
    });
    $('liked-count').textContent = amounts.liked || '';
    $('saved-count').textContent = amounts.saved || '';
    $('following-count').textContent = amounts.following || '';
    const categories = [];
    for (const source of ['liked', 'saved']) {
      for (const [name, amount] of Object.entries(value.libraries?.[source]?.categories || {})) {
        if (name !== '待分析' && amount > 0) categories.push({source, name, amount});
      }
    }
    categories.sort((a, b) => b.amount - a.amount || a.name.localeCompare(b.name));
    const list = $('category-links');
    list.replaceChildren(...categories.slice(0, 15).map(item => {
      const link = document.createElement('a');
      link.href = `/${item.source}/index.html?category=${encodeURIComponent(item.name)}`;
      const label = document.createElement('span');
      label.textContent = `${item.source === 'liked' ? '♡' : '▯'} ${item.name}`;
      const count = document.createElement('small');
      count.textContent = item.amount;
      link.append(label, count);
      return link;
    }));
    $('sidebar-categories').hidden = categories.length === 0;
  }

  function renderJob(job) {
    $('progress-phase').textContent = job.phase || '准备导入';
    $('job-state').textContent = {running:'进行中', complete:'已完成', partial:'部分待核实', failed:'已停止', cancelled:'已取消'}[job.state] || '等待';
    if (job.state === 'running') {
      $('cancel-import').hidden = false;
      $('retry-import').hidden = true;
      $('progress-bar').style.animation = '';
    }
    $('source-progress').replaceChildren(...status.config.sources.map(source => {
      const row = document.createElement('div');
      row.className = 'source-line';
      const count = job.counts?.[source + '_captured'] || 0;
      row.textContent = names[source];
      const detail = document.createElement('small');
      detail.textContent = source === 'following'
        ? (job.counts?.following_visible ? `已保存 ${job.counts.following_visible} 位` : '名单读取中')
        : `新处理 ${count} 条`;
      row.append(detail);
      return row;
    }));
    const pending = ['liked', 'saved'].reduce((sum, source) => sum + (job.counts?.[source + '_pending'] || 0), 0);
    const analyzed = ['liked', 'saved'].reduce((sum, source) => sum + (job.counts?.[source + '_analyzed'] || 0), 0);
    $('analysis-status').textContent = `本次自动归类 ${analyzed} 条；已呈现 ${['liked', 'saved'].reduce((sum, source) => sum + (job.counts?.[source + '_visible'] || 0), 0)} 条；${pending} 条待分析或补采。`;
    $('event-log').replaceChildren(...(job.events || []).slice(-16).reverse().map(event => {
      const li = document.createElement('li');
      const detail = event.detail;
      const message = typeof detail === 'string' ? detail : detail?.message || detail?.event || '';
      li.textContent = `${event.at?.slice(11, 19) || ''} ${event.source ? names[event.source] + ' · ' : ''}${event.stage}${message ? ' · ' + message : ''}`;
      return li;
    }));
    if (job.state === 'failed' || job.state === 'cancelled') {
      notice(job.error || '任务已停止，之前保存的内容仍在本机。');
      $('cancel-import').hidden = true;
      $('retry-import').hidden = false;
      $('progress-bar').style.animation = 'none';
    }
    if (job.state === 'complete' || job.state === 'partial') {
      const total = ['liked', 'saved'].reduce((sum, source) => sum + (job.counts?.[source + '_visible'] || 0), 0);
      const following = job.counts?.following_visible || 0;
      $('done-summary').textContent = `已生成 ${total} 条笔记、${following} 位关注账号的本机资料；${pending} 条笔记仍需阅读分析或补采。`;
      $('done-title').textContent = job.state === 'partial' ? '导入已保存，部分内容待核实' : '导入已保存到本机';
      show('done');
    }
  }

  async function poll() {
    try {
      status = await request('/api/status');
      updateNavigation(status);
      renderJob(status.job);
    } catch (error) { notice(error.message); }
  }
  function startPolling() { if (!timer) timer = setInterval(poll, 1500); poll(); }

  $('to-connect').addEventListener('click', async () => {
    notice('');
    try {
      const config = await request('/api/settings', {sources: selectedSources(), limit: Number($('limit').value), auto_analyze: $('auto-analyze').checked});
      status.config = config;
      selectionChanged();
      show('connect');
    } catch (error) { notice(error.message); }
  });
  $('back-settings').addEventListener('click', () => { notice(''); show('settings'); });
  $('check-connection').addEventListener('click', async () => {
    notice('');
    const button = $('check-connection');
    button.disabled = true;
    button.textContent = '正在验证登录会话…';
    try {
      const account = await request('/api/connect', {});
      $('profile-label').textContent = `已验证账号 ${account.profile_id.slice(0, 8)}…`;
      $('connect-badge').textContent = '连接已验证';
      await request('/api/import/start', {});
      show('progress');
    } catch (error) { notice(error.message); }
    finally { button.disabled = false; button.textContent = '我已登录，验证连接'; }
  });
  $('cancel-import').addEventListener('click', async () => {
    try { await request('/api/import/cancel', {}); await poll(); }
    catch (error) { notice(error.message); }
  });
  $('retry-import').addEventListener('click', () => { notice(''); show('settings'); });
  $('new-import').addEventListener('click', () => { notice(''); show('settings'); });
  document.querySelectorAll('input[name="source"]').forEach(input => input.addEventListener('change', selectionChanged));
  request('/api/status').then(value => {
    status = value;
    syncSettings(value.config);
    updateNavigation(value);
    $('import-type').textContent = value.libraries.liked.visible || value.libraries.saved.visible || value.following_count ? '增量导入' : '首次导入';
    if (value.job.state === 'running' || value.job.state === 'failed' || value.job.state === 'cancelled') show('progress');
    else if (value.job.state === 'complete' || value.job.state === 'partial') { show('done'); renderJob(value.job); }
    else show('settings');
  }).catch(error => notice(error.message));
})();
