// 「交給 Agent 撰寫」的報告：用官方深層連結開啟桌面 App 並預填指令，不會自動送出。
// Claude：https://support.claude.com/en/articles/14729294-open-claude-desktop-with-a-link
// Codex：https://learn.chatgpt.com/docs/reference/commands.md。Codex 與 ChatGPT 是同一個 App，沒帶 mode 會開在
// 預設模式（可能是「工作」）；mode=codex 文件未列，讀 App 程式得知並於 2026-10-21 在 Windows 實測可開到 Codex。
// Antigravity 桌面版官方沒有帶指令的連結，只提供複製指令。
export type HandoffPrompts = { slash: string; plain: string };
export type HandoffLink = { app: 'claude-code' | 'claude-chat' | 'codex'; href: string; prompt: string };

export function handoffLinks(prompts: HandoffPrompts): HandoffLink[] {
  const q = (text: string) => encodeURIComponent(text);
  return [
    { app: 'claude-code', href: `claude://code/new?q=${q(prompts.slash)}`, prompt: prompts.slash },
    { app: 'claude-chat', href: `claude://claude.ai/new?q=${q(prompts.plain)}`, prompt: prompts.plain },
    { app: 'codex', href: `codex://new?prompt=${q(prompts.plain)}&mode=codex`, prompt: prompts.plain },
  ];
}
