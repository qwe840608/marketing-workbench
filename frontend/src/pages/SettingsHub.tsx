import type { Brand, User } from '../api';
import type { SettingsTab } from '../ideationNavigation';
import { AISettingsPage } from './AISettings';
import { ClassificationSettings } from './Classification';
import { SettingsPage } from './Settings';
import { PageHeader } from './PageHeader';
import { PlatformConnections } from './PlatformConnections';
import { Members } from './Members';
import { MyAccount } from './MyAccount';
import { NeedBrand } from './NeedBrand';
import { t } from '../i18n.ts';

const adminTabs = [{ id: 'connections', label: t('平台連線') }, { id: 'ai', label: 'AI' }, { id: 'policy', label: t('訊息分類') }, { id: 'workspace', label: t('工作區') }, { id: 'members', label: t('成員') }, { id: 'account', label: t('我的帳號') }] as const;

export function SettingsHub({ tab: selected, onTab, brand, brands, user, onChanged, onUserChanged, onSelfReset }: {
  tab: SettingsTab; onTab: (tab: SettingsTab) => void; brand: string; brands: Brand[]; user: User; onChanged: (user: User) => void; onUserChanged: () => void; onSelfReset: (password: string) => void;
}) {
  const role = user.role, tabs = role === 'admin' ? adminTabs : adminTabs.filter(entry => entry.id === 'account');
  const tab = tabs.some(entry => entry.id === selected) ? selected : 'account';
  const needBrand = brands.length > 1 && !brand;
  return <section className="settings-page settings-hub">
    <PageHeader title={t('設定')} />
    <div className="settings-tabs tabs" role="tablist" aria-label={t('設定')}>
      {tabs.map((item, index) => <button key={item.id} type="button" role="tab" id={'settings-tab-' + item.id}
        aria-selected={tab === item.id}
        aria-controls={'settings-panel-' + item.id} tabIndex={tab === item.id ? 0 : -1}
        onClick={() => onTab(item.id)} onKeyDown={event => {
          const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
          if (next === null) return;
          event.preventDefault(); onTab(tabs[next].id);
          document.getElementById('settings-tab-' + tabs[next].id)?.focus();
        }}>{item.label}</button>)}
    </div>
    {tabs.map(item => <div key={item.id} role="tabpanel" id={'settings-panel-' + item.id} aria-labelledby={'settings-tab-' + item.id} tabIndex={0} hidden={tab !== item.id}>
      {tab === item.id && (tab === 'ai' ? (needBrand ? <NeedBrand /> : <AISettingsPage brands={brands} brand={brand} canEdit={role !== 'viewer'} role={role} />)
        : tab === 'connections' ? <PlatformConnections role={role} />
          : tab === 'policy' ? (needBrand ? <NeedBrand /> : <ClassificationSettings brands={brands} brand={brand} canEdit={role !== 'viewer'} />)
          : tab === 'workspace' ? <SettingsPage brand={brand} brands={brands} role={role} />
            : tab === 'members' ? <Members brands={brands} currentUserId={user.id} onUserChanged={onUserChanged} onSelfReset={onSelfReset} />
              : <MyAccount user={user} brands={brands} onChanged={onChanged} />)}
    </div>)}
  </section>;
}
