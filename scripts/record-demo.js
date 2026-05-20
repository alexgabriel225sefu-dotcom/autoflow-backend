/**
 * Blueprint Studio — Demo Recording Script
 * ==========================================
 * Rulează cu: npx playwright@latest chromium scripts/record-demo.js
 * sau:        node scripts/record-demo.js  (dacă ai playwright instalat)
 *
 * Pornești screen record → rulezi scriptul → oprești screen record → bagi în HeyGen
 */

const { chromium } = require('playwright');

const SITE = 'https://aicashsystem.space';
const DEMO_INPUT = 'When someone messages on WhatsApp, use GPT-4 to reply automatically with info about our restaurant menu and prices.';

/* ── helpers ── */
const wait = ms => new Promise(r => setTimeout(r, ms));

async function typeSlowly(el, text, delayMs = 55) {
  for (const ch of text) {
    await el.type(ch, { delay: delayMs + Math.random() * 30 });
  }
}

async function smoothScroll(page, targetY, steps = 18) {
  const current = await page.evaluate(() => window.scrollY);
  const diff = targetY - current;
  for (let i = 1; i <= steps; i++) {
    await page.evaluate((y) => window.scrollTo(0, y), current + (diff * i) / steps);
    await wait(40);
  }
}

(async () => {
  const browser = await chromium.launch({
    headless: false,
    args: ['--start-maximized', '--disable-blink-features=AutomationControlled'],
  });

  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    locale: 'en-US',
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
  });

  const page = await ctx.newPage();

  /* ══════════════════════════════════════════════
     SCENA 1 — Google Search
  ══════════════════════════════════════════════ */
  console.log('🔍 Scena 1: Google search...');
  await page.goto('https://www.google.com', { waitUntil: 'networkidle' });
  await wait(1800);

  const searchBox = page.locator('textarea[name="q"], input[name="q"]').first();
  await searchBox.click();
  await wait(600);
  await typeSlowly(searchBox, 'how to make money online 2025', 70);
  await wait(900);
  await page.keyboard.press('Enter');
  await page.waitForLoadState('networkidle');
  await wait(2500);

  /* scroll un pic prin rezultate */
  await smoothScroll(page, 400);
  await wait(1200);
  await smoothScroll(page, 800);
  await wait(1000);
  await smoothScroll(page, 0);
  await wait(800);

  /* ══════════════════════════════════════════════
     SCENA 2 — A doua căutare mai specifică
  ══════════════════════════════════════════════ */
  console.log('🔍 Scena 2: A doua căutare...');
  await searchBox.fill('');
  await searchBox.click();
  await wait(400);

  // Caută direct în bara de adresă
  await page.goto('https://www.google.com/search?q=ai+automation+agency+make+money+make.com', { waitUntil: 'networkidle' });
  await wait(2200);
  await smoothScroll(page, 350);
  await wait(1500);

  /* ══════════════════════════════════════════════
     SCENA 3 — Navigare spre site
  ══════════════════════════════════════════════ */
  console.log('🌐 Scena 3: Navigare spre Blueprint Studio...');
  await page.goto(SITE, { waitUntil: 'networkidle' });
  await wait(2000);

  /* scroll lent prin landing page */
  await smoothScroll(page, 300);
  await wait(1000);
  await smoothScroll(page, 700);
  await wait(1200);
  await smoothScroll(page, 1200);
  await wait(1000);
  await smoothScroll(page, 1800);
  await wait(1500);
  await smoothScroll(page, 0);
  await wait(800);

  /* ══════════════════════════════════════════════
     SCENA 4 — Pagina /try (demo)
  ══════════════════════════════════════════════ */
  console.log('⚡ Scena 4: Blueprint Studio /try demo...');
  await page.goto(`${SITE}/try`, { waitUntil: 'networkidle' });
  await wait(2000);

  /* scroll ușor */
  await smoothScroll(page, 200);
  await wait(800);
  await smoothScroll(page, 0);
  await wait(600);

  /* click pe chip "WhatsApp AI Bot" */
  try {
    const chip = page.locator('.chip').first();
    await chip.click();
    await wait(1200);
  } catch (_) {}

  /* sau type manual în textarea */
  const ta = page.locator('#ta');
  await ta.click();
  await ta.fill('');
  await wait(500);
  await typeSlowly(ta, DEMO_INPUT, 45);
  await wait(1500);

  /* ══════════════════════════════════════════════
     SCENA 5 — Generate
  ══════════════════════════════════════════════ */
  console.log('🤖 Scena 5: Generate automation...');
  const btn = page.locator('#gen-btn');
  await btn.click();
  await wait(800);

  /* loading steps vizibile */
  await smoothScroll(page, 150);
  await wait(8000); // așteaptă răspunsul AI (~5-8 secunde)

  /* ══════════════════════════════════════════════
     SCENA 6 — Rezultate + locked blueprint
  ══════════════════════════════════════════════ */
  console.log('💰 Scena 6: Rezultate...');
  await smoothScroll(page, 0);
  await wait(1000);
  await smoothScroll(page, 400);
  await wait(1500);
  await smoothScroll(page, 800);
  await wait(1200);

  /* hover pe locked card */
  try {
    const locked = page.locator('#r-locked');
    await locked.hover();
    await wait(2000);
  } catch (_) {}

  /* scroll spre FOMO section */
  await smoothScroll(page, 1400);
  await wait(2000);

  /* ══════════════════════════════════════════════
     SCENA 7 — CTA final, freeze pe buton
  ══════════════════════════════════════════════ */
  console.log('🎯 Scena 7: CTA...');
  try {
    const cta = page.locator('.fomo-cta');
    await cta.scrollIntoViewIfNeeded();
    await wait(3000);
  } catch (_) {}

  await wait(2000);
  console.log('✅ Gata! Oprește screen recording-ul acum.');

  /* lasă browserul deschis 5 secunde apoi închide */
  await wait(5000);
  await browser.close();
})();
