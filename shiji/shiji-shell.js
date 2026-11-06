(() => {
  'use strict';
  const main = document.querySelector('body > main, body > .shiji-shell > .shiji-workspace > main');
  const scope = document.body.dataset.library;
  if (!main || !['liked', 'following', 'bookmarks'].includes(scope)) return;

  const icon = name => `<img src="shiji-assets/${name}.svg" alt="" aria-hidden="true">`;
  let shell = document.querySelector('body > .shiji-shell');
  if (!shell) {
    shell = document.createElement('div');
    shell.className = 'shiji-shell';
    shell.innerHTML = `
    <aside class="shiji-sidebar" aria-label="资料库导航">
      <a class="shiji-brand" href="index.html" aria-label="拾集 · 本机资料库"><span class="shiji-mark">${icon('bookmark')}</span><strong>拾集</strong><small>SHIJI</small></a>
      <nav class="shiji-platforms" aria-label="内容平台">
        <a href="bookmarks.html" ${scope === 'bookmarks' ? 'aria-current="page"' : ''}><span class="shiji-platform-icon chrome" aria-hidden="true">C</span>Chrome</a>
        <a href="index.html" ${scope !== 'bookmarks' ? 'aria-current="page"' : ''}><span class="shiji-platform-icon xhs" aria-hidden="true">小</span>小红书</a>
      </nav>
      <nav class="shiji-nav" aria-label="平台功能">${scope === 'bookmarks'
        ? `<a href="bookmarks.html" aria-current="page">${icon('bookmark')}<span>收藏夹</span><small class="shiji-bookmarks-count"></small></a>`
        : `<a href="index.html" ${scope === 'liked' ? 'aria-current="page"' : ''}>${icon('heart')}<span>点赞</span><small class="shiji-liked-count"></small></a>
        <a href="following.html" ${scope === 'following' ? 'aria-current="page"' : ''}>${icon('users')}<span>关注</span><small class="shiji-following-count"></small></a>
        <a class="shiji-trash-link" href="index.html?view=trash">${icon('trash')}<span>回收站</span><small class="shiji-trash-count"></small></a>`}
      </nav>
      <div class="shiji-sidebar-divider"></div>
      <div class="shiji-sidebar-heading"><span>${scope === 'bookmarks' ? '分类' : '我的分组'}</span>${scope === 'liked' ? '<button class="shiji-folder-add" type="button" aria-label="新建文件夹" title="新建文件夹">＋</button>' : `<small>${scope === 'bookmarks' ? '按内容整理' : '可自定义'}</small>`}</div>
      <div class="shiji-side-groups" aria-label="${scope === 'liked' ? '分组文件夹' : '常用分组'}"></div>
      <button class="shiji-all-groups" type="button">${icon('plus')}<span>${scope === 'bookmarks' ? '查看全部分类' : '查看全部分组'}</span></button>
      <div class="shiji-sidebar-spacer"></div>
      <div class="shiji-sidebar-footer">本机资料库 · 仅在此设备保存</div>
    </aside>
    <div class="shiji-workspace">
      <div class="shiji-topbar"><div class="shiji-breadcrumb"><span>我的空间</span>${icon('chevron')}<strong>${{liked:'点赞资料库',following:'关注资料库',bookmarks:'收藏夹'}[scope]}</strong></div><div class="shiji-top-search">${icon('search')}</div></div>
    </div>`;
    document.body.insertBefore(shell, main);
  }
  const workspace = shell.querySelector('.shiji-workspace');
  const nav = shell.querySelector('.shiji-nav');
  if (scope !== 'bookmarks' && !nav.querySelector('.shiji-trash-link')) {
    const link = document.createElement('a');
    link.className = 'shiji-trash-link';
    link.href = 'index.html?view=trash';
    link.innerHTML = `${icon('trash')}<span>回收站</span><small class="shiji-trash-count"></small>`;
    nav.append(link);
  }
  if (scope === 'liked' && new URLSearchParams(location.search).get('view') === 'trash') {
    nav.querySelector('a[href="index.html"]')?.removeAttribute('aria-current');
    nav.querySelector('.shiji-trash-link').setAttribute('aria-current', 'page');
    shell.querySelector('.shiji-breadcrumb strong').textContent = '回收站';
  }
  if (main.parentElement !== workspace) workspace.append(main);
  const search = main.querySelector('#search');
  if (search) shell.querySelector('.shiji-top-search').append(search);
  const cards = main.querySelectorAll(scope === 'bookmarks' ? 'article[data-bookmark-id]' : 'article[data-item-id]');
  const currentCount = shell.querySelector('.shiji-' + scope + '-count');
  if (currentCount) currentCount.textContent = cards.length.toLocaleString('zh-CN');
  fetch('/api/status', {cache: 'no-store'}).then(response => response.ok ? response.json() : null).then(status => {
    if (!status) return;
    const likedCount = status.libraries?.liked?.visible;
    const followingCount = status.following_count;
    const likedTarget = shell.querySelector('.shiji-liked-count');
    const followingTarget = shell.querySelector('.shiji-following-count');
    if (likedTarget && Number.isInteger(likedCount)) likedTarget.textContent = Math.max(0, likedCount - (Number(window.libraryTrashCount) || 0)).toLocaleString('zh-CN');
    if (followingTarget && Number.isInteger(followingCount)) followingTarget.textContent = followingCount.toLocaleString('zh-CN');
  }).catch(() => {});
  const filters = main.querySelector('.filters');
  const menu = shell.querySelector('.shiji-side-groups');
  const likedFolders = [
    {id: 'design', name: '设计', sources: ['App设计', '视觉', '动效', '影视与创作', '动画', '产品设计', '设计方法'], custom: ['视觉灵感', '想法灵感']},
    {id: 'ai', name: 'AI', sources: ['AI与工具', 'AI工具', '独立开发', '效率工具'], custom: []},
    {id: 'life', name: '生活', sources: ['职业与成长', '家居', '饮食', '生活与技能', '出行与居住', '咖啡与器具', '创业想法', '文化与知识', '数码设备', '音乐与演出', '财经与市场', '旅行'], custom: []}
  ];
  const groupLabel = button => button.childNodes[0]?.textContent.trim() || button.textContent.trim();
  const makeGroup = button => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'shiji-side-group';
    item.dataset.groupId = button.dataset.groupId;
    const label = groupLabel(button);
    item.innerHTML = icon('folder') + '<span></span><small></small>';
    item.querySelector('span').textContent = label;
    item.querySelector('small').textContent = button.querySelector('span')?.textContent || '';
    item.classList.toggle('active', button.getAttribute('aria-pressed') === 'true');
    item.setAttribute('aria-pressed', String(item.classList.contains('active')));
    item.addEventListener('click', () => button.click());
    return item;
  };
  let currentFolders = likedFolders;
  let currentGrouped = {};
  const folderFor = (button, folders, assignments) => {
    const id = button.dataset.groupId || '';
    const label = groupLabel(button);
    if (assignments[id] && folders.some(folder => folder.id === assignments[id])) return assignments[id];
    if (id === 'source:待分析' || label === '待分析') return null;
    const source = id.startsWith('source:') ? id.slice(7) : '';
    const explicit = likedFolders.find(folder => folder.sources.includes(source) || folder.custom.includes(label));
    const fallback = explicit?.id || (/设计|视觉|动效|动画|创作|灵感|作品|交互|UI|UX/i.test(label) ? 'design' : /\bAI\b|智能|模型|编程|开发|工具|Agent/i.test(label) ? 'ai' : 'life');
    return folders.some(folder => folder.id === fallback) ? fallback : folders[0]?.id || null;
  };
  const updateGroups = () => {
    if (!filters) return;
    const source = [...filters.querySelectorAll('button[data-group-id]')];
    if (scope !== 'liked') {
      menu.replaceChildren(...source.slice(0, 8).map(makeGroup));
      return;
    }
    const folderState = window.libraryGroups?.folderState?.();
    const folders = folderState?.folders?.length ? folderState.folders : likedFolders;
    const assignments = folderState?.assignments || {};
    const grouped = Object.fromEntries(folders.map(folder => [folder.id, []]));
    for (const button of source) {
      const folder = folderFor(button, folders, assignments);
      if (folder) grouped[folder].push(button);
    }
    currentFolders = folders;
    currentGrouped = grouped;
    let activeFolder = window.libraryPage?.activeFolder || '';
    if (activeFolder && !grouped[activeFolder]) {
      window.libraryPage.selectFolder('', '', []);
      activeFolder = '';
    }
    const ids = activeFolder ? grouped[activeFolder].map(button => button.dataset.groupId) : [];
    if (activeFolder && ids.join('\n') !== window.libraryPage.folderGroupIds.join('\n')) window.libraryPage.refreshFolder(ids);
    const totalCount = source.reduce((total, button) => total + (Number((button.querySelector('span')?.textContent || '').replace(/,/g, '')) || 0), 0);
    const folderCount = activeFolder ? grouped[activeFolder].reduce((total, button) => total + (Number((button.querySelector('span')?.textContent || '').replace(/,/g, '')) || 0), 0) : totalCount;
    const allCount = filters.querySelector('button[data-filter=""] span');
    if (allCount && allCount.textContent !== String(folderCount)) allCount.textContent = String(folderCount);
    source.forEach(button => {
      button.dataset.hiddenFolder = activeFolder && folderFor(button, folders, assignments) !== activeFolder ? 'true' : 'false';
    });
    menu.replaceChildren(...folders.map(folder => {
      const row = document.createElement('div');
      row.className = 'shiji-folder-row';
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'shiji-side-folder';
      item.dataset.folder = folder.id;
      item.innerHTML = icon('folder') + '<span></span><small></small>';
      item.querySelector('span').textContent = folder.name;
      item.querySelector('small').textContent = String(grouped[folder.id].reduce((total, button) => total + (Number((button.querySelector('span')?.textContent || '').replace(/,/g, '')) || 0), 0));
      item.classList.toggle('active', activeFolder === folder.id);
      item.setAttribute('aria-pressed', String(activeFolder === folder.id));
      item.addEventListener('click', () => {
        const next = window.libraryPage.activeFolder === folder.id ? '' : folder.id;
        window.libraryPage.selectFolder(next, folder.name, grouped[folder.id].map(button => button.dataset.groupId));
        updateGroups();
      });
      item.addEventListener('keydown', event => {
        if (event.key === 'F2') { event.preventDefault(); openFolderDialog('rename', folder); }
      });
      const more = document.createElement('button');
      more.type = 'button';
      more.className = 'shiji-folder-more';
      more.textContent = '···';
      more.setAttribute('aria-label', `管理${folder.name}文件夹`);
      more.title = '重命名或删除文件夹';
      const actions = document.createElement('div');
      actions.className = 'shiji-folder-actions';
      actions.hidden = true;
      actions.innerHTML = '<button type="button" data-folder-action="rename">重命名</button><button type="button" data-folder-action="delete">删除文件夹</button>';
      more.addEventListener('click', () => {
        menu.querySelectorAll('.shiji-folder-actions').forEach(panel => { if (panel !== actions) panel.hidden = true; });
        actions.hidden = !actions.hidden;
      });
      actions.addEventListener('click', event => {
        const action = event.target.closest('[data-folder-action]')?.dataset.folderAction;
        if (action) openFolderDialog(action, folder);
      });
      row.append(item, more, actions);
      return row;
    }));
  };
  const folderDialog = scope === 'liked' ? document.createElement('dialog') : null;
  let editingFolder = null;
  let folderDialogMode = '';
  if (folderDialog) {
    folderDialog.className = 'group-dialog shiji-folder-dialog';
    folderDialog.setAttribute('aria-labelledby', 'shiji-folder-dialog-title');
    folderDialog.innerHTML = '<form><h2 id="shiji-folder-dialog-title"></h2><label class="shiji-folder-name-label">文件夹名称<input name="folder-name" maxlength="40" autocomplete="off" required></label><label class="shiji-folder-target-label" hidden>将其中的二级分类移到<select name="folder-target"></select></label><p class="group-dialog-error" role="alert"></p><div class="group-dialog-actions"><button type="button" class="group-cancel">取消</button><button type="submit" class="group-confirm">保存</button></div></form>';
    document.body.append(folderDialog);
    folderDialog.querySelector('.group-cancel').addEventListener('click', () => folderDialog.close());
    folderDialog.addEventListener('click', event => { if (event.target === folderDialog) folderDialog.close(); });
    folderDialog.querySelector('form').addEventListener('submit', async event => {
      event.preventDefault();
      const error = folderDialog.querySelector('.group-dialog-error');
      const confirm = folderDialog.querySelector('.group-confirm');
      error.textContent = '';
      let action, values, nextFolder = '';
      if (folderDialogMode === 'delete') {
        const target = folderDialog.querySelector('[name="folder-target"]').value;
        action = 'folder_delete';
        values = {folder_id: editingFolder.id, target_id: target};
        if (window.libraryPage.activeFolder === editingFolder.id) nextFolder = target;
      } else {
        const name = folderDialog.querySelector('[name="folder-name"]').value.trim();
        if (!name || name.length > 40) { error.textContent = '请输入1–40个字符的名称'; return; }
        if (currentFolders.some(folder => folder.name === name && folder.id !== editingFolder?.id)) { error.textContent = '已有同名文件夹'; return; }
        const folder = editingFolder ? {id: editingFolder.id, name} : {id: 'custom:' + crypto.randomUUID(), name};
        action = editingFolder ? 'folder_rename' : 'folder_create';
        values = {folder};
        if (!editingFolder || window.libraryPage.activeFolder === folder.id) nextFolder = folder.id;
      }
      confirm.disabled = true;
      const saved = await window.libraryGroups.folderAction(action, values);
      confirm.disabled = false;
      if (!saved) { error.textContent = '保存失败，请检查页面提示'; return; }
      updateGroups();
      if (nextFolder) {
        const folder = currentFolders.find(item => item.id === nextFolder);
        if (folder) window.libraryPage.selectFolder(folder.id, folder.name, currentGrouped[folder.id].map(button => button.dataset.groupId));
        updateGroups();
      }
      folderDialog.close();
    });
    shell.querySelector('.shiji-folder-add').addEventListener('click', () => openFolderDialog('create'));
    document.addEventListener('click', event => {
      if (!event.target.closest('.shiji-folder-more,.shiji-folder-actions')) menu.querySelectorAll('.shiji-folder-actions').forEach(panel => { panel.hidden = true; });
    });
  }
  function openFolderDialog(mode, folder = null) {
    if (!folderDialog) return;
    editingFolder = folder;
    folderDialogMode = mode;
    const deleting = mode === 'delete';
    folderDialog.querySelector('h2').textContent = mode === 'create' ? '新建文件夹' : deleting ? `删除「${folder.name}」` : '重命名文件夹';
    folderDialog.querySelector('.shiji-folder-name-label').hidden = deleting;
    folderDialog.querySelector('.shiji-folder-target-label').hidden = !deleting;
    folderDialog.querySelector('.group-dialog-error').textContent = '';
    folderDialog.querySelector('.group-confirm').textContent = deleting ? '删除文件夹' : '保存';
    const nameInput = folderDialog.querySelector('[name="folder-name"]');
    nameInput.required = !deleting;
    nameInput.value = folder?.name || '';
    const target = folderDialog.querySelector('[name="folder-target"]');
    target.replaceChildren(...currentFolders.filter(item => item.id !== folder?.id).map(item => {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.name;
      return option;
    }));
    if (deleting && !target.options.length) {
      folderDialog.querySelector('.group-dialog-error').textContent = '请先新建另一个文件夹，再删除最后一个文件夹';
      folderDialog.querySelector('.group-confirm').disabled = true;
    } else folderDialog.querySelector('.group-confirm').disabled = false;
    folderDialog.showModal();
    if (!deleting) { nameInput.focus(); nameInput.select(); }
    else target.focus();
  }
  if (filters) {
    new MutationObserver(updateGroups).observe(filters, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['aria-pressed']});
    updateGroups();
  }
  const allGroups = shell.querySelector('.shiji-all-groups');
  if (scope === 'liked') allGroups.remove();
  else allGroups.addEventListener('click', () => {
    const expand = main.querySelector('#expand-groups');
    if (expand?.getAttribute('aria-expanded') === 'false') expand.click();
    filters?.scrollIntoView({behavior: 'smooth', block: 'center'});
  });
})();
