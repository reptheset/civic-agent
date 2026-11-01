"""Turns a live page into a compact, numbered description the LLM can act on."""
import re

OBSERVE_JS = r"""
() => {
  const isVisible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
           && r.right > 0 && r.bottom > 0;
  };
  const labelOf = el => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'button' || tag === 'a') return (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return l.innerText.trim(); }
    const wrap = el.closest('label'); if (wrap) return wrap.innerText.trim();
    if (el.placeholder) return el.placeholder;
    const td = el.closest('td'); if (td && td.previousElementSibling) return td.previousElementSibling.innerText.trim();
    return (el.value || el.name || '').trim();
  };
  document.querySelectorAll('[data-agent-id]').forEach(e => e.removeAttribute('data-agent-id'));
  const out = []; let i = 1;
  for (const el of document.querySelectorAll('input:not([type=hidden]), select, textarea, button, a[href], [role=button]')) {
    if (!isVisible(el)) continue;
    el.setAttribute('data-agent-id', String(i));
    const tag = el.tagName.toLowerCase();
    const item = { id: i, tag, type: tag === 'input' ? (el.type || 'text') : '', label: labelOf(el).slice(0, 120),
                   required: !!el.required || /\*\s*$/.test(labelOf(el)) };
    if (tag === 'select') {
      item.options = [...el.options].map(o => o.text.trim()).filter(t => t && !t.startsWith('--')).slice(0, 30);
      item.filled = el.selectedIndex > 0;
    } else if (el.type === 'checkbox' || el.type === 'radio') {
      item.checked = el.checked;
    } else if (el.type === 'file') {
      item.filled = el.files.length > 0;
    } else if (tag === 'input' || tag === 'textarea') {
      item.filled = el.value.trim().length > 0;
    }
    out.push(item); i++;
  }
  const texts = sel => [...document.querySelectorAll(sel)].filter(isVisible).map(e => e.innerText.trim()).filter(Boolean);
  return {
    url: location.href, title: document.title,
    headings: texts('h1,h2,h3').slice(0, 8),
    alerts: texts('[role=alert], .error, .err, .alert-danger').slice(0, 10),
    dialogs: texts('[role=dialog], [aria-modal=true]').map(t => t.slice(0, 200)),
    elements: out,
    text: (document.body ? document.body.innerText : '').slice(0, 4000),
  };
}
"""

INJECTION_PATTERNS = [re.compile(p, re.I) for p in [
    r"ignore (all |any )?(previous|prior|above|earlier) instructions",
    r"\b(ai|llm) (assistant|agent|model)s?\b",
    r"system (notice|prompt|message|instruction)",
    r"pre-?authori[sz]ed",
    r"\byou are now\b",
    r"disregard (the |your )?(rules|instructions)",
    r"https?://(?!localhost|127\.0\.0\.1)[^\s]+",
]]


def sanitize(text: str) -> tuple[str, list[str]]:
    """Remove sentences that look like instructions aimed at an AI agent."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    keep, flagged = [], []
    for p in parts:
        if not p.strip():
            continue
        (flagged if any(rx.search(p) for rx in INJECTION_PATTERNS) else keep).append(p.strip())
    return " ".join(keep)[:1500], flagged


async def observe(page) -> dict:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass
    for attempt in range(3):
        try:
            obs = await page.evaluate(OBSERVE_JS)
            break
        except Exception:
            if attempt == 2:
                raise
            await page.wait_for_timeout(1500)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass
    obs["text"], obs["injection_flags"] = sanitize(obs["text"])
    return obs
