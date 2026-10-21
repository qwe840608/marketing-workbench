import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { initLanguage } from './i18n.ts';
import './style.css';
import './ui-shell.css';
import './ui-padding.css';
import './ui-components.css';

// 先載入語言再動態載入頁面，頁面模組裡的常數字串才會用到正確的翻譯表。
await initLanguage();
const { App } = await import('./pages/App');
createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
