// Headed browser verification for Feldexa-Web. Run from the workspace with node.
// Captures screenshots at several widths, measures real contrast per text element, exercises the
// keyboard skip link, and records network requests and console errors. Output: JSON + PNG files.
// Headed browser measurement for the Feldexa-Web evidence note. Host-local tooling, not a required
// check: it needs `playwright-core` and a Chromium binary, neither of which the repository installs.
//
//   CHROME_PATH=/path/to/chrome PW=/path/to/playwright-core node docs/verify/web_headed_evidence.js <out-dir>
//
// It writes one PNG per page and width plus `report.json` and prints a compact summary. It launches
// the browser headed (not headless) against the operator's display.

const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH;
const PW = process.env.PW;
if (!CHROME || !PW) {
  console.error('set CHROME_PATH to a Chromium binary and PW to the playwright-core package directory');
  process.exit(2);
}
const { chromium } = require(PW);
const OUT = process.argv[2] || 'web-evidence';
const URLS = {
  local: process.env.LOCAL_URL || 'http://127.0.0.1:8765/',
  live: process.env.LIVE_URL || 'https://feldexa.github.io/Feldexa-Web/',
};

fs.mkdirSync(OUT, { recursive: true });

function contrastFns() {
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lum = ({ r, g, b }) => {
    const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => { const la = lum(a), lb = lum(b); const hi = Math.max(la, lb), lo = Math.min(la, lb); return (hi + 0.05) / (lo + 0.05); };
  const blend = (fg, bg) => ({ r: Math.round(fg.r * fg.a + bg.r * (1 - fg.a)), g: Math.round(fg.g * fg.a + bg.g * (1 - fg.a)), b: Math.round(fg.b * fg.a + bg.b * (1 - fg.a)), a: 1 });
  return { parse, ratio, blend };
}

(async () => {
  const browser = await chromium.launch({ headless: false, executablePath: CHROME });
  const report = { generated: new Date().toISOString(), chrome: browser.version(), pages: {} };

  for (const [name, url] of Object.entries(URLS)) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const requests = [];
    const consoleErrors = [];
    page.on('request', (r) => requests.push(r.url()));
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message));
    await page.goto(url, { waitUntil: 'load' });

    const data = await page.evaluate(() => {
      const out = {};
      out.title = document.title;
      out.lang = document.documentElement.lang;
      out.metaViewport = document.querySelector('meta[name=viewport]')?.content || null;
      out.h1 = [...document.querySelectorAll('h1')].map((h) => h.textContent.trim());
      out.headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map((h) => h.tagName.toLowerCase() + ':' + h.textContent.trim().slice(0, 40));
      out.landmarks = [...document.querySelectorAll('main,header,footer,nav,aside')].map((e) => e.tagName.toLowerCase() + (e.getAttribute('aria-label') ? `[${e.getAttribute('aria-label')}]` : ''));
      out.navs = [...document.querySelectorAll('nav')].map((n) => n.getAttribute('aria-label'));
      out.skipLink = (() => {
        const first = document.querySelector('a');
        return first ? { href: first.getAttribute('href'), text: first.textContent.trim(), className: first.className } : null;
      })();
      out.scrollWidth = document.documentElement.scrollWidth;
      out.clientWidth = document.documentElement.clientWidth;
      return out;
    });

    // Focus the first focusable element via keyboard and record the skip link's box/style.
    await page.keyboard.press('Tab');
    const skipFocus = await page.evaluate(() => {
      const el = document.activeElement;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return {
        tag: el.tagName, text: el.textContent.trim(),
        rect: { top: Math.round(rect.top), left: Math.round(rect.left), width: Math.round(rect.width), height: Math.round(rect.height) },
        outlineWidth: style.outlineWidth, outlineStyle: style.outlineStyle, outlineColor: style.outlineColor,
      };
    });
    await page.screenshot({ path: path.join(OUT, `${name}-skip-focus.png`) });

    // Real measured contrast: every text-bearing element against its composited effective background.
    const contrasts = await page.evaluate(() => {
      const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
      const lum = ({ r, g, b }) => { const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
      const ratio = (a, b) => { const la = lum(a), lb = lum(b); const hi = Math.max(la, lb), lo = Math.min(la, lb); return (hi + 0.05) / (lo + 0.05); };
      const blend = (fg, bg) => ({ r: Math.round(fg.r * fg.a + bg.r * (1 - fg.a)), g: Math.round(fg.g * fg.a + bg.g * (1 - fg.a)), b: Math.round(fg.b * fg.a + bg.b * (1 - fg.a)), a: 1 });
      // The page draws a gradient on body; approximate its two stops as the surface candidates.
      const baseStops = [{ r: 247, g: 251, b: 251, a: 1 }, { r: 228, g: 241, b: 242, a: 1 }, { r: 255, g: 255, b: 255, a: 1 }];
      const results = [];
      for (const el of document.querySelectorAll('body *')) {
        const own = [...el.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim()).map((n) => n.textContent.trim());
        if (!own.length) continue;
        const style = getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') continue;
        const fg = parse(style.color);
        if (!fg) continue;
        // Composite ancestor backgrounds (only solid colours and alpha layers are measurable here).
        const layers = [];
        for (let node = el; node && node !== document.documentElement; node = node.parentElement) {
          const bg = parse(getComputedStyle(node).backgroundColor);
          if (bg && bg.a > 0) layers.push(bg);
        }
        const worst = { ratio: 99 };
        for (const base of baseStops) {
          let surface = base;
          for (const layer of layers.reverse()) surface = blend(layer, surface);
          const text = fg.a < 1 ? blend(fg, surface) : fg;
          const r = ratio(text, surface);
          if (r < worst.ratio) worst.ratio = r;
        }
        const fontSize = parseFloat(style.fontSize);
        const bold = parseInt(style.fontWeight, 10) >= 700;
        const large = fontSize >= 24 || (fontSize >= 18.66 && bold);
        results.push({ text: own.join(' ').slice(0, 50), fontSize, large, ratio: Number(worst.ratio.toFixed(2)) });
      }
      return results;
    });
    const failing = contrasts.filter((c) => c.ratio < (c.large ? 3 : 4.5));

    const widths = {};
    for (const width of [320, 390, 768, 1024, 1280, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.waitForTimeout(150);
      const m = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth }));
      widths[width] = { ...m, overflow: m.scrollWidth > m.clientWidth };
      // Viewport screenshot at the representative width; a tall viewport captures the whole page
      // without relying on fullPage, which the headed compositor refuses at this page height.
      await page.screenshot({ path: path.join(OUT, `${name}-${width}.png`) });
      if (width === 390 || width === 1280) {
        const pageHeight = await page.evaluate(() => document.documentElement.scrollHeight);
        await page.setViewportSize({ width, height: Math.min(pageHeight, 3400) });
        await page.waitForTimeout(200);
        await page.screenshot({ path: path.join(OUT, `${name}-${width}-full.png`) });
        await page.setViewportSize({ width, height: 900 });
        await page.waitForTimeout(100);
      }
    }

    report.pages[name] = {
      url, ...data, skipFocus, contrastSamples: contrasts.length,
      contrastFailing: failing, widths,
      requests, externalRequests: requests.filter((u) => !u.startsWith(url.slice(0, url.indexOf('/', 8)))),
      consoleErrors,
    };
    await page.close();
  }

  // Dark-mode rendering: the design is light-only, so record whether the UA dark scheme changes anything.
  const dark = await browser.newPage({ viewport: { width: 390, height: 844 }, colorScheme: 'dark' });
  await dark.goto(URLS.local, { waitUntil: 'load' });
  await dark.screenshot({ path: path.join(OUT, 'local-390-dark-preference.png') });
  report.darkPreference = await dark.evaluate(() => ({
    bodyBackground: getComputedStyle(document.body).backgroundImage,
    bodyColor: getComputedStyle(document.body).color,
    colorScheme: getComputedStyle(document.documentElement).colorScheme,
  }));
  await dark.close();

  await browser.close();
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ pages: Object.fromEntries(Object.entries(report.pages).map(([k, v]) => [k, {
    overflow: Object.entries(v.widths).filter(([, m]) => m.overflow).map(([w]) => w),
    contrastFailing: v.contrastFailing, externalRequests: v.externalRequests,
    consoleErrors: v.consoleErrors, skipFocus: v.skipFocus, headings: v.headings.length,
  }])), darkPreference: report.darkPreference }, null, 2));
})().catch((e) => { console.error('ERR', e.stack); process.exit(1); });
