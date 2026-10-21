() => {
    const rows = [], failures = [];
    let assertions = 0;
    const check = (pass, message) => { assertions++; if (!pass) failures.push(message); };
    const rendered = e => {
        const s = getComputedStyle(e), r = e.getBoundingClientRect();
        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0
            && !e.closest('details:not([open]) > :not(summary)');
    };
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 1;
    const context = canvas.getContext('2d', {willReadFrequently:true});
    const rgba = value => {
        context.clearRect(0,0,1,1); context.fillStyle = value; context.fillRect(0,0,1,1);
        return [...context.getImageData(0,0,1,1).data].map(v => v/255);
    };
    const luminance = rgb => rgb.slice(0,3).map(v => v <= .04045 ? v/12.92 : ((v+.055)/1.055)**2.4)
        .reduce((sum,n,i) => sum + n*[.2126,.7152,.0722][i],0);
    const contrast = (fg,bg) => {
        const a=luminance(fg), b=luminance(bg);
        return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
    };
    const token = name => {
        const probe=document.createElement('span'); probe.style.color=`var(${name})`;
        document.body.append(probe); const color=getComputedStyle(probe).color; probe.remove();
        return color;
    };
    const danger=token('--state-danger'), pending=token('--state-pending-text');
    const success=token('--state-success');
    const background = e => {
        for(let node=e;node;node=node.parentElement) {
            const bg=rgba(getComputedStyle(node).backgroundColor);
            if(bg[3] === 1) return bg;
        }
        return rgba(token('--bg-app'));
    };
    for (const e of document.querySelectorAll('body,h1,h2')) {
        const family=getComputedStyle(e).fontFamily;
        check(!family.split(',').some(f => /mincho|pmingliu|^serif/i.test(f.trim().replace(/^["']/,''))),
            `${e.tagName}: serif font ${family}`);
        rows.push({element:e.tagName,fontFamily:family});
    }
    const warning = '.send-unavailable,.send-warning,.state.pending,.priority-label,.legacy-note,.ideation-card > .review-reason';
    const error = '.error,.composer-error,.save-error,.review-reason,.composer-reasons,.draft-status.needs-edit,.receive-banner,.conversation-layout:has(.draft-status.needs-edit) .processing-flow li[aria-current=step]';
    for (const e of document.querySelectorAll(`${warning},${error},.jev-light.fail`)) {
        if(!rendered(e)) continue;
        const s=getComputedStyle(e), lamp=e.matches('.jev-light.fail');
        if (e.matches('.ideation-notice.warning,.ideation-page .script-editor .legacy-note')) {
            check(s.color === token('--text-subtle'), `${e.className}: notice text token`);
            check(s.backgroundColor === token('--bg-subtle'), `${e.className}: notice background token`);
            check(s.borderLeftColor === token('--state-pending') && s.borderLeftWidth === '3px',
                `${e.className}: warning must use amber border`);
            rows.push({element:e.className,color:s.color,semantic:'warning-border'});
            continue;
        }
        const color=lamp || e.matches('.receive-banner') ? s.backgroundColor : s.color;
        check([danger,pending].includes(color), `${e.className}: warning/error token ${color}`);
        check(color !== success, `${e.className}: warning/error became green`);
        if(e.matches(warning)) check(color === pending, `${e.className}: warning must use amber`);
        rows.push({element:e.className,color,semantic:'warning/error'});
    }
    const badges = '.state,.key-source,.readonly-label,.draft-status,.send-availability,.success-note,.error,.review-reason,.legacy-note,.priority-label,.composer-feedback,.receive-banner,.stage-tag,.processing-flow li b';
    for (const e of document.querySelectorAll(badges)) {
        if(!rendered(e) || e.matches(':disabled') || e.closest(':disabled')) continue;
        const s=getComputedStyle(e), bg=background(e), fg=rgba(s.color);
        const ratio=contrast(fg,bg);
        check(ratio >= 4.5, `${e.className}: status text contrast ${ratio.toFixed(3)} < 4.5`);
        rows.push({element:e.className,color:s.color,background:bg,ratio});
    }
    for(const e of document.querySelectorAll('.jev-light.pass,.jev-light.fail')) {
        if(!rendered(e)) continue;
        const s=getComputedStyle(e), color=s.backgroundColor;
        check(color === (e.matches('.fail') ? danger : success), `${e.className}: lamp token ${color}`);
        const ratio=contrast(rgba(color),background(e.parentElement));
        check(ratio >= 3, `${e.className}: lamp contrast ${ratio} < 3`);
        rows.push({element:e.className,color,ratio});
    }
    return {assertions,failures,rows};
}
