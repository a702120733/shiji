import { cli, Strategy } from '@jackwener/opencli/registry';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const registryPath = require.resolve('@jackwener/opencli/registry');
const helpers = await import(pathToFileURL(resolve(dirname(registryPath), '../../clis/xiaohongshu/collection-helpers.js')).href);

const LABELS = ['综合排序', '最新关注', '最早关注'];

const snapshot = `(() => {
  const panel = document.querySelector('.xhs-following-scroll');
  const items = [...document.querySelectorAll('.xhs-following-scroll .xhs-relation-item')];
  return {
    url: location.href,
    text: document.body.innerText.slice(-500),
    sort: document.querySelector('.xhs-sort-label')?.textContent?.trim() || '',
    scrollTop: panel?.scrollTop ?? null,
    scrollHeight: panel?.scrollHeight ?? null,
    clientHeight: panel?.clientHeight ?? null,
    items: items.map((el, index) => ({
      position: index + 1,
      name: el.querySelector('.xhs-relation-name')?.textContent?.trim() || '',
      description: el.querySelector('.xhs-relation-desc')?.textContent?.trim() || '',
      avatar: el.querySelector('.xhs-relation-avatar-img')?.getAttribute('src') || '',
      profile_url: (() => {
        const href = el.querySelector('a[href*="/user/profile/"]')?.href;
        if (!href) return '';
        const url = new URL(href);
        return /^\/user\/profile\/[0-9a-f]{24}\/?$/i.test(url.pathname) ? url.origin + url.pathname : '';
      })(),
      starred: Boolean(el.querySelector('.xhs-relation-star')),
    })),
  };
})()`;

function assertReadable(data) {
  if (String(data?.url || '').includes('/login') || /安全验证|请完成验证|验证码/.test(data?.text || '')) {
    throw new Error('小红书要求登录或安全验证；已停止后台采集');
  }
  if (!Array.isArray(data?.items)) throw new Error('关注弹窗未加载');
}

async function read(page) {
  const data = await page.evaluate(snapshot);
  assertReadable(data);
  return data;
}

const command = cli({
  site: 'xiaohongshu',
  name: 'shiji-following',
  access: 'read',
  description: '从后台适配器窗口读取本人关注名单和三种排序',
  domain: 'www.xiaohongshu.com',
  strategy: Strategy.COOKIE,
  browser: true,
  navigateBefore: false,
  args: [
    { name: 'id', type: 'string', help: 'Signed-in account profile ID' },
    { name: 'limit', type: 'int', default: 1000, help: 'Each sort must reach this count or the visible follow count, whichever is smaller' },
    { name: 'sort', type: 'string', default: 'all', help: 'all, comprehensive, latest, or earliest' },
    { name: 'timeout', type: 'int', default: 600, help: 'Seconds allowed for complete scrolling across all selected sorts' },
    { name: 'maxSteps', type: 'int', default: 180, help: 'Maximum scroll steps per sort' },
  ],
  columns: ['sort', 'position', 'name', 'description', 'avatar', 'profile_url', 'starred', 'source_count'],
  func: async (page, kwargs) => {
    const requested = Number(kwargs.limit);
    if (!Number.isInteger(requested) || requested < 1 || requested > 2000) throw new Error('limit 必须为 1–2000 的整数');
    const selectedSorts = { all: [0, 1, 2], comprehensive: [0], latest: [1], earliest: [2] }[String(kwargs.sort)];
    if (!selectedSorts) throw new Error('sort 必须为 all、comprehensive、latest 或 earliest');
    const profileId = await helpers.resolveXhsUserId(page, kwargs.id);
    if (!/^[0-9a-f]{24}$/i.test(String(profileId))) throw new Error('未找到当前账号主页');
    await page.goto(`https://www.xiaohongshu.com/user/profile/${profileId}`);
    let count = 0;
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const state = await page.evaluate(`(() => ({
        url: location.href,
        text: document.body.innerText.slice(-500),
        count: Number(document.querySelector('.clickable:has(.shows) .count')?.textContent?.trim() || 0),
      }))()`);
      if (String(state?.url || '').includes('/login') || /安全验证|请完成验证|验证码/.test(state?.text || '')) {
        throw new Error('小红书要求登录或安全验证；已停止后台采集');
      }
      count = state?.count || 0;
      if (count > 0) break;
      await page.wait(1);
    }
    if (!count) throw new Error('本人主页关注数未加载');
    const target = Math.min(count, requested);
    const alreadyOpen = await page.evaluate(`Boolean(document.querySelector('.xhs-following-scroll'))`);
    if (!alreadyOpen) await page.click('.clickable:has(.shows)', { nth: 0 });
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const state = await read(page);
      if (state.items.length) break;
      const panelOpen = await page.evaluate(`Boolean(document.querySelector('.xhs-following-scroll'))`);
      if (!panelOpen && (attempt === 2 || attempt === 5)) {
        await page.click('.clickable:has(.shows)', { nth: 0 });
      }
      if (attempt === 7) {
        const diagnostics = await page.evaluate(`(() => ({
          focused: document.hasFocus(),
          visibility: document.visibilityState,
          targets: [...document.querySelectorAll('.clickable:has(.shows)')].map((el) => el.innerText),
        }))()`);
        throw new Error(`关注弹窗无列表：${JSON.stringify({url: state.url, sort: state.sort, panelOpen, diagnostics})}`);
      }
      await page.wait(1);
    }

    const rows = [];
    for (const sortIndex of selectedSorts) {
      let data = await read(page);
      if (data.sort !== LABELS[sortIndex]) {
        await page.hover('.xhs-following-scroll');
        await page.hover('.xhs-sort-trigger');
        await page.wait(0.3);
        const menu = await page.evaluate(`(() => ({
          count: document.querySelectorAll('.xhs-sort-option').length,
          focused: document.hasFocus(),
          visibility: document.visibilityState,
          hovered: document.querySelector('.xhs-sort-trigger')?.matches(':hover'),
          dropdownHovered: document.querySelector('.xhs-sort-dropdown')?.matches(':hover'),
        }))()`);
        if (menu.count !== 3) throw new Error(`后台排序菜单未打开：${JSON.stringify(menu)}；保留完整基线`);
        await page.click('.xhs-sort-option', { nth: sortIndex });
        await page.wait(1);
      }
      data = await read(page);
      if (data.sort !== LABELS[sortIndex]) throw new Error(`排序切换失败：预期 ${LABELS[sortIndex]}，实际 ${data.sort}`);
      let stalls = 0;
      for (let step = 0; data.items.length < target && step < Number(kwargs.maxSteps); step += 1) {
        const before = data.items.length;
        const beforeTop = data.scrollTop;
        await page.evaluate(`(() => {
          const panel = document.querySelector('.xhs-following-scroll');
          if (!panel) throw new Error('关注列表滚动容器缺失');
          panel.scrollTop += Math.max(300, panel.clientHeight * 0.8);
        })()`);
        await page.wait(0.7);
        data = await read(page);
        if (data.items.length <= before && data.scrollTop === beforeTop) {
          stalls += 1;
          await page.wait(2.5);
          data = await read(page);
          if (data.items.length > before || data.scrollTop !== beforeTop) stalls = 0;
        } else stalls = 0;
        if (stalls >= 6) break;
      }
      if (data.items.length < target) {
        throw new Error(`${LABELS[sortIndex]}仅加载 ${data.items.length}/${target}（scrollTop=${data.scrollTop}, scrollHeight=${data.scrollHeight}, clientHeight=${data.clientHeight}）；保留旧完整基线`);
      }
      const selected = data.items.slice(0, target);
      if (selected.some((item) => !item.name)) throw new Error(`${LABELS[sortIndex]}存在空昵称`);
      rows.push(...selected.map((item) => ({ sort: LABELS[sortIndex], ...item, source_count: count })));
    }
    return rows;
  },
});

export { command };
