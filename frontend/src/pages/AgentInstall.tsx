import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api';
import { SegmentedControl } from './SegmentedControl';
import './agent-auth.css';
import { t } from '../i18n.ts';

type InstallInfo = { backoffice_origin: string; plugin_version: string };

function Command({ value }: { value: string }) {
  const [copied, setCopied] = useState(false), [error, setError] = useState('');
  useEffect(() => { setCopied(false); setError(''); }, [value]);
  return <div className="agent-install-command"><code>{value}</code><button type="button" className="secondary" onClick={async () => {
    try { await navigator.clipboard.writeText(value); setCopied(true); setError(''); }
    catch { setError(t('無法複製，請手動選取內容')); }
  }}>{copied ? t('已複製') : t('複製')}</button>{error && <p className="notice danger" role="alert">{error}</p>}</div>;
}

export function AgentInstall() {
  const [agent, setAgent] = useState('claude'), [info, setInfo] = useState<InstallInfo | null>(null), [error, setError] = useState('');
  const origin = location.origin;
  useEffect(() => {
    const controller = new AbortController();
    api<InstallInfo>('/workspace/identity', { signal: controller.signal }).then(setInfo).catch(e => {
      if (!controller.signal.aborted) setError(errorMessage(e, t('安裝資訊載入失敗')));
    });
    return () => controller.abort();
  }, []);
  return <section className="agent-install" aria-labelledby="agent-install-title">
    <div className="member-card-heading"><h3 id="agent-install-title">{t('安裝 Agent')}</h3><SegmentedControl label={t('Agent 類型')} compact value={agent} onChange={setAgent} options={[{ value: 'claude', label: 'Claude Code' }, { value: 'codex', label: 'Codex' }, { value: 'desktop', label: t('Claude 桌面版') }]} /></div>
    {error && <p className="notice danger" role="alert">{error}</p>}
    {location.protocol === 'http:' && location.hostname === '127.0.0.1' && <p className="notice agent-install-origin">{t('其他成員請用內部 https 網址開啟工作檯後再複製指令')}{info?.backoffice_origin.startsWith('https://') && <> · <a href={info.backoffice_origin}>{t('開啟工作檯')}</a></>}</p>}
    {agent === 'claude' ? <>
      <Command value={`/plugin marketplace add ${origin}/plugin/marketplace.json`} />
      <Command value="/plugin install mwb@marketing-workbench" />
      <p className="agent-install-help">{t('到 /plugin → Marketplaces 開啟 Enable auto-update，之後會自動更新')}</p>
    </> : agent === 'codex' ? <>
      {info && <a className="secondary agent-install-download" href={`${origin}/plugin/codex/mwb-codex-${info.plugin_version}.zip`} download>{t('下載 Codex 套件')}</a>}
      {info && <Command value={`Expand-Archive ./mwb-codex-${info.plugin_version}.zip ./mwb-codex`} />}
      <p className="agent-install-help">{t('將 skills 下五個資料夾放到 ~/.agents/skills/，將 config.toml 合併至 ~/.codex/config.toml')}</p>
      <Command value="codex mcp login mwb" />
    </> : <>
      {info && <a className="secondary agent-install-download" href={`${origin}/plugin/desktop/mwb-${info.plugin_version}.mcpb`} download>{t('下載桌面擴充')}</a>}
      <ol className="agent-install-help agent-install-steps">
        <li>{t('開啟 Claude 桌面版 → 設定 → 擴充功能 → 安裝擴充功能，選擇下載的檔案。')}</li>
        <li>{t('工作檯網址填下列網址')}{location.protocol === 'http:' && location.hostname === '127.0.0.1' && t('；成員請填內部 https 網址，本機可填 http://127.0.0.1:8000')}{t('。')}<Command value={origin} /></li>
        <li>{t('在下方「Agent 連線」建立連線權杖，貼到擴充設定。')}</li>
      </ol>
    </>}
  </section>;
}
