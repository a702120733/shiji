// OpenCLI read-only adapter: continue DOM fallback pagination when interception misses.
import { cli, Strategy } from '@jackwener/opencli/registry';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url);
const registryPath = require.resolve('@jackwener/opencli/registry');
const helpers = await import(pathToFileURL(resolve(dirname(registryPath), '../../clis/xiaohongshu/collection-helpers.js')).href);

cli({
  site: 'xiaohongshu', name: 'shiji-list', access: 'read',
  description: 'Load liked/saved notes with bounded DOM pagination fallback',
  domain: 'www.xiaohongshu.com', strategy: Strategy.COOKIE, browser: true, navigateBefore: false,
  args: [{name:'source', default:'liked'}, {name:'id', type:'string'}, {name:'limit', type:'int', default:50}],
  columns: ['rank','id','title','author','author_url','likes','type','url'],
  func: async (page, kwargs) => {
    const trace = stage => { if (process.env.XHS_LIBRARY_DEBUG) console.error('[library-list] ' + stage); };
    const limit = Number(kwargs.limit);
    if (!Number.isInteger(limit) || limit < 1 || limit > 1000) throw new Error('limit must be 1–1000');
    const userId = await helpers.resolveXhsUserId(page, kwargs.id);
    trace('profile resolved');
    const liked = kwargs.source !== 'saved';
    await page.installInterceptor(liked ? helpers.LIKE_API_PATTERN : helpers.COLLECT_API_PATTERN);
    trace('interceptor ready');
    await page.goto(helpers.buildProfileCollectionUrl(userId, liked ? helpers.LIKED_PROFILE_TAB : helpers.SAVED_PROFILE_TAB));
    trace('collection opened');
    await page.wait({time:3});
    const all = new Map();
    let noGrowth = 0;
    for (let pass=0; pass<80; pass++) {
      await helpers.assertOnCollectionProfile(page, userId);
      trace('pass ' + pass + ' profile checked');
      const before = all.size;
      const captures = await page.getInterceptedRequests();
      if (Array.isArray(captures) && captures.length) {
        for (const row of helpers.extractNotesFromResponses(captures, userId)) {
          const match = new URL(row.url).pathname.match(/^\/user\/profile\/([0-9a-f]{24})\//i);
          all.set(row.id,{...row,author_url:match ? `https://www.xiaohongshu.com/user/profile/${match[1]}` : ''});
        }
      }
      // The liked grid is virtualized: offscreen cards disappear from the DOM.
      // Slot 2 holds the likes already loaded by this profile page; read only
      // that collection, retaining the page's own order and signed note URLs.
      if (liked) {
        const cached = helpers.unwrapBrowserResult(await page.evaluate(`() => {
          if (new URL(location.href).searchParams.get('tab') !== 'liked') return [];
          const notes = window.__INITIAL_STATE__?.user?.notes;
          const lists = notes?._value ?? notes;
          return JSON.parse(JSON.stringify(Array.isArray(lists?.[2]) ? lists[2] : []));
        }`));
        for (const entry of Array.isArray(cached) ? cached : []) {
          const row = helpers.mapCollectionNote(entry);
          if (!row) continue;
          const match = new URL(row.url).pathname.match(/^\/user\/profile\/([0-9a-f]{24})\//i);
          all.set(row.id, {...row, author_url:match ? 'https://www.xiaohongshu.com/user/profile/' + match[1] : ''});
        }
      }
      const authors = helpers.unwrapBrowserResult(await page.evaluate(`() => {
        const found = {};
        for (const el of document.querySelectorAll('section.note-item')) {
          const cover = el.querySelector('a.cover.mask');
          const href = cover?.getAttribute('href') || '';
          const id = href.match(/\\/(?:explore|search_result|note)\\/([0-9a-f]{24})|\\/user\\/profile\\/[^/]+\\/([0-9a-f]{24})/i);
          const author = el.querySelector('a.author[href*="/user/profile/"]');
          const match = (author?.getAttribute('href') || '').match(/\\/user\\/profile\\/([0-9a-f]{24})(?:[/?#]|$)/i);
          if (id && match) found[id[1] || id[2]] = 'https://www.xiaohongshu.com/user/profile/' + match[1];
        }
        return found;
      }`));
      for (const row of await helpers.extractNotesFromDom(page)) {
        const old = all.get(row.id);
        all.set(row.id, {...row, ...old, author_url:authors?.[row.id] || old?.author_url || ''});
      }
      trace('pass ' + pass + ' notes ' + all.size);
      if (all.size >= limit) break;
      noGrowth = all.size === before ? noGrowth+1 : 0;
      if (noGrowth >= 3) break;
      await page.evaluate(`() => {
        const last = [...document.querySelectorAll('section.note-item')].at(-1);
        if (last) last.scrollIntoView({block:'end'});
      }`);
      await page.autoScroll({times:1,delayMs:1600});
      await page.wait({time:3});
    }
    if (!all.size) throw new Error('No visible liked/saved notes; check login and profile tab');
    return [...all.values()].slice(0,limit).map((item,i)=>({rank:i+1,...item}));
  }
});
