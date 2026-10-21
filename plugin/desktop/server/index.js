'use strict';

// 擴充入口。Claude 桌面版的內建 Node 可能經由自己的外殼載入本檔，require.main 不一定是本檔，
// 因此入口一律啟動；可測試的邏輯放在 bridge.js。
require('./bridge.js').main().catch(() => {
  process.stderr.write('桌面擴充無法啟動，請重新安裝\n');
  process.exitCode = 1;
});
