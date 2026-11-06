// Read-only connection check. The account stays signed in inside the user's Chrome.
import { cli, Strategy } from '@jackwener/opencli/registry';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const registryPath = require.resolve('@jackwener/opencli/registry');
const helpers = await import(pathToFileURL(resolve(dirname(registryPath), '../../clis/xiaohongshu/collection-helpers.js')).href);

cli({
  site: 'xiaohongshu', name: 'shiji-connect', access: 'read',
  description: 'Check the signed-in Xiaohongshu account for a local import',
  domain: 'www.xiaohongshu.com', strategy: Strategy.COOKIE,
  browser: true, navigateBefore: false, args: [],
  columns: ['profile_id'],
  func: async (page) => {
    const profileId = await helpers.resolveXhsUserId(page);
    if (!/^[0-9a-f]{24}$/i.test(String(profileId))) throw new Error('No signed-in account found');
    return [{profile_id: profileId}];
  },
});
