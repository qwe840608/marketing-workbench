// 各群組分檔，讓不同頁面的翻譯可以分開維護。
import app from './app.ts';
import publish from './publish.ts';
import posts from './posts.ts';
import guides from './guides.ts';
import ai from './ai.ts';
import settings from './settings.ts';
import dashboard from './dashboard.ts';
import backend from './backend.ts';

export default { ...app, ...publish, ...posts, ...guides, ...ai, ...settings, ...dashboard, ...backend } as Record<string, string>;
