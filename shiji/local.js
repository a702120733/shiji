(() => {
  'use strict';
  const page = document.body.dataset.page;
  const message = document.querySelector('#message');
  const count = document.querySelector('#count');
  const total = document.querySelector('#total');
  const empty = document.querySelector('#empty');
  let rows = [];

  const node = (tag, className, value) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = String(value);
    return element;
  };
  const request = async (path, payload) => {
    const options = payload === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    };
    const response = await fetch(path, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `请求失败：${response.status}`);
    return result;
  };
  const notice = (text, error = false) => {
    message.textContent = text;
    message.style.color = error ? '#b22f3a' : '#4f7655';
  };
  const validUrl = value => {
    try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : ''; }
    catch { return ''; }
  };
  const addLink = (card, row) => {
    const href = validUrl(row.url);
    if (!href) return;
    const anchor = node('a', '', row.title);
    anchor.href = href;
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
    card.append(anchor);
    card.append(node('small', '', new URL(href).hostname));
  };

  if (page === 'bookmarks') {
    const file = document.querySelector('#bookmark-file');
    const importButton = document.querySelector('#import-bookmarks');
    const folderFilter = document.querySelector('#folder-filter');
    const search = document.querySelector('#search');
    const groups = document.querySelector('#bookmark-groups');
    const folderName = row => row.folders?.[0] || '未分类';
    const secondaryName = row => row.folders?.[1] || '书签';
    const tertiaryName = row => row.folders?.slice(2).join(' / ') || '链接';
    const render = () => {
      const query = search.value.trim().toLocaleLowerCase();
      const selectedFolder = folderFilter.value;
      const visible = rows.filter(row => (!selectedFolder || folderName(row) === selectedFolder) &&
        (!query || `${row.title} ${row.url} ${row.folders?.join(' ')}`.toLocaleLowerCase().includes(query)));
      count.textContent = `显示 ${visible.length} / ${rows.length} 条`;
      total.textContent = `${rows.length} 条`;
      empty.hidden = visible.length > 0;
      const tree = new Map();
      for (const row of visible) {
        const folder = folderName(row), secondary = secondaryName(row), tertiary = tertiaryName(row);
        if (!tree.has(folder)) tree.set(folder, new Map());
        if (!tree.get(folder).has(secondary)) tree.get(folder).set(secondary, new Map());
        if (!tree.get(folder).get(secondary).has(tertiary)) tree.get(folder).get(secondary).set(tertiary, []);
        tree.get(folder).get(secondary).get(tertiary).push(row);
      }
      const fragment = document.createDocumentFragment();
      for (const [folder, secondaries] of tree) {
        const section = node('section', 'group');
        section.append(node('h2', '', folder));
        for (const [secondary, tertiaries] of secondaries) {
          const subsection = node('section', 'subgroup');
          subsection.append(node('h3', '', secondary));
          for (const [tertiary, items] of tertiaries) {
            subsection.append(node('div', 'tertiary', tertiary));
            const grid = node('div', 'bookmark-grid');
            for (const row of items) {
              const card = node('article', 'card');
              addLink(card, row);
              grid.append(card);
            }
            subsection.append(grid);
          }
          section.append(subsection);
        }
        fragment.append(section);
      }
      groups.replaceChildren(fragment);
    };
    const load = async () => {
      rows = await request('/api/bookmarks');
      const selected = folderFilter.value;
      folderFilter.replaceChildren(node('option', '', '全部'));
      for (const folder of [...new Set(rows.map(folderName))]) {
        const option = node('option', '', folder);
        option.value = folder;
        folderFilter.append(option);
      }
      folderFilter.value = selected;
      render();
    };
    importButton.addEventListener('click', async () => {
      if (!file.files?.length) return notice('请先选择 Chrome 导出的书签 HTML', true);
      if (file.files[0].size > 10_000_000) return notice('书签文件不能超过 10 MB', true);
      importButton.disabled = true;
      notice('正在导入到本机…');
      try {
        const result = await request('/api/bookmarks/import', {content: await file.files[0].text()});
        await load();
        notice(`已导入 ${result.imported} 条书签`);
      } catch (error) { notice(error.message, true); }
      finally { importButton.disabled = false; }
    });
    folderFilter.addEventListener('change', render);
    search.addEventListener('input', render);
    load().catch(error => notice(error.message, true));
  }

  if (page === 'products') {
    const form = document.querySelector('#product-form');
    const search = document.querySelector('#search');
    const grid = document.querySelector('#product-grid');
    const render = () => {
      const query = search.value.trim().toLocaleLowerCase();
      const visible = rows.filter(row => `${row.title} ${row.description} ${row.url}`.toLocaleLowerCase().includes(query));
      total.textContent = `${rows.length} 个`;
      count.textContent = `显示 ${visible.length} / ${rows.length} 个`;
      empty.hidden = visible.length > 0;
      grid.replaceChildren(...visible.map(row => {
        const card = node('article', 'card');
        addLink(card, row);
        card.append(node('p', '', row.description));
        const remove = node('button', '', '移除');
        remove.type = 'button';
        remove.addEventListener('click', async () => {
          try { await request('/api/products/remove', {id: row.id}); await load(); notice('已从本机列表移除'); }
          catch (error) { notice(error.message, true); }
        });
        card.append(remove);
        return card;
      }));
    };
    const load = async () => { rows = await request('/api/products'); render(); };
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(form));
      try { await request('/api/products/save', values); form.reset(); await load(); notice('已保存到本机'); }
      catch (error) { notice(error.message, true); }
    });
    search.addEventListener('input', render);
    load().catch(error => notice(error.message, true));
  }
})();
