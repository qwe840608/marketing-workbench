() => {
  const rows = [], failures = [];
  const numeric = /^(?=.*\p{N})[\p{N},.%\p{Sc}]+$/u;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode, e = node.parentElement;
    const text = node.textContent.trim();
    if (!numeric.test(text) || e.closest('script,style,option')) continue;
    if (!e.getClientRects().length) continue;
    let hidden = false;
    for (let a = e; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.visibility === 'hidden' || s.opacity === '0' || s.display === 'none'
          || s.clip === 'rect(0px, 0px, 0px, 0px)' || s.clipPath === 'inset(100%)') hidden = true;
    }
    if (hidden) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    const tops = [];
    for (const r of range.getClientRects()) {
      if (r.width && r.height && !tops.some(top => Math.abs(top - r.top) <= 1)) tops.push(r.top);
    }
    const row = {element:e.tagName.toLowerCase() + '.' + e.className, text, lines:tops.length};
    rows.push(row);
    if (tops.length > 1) failures.push(`numeric text wraps: ${text} (${tops.length} lines)`);
  }
  return {rows, failures, assertions:rows.length};
}
