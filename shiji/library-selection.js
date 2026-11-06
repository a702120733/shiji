(() => {
  'use strict';
  if (document.body.dataset.library !== 'liked' || !window.libraryPage) return;
  const page = window.libraryPage;
  const cards = page.cards;
  const byId = new Map(cards.map(card => [card.dataset.itemId, card]));
  const grid = document.querySelector('.grid');
  const trashLink = document.querySelector('.shiji-trash-link');
  const selection = new Set();
  let trashed = new Set();
  let anchor = null;
  let drag = null;
  let suppressClickUntil = 0;
  let busy = false;

  if (page.trashView) {
    document.body.classList.add('trash-view');
    document.querySelector('main h1').textContent = '回收站';
    document.querySelector('main header p').textContent = '移入回收站的笔记可随时恢复，原图、视频和总结仍保存在本机。';
    document.querySelector('#empty').textContent = '回收站暂无内容。';
    page.setView('original', false);
  }

  const actions = document.createElement('div');
  actions.className = 'selection-actions';
  actions.hidden = true;
  actions.innerHTML = '<strong class="selection-total"></strong><span class="selection-hint">拖到左侧分组、上方标签或回收站</span><button type="button" class="selection-primary"></button><button type="button" class="selection-clear">取消选择</button><span class="selection-message" role="status" aria-live="polite"></span>';
  document.querySelector('.filter-state').insertBefore(actions, document.querySelector('.sort-controls'));
  const total = actions.querySelector('.selection-total');
  if (page.trashView) actions.querySelector('.selection-hint').remove();
  const primary = actions.querySelector('.selection-primary');
  primary.textContent = page.trashView ? '恢复所选' : '移到回收站';

  for (const card of cards) {
    const gallery = card.querySelector('.gallery');
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'select-toggle';
    toggle.textContent = '✓';
    toggle.setAttribute('aria-label', '选中：' + card.querySelector('h2').textContent);
    toggle.setAttribute('aria-pressed', 'false');
    toggle.title = page.trashView ? '选中待恢复笔记' : '点击选中；按住拖动到回收站或分组';
    gallery.append(toggle);
    const restore = document.createElement('button');
    restore.type = 'button';
    restore.className = 'restore-item';
    restore.textContent = '恢复';
    restore.setAttribute('aria-label', '恢复：' + card.querySelector('h2').textContent);
    gallery.append(restore);
  }

  function syncSelection() {
    for (const card of cards) {
      const active = selection.has(card.dataset.itemId);
      card.classList.toggle('is-selected', active);
      card.querySelector('.select-toggle').setAttribute('aria-pressed', String(active));
      card.querySelector('.select-toggle').title = page.trashView
        ? (active ? '取消选中' : '选中待恢复笔记')
        : (active ? '按住拖动所选笔记到回收站或分组；点击取消选中' : '点击选中；按住拖动到回收站或分组');
    }
    actions.hidden = selection.size === 0;
    total.textContent = `已选 ${selection.size} 条`;
  }
  function clearSelection() {
    selection.clear();
    anchor = null;
    syncSelection();
  }
  document.addEventListener('library-mode-change', event => {
    if (event.detail?.mode === 'clean') clearSelection();
  });
  function choose(card, event, toggle = false) {
    const id = card.dataset.itemId;
    if (event.shiftKey && anchor && byId.has(anchor)) {
      const visible = [...grid.querySelectorAll('article[data-item-id]:not([hidden])')];
      const a = visible.findIndex(item => item.dataset.itemId === anchor);
      const b = visible.indexOf(card);
      if (a >= 0 && b >= 0) {
        if (!event.metaKey && !event.ctrlKey) selection.clear();
        for (const item of visible.slice(Math.min(a, b), Math.max(a, b) + 1)) selection.add(item.dataset.itemId);
      }
    } else if (toggle || event.metaKey || event.ctrlKey) {
      if (selection.has(id)) selection.delete(id); else selection.add(id);
      anchor = id;
    } else {
      if (selection.size === 1 && selection.has(id)) selection.clear();
      else { selection.clear(); selection.add(id); }
      anchor = id;
    }
    syncSelection();
  }
  function updateNav() {
    window.libraryTrashCount = trashed.size;
    document.querySelectorAll('.shiji-trash-count').forEach(label => label.textContent = trashed.size ? String(trashed.size) : '');
    const liked = document.querySelector('.shiji-liked-count');
    if (liked) liked.textContent = (cards.length - cards.filter(card => card.dataset.trashed === 'true').length).toLocaleString('zh-CN');
  }
  function applyState(state) {
    trashed = new Set(Object.keys(state.liked || {}));
    for (const card of cards) card.dataset.trashed = String(trashed.has(card.dataset.itemId));
    clearSelection();
    document.dispatchEvent(new Event('library-trash-change'));
    page.refresh();
    updateNav();
  }
  async function save(action, ids) {
    if (busy || !ids.length) return;
    busy = true;
    primary.disabled = true;
    actions.querySelector('.selection-message').textContent = '正在保存…';
    try {
      const response = await fetch('/api/trash' + (location.pathname.startsWith('/saved/') ? '?source=saved' : ''), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action, ids})});
      const state = await response.json();
      if (!response.ok) throw new Error(state.error || '回收站保存失败');
      applyState(state);
    } catch (error) {
      actions.querySelector('.selection-message').textContent = error.message || '保存失败，请重试';
      actions.hidden = false;
    } finally {
      busy = false;
      primary.disabled = false;
    }
  }

  actions.addEventListener('click', event => {
    if (event.target.closest('.selection-clear')) clearSelection();
    if (event.target.closest('.selection-primary')) save(page.trashView ? 'restore' : 'trash', [...selection]);
  });
  document.addEventListener('click', event => {
    if (Date.now() < suppressClickUntil && event.target.closest('article')) {
      event.preventDefault(); event.stopImmediatePropagation(); return;
    }
    const restore = event.target.closest('.restore-item');
    if (restore && page.trashView) {
      event.stopPropagation();
      save('restore', [restore.closest('article').dataset.itemId]);
      return;
    }
    if (document.body.classList.contains('clean-mode')) return;
    const toggle = event.target.closest('.select-toggle');
    if (toggle) {
      event.stopPropagation();
      choose(toggle.closest('article'), event, true);
      return;
    }
    const card = event.target.closest('article[data-item-id]');
    if (!card || card.hidden || event.target.closest('a,button,input,select,textarea,details,summary,video')) return;
    choose(card, event);
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && selection.size && !document.querySelector('dialog[open]')) clearSelection();
  });

  const marquee = document.createElement('div');
  marquee.className = 'selection-marquee';
  marquee.hidden = true;
  document.body.append(marquee);
  const ghost = document.createElement('div');
  ghost.className = 'selection-drag-ghost';
  ghost.hidden = true;
  ghost.innerHTML = '<span class="selection-drag-thumb"></span><span class="selection-drag-copy"><strong></strong><small></small></span>';
  document.body.append(ghost);
  const ghostThumb = ghost.querySelector('.selection-drag-thumb');
  const ghostTitle = ghost.querySelector('strong');
  const ghostHint = ghost.querySelector('small');
  function showDragPreview(card, count) {
    const image = card.querySelector('.gallery .slide:not([hidden]) img, .gallery img');
    const video = card.querySelector('.gallery video');
    const source = image?.currentSrc || image?.src || video?.poster;
    ghostThumb.replaceChildren();
    if (source) {
      const preview = document.createElement('img');
      preview.src = source;
      preview.alt = '';
      ghostThumb.append(preview);
    } else ghostThumb.textContent = '▣';
    ghostTitle.textContent = count > 1 ? `${count} 条笔记` : card.querySelector('h2')?.textContent || '1 条笔记';
    ghostHint.textContent = '拖到分组或回收站';
    ghost.hidden = false;
    document.body.classList.add('library-drag-active');
  }
  function rect(a, b) {
    return {left: Math.min(a.x, b.x), top: Math.min(a.y, b.y), right: Math.max(a.x, b.x), bottom: Math.max(a.y, b.y)};
  }
  function intersects(a, b) { return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top; }
  function dropTarget(x, y) {
    const element = document.elementFromPoint(x, y);
    if (element?.closest('.shiji-trash-link')) return {kind: 'trash', element: trashLink};
    const chip = element?.closest('.filters [data-group-id], .shiji-side-group[data-group-id]');
    return chip && !page.trashView ? {kind: 'group', element: chip} : null;
  }
  function clearDropTarget() {
    trashLink?.classList.remove('trash-drop-target');
    document.querySelectorAll('.group-drop-target').forEach(item => item.classList.remove('group-drop-target'));
  }
  function finishPointer() {
    if (drag?.capture) {
      try { drag.capture.releasePointerCapture(drag.pointerId); } catch {}
    }
    drag = null;
    marquee.hidden = true;
    ghost.hidden = true;
    document.body.classList.remove('library-pointer-armed', 'library-drag-active');
    clearDropTarget();
  }
  document.addEventListener('pointerdown', event => {
    if (event.button !== 0 || busy || document.body.classList.contains('clean-mode')) return;
    const card = event.target.closest('article[data-item-id]');
    if (card && !page.trashView && !card.hidden && !event.target.closest('a,input,select,textarea,details,summary,video,.restore-item,.arrow,.group-handle')) {
      drag = {kind: 'card', id: card.dataset.itemId, start: {x: event.clientX, y: event.clientY}, active: false, pointerId: event.pointerId, capture: event.target};
    } else if (event.target === grid) {
      drag = {kind: 'marquee', start: {x: event.clientX, y: event.clientY}, base: new Set(event.metaKey || event.ctrlKey ? selection : []), active: false, pointerId: event.pointerId, capture: grid};
    }
    if (!drag) return;
    event.preventDefault();
    document.body.classList.add('library-pointer-armed');
    try { drag.capture.setPointerCapture(event.pointerId); } catch {}
  });
  document.addEventListener('dragstart', event => {
    if (event.target.closest('.grid article[data-item-id]') && !document.body.classList.contains('clean-mode')) event.preventDefault();
  });
  document.addEventListener('pointermove', event => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const now = {x: event.clientX, y: event.clientY};
    if (!drag.active && Math.hypot(now.x - drag.start.x, now.y - drag.start.y) < 7) return;
    if (!drag.active) {
      drag.active = true;
      if (drag.kind === 'card') {
        if (!selection.has(drag.id)) { selection.clear(); selection.add(drag.id); syncSelection(); }
        drag.ids = [...selection];
        showDragPreview(byId.get(drag.id), drag.ids.length);
      } else marquee.hidden = false;
      document.getSelection()?.removeAllRanges();
    }
    event.preventDefault();
    if (drag.kind === 'marquee') {
      const box = rect(drag.start, now);
      Object.assign(marquee.style, {left: box.left + 'px', top: box.top + 'px', width: box.right - box.left + 'px', height: box.bottom - box.top + 'px'});
      selection.clear();
      drag.base.forEach(id => selection.add(id));
      for (const card of cards) {
        if (card.hidden) continue;
        if (intersects(box, card.getBoundingClientRect())) selection.add(card.dataset.itemId);
      }
      syncSelection();
    } else {
      ghost.style.transform = `translate3d(${now.x + 16}px,${now.y + 16}px,0)`;
      clearDropTarget();
      const target = dropTarget(now.x, now.y);
      target?.element.classList.add(target.kind === 'trash' ? 'trash-drop-target' : 'group-drop-target');
      ghostHint.textContent = target?.kind === 'trash' ? '移到回收站'
        : target?.kind === 'group' ? `移到「${target.element.querySelector('span')?.textContent?.trim() || target.element.textContent.trim()}」`
        : '拖到分组或回收站';
    }
  }, {passive: false});
  document.addEventListener('pointerup', event => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const finished = drag;
    const target = finished.active && finished.kind === 'card' ? dropTarget(event.clientX, event.clientY) : null;
    finishPointer();
    if (!finished.active) return;
    suppressClickUntil = Date.now() + 400;
    if (finished.kind !== 'card') return;
    if (target?.kind === 'trash' && !page.trashView) save('trash', finished.ids);
    else if (target?.kind === 'group') window.libraryGroups?.moveItems(finished.ids, target.element.dataset.groupId).then(success => {
      if (success) clearSelection();
    });
    else actions.querySelector('.selection-message').textContent = '请拖到分组标签或回收站';
  });
  document.addEventListener('pointercancel', finishPointer);

  fetch('/api/trash' + (location.pathname.startsWith('/saved/') ? '?source=saved' : ''), {cache: 'no-store'}).then(async response => {
    const state = await response.json();
    if (!response.ok) throw new Error(state.error || '回收站读取失败');
    applyState(state);
  }).catch(error => {
    document.querySelector('#count').textContent = error.message || '回收站读取失败';
  });
})();
