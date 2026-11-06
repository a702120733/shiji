import { cli, Strategy } from '@jackwener/opencli/registry';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url);
const registryPath = require.resolve('@jackwener/opencli/registry');
const { command } = await import(pathToFileURL(resolve(dirname(registryPath), '../../clis/xiaohongshu/note.js')).href);
cli({
  site:'xiaohongshu',name:'shiji-note',access:'read',domain:'www.xiaohongshu.com',
  description:'Read note content and its actual author profile',strategy:Strategy.COOKIE,navigateBefore:false,
  args:command.args,columns:['field','value'],
  func:async(page,kwargs)=>{
    const rows = await command.func(page,kwargs);
    const result = await page.evaluate(`() => {
      const author = document.querySelector('.author-wrapper a[href*="/user/profile/"], .author-container a[href*="/user/profile/"], a.username[href*="/user/profile/"]');
      const match = (author?.getAttribute('href') || '').match(/\\/user\\/profile\\/([0-9a-f]{24})(?:[/?#]|$)/i);
      return match ? 'https://www.xiaohongshu.com/user/profile/' + match[1] : '';
    }`);
    const url = result?.session && 'data' in result ? result.data : result;
    if (url) rows.push({field:'author_url',value:url});
    return rows;
  }
});
