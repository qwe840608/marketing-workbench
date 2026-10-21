() => {
  const rows = [], containers = [], violations = [], failures = [];
  let assertions = 0;
  const minimum = innerWidth < 600 ? 14 : 20;
  const describe = e => e.tagName.toLowerCase() + [...e.classList].map(c => '.' + c).join('');
  const contentCards = '.conversation,.post-card,.ranked-post,.settings-shortcuts button';
  const badges = '.avatar,.state,.readonly-label,.key-source,.status-badge,.processing-flow li span,.routing-table small,.demo-tag,.ideation-step-number';
  const roots = [...document.querySelectorAll('.workspace > :not(.sidebar),.receive-banner,dialog[open]')];
  const painted = e => {
    const s = getComputedStyle(e);
    const opaque = color => color !== 'transparent' && !/rgba\([^)]*,\s*0\)$/.test(color);
    return opaque(s.backgroundColor) || s.backgroundImage !== 'none'
      || ['Left','Right','Top','Bottom'].some(side =>
        parseFloat(s['border' + side + 'Width']) > 0 && opaque(s['border' + side + 'Color']));
  };
  const visible = (e, r) => {
    if (r.width <= 0 || r.height <= 0 || r.right <= 0 || r.left >= innerWidth
        || r.bottom <= 0 || r.top >= innerHeight) return false;
    for (let a = e; a; a = a.parentElement) {
      const s = getComputedStyle(a), b = a.getBoundingClientRect();
      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0'
          || s.clip === 'rect(0px, 0px, 0px, 0px)' || s.clipPath === 'inset(100%)') return false;
      if (['auto','scroll','hidden','clip'].includes(s.overflowY) && (r.bottom <= b.top || r.top >= b.bottom)) return false;
      if (['auto','scroll','hidden','clip'].includes(s.overflowX) && (r.right <= b.left || r.left >= b.right)) return false;
    }
    return true;
  };
  const excluded = e => {
    if (e.closest('input,select,textarea,option,.search,' + badges)) return true;
    const button = e.closest('button');
    return button && !button.matches(contentCards);
  };
  const panels = '.dashboard-card,.kpi,.settings-section,.settings-shortcuts button,.metric-chart,.comment-sync,.post-comment,.bubble,.workflow-panel,.reply-composer,.post-backfill,.post-toolbar,.post-date-filter,.key-overview > div,.brand-people article,.person-editor,.dm-backfill-status,.full-prompt,.prompt-history pre,.price-history,.price-result,.send-content,.send-warning,.legacy-note,.reader-heading,.info-heading,.classification-panel,.thread-tools,.sheet-heading,.sheet-content,.inbox-heading,.message-stream,.post-metrics,.post-intro,.post-comments,.sync-notice,.pagination,.receive-banner,.price-top,.price-form,.price-match,.export-status,.prompt-history,.price-history details,.price-result pre,.success-note,.error,.review-reason,.routing-table label,.sheet-source';
  const smalls = '.metric-grid > div,.ideation-chip,.ideation-platform,.report-status,.ideation-goal > h2';
  // 貼文清單內的日期篩選與清單卡片同一欄，使用清單內距。
  const lists = '.conversation,.post-card,.post-list .post-date-filter';
  for (const root of roots) {
    for (const e of [root, ...root.querySelectorAll('*')]) {
      if (e.matches(panels + ',.section-card,.workspace-group > summary,.workspace-group-content,.stat-tile,.list-row,.follower-panel,' + lists + ',' + smalls) && visible(e, e.getBoundingClientRect())) {
        // 表單內的透明日期列沿用外層內距；文字仍由下方通用檢查驗證。
        // 粉絲數列內嵌的發文日期是工具列的一段（UI規格例外），內距沿用外層面板。
        const s = getComputedStyle(e), kind = e.matches('.workspace-group') ? 'group-shell' : e.matches('.workspace-group > summary,.workspace-group-content') ? 'group-content' : e.matches('.notice,.error,.ideation-notice,.script-editor .legacy-note') ? 'notice' : e.matches('.ideation-comment-window,.workspace-subsection,.branding-settings,.post-toolbar,.pagination,.follower-panel .post-date-filter') ? 'inline'
          : e.matches('.stat-tile') ? 'stat' : e.matches('.list-row,.post-comment,.credential-field') ? 'common-row' : e.matches('.post-list .post-date-filter') ? 'date-row'
          : e.matches('.ideation-card') ? 'idea-card' : e.matches('.ideation-goal > h2') ? 'goal-title' : e.matches('.ideation-chip,.ideation-platform,.report-status') ? 'chip'
          : e.matches(smalls) ? 'small' : e.matches(lists) ? 'list' : 'panel';
        const expectedLeft = kind === 'group-shell' || kind === 'inline' ? 0 : kind === 'group-content' ? (innerWidth < 600 ? 16 : 24) : kind === 'notice' || kind === 'common-row' ? 16 : kind === 'date-row' ? 17 : kind === 'stat' ? 20 : kind === 'goal-title' ? 12 : kind === 'idea-card' ? 20 : kind === 'chip' ? 8 : kind === 'small' ? 12 : innerWidth < 600 ? 16 : kind === 'list' ? 20 : 24;
        const row = {element:describe(e),kind,left:parseFloat(s.paddingLeft),right:parseFloat(s.paddingRight)};
        containers.push(row);
        assertions += 2;
        for (const side of ['left','right']) {
          const expected = expectedLeft;
          if (Math.abs(row[side] - expected) > 1)
            failures.push(`${row.element}: ${side} padding ${row[side]} expected ${expected}`);
        }
      }
      if (excluded(e)) continue;
      for (const node of e.childNodes) {
        if (node.nodeType !== Node.TEXT_NODE || !node.textContent.trim()) continue;
        const range = document.createRange(); range.selectNodeContents(node);
        for (const text of range.getClientRects()) {
          if (!visible(e, text)) continue;
          let ancestor = e;
          while (ancestor && !painted(ancestor)) ancestor = ancestor.parentElement;
          if (!ancestor) continue;
          if (e instanceof SVGElement) {
            const svg = e.closest('svg'), box = svg?.getBoundingClientRect();
            assertions++;
            if (box && (text.left < box.left - 1 || text.right > box.right + 1))
              failures.push(`${describe(e)}: text clipped by SVG viewport`);
          }
          const textMinimum = ancestor.matches('.notice,.error,.list-box,.list-row,.credential-field,.post-comment,.ideation-notice,.script-editor .legacy-note,.ideation-post-preview,.ideation-preview-item') || ancestor.matches('.list-box th,.list-box td') ? 16 : ancestor.matches('.ideation-chip,.ideation-platform,.report-status') ? 8 : ancestor.matches('.stat-tile') ? 20 : ancestor.matches(smalls) ? 12 : minimum;
          const distance = text.left - ancestor.getBoundingClientRect().left;
          const row = {element:describe(e),text:node.textContent.trim().slice(0,90),container:describe(ancestor),distance:Math.round(distance * 100) / 100,minimum:textMinimum};
          rows.push(row); assertions++;
          if (distance < textMinimum - 0.01) {
            violations.push(row);
            failures.push(`${row.element}: text padding ${row.distance}px from ${row.container}, minimum ${textMinimum}`);
          }
        }
      }
    }
  }
  return {rows,containers,violations,failures,assertions};
}
