// Read the public identity shown on one Xiaohongshu profile. No interaction or account mutation.
import { cli, Strategy } from '@jackwener/opencli/registry';

cli({
  site: 'xiaohongshu', name: 'shiji-account-profile', access: 'read',
  description: 'Read a Xiaohongshu profile name and avatar for local account settings',
  domain: 'www.xiaohongshu.com', strategy: Strategy.COOKIE,
  browser: true, navigateBefore: false,
  args: [{name: 'id', type: 'string', help: 'Exact 24 character profile ID'}],
  columns: ['profile_id', 'name', 'avatar_url', 'profile_url'],
  func: async (page, kwargs) => {
    const id = String(kwargs.id || '').trim().toLowerCase();
    if (!/^[0-9a-f]{24}$/.test(id)) throw new Error('Profile ID is invalid');
    await page.goto(`https://www.xiaohongshu.com/user/profile/${id}`);
    await page.wait(1.2);
    const profile = await page.evaluate(`(() => ({
      name: document.querySelector('.user-name')?.textContent?.trim() || '',
      avatar_url: document.querySelector('.user-image')?.getAttribute('src') || '',
      page_text: document.body.innerText.slice(0, 500),
      path: location.pathname,
    }))()`);
    if (/安全验证|验证码|访问频次异常|登录后查看|请先登录/.test(profile.page_text)) {
      throw new Error('Xiaohongshu login or security verification required');
    }
    if (profile.path !== `/user/profile/${id}` || !profile.name || !profile.avatar_url) {
      throw new Error('Profile name or avatar is unavailable');
    }
    return [{profile_id: id, name: profile.name, avatar_url: profile.avatar_url,
             profile_url: `https://www.xiaohongshu.com/user/profile/${id}`}];
  },
});
