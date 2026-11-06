(() => {
  'use strict';
  const scope = document.body.dataset.library;
  const bridge = window.libraryPage;
  const filters = document.querySelector('.filters');
  if (!bridge || !filters || !['liked', 'following'].includes(scope)) return;
  const cards = [...document.querySelectorAll('article[data-item-id]')];
  const buttonClass = scope === 'liked' ? 'tag' : 'chip';
  const sources = new Map();
  const original = new WeakMap();
  const defaultNames = new Set(cards.map(card => card.dataset.defaultGroup));
  for (const button of filters.querySelectorAll('button')) {
    const source = scope === 'liked' ? button.dataset.filter : button.dataset.category;
    if (source && defaultNames.has(source)) sources.set('source:' + source, {id:'source:' + source, name:source, source});
  }
  for (const card of cards) {
    const source = card.dataset.defaultGroup;
    const id = 'source:' + source;
    if (!sources.has(id)) sources.set(id, {id, name: source, source});
    original.set(card, {search: card.dataset.search, tags: scope === 'liked' ? JSON.parse(card.dataset.tags) : []});
  }
  let state = {groups: {}, order: [], assignments: {}};
  let groups = [], saving = false, loaded = false, drag = null, statusTimer;
  const tools = document.createElement('div');
  tools.className = scope === 'liked' ? 'group-tools group-tools-compact' : 'group-tools';
  tools.innerHTML = scope === 'liked'
    ? '<span class="group-status" role="status" aria-live="polite"></span>'
    : '<span>分组 <small>双击改名 · 拖动标签排序 · 拖动卡片 ⠿ 改组</small></span><button type="button" class="group-create">＋ 新建分组</button><span class="group-status" role="status" aria-live="polite"></span>';
  const createButton = scope === 'liked' ? document.createElement('button') : tools.querySelector('.group-create');
  if (scope === 'liked') {
    createButton.type = 'button';
    createButton.className = 'tag group-create';
    createButton.textContent = '+';
    createButton.setAttribute('aria-label', '新建分组');
    createButton.title = '新建分组';
    filters.append(createButton, tools);
  } else filters.before(tools);
  const status = tools.querySelector('.group-status');
  function notify(message, error = false) {
    clearTimeout(statusTimer);
    status.textContent = message;
    status.classList.toggle('error', error);
    if (!error) statusTimer = setTimeout(() => { status.textContent = ''; }, 4500);
  }
  function resolvedGroups() {
    const merged = new Map(sources);
    for (const group of Object.values(state.groups)) merged.set(group.id, group);
    return [...new Set([...state.order, ...merged.keys()])].filter(id => merged.has(id)).map(id => merged.get(id));
  }
  function chip(group, count) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = buttonClass;
    const label = group ? group.name : '全部';
    if (scope === 'liked') button.dataset.filter = label === '全部' && !group ? '' : label;
    else button.dataset.category = group ? label : '';
    button.setAttribute('aria-pressed', 'false');
    button.append(document.createTextNode(label + ' '));
    const total = document.createElement('span');
    total.textContent = count;
    button.append(total);
    if (group) {
      button.dataset.groupId = group.id;
      button.draggable = false;
      button.title = '双击或按 F2 重命名；拖动调整顺序';
      button.addEventListener('dblclick', event => {
        event.preventDefault();
        bridge.selectGroup(group.name, group.id);
        openName(group);
      });
      button.addEventListener('keydown', event => {
        if (event.key === 'F2') { event.preventDefault(); openName(group); }
      });
    }
    return button;
  }
  function render(selectedId) {
    groups = resolvedGroups();
    const lookup = new Map(groups.map(group => [group.id, group]));
    const counts = new Map();
    for (const card of cards) {
      const preferred = state.assignments[card.dataset.itemId];
      const id = lookup.has(preferred) ? preferred : 'source:' + card.dataset.defaultGroup;
      const group = lookup.get(id);
      card.dataset.groupId = id;
      if (card.dataset.trashed !== 'true') counts.set(id, (counts.get(id) || 0) + 1);
      card.dataset.search = original.get(card).search + ' ' + group.name.toLocaleLowerCase();
      if (scope === 'liked') {
        card.dataset.tags = JSON.stringify([...new Set([group.name, ...original.get(card).tags.slice(1)])]);
        const primary = card.querySelector('.tags button');
        if (primary) { primary.textContent = group.name; primary.dataset.filter = group.name; primary.dataset.groupId = id; }
      } else {
        card.dataset.category = group.name;
        const primary = card.querySelector('button.category');
        primary.textContent = group.name;
        primary.dataset.category = group.name;
      }
      card.querySelector('.group-handle').setAttribute('aria-label', '移动到分组：' + group.name);
    }
    filters.replaceChildren(chip(null, cards.filter(card => card.dataset.trashed !== 'true').length), ...groups.map(group => chip(group, counts.get(group.id) || 0)), ...(scope === 'liked' ? [createButton, tools] : []));
    bridge.selectGroup(lookup.get(selectedId)?.name || '', lookup.has(selectedId) ? selectedId : '');
  }
  async function commit(action, values, selectId) {
    if (!loaded) { notify('分组尚未载入，请稍后重试', true); return false; }
    if (saving) { notify('正在保存，请稍候'); return false; }
    const active = filters.querySelector('[aria-pressed="true"]')?.dataset.groupId;
    saving = true;
    tools.classList.add('saving');
    createButton.disabled = true;
    notify('正在保存…');
    try {
      const response = await fetch('/api/groups' + (location.pathname.startsWith('/saved/') ? '?source=saved' : ''), {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scope, action, groups, ...values})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '本机保存失败');
      state = result[scope];
      render(selectId || active);
      notify('已保存到本机');
      return true;
    } catch (error) {
      notify(error.message || '保存失败，请重试', true);
      return false;
    } finally {
      saving = false;
      tools.classList.remove('saving');
      createButton.disabled = false;
    }
  }
  const dialog = document.createElement('dialog');
  dialog.className = 'group-dialog';
  dialog.setAttribute('aria-labelledby', 'group-dialog-title');
  dialog.innerHTML = '<form><h2 id="group-dialog-title"></h2><label class="group-name-label">分组名称<input name="group-name" maxlength="40" autocomplete="off" required></label><label class="group-move-label" hidden>选择分组<select name="group-target"></select></label><p class="group-dialog-error" role="alert"></p><div class="group-dialog-actions"><button type="button" class="group-cancel">取消</button><button type="submit" class="group-confirm">保存</button></div></form>';
  document.body.append(dialog);
  const form = dialog.querySelector('form'), nameInput = form.elements['group-name'], targetSelect = form.elements['group-target'];
  let editing = null, moving = null;
  function prepareDialog(title, isMove) {
    dialog.querySelector('h2').textContent = title;
    dialog.querySelector('.group-name-label').hidden = isMove;
    dialog.querySelector('.group-move-label').hidden = !isMove;
    nameInput.required = !isMove;
    dialog.querySelector('.group-dialog-error').textContent = '';
  }
  function openName(group = null) {
    editing = group; moving = null;
    prepareDialog(group ? '重命名分组' : '新建分组', false);
    nameInput.value = group?.name || '';
    dialog.showModal(); nameInput.focus(); nameInput.select();
  }
  function openMove(card) {
    moving = card; editing = null;
    prepareDialog('移动到分组', true);
    targetSelect.replaceChildren(...groups.map(group => {
      const option = document.createElement('option'); option.value = group.id; option.textContent = group.name; return option;
    }));
    targetSelect.value = card.dataset.groupId;
    dialog.showModal(); targetSelect.focus();
  }
  createButton.addEventListener('click', () => openName());
  dialog.querySelector('.group-cancel').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const confirm = dialog.querySelector('.group-confirm');
    const error = dialog.querySelector('.group-dialog-error');
    error.textContent = '';
    let action, values, selectId;
    if (moving) {
      const group = groups.find(group => group.id === targetSelect.value);
      action = 'move'; values = {item_id: moving.dataset.itemId, group}; selectId = group.id;
    } else {
      const name = nameInput.value.trim();
      if (!name || name.length > 40) { error.textContent = '请输入1–40个字符的名称'; return; }
      if (groups.some(group => group.name === name && group.id !== editing?.id)) { error.textContent = '已有同名分组'; return; }
      const group = editing ? {...editing, name} : {id: 'custom:' + crypto.randomUUID(), name, source: null};
      action = editing ? 'rename' : 'create'; values = {group};
      if (!editing && scope === 'liked' && bridge.activeFolder) values.folder_id = bridge.activeFolder;
    }
    confirm.disabled = true;
    const success = await commit(action, values, selectId);
    confirm.disabled = false;
    if (success) dialog.close(); else error.textContent = status.textContent;
  });
  for (const card of cards) {
    const handle = document.createElement('button');
    handle.type = 'button'; handle.className = 'group-handle'; handle.draggable = false;
    handle.textContent = '⠿'; handle.title = '拖到分组标签，或点击选择分组';
    handle.addEventListener('click', event => { event.stopPropagation(); openMove(card); });
    (scope === 'liked' ? card.querySelector('.gallery') : card.querySelector('.row')).append(handle);
  }
  let suppressDragClick = false;
  const ghost = document.createElement('div');
  ghost.className = 'group-drag-preview'; ghost.hidden = true;
  document.body.append(ghost);
  document.addEventListener('click', event => {
    if (suppressDragClick && event.target.closest('.group-handle,.filters [data-group-id]')) {
      suppressDragClick = false; event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  document.addEventListener('pointerdown', event => {
    if (event.button !== 0 || saving) return;
    const handle = event.target.closest('.group-handle');
    const chip = event.target.closest('.filters [data-group-id]');
    if (!handle && !chip) return;
    const element = handle || chip;
    drag = {kind: handle ? 'item' : 'group', id: handle ? handle.closest('article').dataset.itemId : chip.dataset.groupId,
      x: event.clientX, y: event.clientY, pointerId: event.pointerId, element, active: false};
    element.setPointerCapture(event.pointerId);
  });
  document.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (!drag.active && Math.hypot(event.clientX-drag.x,event.clientY-drag.y)<7) return;
    if (!drag.active) {
      drag.active = true;
      drag.element.classList.add('group-dragging');
      document.body.classList.add('group-drag-active');
      ghost.textContent = drag.kind === 'item' ? drag.element.closest('article').querySelector('h2').textContent : drag.element.textContent;
      ghost.hidden = false;
    }
    event.preventDefault();
    ghost.style.transform = `translate(${event.clientX+14}px,${event.clientY+14}px)`;
    document.querySelectorAll('.group-drop-target').forEach(target => target.classList.remove('group-drop-target'));
    const target = document.elementFromPoint(event.clientX,event.clientY)?.closest(drag.kind === 'group' ? '.filters [data-group-id],.shiji-side-folder' : '.filters [data-group-id]');
    target?.classList.add('group-drop-target');
  }, {passive:false});
  function finishDrag() {
    if (!drag) return;
    try { drag.element.releasePointerCapture(drag.pointerId); } catch {}
    document.querySelectorAll('.group-dragging,.group-drop-target').forEach(element=>element.classList.remove('group-dragging','group-drop-target'));
    document.body.classList.remove('group-drag-active'); ghost.hidden = true;
    drag = null;
  }
  document.addEventListener('pointerup', async event => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const ended = drag;
    const target = document.elementFromPoint(event.clientX,event.clientY)?.closest(ended.kind === 'group' ? '.filters [data-group-id],.shiji-side-folder' : '.filters [data-group-id]');
    finishDrag();
    if (!ended.active) return;
    suppressDragClick = true; setTimeout(()=>{suppressDragClick=false;},400);
    if (!target) { notify(ended.kind === 'group' ? '拖到左侧文件夹或上方标签' : '拖到上方分组标签即可改组'); return; }
    if (target.classList.contains('shiji-side-folder')) {
      await commit('folder_assign', {group_id: ended.id, folder_id: target.dataset.folder});
      return;
    }
    const group = groups.find(group=>group.id===target.dataset.groupId);
    if (ended.kind === 'item') await commit('move',{item_id:ended.id,group},group.id);
    else if (ended.id !== group.id) {
      const ids=groups.map(group=>group.id).filter(id=>id!==ended.id);
      const rect=target.getBoundingClientRect();
      ids.splice(ids.indexOf(group.id)+(event.clientX>rect.left+rect.width/2?1:0),0,ended.id);
      await commit('reorder',{ids,groups});
    }
  });
  document.addEventListener('pointercancel', finishDrag);
  async function load() {
    try {
      const response = await fetch('/api/groups' + (location.pathname.startsWith('/saved/') ? '?source=saved' : ''), {cache: 'no-store'});
      if (!response.ok) throw new Error('请使用资料库本机服务以保存分组');
      const result = await response.json(); state = result[scope]; loaded = true;
      render(filters.querySelector('[aria-pressed="true"]')?.dataset.groupId);
    } catch (error) { notify(error.message || '分组读取失败，请刷新重试', true); }
  }
  groups = resolvedGroups();
  if (scope === 'liked') {
    window.libraryGroups = {
      moveItems(ids, groupId) {
        const group = groups.find(item => item.id === groupId);
        if (!group) return Promise.resolve(false);
        return commit('move_many', {ids, group}, group.id);
      },
      folderState() {
        return loaded ? {folders: state.folders, assignments: state.folderAssignments} : null;
      },
      folderAction(action, values) {
        return commit(action, values);
      },
      refresh() { render(filters.querySelector('[aria-pressed="true"]')?.dataset.groupId); }
    };
    document.addEventListener('library-trash-change', () => window.libraryGroups.refresh());
  }
  load();
})();
