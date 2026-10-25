# Agent 套件

Claude Code 原始檔在 `mwb/`。`.claude-plugin/plugin.json` 的 version 是唯一版本來源，目前 0.4.5；開發用 `.mcp.json` 的版本 header 須同步，HTTP 打包會自動填入版本及請求 origin。Codex skills 直接使用相同五份 SKILL.md，流程由 `get_guide` 提供。

發佈新版：修改 `mwb/` 或 `desktop/` 內容 → 提高 plugin.json version 並同步開發 header → 在 backend 執行 `uv run python ../scripts/update_plugin_hash.py` → 跑測試 → 由授權操作者部署。`content-hash.json` 記錄共用版本與內容 SHA-256；計算包含 mwb 的路徑與完整檔案（只移除 plugin.json 的 version 欄位），以及以 desktop/ 為前綴的全部桌面擴充檔案。版本未變而內容不同時，更新工具拒絕覆寫記錄，測試提示「請提高 plugin 版本」。最低相容維持 0.3.0。

Claude archive 採固定順序、時間戳及檔案權限；只改 `.mcp.json` 的 URL 與版本 header，plugin.json 與其他檔案維持原始 bytes。marketplace 項目不設 version，owner 讀工作區名稱。

Claude 桌面擴充在 `desktop/`：manifest.json 的 `${plugin_version}` 是打包模板，`agent_packages.desktop_archive()` 自動替換為唯一來源的版本，不直接安裝模板。`server/index.js` 不依賴 npm 套件，透過內建 Node／fetch 將 stdio 轉到內部 `/mcp`；權杖設定為 sensitive，由桌面版安全儲存。`upload_local_file` 直接串流本機媒體，不需 curl。下載 `/plugin/desktop/mwb-<version>.mcpb`，只限本機／Tailscale；ZIP 根目錄 manifest.json 與 server/index.js 使用相同決定性打包規則。更新需下載新版並重新安裝，不宣稱自動更新。部署前以官方 `mcpb validate <解出的 manifest.json>`／`mcpb info <套件.mcpb>` 驗證，再由使用者實機安裝；開發驗收不執行 Claude CLI 或修改桌面設定。

規格查證（2026-10-11）：[官方 README](https://github.com/modelcontextprotocol/mcpb/blob/main/README.md) 確認 MCPB 是 ZIP、根目錄需 manifest.json，Claude 桌面版內建 Node；[MANIFEST](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md) 定義 node、entry_point、mcp_config、user_config 變數及 sensitive 系統安全儲存。本套件採 manifest_version 0.3；套件 version 與規格版本各自獨立。

Codex 採 skills ZIP＋config.toml：官方目前把工具核准 policy 放在使用者 config，無可核對的 plugin 內核准格式。ZIP 的 config 依 `list_tools()` annotations 自動產生，所有寫入預設 prompt，唯讀 approve，confirm_publish 明確 prompt。更新需重新下載；安裝與 OAuth 由成員在自己的電腦操作。

依據：[Claude marketplace 託管](https://code.claude.com/docs/en/plugins/host-marketplace)、[archive 格式](https://code.claude.com/docs/en/plugins/marketplace-reference)、[OpenAI plugin 打包與 installed server policy](https://developers.openai.com/plugins/build/plugins)、[Codex MCP config](https://learn.chatgpt.com/docs/extend/mcp)。
