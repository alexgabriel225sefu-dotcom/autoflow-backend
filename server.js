const express = require('express');
const cors = require('cors');
const path = require('path');
const { createClient } = require('@supabase/supabase-js');
const Anthropic = require('@anthropic-ai/sdk');
const nodemailer = require('nodemailer');
const crypto = require('crypto');
const stripe = process.env.STRIPE_SECRET_KEY ? require('stripe')(process.env.STRIPE_SECRET_KEY) : null;
const DodoPayments = require('dodopayments');
const dodopayments = process.env.DODO_PAYMENTS_API_KEY ? new DodoPayments({
  bearerToken: process.env.DODO_PAYMENTS_API_KEY,
  webhookKey: process.env.DODO_PAYMENTS_WEBHOOK_KEY || undefined,
  environment: process.env.DODO_PAYMENTS_ENV === 'test' ? 'test_mode' : 'live_mode',
}) : null;

process.on('uncaughtException', err => console.error('UNCAUGHT EXCEPTION:', err.stack || err));
process.on('unhandledRejection', err => console.error('UNHANDLED REJECTION:', err));

const app = express();
app.set('trust proxy', 1);
const rateLimit = require('express-rate-limit');
app.use(cors({
  origin: ['https://aicashsystem.onrender.com', 'https://aicashsystem.space', 'https://www.aicashsystem.space'],
  credentials: true
}));
// Skip JSON body parsing for the Digistore24 webhook — it posts form-urlencoded.
// The Meta webhook needs the raw body preserved too (HMAC signature check in
// _metaVerifySignature can't hash a body that's already been re-serialized).
app.use((req, res, next) => {
  if (req.path === '/digistore24-webhook') return next();
  // Stripe needs the untouched raw body Buffer to verify its signature —
  // skip JSON parsing entirely here; the route below applies express.raw() itself.
  if (req.path === '/stripe-webhook') return next();
  // Same deal for Dodo Payments — its webhook signature is computed over the raw body.
  if (req.path === '/dodo-webhook') return next();
  if (req.path === '/webhooks/meta') {
    return express.json({ verify: (req2, res2, buf) => { req2.rawBody = buf; } })(req, res, next);
  }
  express.json()(req, res, next);
});
// Serve static assets (JS, CSS, images) but NOT HTML — HTML goes through route handlers
const _serveStatic = express.static(path.join(__dirname, 'public'), { index: false });
app.use((req, res, next) => {
  if (/\.html?$/i.test(req.path)) return next();
  _serveStatic(req, res, next);
});

// /health — DB ping to keep Supabase free tier from pausing (use for cron-job.org)
app.get('/health', async (req, res) => {
  let db = 'skip';
  if (supabase) {
    try {
      await supabase.from('licenses').select('*', { count: 'exact', head: true });
      db = 'ok';
    } catch(e) { db = 'error'; }
  }
  res.json({ ok: true, db, node: process.version, time: new Date().toISOString() });
});
app.get('/ping', (req, res) => res.json({ ok: true, version: 'v9-chat-fix', time: new Date().toISOString() }));

// /api/health — production readiness check. Reports true/false per integration.
// Never exposes secret values — only whether each required env var is present.
app.get('/api/health', async (req, res) => {
  const has = (v) => !!(process.env[v] && String(process.env[v]).trim());
  // Email is ready if ANY delivery path is fully configured.
  const emailReady =
    (has('RESEND_API_KEY') && has('RESEND_FROM')) ||
    has('BREVO_API_KEY') ||
    (has('BREVO_SMTP_USER') && has('BREVO_SMTP_PASS')) ||
    (has('GMAIL_USER') && has('GMAIL_APP_PASSWORD'));

  let dbConnect = false;
  if (supabase) {
    try { await supabase.from('licenses').select('*', { count: 'exact', head: true }); dbConnect = true; }
    catch (e) { dbConnect = false; }
  }

  const checks = {
    // CRITICAL — purchase → license → email flow cannot work without these
    digistore24_ipn_passphrase: has('DIGISTORE24_IPN_PASSPHRASE'),
    license_signing_key:  has('BOT_EMAIL_SECRET'),
    supabase_url:         has('SUPABASE_URL'),
    supabase_key:         has('SUPABASE_SERVICE_KEY'),
    supabase_connects:    dbConnect,
    email_delivery:       emailReady,
    // RECOMMENDED — degraded experience if missing, but sale still completes
    ai_fallback:          has('GROQ_API_KEY') || has('ANTHROPIC_API_KEY') || has('GOOGLE_AI_API_KEY'),
    affiliate_bot:        has('AFFILIATE_BOT_TOKEN'),
    dodo_payments_api_key:     has('DODO_PAYMENTS_API_KEY'),
    dodo_payments_webhook_key: has('DODO_PAYMENTS_WEBHOOK_KEY'),
    stripe_secret_key:         has('STRIPE_SECRET_KEY'),
    stripe_webhook_secret:     has('STRIPE_WEBHOOK_SECRET'),
    session_secrets:      has('JWT_SECRET') && has('COOKIE_SECRET'),
  };

  const critical = ['digistore24_ipn_passphrase','license_signing_key','supabase_url','supabase_key','supabase_connects','email_delivery'];
  const missing = critical.filter(k => !checks[k]);
  const saleReady = missing.length === 0;

  res.status(saleReady ? 200 : 503).json({
    sale_ready: saleReady,
    missing_critical: missing,
    checks,
    env: process.env.NODE_ENV || 'unknown',
    time: new Date().toISOString(),
  });
});

// ── SETUP CHAT (early registration — must come before any catch-all) ──────────
const _setupChatLimiter = rateLimit({ windowMs: 60*1000, max: 15, standardHeaders: true, legacyHeaders: false,
  message: { error: 'Too many messages — please wait a minute.' } });

const SETUP_SYSTEM = `You are a concise support assistant for Apex Trade Bot — a crypto trading bot deployed on Railway.
Help users set up their bot. Be short and direct (2-4 sentences max). No markdown headers. Use plain text.
IMPORTANT: Always reply in the SAME language the user wrote in. If they write in English, reply in English. If Romanian, reply in Romanian. If Spanish, reply in Spanish. Detect the language automatically.

SETUP STEPS:
1. Railway → New Project → New Service → Docker Image → paste: ghcr.io/alexgabriel225sefu-dotcom/apex-crypto:latest
2. Add 2 Variables: LICENSE_KEY (from their email) and GROQ_API_KEY (free from console.groq.com → API Keys)
3. Go to aicashsystem.space/configurator → enter license key + Groq key + exchange → Save Config
4. Set up Telegram (optional): @BotFather for token, @userinfobot for chat ID → add TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to Railway → send /resume

COMMON ERRORS:
- "Invalid license key" → They must go to the configurator (aicashsystem.space/configurator) and save settings first, then restart Railway.
- "No AI key found" → Add GROQ_API_KEY to Railway Variables. Get it free at console.groq.com.
- "No exchange API key" → Bot auto-switches to Paper Trading (safe, no real funds). Normal for first setup.
- "Bot is paused" → Needs Telegram /resume command. Set up Telegram first.
- Bot restarting in loop → Normal during first deploy. Stabilizes in 1-2 min after variables are added.

BINANCE API: Profile → API Management → Create API → enable Spot Trading only, Withdrawals OFF.
GROQ: console.groq.com → Sign up free → API Keys → Create Key. No credit card.
PAPER TRADING: Simulated mode, no real funds. Safe to test. Switch to live via configurator.
SUPPORT EMAIL: supportaicashsystem@gmail.com`;

app.post('/api/setup-chat', _setupChatLimiter, async (req, res) => {
  const { message, history = [] } = req.body || {};
  if (!message || typeof message !== 'string' || message.length > 500)
    return res.status(400).json({ error: 'Invalid message.' });

  // Smart static fallback — always available regardless of AI keys
  // Detects language (EN/RO) and responds accordingly
  function staticFallback(msg) {
    const m = msg.toLowerCase();
    const isEN = /\b(the|is|are|do|can|how|what|where|when|why|i|you|my|your|help|please|and|or|not|have|get|set|need|want|does)\b/.test(m);
    const T = (ro, en) => isEN ? en : ro;

    if (m.includes('license') || m.includes('licenta') || m.includes('cheie') || (m.includes('key') && !m.includes('api key') && !m.includes('groq') && !m.includes('binance')))
      return T('LICENSE_KEY-ul l-ai primit pe email dupa cumparare. Daca nu l-ai primit, verifica Spam sau scrie la supportaicashsystem@gmail.com.', 'Your LICENSE_KEY was sent by email after purchase. If you didn\'t receive it, check your Spam folder or email supportaicashsystem@gmail.com.');
    if (m.includes('groq') || m.includes('llama') || m.includes('ai key'))
      return T('GROQ_API_KEY e gratuit: console.groq.com → Sign up → API Keys → Create. Nu necesita card bancar.', 'GROQ_API_KEY is free: go to console.groq.com → Sign up → API Keys → Create a new key. No credit card needed.');
    if (m.includes('paused') || m.includes('pause') || m.includes('pornit') || m.includes('resume') || m.includes('start the bot'))
      return T('Botul porneste in modul PAUSED. Trimite /resume pe Telegram dupa ce ai configurat TELEGRAM_BOT_TOKEN si TELEGRAM_CHAT_ID in Railway.', 'The bot starts in PAUSED mode for safety. Send /resume on Telegram after setting TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Railway Variables.');
    if (m.includes('invalid') || m.includes('403') || m.includes('license error'))
      return T('Mergi la aicashsystem.space/configurator, introdu LICENSE_KEY-ul si apasa Save Config. Dupa, reporneste in Railway.', 'Go to aicashsystem.space/configurator, enter your LICENSE_KEY and click Save Config. Then restart the Railway service.');
    if (m.includes('telegram') || m.includes('botfather') || m.includes('bot token'))
      return T('Setup Telegram: 1) @BotFather → /newbot → copiaza tokenul. 2) @userinfobot → copiaza ID-ul. 3) Adauga TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in Railway Variables.', 'Telegram setup: 1) @BotFather → /newbot → copy the token. 2) @userinfobot → copy your ID. 3) Add TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in Railway Variables.');
    if (m.includes('binance') || m.includes('exchange') || m.includes('api key') || m.includes('trading key'))
      return T('Binance: Profile → API Management → Create API → activeaza Spot Trading, dezactiveaza Withdrawals. Adauga BINANCE_API_KEY + BINANCE_SECRET in Railway.', 'Binance: Profile → API Management → Create API → enable Spot Trading only, disable Withdrawals. Add BINANCE_API_KEY + BINANCE_SECRET in Railway Variables.');
    if (m.includes('paper') || m.includes('bani reali') || m.includes('real money') || m.includes('live trading'))
      return T('Fara cheia Binance, botul ruleaza in Paper Trading (bani virtuali, zero risc). Ca sa treci pe live, adauga cheile Binance in Railway.', 'Without a Binance key, the bot runs in Paper Trading mode (simulated funds, zero risk). To go live, add your Binance keys in Railway Variables.');
    if (m.includes('railway') || m.includes('deploy') || m.includes('docker') || m.includes('image'))
      return T('Railway: New Project → New Service → Docker Image → lipeste: ghcr.io/alexgabriel225sefu-dotcom/apex-crypto:latest → Deploy. Adauga LICENSE_KEY si GROQ_API_KEY in Variables.', 'Railway: New Project → New Service → Docker Image → paste: ghcr.io/alexgabriel225sefu-dotcom/apex-crypto:latest → Deploy. Add LICENSE_KEY and GROQ_API_KEY in Variables.');
    if (m.includes('crash') || m.includes('restart') || m.includes('loop') || m.includes('eroare') || m.includes('error'))
      return T('Daca botul tot restarteaza: 1) Verifica LICENSE_KEY. 2) Adauga GROQ_API_KEY in Railway. 3) Asteapta 2 minute — primele deploy-uri pot restart de 2-3 ori.', 'If the bot keeps restarting: 1) Check LICENSE_KEY is correct. 2) Add GROQ_API_KEY in Railway Variables. 3) Wait 2 minutes — first deploys can restart 2-3 times.');
    if (m.includes('hello') || m.includes('hi') || m.includes('hey') || m.includes('salut') || m.includes('buna') || m.includes('help'))
      return T('Salut! Sunt asistentul Apex Trade Bot. Te pot ajuta cu: Railway setup, Telegram, erori, chei API. Ce problema ai?', 'Hi! I\'m the Apex Trade Bot assistant. I can help with: Railway setup, Telegram config, errors, API keys. What\'s your issue?');
    if (m.includes('support') || m.includes('contact') || m.includes('email') || m.includes('suport'))
      return T('Suport direct: supportaicashsystem@gmail.com. Include screenshot-uri cu erorile din Railway Logs.', 'Direct support: supportaicashsystem@gmail.com. Include screenshots of the errors from Railway Logs.');
    if (m.includes('english') || m.includes('engleza') || m.includes('language') || m.includes('limba'))
      return 'Yes, I speak English too! Ask me anything about the bot setup — Railway, Telegram, license key, Binance API, errors.';
    return T('Pentru aceasta intrebare, contacteaza supportaicashsystem@gmail.com. Pot ajuta cu: Railway, Telegram, license key, Groq API, Binance.', 'For this question, contact supportaicashsystem@gmail.com. I can help with: Railway, Telegram, license key, Groq API, Binance setup.');
  }

  try {
    const ANTHROPIC_KEY_LOCAL = process.env.ANTHROPIC_API_KEY;
    if (ANTHROPIC_KEY_LOCAL) {
      const client = new Anthropic({ apiKey: ANTHROPIC_KEY_LOCAL });
      const msgs = [...history.slice(-6), { role: 'user', content: message }];
      const resp = await client.messages.create({
        model: 'claude-haiku-4-5-20251001', max_tokens: 300,
        system: SETUP_SYSTEM, messages: msgs
      });
      return res.json({ reply: resp.content[0]?.text || staticFallback(message) });
    }
    const groqKey = process.env.GROQ_API_KEY;
    if (groqKey) {
      const msgs = [{ role:'system', content: SETUP_SYSTEM },
        ...history.slice(-6), { role:'user', content: message }];
      const gr = await fetch('https://api.groq.com/openai/v1/chat/completions', {
        method: 'POST', headers: { 'Authorization': `Bearer ${groqKey}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: 'llama-3.1-8b-instant', messages: msgs, max_tokens: 300 })
      });
      const gd = await gr.json();
      const reply = gd.choices?.[0]?.message?.content;
      if (reply) return res.json({ reply });
    }
    return res.json({ reply: staticFallback(message) });
  } catch(e) {
    console.error('[SETUP-CHAT] error:', e.message);
    return res.json({ reply: staticFallback(message) });
  }
});
app.get('/api/app-status', auth, (req, res) => res.json({
  ai_openai:       !!process.env.OPENAI_API_KEY,
  ai_anthropic:    !!process.env.ANTHROPIC_API_KEY,
  ai_works:        !!(process.env.OPENAI_API_KEY || process.env.ANTHROPIC_API_KEY),
  email_works:     !!(process.env.BREVO_API_KEY || (process.env.BREVO_SMTP_USER && process.env.BREVO_SMTP_PASS)),
  digistore24_ipn: !!process.env.DIGISTORE24_IPN_PASSPHRASE,
  supabase:        !!process.env.SUPABASE_URL,
  verdict: !!(process.env.OPENAI_API_KEY || process.env.ANTHROPIC_API_KEY) ? '✅ Aplicatia functioneaza complet' : '❌ Lipseste cheia AI — Wizard/Chat/Email nu merg'
}));
app.get('/api/email-config', auth, (req, res) => res.json({
  brevo_api_key:  !!process.env.BREVO_API_KEY,
  brevo_smtp_user: !!process.env.BREVO_SMTP_USER,
  brevo_smtp_pass: !!process.env.BREVO_SMTP_PASS,
  sender_email:   !!process.env.SENDER_EMAIL,
  supabase:       !!process.env.SUPABASE_URL,
  email_will_send: !!(process.env.BREVO_API_KEY || (process.env.BREVO_SMTP_USER && process.env.BREVO_SMTP_PASS)),
}));

// ── ENV VARIABLES ──
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_KEY;
const ANTHROPIC_KEY = process.env.ANTHROPIC_API_KEY;
const OPENAI_KEY = process.env.OPENAI_API_KEY;
const HEYGEN_KEY = process.env.HEYGEN_API_KEY;
const CREATIFY_API_ID  = process.env.CREATIFY_API_ID  || '';
const CREATIFY_API_KEY = process.env.CREATIFY_API_KEY || '';
const JWT_SECRET = process.env.JWT_SECRET || (() => {
  const fallback = require('crypto').randomBytes(32).toString('hex');
  console.warn('[WARN] JWT_SECRET not set — generated random secret for this session. Sessions will reset on restart. Set JWT_SECRET in Render env vars.');
  return fallback;
})();
const COOKIE_SECRET = process.env.COOKIE_SECRET || JWT_SECRET + '-cookie';
const BREVO_API_KEY = process.env.BREVO_API_KEY;
const RESEND_API_KEY = process.env.RESEND_API_KEY;
const SENDER_EMAIL = process.env.SENDER_EMAIL || process.env.BREVO_SMTP_USER || 'supportaicashsystem@gmail.com';
const SENDER_NAME  = process.env.SENDER_NAME  || 'AI Cash Systems';

// ── UNIVERSAL EMAIL SENDER ──────────────────────────────────
// Priority: Resend → Brevo API → SMTP transporter
async function _sendEmail({ to, subject, html, fromName }) {
  const from = fromName || SENDER_NAME;
  const sender = SENDER_EMAIL;

  // 1. Resend (fastest, works immediately)
  if (RESEND_API_KEY) {
    // RESEND_FROM must be set to a verified Resend sender, e.g. "Apex Bot <bot@aicashsystem.space>"
    // Without it, emails may be blocked. Set RESEND_FROM in Render env vars.
    const resendFrom = process.env.RESEND_FROM;
    if (!resendFrom) { console.warn('[WARN] RESEND_FROM not set — Resend will likely reject the send. Set it to a verified sender.'); }
    try {
      const r = await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${RESEND_API_KEY}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ from: resendFrom, to: [to], subject, html }),
        signal: AbortSignal.timeout(12000),
      });
      if (r.ok) { addLog(`Email sent via Resend to ${to}`, 'email', 'success'); return { ok: true, method: 'resend' }; }
      const err = await r.text(); throw new Error(err);
    } catch(e) { console.error('Resend error:', e.message); }
  }

  // 2. Brevo API
  if (BREVO_API_KEY) {
    try {
      const r = await fetch('https://api.brevo.com/v3/smtp/email', {
        method: 'POST',
        headers: { 'api-key': BREVO_API_KEY, 'Content-Type': 'application/json' },
        body: JSON.stringify({ sender: { name: from, email: sender }, to: [{ email: to }], subject, htmlContent: html }),
        signal: AbortSignal.timeout(12000),
      });
      if (r.ok) { addLog(`Email sent via Brevo to ${to}`, 'email', 'success'); return { ok: true, method: 'brevo' }; }
      const err = await r.text(); throw new Error(err);
    } catch(e) { console.error('Brevo API error:', e.message); }
  }

  // 3. SMTP fallback (Brevo SMTP or Gmail)
  if (transporter) {
    try {
      const smtpFrom = (GMAIL_USER && GMAIL_PASS) ? `"${from}" <${GMAIL_USER}>` : `"${from}" <${sender}>`;
      await Promise.race([
        transporter.sendMail({ from: smtpFrom, to, subject, html }),
        new Promise((_, rej) => setTimeout(() => rej(new Error('SMTP timeout')), 15000)),
      ]);
      addLog(`Email sent via SMTP to ${to}`, 'email', 'success');
      return { ok: true, method: 'smtp' };
    } catch(e) { console.error('SMTP error:', e.message); return { ok: false, error: e.message }; }
  }

  return { ok: false, error: 'No email provider configured' };
}

// ── GLOBAL HTML ESCAPE HELPER ──
const _he = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

// ── COURSE ACCESS COOKIE HELPERS ──
function _parseCookies(req) {
  const out = {};
  (req.headers.cookie || '').split(';').forEach(p => {
    const [k, ...v] = p.trim().split('=');
    if (k) out[k.trim()] = decodeURIComponent(v.join('='));
  });
  return out;
}
function _signAccess(plan) {
  const sig = crypto.createHmac('sha256', COOKIE_SECRET).update(plan).digest('hex');
  return plan + '.' + sig;
}
function _verifyAccess(signed) {
  if (!signed || !signed.includes('.')) return null;
  const dot = signed.lastIndexOf('.');
  const plan = signed.slice(0, dot);
  const sig = signed.slice(dot + 1);
  const expected = crypto.createHmac('sha256', COOKIE_SECRET).update(plan).digest('hex');
  try {
    if (!crypto.timingSafeEqual(Buffer.from(sig, 'hex'), Buffer.from(expected, 'hex'))) return null;
  } catch { return null; }
  return plan;
}
function requireCourse(minPlan) {
  return (req, res, next) => {
    const cookies = _parseCookies(req);
    const plan = _verifyAccess(cookies.af_access || '');
    if (!plan) return res.redirect('/access.html');
    if (minPlan === 'pro' && plan !== 'pro') return res.redirect('/access.html');
    next();
  };
}

// ── CLIENTS (wrapped in try-catch so a bad key never crashes the server) ──
let supabase = null;
try { if (SUPABASE_URL && SUPABASE_KEY) supabase = createClient(SUPABASE_URL, SUPABASE_KEY); } catch(e) { console.error('Supabase init error:', e.message); }

let anthropic = null;
try { if (ANTHROPIC_KEY) anthropic = new Anthropic({ apiKey: ANTHROPIC_KEY }); } catch(e) { console.error('Anthropic init error:', e.message); }

// ── SMTP TRANSPORTER (Brevo → Gmail fallback) ──
const BREVO_USER = process.env.BREVO_SMTP_USER;
const BREVO_PASS = process.env.BREVO_SMTP_PASS;
const GMAIL_USER = process.env.GMAIL_USER;
const GMAIL_PASS = process.env.GMAIL_APP_PASSWORD;
let transporter = null;
try {
  if (BREVO_USER && BREVO_PASS) {
    transporter = nodemailer.createTransport({ host: 'smtp-relay.brevo.com', port: 587, secure: false, auth: { user: BREVO_USER, pass: BREVO_PASS } });
  } else if (GMAIL_USER && GMAIL_PASS) {
    transporter = nodemailer.createTransport({ service: 'gmail', auth: { user: GMAIL_USER, pass: GMAIL_PASS } });
    console.log('[EMAIL] Gmail SMTP transporter initialized');
  }
} catch(e) { console.error('Nodemailer init error:', e.message); }

// ── RECENT CLICK DEDUPE (ref|ip → ts) — collapse refreshes within 30 min so a
// single visitor reloading the page doesn't inflate an affiliate's click count. ──
const _recentClicks = new Map();
const _CLICK_DEDUPE_MS = 30 * 60 * 1000;

// ── IN-MEMORY LOGS ──
const logs = [];
function addLog(msg, type = 'info', status = 'success') {
  logs.unshift({ msg, type, status, time: new Date().toISOString() });
  if (logs.length > 200) logs.pop();
}

// ── SIGNED TOKEN ──
function createToken(user) {
  const payload = JSON.stringify({ id: user.id, email: user.email, exp: Date.now() + 30*24*60*60*1000 });
  const sig = crypto.createHmac('sha256', JWT_SECRET).update(payload).digest('hex').slice(0, 32);
  return Buffer.from(payload).toString('base64') + '.' + sig;
}
function verifyToken(token) {
  try {
    if (!token || !token.includes('.')) return null;
    const dot = token.lastIndexOf('.');
    const b64 = token.slice(0, dot);
    const sig = token.slice(dot + 1);
    const raw = Buffer.from(b64, 'base64').toString('utf8');
    const check = crypto.createHmac('sha256', JWT_SECRET).update(raw).digest('hex').slice(0, 32);
    try { if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(check))) return null; } catch { return null; }
    const payload = JSON.parse(raw);
    if (payload.exp && payload.exp < Date.now()) return null;
    return payload;
  } catch(e) { return null; }
}

// ── AUTH MIDDLEWARE ──
function auth(req, res, next) {
  const header = req.headers.authorization;
  if (!header) return res.status(401).json({ error: 'No token' });
  const token = header.replace('Bearer ', '');
  const payload = verifyToken(token);
  if (!payload) return res.status(401).json({ error: 'Invalid token' });
  req.user = payload;
  next();
}

// ── RATE LIMITERS ──
const _authLimiter    = rateLimit({ windowMs: 15*60*1000, max: 10, standardHeaders: true, legacyHeaders: false,
  message: { error: 'Too many attempts. Try again in 15 minutes.' } });
const _codeLimiter    = rateLimit({ windowMs: 15*60*1000, max: 30, standardHeaders: true, legacyHeaders: false,
  message: { error: 'Too many code attempts. Try again in 15 minutes.' } });
const _aiLimiter      = rateLimit({ windowMs: 60*1000, max: 5, standardHeaders: true, legacyHeaders: false,
  message: { error: 'Too many AI requests. Slow down.' } });
const _emailLimiter   = rateLimit({ windowMs: 15*60*1000, max: 10, standardHeaders: true, legacyHeaders: false,
  message: { error: 'Too many email requests. Try again later.' } });
const _webhookLimiter = rateLimit({ windowMs: 60*1000, max: 30, standardHeaders: true, legacyHeaders: false,
  message: { error: 'Too many webhook requests.' } });
const _paymentLimiter = rateLimit({ windowMs: 15*60*1000, max: 8, standardHeaders: true, legacyHeaders: false,
  message: { error: 'Too many payment requests — please wait a few minutes.' } });
const _licenseLimiter = rateLimit({ windowMs: 60*1000, max: 10, standardHeaders: true, legacyHeaders: false,
  message: { error: 'Too many license checks — please slow down.' } });

// ════════════════════════════════════════
// AUTH ROUTES
// ════════════════════════════════════════

const ADMIN_EMAIL = (process.env.ADMIN_EMAIL || '').toLowerCase();
const ADMIN_CODE  = process.env.ADMIN_CODE  || '';
const COURSE_BYPASS_CODE = process.env.COURSE_BYPASS_CODE || '';
if (!ADMIN_EMAIL || !ADMIN_CODE) console.warn('[WARN] ADMIN_EMAIL or ADMIN_CODE env var not set — admin login disabled');

// POST /api/auth/login
app.post('/api/auth/login', _authLimiter, async (req, res) => {
  const { email, code } = req.body;
  if (!email || !code) return res.status(400).json({ error: 'Email and code required' });

  try {
    if (supabase) {
      // Check users table first (manually created accounts)
      const { data: userData } = await supabase
        .from('users')
        .select('*')
        .eq('email', email.toLowerCase())
        .eq('code', code.toUpperCase())
        .single();

      if (userData) {
        const token = createToken(userData);
        addLog(`User logged in: ${email}`, 'auth', 'success');
        return res.json({ token, user: { id: userData.id, email: userData.email, name: userData.name || email.split('@')[0], plan: userData.plan || 'pro' } });
      }

      // Also check purchases table (course buyers logging into the app)
      const { data: purchaseData } = await supabase
        .from('purchases')
        .select('*')
        .eq('email', email.toLowerCase())
        .eq('code', code.toUpperCase())
        .single();

      if (purchaseData) {
        const token = createToken(purchaseData);
        addLog(`Buyer logged in: ${email}`, 'auth', 'success');
        return res.json({ token, user: { id: purchaseData.id || purchaseData.email, email: purchaseData.email, name: email.split('@')[0], plan: purchaseData.plan || 'starter' } });
      }
    }

    // Fallback hardcoded admin access
    if (email.toLowerCase() === ADMIN_EMAIL && code.toUpperCase() === ADMIN_CODE.toUpperCase()) {
      const user = { id: 'admin', email: email.toLowerCase(), name: 'Admin', plan: 'pro' };
      const token = createToken(user);
      addLog(`Admin logged in: ${email}`, 'auth', 'success');
      return res.json({ token, user });
    }

    addLog(`Failed login attempt: ${email}`, 'auth', 'error');
    return res.status(401).json({ error: 'Invalid email or access code.' });
  } catch (e) {
    console.error('Login error:', e);
    return res.status(500).json({ error: 'Server error. Please try again.' });
  }
});

// POST /api/auth/create-user (admin only)
app.post('/api/auth/create-user', auth, _authLimiter, async (req, res) => {
  if (req.user.email !== ADMIN_EMAIL) return res.status(403).json({ error: 'Forbidden' });
  const { email, name, plan } = req.body;
  if (!email) return res.status(400).json({ error: 'Email required' });
  const code = crypto.randomBytes(4).toString('hex').toUpperCase();
  try {
    if (supabase) {
      const { data, error } = await supabase.from('users').insert([{ email: email.toLowerCase(), name, code, plan: plan || 'starter' }]).select().single();
      if (error) return res.status(400).json({ error: 'Could not create user' });
      addLog(`New user created: ${email}`, 'auth', 'success');
      return res.json({ success: true, email, code, plan: plan || 'starter' });
    }
    res.json({ success: true, email, code, plan: plan || 'starter' });
  } catch (e) {
    res.status(500).json({ error: 'Failed to create user' });
  }
});

// ════════════════════════════════════════
// AI ROUTES
// ════════════════════════════════════════

// POST /api/ai/generate — single prompt generation
app.post('/api/ai/generate', auth, _aiLimiter, async (req, res) => {
  const { prompt, jsonMode } = req.body;
  if (!prompt) return res.status(400).json({ error: 'Prompt required' });

  try {
    // Try OpenAI first
    if (OPENAI_KEY) {
      const body = {
        model: 'gpt-4o',
        max_tokens: 2000,
        messages: [{ role: 'user', content: prompt }]
      };
      if (jsonMode) body.response_format = { type: 'json_object' };
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 30000);
      try {
        const response = await fetch('https://api.openai.com/v1/chat/completions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + OPENAI_KEY },
          body: JSON.stringify(body),
          signal: controller.signal
        });
        clearTimeout(timeout);
        const data = await response.json();
        if (data.choices && data.choices[0]) {
          const output = data.choices[0].message.content;
          addLog('AI generation completed', 'ai', 'success');
          return res.json({ output });
        }
        console.error('OpenAI unexpected response:', JSON.stringify(data).slice(0, 200));
      } catch (fetchErr) {
        clearTimeout(timeout);
        if (fetchErr.name === 'AbortError') console.error('OpenAI request timed out after 30s');
        else console.error('OpenAI fetch error:', fetchErr.message);
      }
    }

    // Try Anthropic Claude
    if (anthropic) {
      const anthropicTimeout = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('Anthropic timeout')), 28000)
      );
      const anthropicCall = anthropic.messages.create({
        model: 'claude-sonnet-4-6',
        max_tokens: 2000,
        messages: [{ role: 'user', content: prompt }]
      });
      const msg = await Promise.race([anthropicCall, anthropicTimeout]);
      const output = msg.content[0].text;
      addLog('AI generation completed (Claude)', 'ai', 'success');
      return res.json({ output });
    }

    return res.status(500).json({ error: 'No AI provider configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY in Render environment variables.' });
  } catch (e) {
    console.error('AI generate error:', e);
    addLog('AI generation failed: ' + e.message, 'ai', 'error');
    res.status(500).json({ error: 'AI generation failed. Please try again.' });
  }
});

// ════════════════════════════════════════
// AUTOMATION ENGINE
// ════════════════════════════════════════

// Persistent store — file-based fallback so automations survive Render restarts
const fs = require('fs');
const STORE_FILE = path.join(__dirname, 'data', 'automations.json');
const automationStore = new Map();

function loadStore() {
  try {
    if (!fs.existsSync(path.join(__dirname, 'data'))) fs.mkdirSync(path.join(__dirname, 'data'));
    if (fs.existsSync(STORE_FILE)) {
      const items = JSON.parse(fs.readFileSync(STORE_FILE, 'utf8'));
      items.forEach(a => automationStore.set(a.webhook_id, a));
      console.log(`Loaded ${items.length} automations from disk`);
    }
  } catch(e) { console.error('Store load error:', e.message); }
}

function saveStore() {
  if (!fs.existsSync(path.join(__dirname, 'data'))) {
    try { fs.mkdirSync(path.join(__dirname, 'data')); } catch(e) {}
  }
  fs.promises.writeFile(STORE_FILE, JSON.stringify([...automationStore.values()]), 'utf8')
    .catch(e => console.error('Store save error:', e.message));
}

loadStore();

async function callAI(systemPrompt, userMessage) {
  const today = new Date().toLocaleDateString('en-GB', { weekday:'long', year:'numeric', month:'long', day:'numeric' });
  const fullSystem = `${systemPrompt}\n\nToday's date is: ${today}.`;
  if (OPENAI_KEY) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 28000);
    try {
      const r = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + OPENAI_KEY },
        body: JSON.stringify({ model: 'gpt-4o', max_tokens: 600,
          messages: [{ role: 'system', content: fullSystem }, { role: 'user', content: userMessage }] }),
        signal: controller.signal
      });
      clearTimeout(timeoutId);
      const d = await r.json();
      if (d.choices && d.choices[0]) return d.choices[0].message.content;
    } catch(e) {
      clearTimeout(timeoutId);
      throw e;
    }
  }
  if (anthropic) {
    const msg = await Promise.race([
      anthropic.messages.create({ model: 'claude-sonnet-4-6', max_tokens: 600,
        system: fullSystem, messages: [{ role: 'user', content: userMessage }] }),
      new Promise((_, reject) => setTimeout(() => reject(new Error('Anthropic timeout')), 28000))
    ]);
    return msg.content[0].text;
  }
  throw new Error('No AI provider configured');
}



async function sendNotifyEmail(to, automationName, userMsg, aiMsg) {
  const subject = `New message — ${_he(automationName)}`;
  const html = `<div style="font-family:sans-serif;max-width:580px;margin:0 auto;padding:24px">
    <h2 style="color:#E53E2E;margin-bottom:4px">💬 New customer message</h2>
    <p style="color:#888;font-size:13px;margin-bottom:20px">${_he(automationName)} · Blueprint Studio</p>
    <div style="background:#f5f5f5;border-radius:10px;padding:16px;margin-bottom:14px">
      <p style="font-size:11px;text-transform:uppercase;color:#999;margin-bottom:6px">Customer</p>
      <p style="font-size:14px;color:#222;line-height:1.6;margin:0">${_he(userMsg).replace(/\n/g,'<br>')}</p>
    </div>
    <div style="background:#fff3f2;border-left:3px solid #E53E2E;border-radius:10px;padding:16px">
      <p style="font-size:11px;text-transform:uppercase;color:#E53E2E;margin-bottom:6px">AI Reply</p>
      <p style="font-size:14px;color:#222;line-height:1.6;margin:0">${_he(aiMsg).replace(/\n/g,'<br>')}</p>
    </div>
    <p style="color:#ccc;font-size:11px;margin-top:18px;text-align:center">AutoFlow · aicashsystem.space</p>
  </div>`;
  await _sendEmail({ to, subject, html });
}

async function getAutomation(webhookId) {
  if (supabase) {
    try {
      const { data } = await supabase.from('automations').select('*').eq('webhook_id', webhookId).single();
      if (data) return data;
    } catch(e) {}
  }
  return automationStore.get(webhookId) || null;
}

async function incrementCount(webhookId, current, userMessage, aiReply) {
  const newCount = (current || 0) + 1;
  const logEntry = { time: new Date().toISOString(), user: userMessage?.slice(0,300), reply: aiReply?.slice(0,500) };

  // Update in-memory store
  if (automationStore.has(webhookId)) {
    const a = automationStore.get(webhookId);
    a.messages_count = newCount;
    if (!a.message_log) a.message_log = [];
    a.message_log.unshift(logEntry);
    if (a.message_log.length > 20) a.message_log.pop();
    saveStore();
  }

  // Update Supabase
  if (supabase) {
    try {
      const { data: cur } = await supabase.from('automations').select('message_log').eq('webhook_id', webhookId).single();
      const existingLog = cur?.message_log || [];
      existingLog.unshift(logEntry);
      if (existingLog.length > 20) existingLog.pop();
      await supabase.from('automations').update({ messages_count: newCount, message_log: existingLog }).eq('webhook_id', webhookId);
    } catch(e) {}
  }
}

// GET /api/automations/:id/messages
app.get('/api/automations/:id/messages', auth, async (req, res) => {
  if (supabase) {
    try {
      const { data } = await supabase.from('automations').select('message_log,user_id').eq('webhook_id', req.params.id).single();
      if (data && String(data.user_id) === String(req.user.id)) return res.json({ messages: data.message_log || [] });
    } catch(e) {}
  }
  const a = automationStore.get(req.params.id);
  if (!a || String(a.user_id) !== String(req.user.id)) return res.status(404).json({ error: 'Not found' });
  res.json({ messages: a.message_log || [] });
});

// GET /api/automations
app.get('/api/automations', auth, async (req, res) => {
  const userId = String(req.user.id);
  if (supabase) {
    try {
      const { data, error } = await supabase.from('automations').select('*').eq('user_id', userId).order('created_at', { ascending: false });
      if (!error) return res.json({ automations: data || [] });
    } catch(e) {}
  }
  const items = [...automationStore.values()].filter(a => String(a.user_id) === userId);
  res.json({ automations: items });
});

// POST /api/automations
app.post('/api/automations', auth, async (req, res) => {
  const { name, type, system_prompt, config } = req.body;
  if (!name || !type || !system_prompt) return res.status(400).json({ error: 'name, type, system_prompt required' });
  const webhook_id = crypto.randomBytes(10).toString('hex');
  const automation = {
    id: webhook_id,
    user_id: String(req.user.id),
    webhook_id, name, type, system_prompt,
    config: config || {},
    active: true, messages_count: 0,
    created_at: new Date().toISOString()
  };
  const proto = (process.env.NODE_ENV === 'production' || process.env.RENDER) ? 'https' : req.protocol;
  const webhookUrl = `${proto}://${req.get('host')}/webhook/${webhook_id}`;
  if (supabase) {
    try {
      const { data, error } = await supabase.from('automations').insert([automation]).select().single();
      if (!error && data) {
        addLog(`Automation created: ${name}`, 'automation', 'success');
        return res.json({ automation: data, webhook_url: webhookUrl });
      }
    } catch(e) {}
  }
  automationStore.set(webhook_id, automation);
  saveStore();
  addLog(`Automation created: ${name}`, 'automation', 'success');
  res.json({ automation, webhook_url: webhookUrl });
});

// DELETE /api/automations/:id
app.delete('/api/automations/:id', auth, async (req, res) => {
  if (supabase) {
    try { await supabase.from('automations').delete().eq('webhook_id', req.params.id).eq('user_id', String(req.user.id)); } catch(e) {}
  }
  const a = automationStore.get(req.params.id);
  if (a && String(a.user_id) === String(req.user.id)) { automationStore.delete(req.params.id); saveStore(); }
  res.json({ success: true });
});

// PATCH /api/automations/:id — update notify_email (and other config fields)
app.patch('/api/automations/:id', auth, async (req, res) => {
  const { notify_email } = req.body;
  if (supabase) {
    try {
      const { data: cur } = await supabase.from('automations').select('config,user_id').eq('webhook_id', req.params.id).single();
      if (cur && String(cur.user_id) === String(req.user.id)) {
        const newConfig = { ...(cur.config || {}), notify_email: notify_email || undefined };
        if (!notify_email) delete newConfig.notify_email;
        const { data: updated } = await supabase.from('automations').update({ config: newConfig }).eq('webhook_id', req.params.id).select().single();
        if (updated) return res.json({ automation: updated });
      }
    } catch(e) {}
  }
  const a = automationStore.get(req.params.id);
  if (!a || String(a.user_id) !== String(req.user.id)) return res.status(404).json({ error: 'Not found' });
  if (notify_email) a.config = { ...(a.config || {}), notify_email };
  else if (a.config) delete a.config.notify_email;
  saveStore();
  res.json({ automation: a });
});

// PATCH /api/automations/:id/toggle
app.patch('/api/automations/:id/toggle', auth, async (req, res) => {
  if (supabase) {
    try {
      const { data } = await supabase.from('automations').select('active,user_id').eq('webhook_id', req.params.id).single();
      if (data) {
        if (String(data.user_id) !== String(req.user.id)) return res.status(403).json({ error: 'Forbidden' });
        const { data: updated } = await supabase.from('automations').update({ active: !data.active }).eq('webhook_id', req.params.id).select().single();
        return res.json({ automation: updated });
      }
    } catch(e) {}
  }
  const a = automationStore.get(req.params.id);
  if (!a || String(a.user_id) !== String(req.user.id)) return res.status(404).json({ error: 'Not found' });
  a.active = !a.active; saveStore(); return res.json({ automation: a });
});

// POST /webhook/:webhookId — PUBLIC execution endpoint
app.post('/webhook/:webhookId', _webhookLimiter, async (req, res) => {
  const { webhookId } = req.params;
  try {
    const automation = await getAutomation(webhookId);
    if (!automation) return res.status(404).json({ error: 'Automation not found' });
    if (!automation.active) return res.json({ message: 'Automation paused' });

    const body = req.body;
    let userMessage = '';
    let aiReply = '';

    if (automation.type === 'whatsapp') {
      // 360dialog / WhatsApp Cloud API format
      const msg = body?.messages?.[0] || body?.entry?.[0]?.changes?.[0]?.value?.messages?.[0];
      userMessage = msg?.text?.body || msg?.interactive?.button_reply?.title || JSON.stringify(body).slice(0, 500);
      const from = msg?.from || body?.messages?.[0]?.from;
      aiReply = await callAI(automation.system_prompt, userMessage);
      if (automation.config?.api_key && from) {
        const apiKey = automation.config.api_key;
        await fetch('https://waba.360dialog.io/v1/messages', {
          method: 'POST',
          headers: { 'D360-API-KEY': apiKey, 'Content-Type': 'application/json' },
          body: JSON.stringify({ to: from, type: 'text', text: { body: aiReply } })
        });
      }
    } else if (automation.type === 'email') {
      // Tally / Typeform / generic form webhook
      const fields = body?.data?.fields || body?.fields || [];
      const emailVal = fields.find(f => f.type === 'EMAIL' || (f.label||'').toLowerCase().includes('email'))?.value || body?.email || body?.Email || '';
      const nameVal = fields.find(f => (f.label||'').toLowerCase().includes('name'))?.value || body?.name || body?.Name || 'there';
      const msgVal = fields.find(f => ['LONG_TEXT','SHORT_TEXT','TEXTAREA'].includes(f.type) || (f.label||'').toLowerCase().includes('message'))?.value || body?.message || body?.Message || JSON.stringify(body).slice(0,300);
      userMessage = `Name: ${nameVal}\nMessage: ${msgVal}`;
      aiReply = await callAI(automation.system_prompt, userMessage);
      if (transporter && emailVal) {
        await transporter.sendMail({
          from: automation.config?.from_email || SENDER_EMAIL,
          to: emailVal,
          subject: automation.config?.email_subject || 'Thank you for reaching out!',
          text: aiReply,
          html: `<div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px"><p>${aiReply.replace(/\n/g,'<br>')}</p></div>`
        });
      }
    } else {
      // Generic HTTP: receive any JSON, reply with AI output
      userMessage = body?.message || body?.text || body?.content || body?.query || JSON.stringify(body).slice(0,500);
      aiReply = await callAI(automation.system_prompt, userMessage);
      if (automation.config?.callback_url) {
        try {
          const _cbUrl = new URL(automation.config.callback_url);
          if (!['http:','https:'].includes(_cbUrl.protocol)) throw new Error('bad protocol');
          const _h = _cbUrl.hostname;
          const _b = parseInt((_h.match(/^172\.(\d+)\./) || [])[1] || '0');
          if (_h === 'localhost' || _h === '127.0.0.1' || _h === '0.0.0.0' || _h === '::1'
            || _h.startsWith('169.254.') || _h.startsWith('10.') || _h.startsWith('192.168.')
            || (_b >= 16 && _b <= 31)) throw new Error('private host');
          await fetch(automation.config.callback_url, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reply: aiReply, original: body })
          });
        } catch(cbErr) { console.error('Callback URL error:', cbErr.message); }
      }
    }

    await incrementCount(webhookId, automation.messages_count, userMessage, aiReply);
    addLog(`Automation fired: ${automation.name} | "${userMessage.slice(0,60)}"`, 'automation', 'success');

    // Email notification to owner
    if (automation.config?.notify_email) {
      sendNotifyEmail(automation.config.notify_email, automation.name, userMessage, aiReply);
    }

    res.json({ success: true, reply: aiReply });
  } catch(e) {
    console.error('Webhook execution error:', e);
    addLog('Automation error: ' + e.message, 'automation', 'error');
    res.status(500).json({ error: 'Automation failed. Please try again.' });
  }
});

// GET /api/chat/:webhookId/info — public: returns automation name for chat page
app.get('/api/chat/:webhookId/info', async (req, res) => {
  try {
    const a = await getAutomation(req.params.webhookId);
    if (!a) return res.status(404).json({ error: 'Not found' });
    res.json({ name: a.name, active: a.active });
  } catch(e) { res.status(500).json({ error: 'Server error' }); }
});

// GET /chat/:webhookId — serve public chat page
app.get('/chat/:webhookId', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'chat.html'));
});

// POST /api/test-email — send a real test email and return result
app.post('/api/test-email', auth, async (req, res) => {
  const to = req.body.to || req.user.email;
  const result = { to, brevo_api_key: !!BREVO_API_KEY, smtp: !!transporter, brevo_user: !!BREVO_USER };

  if (BREVO_API_KEY) {
    try {
      const senderEmail = SENDER_EMAIL;
      const r = await fetch('https://api.brevo.com/v3/smtp/email', {
        method: 'POST',
        headers: { 'api-key': BREVO_API_KEY, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender: { name: SENDER_NAME, email: SENDER_EMAIL },
          to: [{ email: to }],
          subject: 'Blueprint Studio — Test Email',
          htmlContent: '<p>Test email from Blueprint Studio. If you see this, email notifications work!</p>'
        })
      });
      const body = await r.text();
      if (r.ok) return res.json({ ...result, method: 'brevo_api', success: true });
      return res.json({ ...result, method: 'brevo_api', success: false, error: body });
    } catch(e) {
      return res.json({ ...result, method: 'brevo_api', success: false, error: e.message });
    }
  }

  if (transporter) {
    try {
      await transporter.sendMail({
        from: SENDER_EMAIL,
        to,
        subject: 'Blueprint Studio — Test Email',
        html: '<p>Test email from Blueprint Studio. If you see this, email notifications work!</p>'
      });
      return res.json({ ...result, method: 'smtp', success: true });
    } catch(e) {
      return res.json({ ...result, method: 'smtp', success: false, error: e.message });
    }
  }

  res.json({ ...result, method: 'none', success: false, error: 'No email provider configured' });
});

// GET /api/test — admin only
app.get('/api/test', auth, (req, res) => {
  res.json({
    status: 'ok',
    openai: !!OPENAI_KEY,
    anthropic: !!anthropic,
    email: !!transporter,
    brevo_api: !!BREVO_API_KEY,
    supabase: !!supabase
  });
});

// POST /api/ai/chat — multi-turn conversation
app.post('/api/ai/chat', auth, _aiLimiter, async (req, res) => {
  const { messages } = req.body;
  if (!messages || !messages.length) return res.status(400).json({ error: 'Messages required' });

  try {
    // Try OpenAI first
    if (OPENAI_KEY) {
      const response = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + OPENAI_KEY },
        body: JSON.stringify({
          model: 'gpt-4o',
          max_tokens: 2000,
          messages: messages
        })
      });
      const data = await response.json();
      if (data.choices && data.choices[0]) {
        const output = data.choices[0].message.content;
        addLog('AI chat response sent', 'ai', 'success');
        return res.json({ output });
      }
    }

    // Try Anthropic Claude
    if (anthropic) {
      const systemMsg = messages.find(m => m.role === 'system');
      const chatMsgs = messages.filter(m => m.role !== 'system');
      const msg = await anthropic.messages.create({
        model: 'claude-sonnet-4-6',
        max_tokens: 2000,
        system: systemMsg ? systemMsg.content : '',
        messages: chatMsgs
      });
      const output = msg.content[0].text;
      addLog('AI chat response sent (Claude)', 'ai', 'success');
      return res.json({ output });
    }

    return res.status(500).json({ error: 'No AI provider configured.' });
  } catch (e) {
    console.error('AI chat error:', e);
    addLog('AI chat failed: ' + e.message, 'ai', 'error');
    res.status(500).json({ error: 'AI chat failed. Please try again.' });
  }
});

// ════════════════════════════════════════
// MAKE.COM INTEGRATION ROUTES
// ════════════════════════════════════════

// POST /api/make/connect — verify API key and return teams
app.post('/api/make/connect', auth, async (req, res) => {
  const { apiKey, zone } = req.body;
  if (!apiKey) return res.status(400).json({ error: 'API key required' });
  const host = (zone || 'eu1.make.com').replace(/^https?:\/\//, '');
  const headers = { 'Authorization': `Token ${apiKey}`, 'Content-Type': 'application/json' };
  const safeJson = async (response) => {
    const text = await response.text();
    try { return JSON.parse(text); } catch { return { message: text.slice(0, 200) }; }
  };
  try {
    // Step 1: verify key via /users/me
    const meR = await fetch(`https://${host}/api/v2/users/me`, { headers });
    const meData = await safeJson(meR);
    if (!meR.ok) {
      return res.status(meR.status).json({ error: meData.message || meData.detail || `Make.com returned ${meR.status}. Check your API key and zone.` });
    }

    // Step 2: get organizations
    const orgR = await fetch(`https://${host}/api/v2/organizations`, { headers });
    const orgData = orgR.ok ? await safeJson(orgR) : { organizations: [] };
    const orgs = orgData.organizations || [];

    // Step 3: collect teams from each org
    let teams = [];
    for (const org of orgs) {
      const tR = await fetch(`https://${host}/api/v2/teams?organizationId=${org.id}`, { headers });
      if (tR.ok) {
        const tData = await safeJson(tR);
        teams = teams.concat(tData.teams || []);
      }
    }

    // Fallback: treat orgs as teams if none found
    if (!teams.length) {
      teams = orgs.map(o => ({ id: o.id, name: o.name }));
    }

    // Last resort: create a default team entry from user info
    if (!teams.length) {
      teams = [{ id: meData.organizationId || meData.id || 1, name: meData.name || 'My Team' }];
    }

    addLog('Make.com account connected', 'make', 'success');
    res.json({ teams, user: meData });
  } catch (e) {
    res.status(500).json({ error: 'Cannot reach Make.com: ' + e.message });
  }
});

// POST /api/make/create — create scenario from a blueprint file
app.post('/api/make/create', auth, async (req, res) => {
  const { apiKey, zone, teamId, blueprintFile, scenarioName } = req.body;
  if (!apiKey || !teamId || !blueprintFile) return res.status(400).json({ error: 'apiKey, teamId and blueprintFile required' });

  const host = (zone || 'eu1.make.com').replace(/^https?:\/\//, '');
  const fs = require('fs');
  const BLUEPRINTS_DIR = path.join(__dirname, 'public', 'blueprints');
  const safeName = path.basename(blueprintFile).replace(/[^a-zA-Z0-9._-]/g, '');
  const bpPath = path.join(BLUEPRINTS_DIR, safeName);
  if (!bpPath.startsWith(BLUEPRINTS_DIR + path.sep) && bpPath !== BLUEPRINTS_DIR) {
    return res.status(400).json({ error: 'Invalid blueprint path' });
  }

  let blueprint;
  try {
    blueprint = JSON.parse(fs.readFileSync(bpPath, 'utf8'));
  } catch (e) {
    return res.status(404).json({ error: 'Blueprint file not found' });
  }

  if (scenarioName) blueprint.name = scenarioName;

  try {
    const body = {
      blueprint,
      teamId: parseInt(teamId),
      organizationId: parseInt(teamId),
      scheduling: { type: 'INDEFINITELY', interval: 900 }
    };
    const r = await fetch(`https://${host}/api/v2/scenarios`, {
      method: 'POST',
      headers: { 'Authorization': `Token ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const text = await r.text();
    let data;
    try { data = JSON.parse(text); } catch { data = { message: text.slice(0, 300) }; }
    console.log('Make.com create response:', r.status, JSON.stringify(data).slice(0, 500));
    if (!r.ok) return res.status(r.status).json({ error: data.message || data.detail || `Make.com ${r.status}: ${text.slice(0,200)}` });
    const scenarioId = data.scenario?.id || data.id;
    addLog(`Make.com scenario created: ${blueprint.name} (ID: ${scenarioId})`, 'make', 'success');
    res.json({ success: true, scenarioId, scenarioName: blueprint.name, editUrl: `https://${host}/scenarios/${scenarioId}/edit` });
  } catch (e) {
    addLog('Make.com create failed: ' + e.message, 'make', 'error');
    res.status(500).json({ error: 'Failed to create scenario: ' + e.message });
  }
});

// ════════════════════════════════════════
// EMAIL ROUTES
// ════════════════════════════════════════

// POST /api/email/send
app.post('/api/email/send', auth, _emailLimiter, async (req, res) => {
  const { to, subject, body, fromName } = req.body;
  if (!to || !subject || !body) return res.status(400).json({ error: 'To, subject and body are required' });
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(to)) return res.status(400).json({ error: 'Invalid recipient email' });

  const htmlBody = _he(body).replace(/\n/g, '<br>');
  try {
    if (BREVO_API_KEY) {
      const r = await fetch('https://api.brevo.com/v3/smtp/email', {
        method: 'POST',
        headers: { 'api-key': BREVO_API_KEY, 'Content-Type': 'application/json' },
        body: JSON.stringify({ sender: { name: fromName || SENDER_NAME, email: SENDER_EMAIL },
          to: [{ email: to }], subject, htmlContent: htmlBody })
      });
      if (r.ok) { addLog(`Email sent to ${to}: ${subject}`, 'email', 'success'); return res.json({ success: true }); }
    }
    if (transporter) {
      await transporter.sendMail({ from: `"${fromName || SENDER_NAME}" <${SENDER_EMAIL}>`,
        to, subject, text: body, html: htmlBody });
      addLog(`Email sent to ${to}: ${subject}`, 'email', 'success');
      return res.json({ success: true });
    }
    addLog(`Email not sent — no provider configured`, 'email', 'error');
    return res.status(503).json({ error: 'Email provider not configured' });
  } catch (e) {
    console.error('Email error:', e);
    res.status(500).json({ error: 'Failed to send email' });
  }
});

// ════════════════════════════════════════
// WEBHOOK ROUTES
// ════════════════════════════════════════

const webhooks = [];

// GET /api/webhooks
app.get('/api/webhooks', auth, (req, res) => {
  res.json(webhooks);
});

// POST /api/webhooks/create
app.post('/api/webhooks/create', auth, (req, res) => {
  const { name } = req.body;
  const id = crypto.randomBytes(8).toString('hex');
  const proto = (process.env.NODE_ENV === 'production' || process.env.RENDER) ? 'https' : req.protocol;
  const url = `${proto}://${req.get('host')}/webhook/${id}`;
  const webhook = { id, name: name || 'Webhook', url, hits: 0, lastHit: null, createdAt: new Date().toISOString() };
  webhooks.push(webhook);
  addLog(`Webhook created: ${name}`, 'webhook', 'success');
  res.json(webhook);
});

// GET /webhook/:id — friendly info page (POST is handled by automation engine above)
app.get('/webhook/:id', (req, res) => {
  res.json({ info: 'This is a Blueprint Studio automation webhook. Send a POST request with {"message":"your text"} to trigger it.', id: req.params.id });
});

// ════════════════════════════════════════
// LOGS ROUTES
// ════════════════════════════════════════

// GET /api/logs
app.get('/api/logs', auth, (req, res) => {
  res.json(logs.slice(0, 100));
});

// ════════════════════════════════════════
// COURSE ACCESS ROUTES
// ════════════════════════════════════════

// POST /api/verify-code — verify course access code
app.post('/api/verify-code', _codeLimiter, async (req, res) => {
  const { code } = req.body;
  if (!code) return res.status(400).json({ error: 'Access code required' });

  // Owner bypass — requires COURSE_BYPASS_CODE env var to be set
  if (COURSE_BYPASS_CODE && code.toUpperCase() === COURSE_BYPASS_CODE.toUpperCase()) {
    const maxAge = 60 * 60 * 24 * 30;
    const secure = process.env.NODE_ENV === 'production' || process.env.RENDER ? '; Secure' : '';
    res.setHeader('Set-Cookie', `af_access=${_signAccess('pro')}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${maxAge}${secure}`);
    return res.json({ success: true, plan: 'pro', redirect: '/course-pro.html' });
  }

  try {
    if (supabase) {
      const { data, error } = await supabase
        .from('purchases')
        .select('*')
        .eq('code', code.toUpperCase())
        .single();
      if (data) {
        const plan = data.plan || 'starter';
        const maxAge = 60 * 60 * 24 * 30; // 30 days
        const secure = process.env.NODE_ENV === 'production' || process.env.RENDER ? '; Secure' : '';
        res.setHeader('Set-Cookie', `af_access=${_signAccess(plan)}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${maxAge}${secure}`);
        return res.json({ success: true, plan, redirect: plan === 'pro' ? '/course-pro.html' : '/course-starter.html' });
      }
    }
    return res.status(401).json({ error: 'Invalid access code.' });
  } catch (e) {
    res.status(500).json({ error: 'Server error' });
  }
});

// GET /api/logout — clear course access cookie
app.get('/api/logout', (req, res) => {
  res.setHeader('Set-Cookie', 'af_access=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0');
  res.redirect('/access.html');
});

// ── LICENSE KEY HELPERS ──────────────────────────────────────────────────────
// Crypto keys:  APEX-XXXX-XXXX-XXXX  (verified by crypto bot only)
// Forex keys:   FORX-XXXX-XXXX-XXXX  (verified by forex bot only)
// Both use HMAC-SHA256 with product-specific salt embedded in the prefix.
const _KEY_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // 32 chars, no 0/O/1/I
const _LIC_SALT       = 'apex-bot-2025-v1';   // crypto fallback — never changes
const _FOREX_LIC_SALT = 'apex-forex-2025-v1'; // forex fallback — never changes

function _licSecrets(product = 'apex-bot') {
  const env = process.env.BOT_EMAIL_SECRET;
  const salt = product === 'apex-forex' ? _FOREX_LIC_SALT : _LIC_SALT;
  // When BOT_EMAIL_SECRET is set, ONLY the env-derived secret is trusted for
  // HMAC signing/verification. The hardcoded salt is deliberately dropped so
  // that anyone who can read this source cannot forge valid keys. Legacy keys
  // signed with the salt (issued before BOT_EMAIL_SECRET existed) still pass
  // through the Supabase fallback in /api/verify-license, because every real
  // buyer's key is stored active in the licenses table.
  return env ? [`${env}-${product}`] : [salt];
}

function _hmacMac4(data, secret) {
  const mac = crypto.createHmac('sha256', secret).update(data).digest();
  return [0, 1, 2, 3].map(i => _KEY_CHARS[mac[i] % 32]).join('');
}

function _generateKey(prefix, product) {
  const secret = _licSecrets(product)[0];
  const buf = crypto.randomBytes(8);
  const rnd8 = Array.from(buf).map(b => _KEY_CHARS[b % 32]).join('');
  const mac4 = _hmacMac4(rnd8, secret);
  const full = rnd8 + mac4;
  return `${prefix}-${full.slice(0, 4)}-${full.slice(4, 8)}-${full.slice(8, 12)}`;
}

function generateLicenseKey() { return _generateKey('APEX', 'apex-bot'); }
function generateForexKey()   { return _generateKey('FORX', 'apex-forex'); }

// Returns { valid, product } — product is 'apex-bot' | 'apex-forex' | null
function verifyLicenseKeyHmac(key) {
  if (!key) return { valid: false, product: null };
  const k = key.toUpperCase();
  const prefixMap = { APEX: 'apex-bot', FORX: 'apex-forex' };
  for (const [prefix, product] of Object.entries(prefixMap)) {
    const re = new RegExp(`^${prefix}-([A-Z2-9]{4})-([A-Z2-9]{4})-([A-Z2-9]{4})$`);
    const m = k.match(re);
    if (!m) continue;
    const full = m[1] + m[2] + m[3];
    const data = full.slice(0, 8), given = full.slice(8, 12);
    if (_licSecrets(product).some(s => _hmacMac4(data, s) === given)) return { valid: true, product };
  }
  return { valid: false, product: null };
}

// ── AFFILIATE / REFERRAL SYSTEM ──────────────────────────────────────────────
// Program policy. Bump TERMS_VERSION whenever the affiliate terms change so we
// can tell who accepted which version.
const AFFILIATE_TERMS_VERSION = '2026-06-16';
const REFUND_WINDOW_DAYS = 14;   // commission only matures (becomes payable) after this
const MIN_PAYOUT_CENTS   = 5000; // $50 minimum before a payout can be requested
function _generateAffiliateCode(name) {
  const slug = (name || 'creator').toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 10) || 'creator';
  return `${slug}${crypto.randomBytes(2).toString('hex')}`;
}
function _hashPassword(password) {
  const salt = crypto.randomBytes(16).toString('hex');
  const hash = crypto.scryptSync(String(password), salt, 64).toString('hex');
  return `${salt}:${hash}`;
}
function _verifyPassword(password, stored) {
  if (!stored || !stored.includes(':')) return false;
  const [salt, hash] = stored.split(':');
  const check = crypto.scryptSync(String(password), salt, 64).toString('hex');
  try { return crypto.timingSafeEqual(Buffer.from(hash, 'hex'), Buffer.from(check, 'hex')); } catch { return false; }
}
function _affiliateLink(code) { return `https://aicashsystem.space/?ref=${code}`; }
// Resolve the logged-in affiliate code from a Bearer token; null if invalid.
function _affiliateFromAuth(req) {
  const auth = req.headers.authorization || '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : '';
  const payload = verifyToken(token);
  if (!payload || !payload.id) return null;
  return String(payload.id).toLowerCase().trim();
}

// GET /api/affiliates/click?ref=CODE — count a referral-link visit.
// Fired by the landing page when it sees ?ref=. Validates the code exists, then
// inserts one row (atomic, no lost updates). Deduped per visitor for 30 min.
app.get('/api/affiliates/click', async (req, res) => {
  const ref = String(req.query.ref || '').toLowerCase().trim().slice(0, 40);
  if (!ref || !supabase) return res.json({ ok: false });
  const ip = (req.headers['x-forwarded-for'] || req.socket?.remoteAddress || '').toString().split(',')[0].trim();
  const dedupeKey = `${ref}|${ip}`;
  const now = Date.now();
  const last = _recentClicks.get(dedupeKey);
  if (last && now - last < _CLICK_DEDUPE_MS) return res.json({ ok: true, deduped: true });
  _recentClicks.set(dedupeKey, now);
  // Opportunistic cleanup so the map doesn't grow unbounded.
  if (_recentClicks.size > 5000) {
    for (const [k, t] of _recentClicks) if (now - t > _CLICK_DEDUPE_MS) _recentClicks.delete(k);
  }
  try {
    const { data: aff } = await supabase.from('affiliates').select('code').eq('code', ref).maybeSingle();
    if (aff) await supabase.from('affiliate_clicks').insert([{ affiliate_code: ref }]);
  } catch (e) { /* clicks are best-effort analytics — never block the visitor */ }
  res.json({ ok: true });
});

// POST /api/lead — { email, ref, source } capture a lead from the free funnel.
// Cold DM traffic rarely buys on the first click; this captures the contact so
// it can be nurtured to the sale. Best-effort store (leads table may not exist);
// never blocks the visitor. Affiliate ref is preserved for attribution.
app.post('/api/lead', _authLimiter, async (req, res) => {
  const email = String((req.body && req.body.email) || '').toLowerCase().trim().slice(0, 200);
  const ref = String((req.body && req.body.ref) || '').toLowerCase().trim().slice(0, 40);
  const source = String((req.body && req.body.source) || 'free').trim().slice(0, 40);
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return res.status(400).json({ ok: false, error: 'Please enter a valid email.' });
  }
  try {
    if (supabase) {
      await supabase.from('leads').insert([{ email, ref: ref || null, source }]);
    }
  } catch (e) { /* leads table optional — never block the visitor */ }
  // Fire the affiliate click too, so a lead from an affiliate link is attributed.
  try {
    if (supabase && ref) {
      const { data: aff } = await supabase.from('affiliates').select('code').eq('code', ref).maybeSingle();
      if (aff) await supabase.from('affiliate_clicks').insert([{ affiliate_code: ref }]);
    }
  } catch (e) { /* best-effort */ }
  console.log(`[LEAD] ${email}${ref ? ' (ref ' + ref + ')' : ''} via ${source}`);
  res.json({ ok: true });
});

// POST /api/affiliates/apply — { name, email, tiktokHandle } -> { code, link }
app.post('/api/affiliates/apply', _authLimiter, async (req, res) => {
  const { name, email, tiktokHandle } = req.body || {};
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return res.status(400).json({ error: 'Invalid email address' });
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const cleanEmail = email.toLowerCase().trim();
  try {
    const { data: existing } = await supabase.from('affiliates').select('code').eq('email', cleanEmail).maybeSingle();
    if (existing?.code) return res.json({ code: existing.code, link: `https://aicashsystem.space/?ref=${existing.code}` });

    let code;
    for (let attempts = 0; attempts < 5; attempts++) {
      code = _generateAffiliateCode(name);
      const { data: clash } = await supabase.from('affiliates').select('code').eq('code', code).maybeSingle();
      if (!clash) break;
    }
    const { error } = await supabase.from('affiliates').insert([{
      code, email: cleanEmail, name: name || '', tiktok_handle: tiktokHandle || '', status: 'active'
    }]);
    if (error) return res.status(500).json({ error: error.message });
    addLog(`New affiliate: ${cleanEmail} — code ${code}`, 'affiliate', 'success');
    res.json({ code, link: `https://aicashsystem.space/?ref=${code}` });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ── Telegram tracking-bot bridge ─────────────────────────────────────────────
// Affiliates sign up on the site (name+email) and then open the Telegram bot,
// which generates their link and tracks sales. The deep-link carries a signed
// connect token = hmac12(code) + code, so the bot can prove which affiliate it is.
const AFFILIATE_BOT_USERNAME = process.env.AFFILIATE_BOT_USERNAME || 'AICASHSYSTEM_REF_BOT';
const AFFILIATE_BOT_SECRET   = process.env.AFFILIATE_BOT_SECRET || process.env.JWT_SECRET || 'apex-affiliate-bridge';
function _affConnectSig(code) {
  return crypto.createHmac('sha256', AFFILIATE_BOT_SECRET).update(String(code)).digest('hex').slice(0, 12);
}
function _affConnectToken(code) { return _affConnectSig(code) + code; }
function _affCodeFromToken(token) {
  const t = String(token || '');
  if (t.length < 15) return null;            // 12 sig + >=3 code
  const sig = t.slice(0, 12), code = t.slice(12);
  return _affConnectSig(code) === sig ? code : null;
}
function _affTelegramUrl(code) {
  return `https://t.me/${AFFILIATE_BOT_USERNAME}?start=${_affConnectToken(code)}`;
}

// POST /api/affiliates/start — { name, email } -> { code, telegramUrl }
// Creates (or re-uses) the affiliate, then hands off to the Telegram bot.
app.post('/api/affiliates/start', _authLimiter, async (req, res) => {
  const { name, email } = req.body || {};
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return res.status(400).json({ error: 'Invalid email address' });
  if (!supabase) return res.status(500).json({ error: 'Affiliate system is not configured yet. Please try again later.' });
  const cleanEmail = email.toLowerCase().trim();
  try {
    let code;
    const { data: existing } = await supabase.from('affiliates').select('code').eq('email', cleanEmail).maybeSingle();
    if (existing?.code) {
      code = existing.code;
    } else {
      for (let attempts = 0; attempts < 5; attempts++) {
        code = _generateAffiliateCode(name);
        const { data: clash } = await supabase.from('affiliates').select('code').eq('code', code).maybeSingle();
        if (!clash) break;
      }
      const { error } = await supabase.from('affiliates').insert([{
        code, email: cleanEmail, name: name || '', status: 'active',
        terms_accepted_at: new Date().toISOString(), terms_version: AFFILIATE_TERMS_VERSION
      }]);
      if (error) return res.status(500).json({ error: error.message });
      addLog(`New affiliate (Telegram flow): ${cleanEmail} — code ${code}`, 'affiliate', 'success');
    }
    res.json({ code, telegramUrl: _affTelegramUrl(code), botUsername: AFFILIATE_BOT_USERNAME });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Notify an affiliate on Telegram when one of their referrals buys.
// Alerts the owner on Telegram when a paying customer might not have gotten
// their license email — the D24 IPN itself still returns 'OK' in that case
// (the payment really did go through), so Digistore24 won't retry it and
// nothing else will surface the failure.
async function _notifyAdminAlert(text) {
  const botToken = process.env.AFFILIATE_BOT_TOKEN;
  const chatId = process.env.ADMIN_CHAT_ID || '7585109158';
  if (!botToken) return;
  try {
    await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, text })
    });
  } catch (e) { addLog(`Admin TG alert error: ${e.message}`, 'system', 'warn'); }
}

async function _notifyAffiliateSale(code, product, commissionCents) {
  const botToken = process.env.AFFILIATE_BOT_TOKEN;
  if (!botToken || !supabase) return;
  try {
    const { data: aff } = await supabase.from('affiliates').select('telegram_chat_id').eq('code', code).maybeSingle();
    if (!aff || !aff.telegram_chat_id) return;
    const prod = product === 'apex-forex' ? 'Forex bot ($497)' : 'Crypto bot ($297)';
    const text = `🎉 New sale! You just earned $${(commissionCents / 100).toFixed(2)} on the ${prod}.\n\nSend /stats to see your totals.`;
    await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: aff.telegram_chat_id, text })
    });
  } catch (e) { addLog(`Affiliate TG notify error: ${e.message}`, 'affiliate', 'warn'); }
}

// POST /api/affiliates/telegram-link — bot links a Telegram chat to an affiliate.
// Body: { token, chatId, secret }. Returns { code, name, link }.
app.post('/api/affiliates/telegram-link', async (req, res) => {
  const { token, chatId, secret } = req.body || {};
  if (secret !== AFFILIATE_BOT_SECRET) return res.status(403).json({ error: 'forbidden' });
  if (!supabase) return res.status(500).json({ error: 'not configured' });
  const code = _affCodeFromToken(token);
  if (!code) return res.status(400).json({ error: 'invalid token' });
  try {
    const { data: aff } = await supabase.from('affiliates').select('code,name').eq('code', code).maybeSingle();
    if (!aff) return res.status(404).json({ error: 'affiliate not found' });
    const { data: updated, error: updateErr } = await supabase
      .from('affiliates').update({ telegram_chat_id: String(chatId) }).eq('code', code).select('code');
    console.log(`[tg-link] code=${code} chatId=${chatId} updated=${JSON.stringify(updated)} err=${updateErr?.message}`);
    if (updateErr) return res.status(500).json({ error: 'link failed: ' + updateErr.message });
    if (!updated || updated.length === 0) return res.status(500).json({ error: 'link failed: no rows updated' });
    addLog(`Affiliate linked Telegram: ${code} -> chat ${chatId}`, 'affiliate', 'success');
    res.json({ ok: true, code, name: aff.name || '', link: _affiliateLink(code) });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// POST /api/affiliates/telegram-stats — bot fetches a linked affiliate's stats.
// Body: { chatId, secret }. Returns earnings + recent sales (or { linked:false }).
app.post('/api/affiliates/telegram-stats', async (req, res) => {
  const { chatId, secret } = req.body || {};
  if (secret !== AFFILIATE_BOT_SECRET) return res.status(403).json({ error: 'forbidden' });
  if (!supabase) return res.status(500).json({ error: 'not configured' });
  try {
    const { data: aff } = await supabase.from('affiliates').select('code,name,commission_percent').eq('telegram_chat_id', String(chatId)).maybeSingle();
    console.log(`[tg-stats] chatId=${chatId} found=${!!aff} code=${aff?.code}`);
    if (!aff) return res.json({ linked: false });
    const { data } = await supabase.from('referral_sales').select('commission_amount,paid,refunded,created_at,product').eq('affiliate_code', aff.code).order('created_at', { ascending: false });
    const rows = data || [];
    const now = Date.now(), windowMs = REFUND_WINDOW_DAYS * 24 * 60 * 60 * 1000;
    let available = 0, pending = 0, paid = 0, sales = 0;
    rows.forEach(r => {
      if (r.refunded) return;
      sales++;
      if (r.paid) paid += r.commission_amount;
      else if (new Date(r.created_at).getTime() + windowMs <= now) available += r.commission_amount;
      else pending += r.commission_amount;
    });
    // Link clicks + conversion rate (best-effort — table may not exist yet).
    let clicks = 0;
    try {
      const { count } = await supabase.from('affiliate_clicks')
        .select('id', { count: 'exact', head: true }).eq('affiliate_code', aff.code);
      clicks = count || 0;
    } catch (e) { /* clicks table optional */ }
    const conversionPct = clicks > 0 ? Math.round((sales / clicks) * 1000) / 10 : 0;
    res.json({
      linked: true, code: aff.code, name: aff.name || '', link: _affiliateLink(aff.code),
      commissionPercent: aff.commission_percent, totalSales: sales,
      clicks, conversionPct,
      availableCents: available, pendingCents: pending, paidCents: paid,
      minPayoutCents: MIN_PAYOUT_CENTS, refundWindowDays: REFUND_WINDOW_DAYS,
      recent: rows.slice(0, 5).map(r => ({ product: r.product, commission: r.commission_amount, paid: r.paid, refunded: !!r.refunded, date: r.created_at }))
    });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// POST /api/affiliates/admin-list — bot fetches all affiliates + their sales for admin view.
// Body: { secret }. Gated by AFFILIATE_BOT_SECRET; bot enforces admin chat_id check.
app.post('/api/affiliates/admin-list', async (req, res) => {
  const { secret } = req.body || {};
  if (secret !== AFFILIATE_BOT_SECRET) return res.status(403).json({ error: 'forbidden' });
  if (!supabase) return res.status(500).json({ error: 'not configured' });
  try {
    const { data: affs } = await supabase.from('affiliates').select('code,name,email,status,commission_percent,created_at').order('created_at', { ascending: false });
    const { data: sales } = await supabase.from('referral_sales').select('affiliate_code,commission_amount,paid,refunded,product');
    const salesByCode = {};
    (sales || []).forEach(s => {
      if (!salesByCode[s.affiliate_code]) salesByCode[s.affiliate_code] = { total: 0, paid: 0, pending: 0, refunded: 0 };
      const b = salesByCode[s.affiliate_code];
      if (s.refunded) { b.refunded++; return; }
      b.total++;
      if (s.paid) b.paid += s.commission_amount;
      else b.pending += s.commission_amount;
    });
    res.json({ ok: true, affiliates: (affs || []).map(a => ({ ...a, sales: salesByCode[a.code] || { total: 0, paid: 0, pending: 0, refunded: 0 } })) });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// Reserved codes that must never become an affiliate handle (they collide with
// real query-string flags or look like system values).
const _RESERVED_CODES = new Set(['ref','admin','api','www','direct','intro','affiliate','login','signup','apex','forex','crypto']);
// Validate a user-chosen affiliate handle. Returns { ok, code } or { ok:false, error }.
// Pattern: letters, numbers, _ and - only.
function _validateCustomCode(raw) {
  const code = String(raw || '').toLowerCase().trim();
  if (!/^[a-z0-9_-]{3,20}$/.test(code)) return { ok: false, error: 'Your link name must be 3–20 characters: letters, numbers, - or _ only (no spaces).' };
  if (_RESERVED_CODES.has(code)) return { ok: false, error: 'That name is reserved — please choose another.' };
  return { ok: true, code };
}

// POST /api/affiliates/signup — { name, email, password, code, tiktokHandle, acceptTerms } -> { token, code, link }
app.post('/api/affiliates/signup', _authLimiter, async (req, res) => {
  const { name, email, password, tiktokHandle, code: wantCode, acceptTerms } = req.body || {};
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return res.status(400).json({ error: 'Invalid email address' });
  if (!password || String(password).length < 6) return res.status(400).json({ error: 'Password must be at least 6 characters' });
  if (acceptTerms !== true) return res.status(400).json({ error: 'You must accept the Affiliate Program Terms to continue.' });
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const cleanEmail = email.toLowerCase().trim();
  const nowIso = new Date().toISOString();
  // The affiliate chooses their own link name; fall back to an auto code if none given.
  let customCode = null;
  if (wantCode != null && String(wantCode).trim() !== '') {
    const v = _validateCustomCode(wantCode);
    if (!v.ok) return res.status(400).json({ error: v.error });
    customCode = v.code;
  }
  try {
    const { data: existing } = await supabase.from('affiliates').select('code,password_hash').eq('email', cleanEmail).maybeSingle();
    const pwHash = _hashPassword(password);
    if (existing?.code) {
      if (existing.password_hash) return res.status(409).json({ error: 'An account with this email already exists. Please log in.' });
      // Claim a pre-existing (passwordless) affiliate row created before auth existed.
      const { data: claimed, error: claimErr } = await supabase.from('affiliates')
        .update({ password_hash: pwHash, name: name || '', tiktok_handle: tiktokHandle || '', terms_accepted_at: nowIso, terms_version: AFFILIATE_TERMS_VERSION })
        .eq('code', existing.code).select('code,password_hash');
      if (claimErr) return res.status(500).json({ error: claimErr.message });
      if (!claimed || !claimed.length || !claimed[0].password_hash) return res.status(500).json({ error: 'Could not save your password. Please try again or contact support.' });
      addLog(`Affiliate claimed account: ${cleanEmail} — code ${existing.code}`, 'affiliate', 'success');
      return res.json({ token: createToken({ id: existing.code, email: cleanEmail }), code: existing.code, link: _affiliateLink(existing.code) });
    }
    let code;
    if (customCode) {
      const { data: clash } = await supabase.from('affiliates').select('code').eq('code', customCode).maybeSingle();
      if (clash) return res.status(409).json({ error: 'That link name is already taken — please choose another.' });
      code = customCode;
    } else {
      for (let attempts = 0; attempts < 5; attempts++) {
        code = _generateAffiliateCode(name);
        const { data: clash } = await supabase.from('affiliates').select('code').eq('code', code).maybeSingle();
        if (!clash) break;
      }
    }
    const { error } = await supabase.from('affiliates').insert([{
      code, email: cleanEmail, name: name || '', tiktok_handle: tiktokHandle || '', status: 'active', password_hash: pwHash,
      terms_accepted_at: nowIso, terms_version: AFFILIATE_TERMS_VERSION
    }]);
    if (error) {
      if (String(error.message || '').toLowerCase().includes('duplicate')) return res.status(409).json({ error: 'That link name is already taken — please choose another.' });
      return res.status(500).json({ error: error.message });
    }
    addLog(`New affiliate signup: ${cleanEmail} — code ${code}`, 'affiliate', 'success');
    res.json({ token: createToken({ id: code, email: cleanEmail }), code, link: _affiliateLink(code) });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// POST /api/affiliates/login — { email, password } -> { token, code, link }
app.post('/api/affiliates/login', _authLimiter, async (req, res) => {
  const { email, password } = req.body || {};
  if (!email || !password) return res.status(400).json({ error: 'Email and password required' });
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const cleanEmail = email.toLowerCase().trim();
  try {
    const { data: aff } = await supabase.from('affiliates').select('code,password_hash,status').eq('email', cleanEmail).maybeSingle();
    if (!aff || !aff.password_hash || !_verifyPassword(password, aff.password_hash)) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }
    if (aff.status !== 'active') return res.status(403).json({ error: 'This account is suspended.' });
    res.json({ token: createToken({ id: aff.code, email: cleanEmail }), code: aff.code, link: _affiliateLink(aff.code) });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /api/affiliates/me — dashboard data for the logged-in affiliate (Bearer token)
app.get('/api/affiliates/me', async (req, res) => {
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const code = _affiliateFromAuth(req);
  if (!code) return res.status(401).json({ error: 'Not authenticated' });
  try {
    const { data: affiliate, error: affErr } = await supabase.from('affiliates').select('code,name,email,commission_percent,status,payout_method,payout_details,stripe_account_id').eq('code', code).maybeSingle();
    if (affErr) { addLog(`Affiliate /me lookup error for code "${code}": ${affErr.message}`, 'affiliate', 'error'); return res.status(500).json({ error: affErr.message }); }
    if (!affiliate) { addLog(`Affiliate /me: no row found for code "${code}"`, 'affiliate', 'warn'); return res.status(404).json({ error: `Affiliate not found (code: ${code})` }); }
    const { data: pendingReq } = await supabase.from('payout_requests').select('amount_cents,requested_at').eq('affiliate_code', code).eq('status', 'requested').order('requested_at', { ascending: false }).maybeSingle();
    const { data } = await supabase.from('referral_sales').select('amount,commission_amount,paid,refunded,product,created_at').eq('affiliate_code', code).order('created_at', { ascending: false });
    const rows = data || [];
    const now = Date.now();
    const windowMs = REFUND_WINDOW_DAYS * 24 * 60 * 60 * 1000;
    // Commission lifecycle: pending (inside refund window) -> available (matured, payable)
    // -> paid. A refund/chargeback flips the sale to refunded and the commission is clawed back.
    let availableCents = 0, pendingCents = 0, paidCents = 0, refundedCents = 0, validCount = 0;
    const sales = rows.map(r => {
      let status;
      if (r.refunded) { status = 'refunded'; refundedCents += r.commission_amount; }
      else {
        validCount++;
        if (r.paid) { status = 'paid'; paidCents += r.commission_amount; }
        else if (new Date(r.created_at).getTime() + windowMs <= now) { status = 'available'; availableCents += r.commission_amount; }
        else { status = 'pending'; pendingCents += r.commission_amount; }
      }
      return { amount: r.amount, commission: r.commission_amount, paid: r.paid, refunded: !!r.refunded, status, product: r.product, date: r.created_at };
    });
    res.json({
      code: affiliate.code, name: affiliate.name, email: affiliate.email,
      commissionPercent: affiliate.commission_percent, status: affiliate.status,
      link: _affiliateLink(affiliate.code),
      totalSales: validCount,
      availableCommissionCents: availableCents,
      pendingCommissionCents: pendingCents,
      paidCommissionCents: paidCents,
      refundedCommissionCents: refundedCents,
      totalCommissionCents: availableCents + pendingCents + paidCents,
      minPayoutCents: MIN_PAYOUT_CENTS,
      refundWindowDays: REFUND_WINDOW_DAYS,
      payoutMethod: affiliate.payout_method || '',
      payoutDetails: affiliate.payout_details || '',
      pendingPayout: pendingReq ? { amountCents: pendingReq.amount_cents, requestedAt: pendingReq.requested_at } : null,
      stripeConnected: !!affiliate.stripe_account_id,
      sales
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// POST /api/affiliates/connect-onboard — (Bearer token) -> { url }
// Creates (or reuses) a Stripe Connect Express account for the logged-in
// affiliate and returns an onboarding link. Once onboarding completes, their
// commissions are paid automatically at time of sale — no manual payout.
app.post('/api/affiliates/connect-onboard', _authLimiter, async (req, res) => {
  if (!stripe || !supabase) return res.status(500).json({ error: 'Not configured' });
  const code = _affiliateFromAuth(req);
  if (!code) return res.status(401).json({ error: 'Not authenticated' });
  try {
    const { data: aff } = await supabase.from('affiliates').select('code,email,name,stripe_account_id').eq('code', code).maybeSingle();
    if (!aff) return res.status(404).json({ error: 'Affiliate not found' });

    let accountId = aff.stripe_account_id;
    if (!accountId) {
      const account = await stripe.accounts.create({
        type: 'express',
        email: aff.email || undefined,
        business_type: 'individual',
        capabilities: { transfers: { requested: true } }
      });
      accountId = account.id;
      await supabase.from('affiliates').update({ stripe_account_id: accountId }).eq('code', code);
    }

    const origin = req.headers.origin || 'https://aicashsystem.space';
    const accountLink = await stripe.accountLinks.create({
      account: accountId,
      refresh_url: `${origin}/affiliate-dashboard?connect=refresh`,
      return_url: `${origin}/affiliate-dashboard?connect=done`,
      type: 'account_onboarding'
    });
    res.json({ url: accountLink.url });
  } catch (e) {
    addLog(`[Stripe Connect] Onboarding error for "${code}": ${e.message}`, 'affiliate', 'error');
    res.status(500).json({ error: e.message });
  }
});

// Compute an affiliate's available (matured, unpaid, non-refunded) commission in cents.
function _availableFromSales(rows) {
  const now = Date.now();
  const windowMs = REFUND_WINDOW_DAYS * 24 * 60 * 60 * 1000;
  let available = 0;
  (rows || []).forEach(r => {
    if (!r.refunded && !r.paid && new Date(r.created_at).getTime() + windowMs <= now) available += r.commission_amount;
  });
  return available;
}
function _validatePayout(method, details) {
  const m = String(method || '').toLowerCase().trim();
  if (!['paypal', 'bank', 'crypto'].includes(m)) return { ok: false, error: 'Choose a payout method: PayPal, bank or crypto.' };
  const d = String(details || '').trim();
  if (d.length < 3 || d.length > 200) return { ok: false, error: 'Enter valid payout details (3–200 characters).' };
  return { ok: true, method: m, details: d };
}

// POST /api/affiliates/payout-method — save where the affiliate wants to be paid
app.post('/api/affiliates/payout-method', _authLimiter, async (req, res) => {
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const code = _affiliateFromAuth(req);
  if (!code) return res.status(401).json({ error: 'Not authenticated' });
  const v = _validatePayout(req.body?.method, req.body?.details);
  if (!v.ok) return res.status(400).json({ error: v.error });
  try {
    const { error } = await supabase.from('affiliates').update({ payout_method: v.method, payout_details: v.details }).eq('code', code);
    if (error) return res.status(500).json({ error: error.message });
    res.json({ ok: true, method: v.method, details: v.details });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// POST /api/affiliates/request-payout — request payment of the current available balance
app.post('/api/affiliates/request-payout', _authLimiter, async (req, res) => {
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const code = _affiliateFromAuth(req);
  if (!code) return res.status(401).json({ error: 'Not authenticated' });
  try {
    const { data: aff } = await supabase.from('affiliates').select('payout_method,payout_details,status').eq('code', code).maybeSingle();
    if (!aff) return res.status(404).json({ error: 'Affiliate not found' });
    if (aff.status !== 'active') return res.status(403).json({ error: 'This account is suspended.' });
    if (!aff.payout_method || !aff.payout_details) return res.status(400).json({ error: 'Add your payout method first.' });
    const { data: pending } = await supabase.from('payout_requests').select('id').eq('affiliate_code', code).eq('status', 'requested').maybeSingle();
    if (pending) return res.status(409).json({ error: 'You already have a payout request pending.' });
    const { data: sales } = await supabase.from('referral_sales').select('commission_amount,paid,refunded,created_at').eq('affiliate_code', code);
    const available = _availableFromSales(sales);
    if (available < MIN_PAYOUT_CENTS) return res.status(400).json({ error: `You need at least $${(MIN_PAYOUT_CENTS / 100).toFixed(0)} available to request a payout.` });
    const { error } = await supabase.from('payout_requests').insert([{ affiliate_code: code, amount_cents: available, method: aff.payout_method, details: aff.payout_details, status: 'requested' }]);
    if (error) return res.status(500).json({ error: error.message });
    addLog(`Payout requested: ${code} — $${(available / 100).toFixed(2)} via ${aff.payout_method}`, 'affiliate', 'info');
    res.json({ ok: true, amountCents: available });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// ── OWNER PAYOUT ADMIN (protected by BOT_EMAIL_SECRET) ──
function _ownerSecretOk(req) {
  const secret = req.query.secret || req.headers['x-owner-secret'];
  return process.env.BOT_EMAIL_SECRET && secret === process.env.BOT_EMAIL_SECRET;
}
function _csvCell(v) { const s = (v == null ? '' : String(v)).replace(/"/g, '""'); return /[",\n]/.test(s) ? `"${s}"` : s; }

// GET /api/admin/payout-requests.csv?secret=... — export payout requests for the accountant
app.get('/api/admin/payout-requests.csv', async (req, res) => {
  if (!_ownerSecretOk(req)) return res.status(403).json({ error: 'Forbidden — secret required' });
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const { data: reqs } = await supabase.from('payout_requests').select('*').order('requested_at', { ascending: false });
  const { data: affs } = await supabase.from('affiliates').select('code,name,email');
  const map = {}; (affs || []).forEach(a => { map[a.code] = a; });
  const header = ['id', 'requested_at', 'affiliate_code', 'name', 'email', 'amount_usd', 'method', 'details', 'status', 'processed_at', 'note'];
  const lines = [header.join(',')];
  (reqs || []).forEach(r => {
    const a = map[r.affiliate_code] || {};
    lines.push([r.id, r.requested_at, r.affiliate_code, a.name || '', a.email || '', (r.amount_cents / 100).toFixed(2), r.method || '', r.details || '', r.status, r.processed_at || '', r.note || ''].map(_csvCell).join(','));
  });
  res.setHeader('Content-Type', 'text/csv; charset=utf-8');
  res.setHeader('Content-Disposition', 'attachment; filename="payout-requests.csv"');
  res.send(lines.join('\n'));
});

// GET /api/admin/sales.csv?secret=... — export every referral sale for the accountant
app.get('/api/admin/sales.csv', async (req, res) => {
  if (!_ownerSecretOk(req)) return res.status(403).json({ error: 'Forbidden — secret required' });
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const { data } = await supabase.from('referral_sales').select('created_at,affiliate_code,product,amount,commission_amount,paid,refunded,payment_intent_id').order('created_at', { ascending: false });
  const header = ['date', 'affiliate_code', 'product', 'sale_usd', 'commission_usd', 'paid', 'refunded', 'payment_intent_id'];
  const lines = [header.join(',')];
  (data || []).forEach(r => {
    lines.push([r.created_at, r.affiliate_code, r.product || '', (r.amount / 100).toFixed(2), (r.commission_amount / 100).toFixed(2), r.paid ? 'yes' : 'no', r.refunded ? 'yes' : 'no', r.payment_intent_id || ''].map(_csvCell).join(','));
  });
  res.setHeader('Content-Type', 'text/csv; charset=utf-8');
  res.setHeader('Content-Disposition', 'attachment; filename="affiliate-sales.csv"');
  res.send(lines.join('\n'));
});

// POST /api/admin/payouts/:id/paid?secret=... — mark a payout request paid + settle the sales
app.post('/api/admin/payouts/:id/paid', async (req, res) => {
  if (!_ownerSecretOk(req)) return res.status(403).json({ error: 'Forbidden — secret required' });
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  try {
    const { data: pr } = await supabase.from('payout_requests').select('*').eq('id', req.params.id).maybeSingle();
    if (!pr) return res.status(404).json({ error: 'Payout request not found' });
    if (pr.status === 'paid') return res.json({ ok: true, already: true });
    // Settle matured, unpaid, non-refunded sales oldest-first until the paid amount is covered.
    const { data: sales } = await supabase.from('referral_sales').select('id,commission_amount,created_at')
      .eq('affiliate_code', pr.affiliate_code).eq('paid', false).eq('refunded', false).order('created_at', { ascending: true });
    const now = Date.now(); const windowMs = REFUND_WINDOW_DAYS * 24 * 60 * 60 * 1000;
    let acc = 0; const ids = [];
    for (const s of (sales || [])) {
      if (new Date(s.created_at).getTime() + windowMs > now) continue;
      ids.push(s.id); acc += s.commission_amount;
      if (acc >= pr.amount_cents) break;
    }
    if (ids.length) await supabase.from('referral_sales').update({ paid: true }).in('id', ids);
    await supabase.from('payout_requests').update({ status: 'paid', processed_at: new Date().toISOString() }).eq('id', pr.id);
    addLog(`Payout marked paid: ${pr.affiliate_code} — $${(pr.amount_cents / 100).toFixed(2)} (${ids.length} sales settled)`, 'affiliate', 'success');
    res.json({ ok: true, settledSales: ids.length, amountCents: acc });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// GET /api/affiliates/:code/stats — sales + commission summary for one affiliate
app.get('/api/affiliates/:code/stats', async (req, res) => {
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const code = (req.params.code || '').toLowerCase().trim();
  try {
    const { data: affiliate } = await supabase.from('affiliates').select('code,name,commission_percent,status').eq('code', code).maybeSingle();
    if (!affiliate) return res.status(404).json({ error: 'Affiliate code not found' });
    const { data } = await supabase.from('referral_sales').select('amount,commission_amount,paid,created_at').eq('affiliate_code', code).order('created_at', { ascending: false });
    const rows = data || [];
    const totalCommission  = rows.reduce((s, r) => s + r.commission_amount, 0);
    const paidCommission   = rows.filter(r => r.paid).reduce((s, r) => s + r.commission_amount, 0);
    res.json({
      code: affiliate.code, name: affiliate.name, commissionPercent: affiliate.commission_percent, status: affiliate.status,
      totalSales: rows.length,
      totalCommissionCents: totalCommission,
      paidCommissionCents: paidCommission,
      unpaidCommissionCents: totalCommission - paidCommission,
      sales: rows.map(r => ({ amount: r.amount, commission: r.commission_amount, paid: r.paid, date: r.created_at }))
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /api/owner-license — generate a license key for the owner (requires BOT_EMAIL_SECRET)
// ?product=apex-bot (default) or ?product=apex-forex
app.get('/api/owner-license', async (req, res) => {
  const secret = req.query.secret || req.headers['x-owner-secret'];
  const expected = process.env.BOT_EMAIL_SECRET;
  if (!expected || secret !== expected) return res.status(403).json({ error: 'Forbidden — secret required' });
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const product = req.query.product === 'apex-forex' ? 'apex-forex' : 'apex-bot';
  const key = product === 'apex-forex' ? generateForexKey() : generateLicenseKey();
  let dbStatus = 'skipped';
  try {
    const { error: dbErr } = await supabase.from('licenses').insert([{ key, email: 'owner@aicashsystem.space', name: 'Owner', active: true, product }]);
    dbStatus = dbErr ? `warn: ${dbErr.message}` : 'inserted ok';
  } catch (e) {
    dbStatus = `warn: ${e.message}`;
  }
  // Key is HMAC-signed — valid without Supabase. Return it regardless of DB status.
  res.json({ key, product, message: `Add this as LICENSE_KEY for your ${product} bot`, supabase: dbStatus });
});

// POST /api/verify-license — called by the bot on every startup
// Body: { key, product? }  — product is 'apex-bot' | 'apex-forex'
// Primary: HMAC signature check (no DB). Fallback: Supabase for legacy keys.
app.post('/api/verify-license', _licenseLimiter, async (req, res) => {
  const { key, product: claimedProduct } = req.body || {};
  if (!key) return res.json({ valid: false, message: 'No license key provided' });

  // 1. HMAC check — works without any database
  const hmacResult = verifyLicenseKeyHmac(key);
  if (hmacResult.valid) {
    // Product mismatch check: FORX- key on crypto bot (or APEX- on forex) → reject
    if (claimedProduct && hmacResult.product && claimedProduct !== hmacResult.product) {
      return res.json({ valid: false, message: `Wrong license type. This key is for ${hmacResult.product}. Purchase the correct bot at aicashsystem.space` });
    }
    // A valid signature is NOT proof of payment. The Digistore24 IPN handler is the
    // only place that upserts a license as active:true, on event=on_payment. So: if
    // the key exists in our DB as not-yet-paid, reject it.
    if (supabase) {
      try {
        const { data: row } = await supabase.from('licenses')
          .select('active,refunded').eq('key', key).maybeSingle();
        if (row && row.refunded === true) {
          return res.json({ valid: false, message: 'This license was refunded and is no longer active. Repurchase at aicashsystem.space' });
        }
        if (row && row.active === false) {
          return res.json({ valid: false, message: 'Payment not completed yet. If you just paid, wait a minute and tap the link in your email.' });
        }
        // row.active === true, or no row at all (legacy/manual key) → allow through.
      } catch (_) { /* DB hiccup → fall through to fail-open allow below */ }
    }
    if (supabase) {
      supabase.from('licenses')
        .upsert([{ key, active: true, activated_at: new Date().toISOString(), product: hmacResult.product }], { onConflict: 'key' })
        .then(() => {}).catch(() => {});
    }
    return res.json({ valid: true, message: 'License valid', product: hmacResult.product });
  }

  // 2. Supabase fallback — for legacy keys or manual inserts
  if (supabase) {
    try {
      const { data } = await supabase
        .from('licenses').select('active,product').eq('key', key).eq('active', true).single();
      if (data?.active) {
        if (claimedProduct && data.product && claimedProduct !== data.product) {
          return res.json({ valid: false, message: `Wrong license type. This key is for ${data.product}.` });
        }
        return res.json({ valid: true, message: 'License valid (legacy)', product: data.product });
      }
    } catch (_) {}
  }

  return res.json({ valid: false, message: 'Invalid license key. Purchase at aicashsystem.space' });
});


// ── DIGISTORE24 IPN (webhook) ───────────────────────────────────────────────
// Merchant of Record — D24 handles EU VAT/taxes/invoices, we just deliver the
// license. Events (sent as $_POST['event'] equivalent): on_payment (deliver
// license), on_refund / on_chargeback (revoke license).
//
// Signature: sha_sign = SHA-512 of every OTHER param, sorted by key
// (case-insensitive), concatenated as "UPPERKEY=value" per key, then
// "$" + IPN passphrase appended, all hashed once. (Best-effort from public
// docs — D24's own docs site is unreachable from here; verified against the
// first real IPN hit, see the [D24] signature-mismatch log line if it's off.)
function _digistore24VerifySignature(params, passphrase) {
  const { sha_sign, SHASIGN, ...rest } = params;
  if (!sha_sign || !passphrase) return false;
  const keys = Object.keys(rest)
    .filter(k => rest[k] !== '' && rest[k] !== null && rest[k] !== undefined)
    .sort((a, b) => (a > b ? 1 : a < b ? -1 : 0));
  let buf = '';
  for (const k of keys) buf += `${k}=${rest[k]}${passphrase}`;
  const computed = crypto.createHash('sha512').update(buf, 'utf8').digest('hex').toUpperCase();
  return computed === String(sha_sign).toUpperCase();
}

async function handleDigistore24Webhook(req, res) {
  const params = req.body || {};
  const passphrase = process.env.DIGISTORE24_IPN_PASSPHRASE;
  if (!passphrase) { console.error('[D24] Missing DIGISTORE24_IPN_PASSPHRASE'); return res.status(400).send('Webhook not configured'); }

  const sigOk = _digistore24VerifySignature(params, passphrase);
  if (!sigOk) {
    console.error(`[D24] Signature mismatch — raw params: ${JSON.stringify(params).slice(0, 500)}`);
    addLog(`[D24] Signature mismatch — raw params: ${JSON.stringify(params).slice(0, 500)}`, 'payment', 'error');
    return res.status(401).send('Invalid signature');
  }

  try {
    const event = params.event || '';
    const email = params.email || params.buyer_email || '';
    const buyerName = [params.first_name, params.last_name].filter(Boolean).join(' ')
      || params.buyer_first_name || 'there';
    const orderId = String(params.order_id || '');
    const productId = String(params.product_id || '');
    const amount = Number(params.amount || params.amount_netto || 0);

    // Map D24 product IDs to our products.
    //   DIGISTORE24_PRODUCT_CRYPTO=714550  (the $297 crypto bot)
    //   DIGISTORE24_PRODUCT_FOREX=<set once the forex product is created>
    const cryptoProductId = process.env.DIGISTORE24_PRODUCT_CRYPTO || '714550';
    const forexProductId = process.env.DIGISTORE24_PRODUCT_FOREX || '';
    let product = null;
    if (productId && productId === cryptoProductId) product = 'apex-bot';
    else if (productId && forexProductId && productId === forexProductId) product = 'apex-forex';

    if (event === 'on_payment' && orderId && product) {
      const isForex = product === 'apex-forex';
      const piRef = `d24_${orderId}`;

      // Idempotency: a retried IPN for the same order must not re-generate/re-email.
      let licenseKey;
      if (supabase) {
        const { data: existing } = await supabase.from('licenses').select('key').eq('payment_intent_id', piRef).maybeSingle();
        if (existing?.key) licenseKey = existing.key;
      }
      const isNew = !licenseKey;
      if (!licenseKey) licenseKey = isForex ? generateForexKey() : generateLicenseKey();

      if (supabase) {
        const { error } = await supabase.from('licenses').upsert([{
          key: licenseKey, active: true, activated_at: new Date().toISOString(),
          email: email || '', name: buyerName, product, payment_intent_id: piRef
        }], { onConflict: 'key' });
        if (error) addLog(`[D24] License DB error: ${error.message}`, 'license', 'error');
      }
      addLog(`[D24] License activated: ${licenseKey} for ${email} (${product})`, 'license', 'success');

      // Affiliate commission — D24's own affiliate marketplace already pays its
      // affiliates directly, so this only applies to refs from our own funnel.
      const ref = (params.aff || params.affiliate || params.custom_aff || '').toLowerCase().trim();
      if (isNew && ref && supabase) {
        try {
          const { data: aff } = await supabase.from('affiliates').select('code,commission_percent,status').eq('code', ref).maybeSingle();
          if (aff && aff.status === 'active') {
            const pct = Number(aff.commission_percent) > 0 ? Number(aff.commission_percent) : 30;
            const commission = Math.round(amount * 100 * pct / 100); // amount is in whole currency units
            await supabase.from('referral_sales').upsert([{
              affiliate_code: aff.code, license_key: licenseKey, payment_intent_id: piRef,
              product, amount: Math.round(amount * 100), commission_amount: commission
            }], { onConflict: 'payment_intent_id' });
            addLog(`[D24] Affiliate sale: ${aff.code} earned $${(commission / 100).toFixed(2)} on ${product}`, 'affiliate', 'success');
            _notifyAffiliateSale(aff.code, product, commission);
          }
        } catch (e) { addLog(`[D24] Affiliate error: ${e.message}`, 'affiliate', 'error'); }
      }

      if (isNew && email) {
        const html = isForex
          ? _buildForexEmailHtml(_he(buyerName), _he(email), licenseKey)
          : _buildBotEmailHtml(_he(buyerName), _he(email), licenseKey);
        const subject = isForex
          ? '🤖 Your Apex Forex Bot — License Key inside'
          : '🤖 Your Apex Trade Bot — License Key inside';
        const result = await _sendEmail({ to: email, subject, html, fromName: 'Apex.Bot' });
        if (!result.ok) {
          addLog(`[D24] Email NOT sent for ${email} — ${result.error}`, 'email', 'error');
          _notifyAdminAlert(
            `⚠️ Customer paid but the license email FAILED to send.\n\n` +
            `Product: ${isForex ? 'Forex' : 'Crypto'}\nEmail: ${email}\nOrder: ${orderId}\n` +
            `License key: ${licenseKey}\nError: ${result.error}\n\n` +
            `Send the key to them manually until this is fixed.`
          );
        } else addLog(`[D24] ${isForex ? 'Forex' : 'Crypto'} email sent to ${email}`, 'email', 'success');
      }
      if (isNew) addLog(`[D24] ${isForex ? 'Forex' : 'Crypto'} Bot sold: ${email} — key: ${licenseKey}`, 'payment', 'success');
    } else if (event === 'on_payment') {
      addLog(`[D24] on_payment for unmapped product_id=${productId} order=${orderId} — set DIGISTORE24_PRODUCT_CRYPTO/FOREX`, 'payment', 'warn');
    }

    if ((event === 'on_refund' || event === 'on_chargeback') && orderId) {
      const piRef = `d24_${orderId}`;
      if (supabase) {
        const { data: revoked } = await supabase.from('licenses')
          .update({ active: false, refunded: true, refunded_at: new Date().toISOString() })
          .eq('payment_intent_id', piRef).select('key,product');
        if (revoked?.length) addLog(`[D24] License revoked (${event}): ${revoked[0].key} (${revoked[0].product})`, 'license', 'warn');
        await supabase.from('referral_sales')
          .update({ refunded: true, refunded_at: new Date().toISOString() })
          .eq('payment_intent_id', piRef);
      }
    }

    res.send('OK');
  } catch (e) {
    console.error('[D24] Webhook error:', e);
    res.status(500).send('Internal error');
  }
}
app.post('/digistore24-webhook', (req, res, next) => {
  console.log(`[D24] Incoming request — content-type=${req.headers['content-type']} content-length=${req.headers['content-length']} ip=${req.ip}`);
  next();
}, express.urlencoded({ extended: true }), (req, res, next) => {
  console.log(`[D24] Parsed body: ${JSON.stringify(req.body).slice(0, 500)}`);
  next();
}, handleDigistore24Webhook);

// ── STRIPE CHECKOUT ─────────────────────────────────────────────────────────
// We are the merchant of record here (unlike D24) — Stripe just processes the
// card. Below the Romanian VAT-exemption threshold this needs no special tax
// handling; see the affiliate/PFA discussion elsewhere for when that changes.
// Stripe is the primary/default processor now — ApexTradingSuite (acct_1TSAWQGpBbs5xtI5),
// business profile corrected to match what's actually sold, live and charges_enabled.
// Price IDs default to the ones created on that account; override via env if recreated.
const STRIPE_PRICE_IDS = {
  'apex-crypto': process.env.STRIPE_PRICE_CRYPTO || 'price_1TfI9IGpBbs5xtI5IhufmuL8',
  'apex-forex': process.env.STRIPE_PRICE_FOREX || 'price_1Tge4PGpBbs5xtI5jAjgndKZ'
};
// Matches the one_time_price unit_amount on each Stripe Price above — used to
// compute an affiliate's application_fee_amount without an extra API round-trip.
const STRIPE_PRODUCT_AMOUNTS_CENTS = { 'apex-crypto': 29700, 'apex-forex': 49700 };

// ── DODO PAYMENTS CHECKOUT ──────────────────────────────────────────────────
// Dodo Payments permanently rejected this business ("We do not support auto
// trading bots and related services") — this path is dead and only kept as an
// inert fallback in case DODO_PAYMENTS_API_KEY is ever repurposed for something else.
const DODO_PRODUCT_IDS = {
  'apex-crypto': process.env.DODO_PRODUCT_CRYPTO || 'pdt_0NkMezDmL7t5NGc8rxrXc',
  'apex-forex': process.env.DODO_PRODUCT_FOREX || 'pdt_0NkMezHBscxIfkG8CA7X7'
};

// POST /api/checkout/create-session — { product: 'apex-crypto'|'apex-forex', ref? } -> { url }
app.post('/api/checkout/create-session', _authLimiter, async (req, res) => {
  const product = String(req.body?.product || '');
  const ref = String(req.body?.ref || '').toLowerCase().trim().slice(0, 40);
  const endorselyReferral = String(req.body?.endorsely_referral || '').slice(0, 200);
  const origin = req.headers.origin || 'https://aicashsystem.space';

  if (stripe) {
    const priceId = STRIPE_PRICE_IDS[product];
    if (!priceId) return res.status(400).json({ error: 'Unknown or unavailable product' });
    try {
      const sessionParams = {
        mode: 'payment',
        line_items: [{ price: priceId, quantity: 1 }],
        success_url: `${origin}/thank-you?product=${encodeURIComponent(product)}&session_id={CHECKOUT_SESSION_ID}`,
        cancel_url: `${origin}/${product === 'apex-forex' ? 'forex' : ''}`,
        customer_creation: 'always'
      };

      // Stripe Connect: if this ref belongs to an affiliate who finished onboarding
      // their own Stripe account, split the commission off at time of payment —
      // it lands in their account directly, no manual payout tracking needed.
      let connectApplied = false;
      if (ref && supabase) {
        const { data: aff } = await supabase.from('affiliates')
          .select('stripe_account_id,commission_percent,status').eq('code', ref).maybeSingle();
        if (aff?.status === 'active' && aff.stripe_account_id) {
          try {
            const acct = await stripe.accounts.retrieve(aff.stripe_account_id);
            if (acct.capabilities?.transfers === 'active') {
              const pct = Number(aff.commission_percent) > 0 ? Number(aff.commission_percent) : 30;
              const unitAmount = STRIPE_PRODUCT_AMOUNTS_CENTS[product] || 0;
              sessionParams.payment_intent_data = {
                application_fee_amount: Math.round(unitAmount * pct / 100),
                transfer_data: { destination: aff.stripe_account_id }
              };
              connectApplied = true;
            }
          } catch (e) { addLog(`[Stripe] Connect lookup failed for ref "${ref}": ${e.message}`, 'affiliate', 'warn'); }
        }
      }
      sessionParams.metadata = { product, ref, connectApplied: connectApplied ? '1' : '0' };
      if (endorselyReferral) sessionParams.metadata.endorsely_referral = endorselyReferral;

      const session = await stripe.checkout.sessions.create(sessionParams);
      return res.json({ url: session.url });
    } catch (e) {
      addLog(`[Stripe] Checkout session error: ${e.message}`, 'payment', 'error');
      return res.status(500).json({ error: 'Could not start checkout. Please try again.' });
    }
  }

  if (dodopayments) {
    const productId = DODO_PRODUCT_IDS[product];
    if (!productId) return res.status(400).json({ error: 'Unknown or unavailable product' });
    try {
      const session = await dodopayments.checkoutSessions.create({
        product_cart: [{ product_id: productId, quantity: 1 }],
        return_url: `${origin}/thank-you?product=${encodeURIComponent(product)}`,
        metadata: { product, ref }
      });
      return res.json({ url: session.checkout_url });
    } catch (e) {
      addLog(`[Dodo] Checkout session error: ${e.message}`, 'payment', 'error');
      return res.status(500).json({ error: 'Could not start checkout. Please try again.' });
    }
  }

  return res.status(500).json({ error: 'Payments are not configured' });
});

// GET /api/order-status?session_id=cs_...|order_id=... -> { ready, licenseKey? }
// Polled by thank-you.html. Only returns data for a piRef the caller can already
// prove (a Stripe session_id or D24 order_id from their own redirect) — not a
// general lookup surface.
app.get('/api/order-status', _codeLimiter, async (req, res) => {
  const sessionId = String(req.query?.session_id || '');
  const orderId = String(req.query?.order_id || '');
  if (!sessionId && !orderId) return res.status(400).json({ ready: false, error: 'Missing session_id or order_id' });
  if (!supabase) return res.json({ ready: false });

  try {
    let piRef;
    if (sessionId) {
      if (!stripe) return res.json({ ready: false });
      const session = await stripe.checkout.sessions.retrieve(sessionId);
      if (!session.payment_intent) return res.json({ ready: false });
      piRef = `stripe_${session.payment_intent}`;
    } else {
      piRef = `d24_${orderId}`;
    }

    const { data } = await supabase.from('licenses').select('key,active').eq('payment_intent_id', piRef).maybeSingle();
    if (data?.key && data.active) return res.json({ ready: true, licenseKey: data.key });
    return res.json({ ready: false });
  } catch (e) {
    addLog(`[order-status] ${e.message}`, 'payment', 'error');
    return res.json({ ready: false });
  }
});

// Fulfillment shared by the Stripe and Dodo Payments webhooks — mirrors
// handleDigistore24Webhook's on_payment path (license generation, affiliate
// commission, license email). `provider` only controls the log/alert prefix.
async function _fulfillOrder({ provider, piRef, product, email, buyerName, amountCents, ref, connectApplied }) {
  const isForex = product === 'apex-forex';
  let licenseKey;
  if (supabase) {
    const { data: existing } = await supabase.from('licenses').select('key').eq('payment_intent_id', piRef).maybeSingle();
    if (existing?.key) licenseKey = existing.key;
  }
  const isNew = !licenseKey;
  if (!licenseKey) licenseKey = isForex ? generateForexKey() : generateLicenseKey();

  if (supabase) {
    const { error } = await supabase.from('licenses').upsert([{
      key: licenseKey, active: true, activated_at: new Date().toISOString(),
      email: email || '', name: buyerName || 'there', product, payment_intent_id: piRef
    }], { onConflict: 'key' });
    if (error) addLog(`[${provider}] License DB error: ${error.message}`, 'license', 'error');
  }
  addLog(`[${provider}] License activated: ${licenseKey} for ${email} (${product})`, 'license', 'success');

  if (isNew && ref && supabase) {
    try {
      const { data: aff } = await supabase.from('affiliates').select('code,commission_percent,status').eq('code', ref).maybeSingle();
      if (aff && aff.status === 'active') {
        const pct = Number(aff.commission_percent) > 0 ? Number(aff.commission_percent) : 30;
        const commission = Math.round(amountCents * pct / 100);
        await supabase.from('referral_sales').upsert([{
          affiliate_code: aff.code, license_key: licenseKey, payment_intent_id: piRef,
          product, amount: amountCents, commission_amount: commission,
          // Stripe Connect already transferred this commission directly to the
          // affiliate's own account at time of payment — no manual payout owed.
          paid: !!connectApplied
        }], { onConflict: 'payment_intent_id' });
        addLog(`[${provider}] Affiliate sale: ${aff.code} earned $${(commission / 100).toFixed(2)} on ${product}${connectApplied ? ' (auto-paid via Stripe Connect)' : ''}`, 'affiliate', 'success');
        _notifyAffiliateSale(aff.code, product, commission);
      }
    } catch (e) { addLog(`[${provider}] Affiliate error: ${e.message}`, 'affiliate', 'error'); }
  }

  if (isNew && email) {
    const html = isForex
      ? _buildForexEmailHtml(_he(buyerName || 'there'), _he(email), licenseKey)
      : _buildBotEmailHtml(_he(buyerName || 'there'), _he(email), licenseKey);
    const subject = isForex
      ? '🤖 Your Apex Forex Bot — License Key inside'
      : '🤖 Your Apex Trade Bot — License Key inside';
    const result = await _sendEmail({ to: email, subject, html, fromName: 'Apex.Bot' });
    if (!result.ok) {
      addLog(`[${provider}] Email NOT sent for ${email} — ${result.error}`, 'email', 'error');
      _notifyAdminAlert(
        `⚠️ Customer paid (${provider}) but the license email FAILED to send.\n\n` +
        `Product: ${isForex ? 'Forex' : 'Crypto'}\nEmail: ${email}\nRef: ${piRef}\n` +
        `License key: ${licenseKey}\nError: ${result.error}\n\nSend the key to them manually until this is fixed.`
      );
    } else addLog(`[${provider}] ${isForex ? 'Forex' : 'Crypto'} email sent to ${email}`, 'email', 'success');
  }
  if (isNew) addLog(`[${provider}] ${isForex ? 'Forex' : 'Crypto'} Bot sold: ${email} — key: ${licenseKey}`, 'payment', 'success');
}
const _fulfillStripeOrder = (args) => _fulfillOrder({ provider: 'Stripe', ...args });
const _fulfillDodoOrder = (args) => _fulfillOrder({ provider: 'Dodo', ...args });

app.post('/stripe-webhook', express.raw({ type: 'application/json' }), async (req, res) => {
  if (!stripe) return res.status(500).send('Stripe not configured');
  const sig = req.headers['stripe-signature'];
  const whSecret = process.env.STRIPE_WEBHOOK_SECRET;
  if (!whSecret) { console.error('[Stripe] Missing STRIPE_WEBHOOK_SECRET'); return res.status(400).send('Webhook not configured'); }
  let event;
  try {
    event = stripe.webhooks.constructEvent(req.body, sig, whSecret);
  } catch (e) {
    addLog(`[Stripe] Webhook signature verification failed: ${e.message}`, 'payment', 'error');
    return res.status(400).send(`Webhook Error: ${e.message}`);
  }

  try {
    if (event.type === 'checkout.session.completed') {
      const session = event.data.object;
      const product = session.metadata?.product || '';
      const ref = session.metadata?.ref || '';
      const connectApplied = session.metadata?.connectApplied === '1';
      if (STRIPE_PRICE_IDS[product]) {
        const piRef = `stripe_${session.payment_intent || session.id}`;
        const email = session.customer_details?.email || '';
        const buyerName = session.customer_details?.name || 'there';
        const amountCents = Number(session.amount_total || 0);
        await _fulfillStripeOrder({ piRef, product, email, buyerName, amountCents, ref, connectApplied });
      } else {
        addLog(`[Stripe] checkout.session.completed for unmapped product="${product}" session=${session.id}`, 'payment', 'warn');
      }
    } else if (event.type === 'charge.refunded' || event.type === 'charge.dispute.created') {
      const obj = event.data.object;
      const paymentIntentId = obj.payment_intent || '';
      if (paymentIntentId && supabase) {
        const piRef = `stripe_${paymentIntentId}`;
        const { data: revoked } = await supabase.from('licenses')
          .update({ active: false, refunded: true, refunded_at: new Date().toISOString() })
          .eq('payment_intent_id', piRef).select('key,product');
        if (revoked?.length) addLog(`[Stripe] License revoked (${event.type}): ${revoked[0].key} (${revoked[0].product})`, 'license', 'warn');
        await supabase.from('referral_sales')
          .update({ refunded: true, refunded_at: new Date().toISOString() })
          .eq('payment_intent_id', piRef);
      }
    }
    res.json({ received: true });
  } catch (e) {
    console.error('[Stripe] Webhook error:', e);
    res.status(500).send('Internal error');
  }
});

// ── DODO PAYMENTS WEBHOOK ───────────────────────────────────────────────────
// Dodo signs webhooks per the Standard Webhooks spec (webhook-id/webhook-timestamp/
// webhook-signature headers), verified here via the SDK's webhooks.unwrap(), which
// falls back to the webhookKey passed at client construction when `key` is omitted.
app.post('/dodo-webhook', express.raw({ type: 'application/json' }), async (req, res) => {
  if (!dodopayments) return res.status(500).send('Dodo Payments not configured');
  let event;
  try {
    event = await dodopayments.webhooks.unwrap(req.body.toString('utf8'), { headers: req.headers });
  } catch (e) {
    addLog(`[Dodo] Webhook signature verification failed: ${e.message}`, 'payment', 'error');
    return res.status(400).send(`Webhook Error: ${e.message}`);
  }

  try {
    const type = event.type || '';
    const data = event.data || {};

    if (type === 'payment.succeeded') {
      const productId = data.product_cart?.[0]?.product_id || '';
      const product = Object.keys(DODO_PRODUCT_IDS).find(k => DODO_PRODUCT_IDS[k] === productId) || '';
      if (product) {
        const piRef = `dodo_${data.payment_id}`;
        const email = data.customer?.email || '';
        const buyerName = data.customer?.name || 'there';
        const amountCents = Number(data.total_amount || 0);
        const ref = data.metadata?.ref || '';
        await _fulfillDodoOrder({ piRef, product, email, buyerName, amountCents, ref });
      } else {
        addLog(`[Dodo] payment.succeeded for unmapped product_id="${productId}" payment=${data.payment_id}`, 'payment', 'warn');
      }
    } else if (type === 'refund.succeeded' || type === 'dispute.opened') {
      const paymentId = data.payment_id || '';
      if (paymentId && supabase) {
        const piRef = `dodo_${paymentId}`;
        const { data: revoked } = await supabase.from('licenses')
          .update({ active: false, refunded: true, refunded_at: new Date().toISOString() })
          .eq('payment_intent_id', piRef).select('key,product');
        if (revoked?.length) addLog(`[Dodo] License revoked (${type}): ${revoked[0].key} (${revoked[0].product})`, 'license', 'warn');
        await supabase.from('referral_sales')
          .update({ refunded: true, refunded_at: new Date().toISOString() })
          .eq('payment_intent_id', piRef);
      }
    }
    res.json({ received: true });
  } catch (e) {
    console.error('[Dodo] Webhook error:', e);
    res.status(500).send('Internal error');
  }
});

// ════════════════════════════════════════
// VIDEO DOWNLOAD ROUTES (Veo 3 generated)
// ════════════════════════════════════════

const VEO_FILES = {
  v1: 'okco5vw2ygdo',
  v2: 'kb3wyz27b6rg',
  v3: 'wish204mx53o',
  v4: 'mo5kg30u0q2x',
  v5: 'wehowxf92z6t',
  v6: 'ki993zeg87pw',
  v7: 'hcu69oshg8qf',
};

app.get('/download/:id', requireCourse('any'), async (req, res) => {
  const fileId = VEO_FILES[req.params.id];
  if (!fileId) return res.status(404).json({ error: 'Video not found' });
  const apiKey = process.env.GOOGLE_AI_API_KEY;
  if (!apiKey) return res.status(500).json({ error: 'API key not configured' });
  try {
    const url = `https://generativelanguage.googleapis.com/v1beta/files/${fileId}:download?alt=media&key=${apiKey}`;
    const response = await fetch(url);
    if (!response.ok) return res.status(502).json({ error: 'Video expired or unavailable' });
    res.setHeader('Content-Type', 'video/mp4');
    res.setHeader('Content-Disposition', `attachment; filename="aicash_ugc_${req.params.id}.mp4"`);
    const { Readable } = require('stream');
    const stream = Readable.fromWeb(response.body);
    stream.on('error', () => { if (!res.headersSent) res.status(500).end(); });
    stream.pipe(res);
  } catch (e) {
    if (!res.headersSent) res.status(500).json({ error: 'Download failed' });
  }
});

app.get('/descarcare', requireCourse('any'), (req, res) => {
  const videos = [
    { id: 'v1', title: '"I Made $300 Selling AI Bots"', desc: 'Hook direct · 8s' },
    { id: 'v2', title: '"One Skill Changes Everything"', desc: 'Empatie · 8s' },
    { id: 'v3', title: '"I Failed First"', desc: 'Vulnerabil · 8s' },
    { id: 'v4', title: '"Nobody Teaches You This"', desc: 'Educational · 8s' },
    { id: 'v5', title: '"What Would You Do?"', desc: 'Aspirational · 8s' },
    { id: 'v6', title: '"2025 Reality Check"', desc: 'Urgenta · 8s' },
    { id: 'v7', title: '"To the Version of Me"', desc: 'Emotional · 8s' },
  ];
  const cards = videos.map(v => `
    <div style="background:#111;border:1px solid rgba(200,169,110,.2);border-radius:12px;padding:20px;display:flex;align-items:center;justify-content:space-between;gap:16px">
      <div>
        <div style="color:#C8A96E;font-weight:700;font-size:15px">${v.title}</div>
        <div style="color:#666;font-size:12px;margin-top:4px">${v.desc} · Veo 3 · 9:16</div>
      </div>
      <a href="/download/${v.id}" style="background:linear-gradient(135deg,#8A6A2E,#E8CB8A);color:#000;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:700;font-size:12px;white-space:nowrap">⬇ Download</a>
    </div>`).join('');
  res.send(`<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Download Videoclipuri TikTok</title></head>
  <body style="background:#080808;color:#F5F0E8;font-family:sans-serif;padding:24px 16px;max-width:600px;margin:0 auto">
    <h1 style="color:#C8A96E;text-align:center;font-size:20px;margin-bottom:4px">Videoclipuri TikTok</h1>
    <p style="text-align:center;color:#666;font-size:12px;margin-bottom:24px">Generate cu Veo 3 · Descarca pe telefon</p>
    <div style="display:flex;flex-direction:column;gap:12px">${cards}</div>
    <p style="text-align:center;color:#444;font-size:11px;margin-top:24px">Disponibile 48 ore · aicashsystem.space</p>
  </body></html>`);
});

// Diagnostic route — admin only
app.get('/debug', auth, (req, res) => {
  res.json({ ok: true, env: process.env.NODE_ENV, port: process.env.PORT });
});

// Favicon + OG image (3-candle logo)
const _LOGO_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#060608"/><rect x="3" y="19" width="5" height="10" rx="2.5" fill="#ff2d4f" opacity=".45"/><rect x="11.5" y="12" width="5" height="17" rx="2.5" fill="#ff2d4f" opacity=".72"/><rect x="20" y="6" width="5" height="23" rx="2.5" fill="#ff2d4f"/><circle cx="22.5" cy="5" r="3.1" fill="#ff5c74"/></svg>';
const _OG_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630"><rect width="1200" height="630" fill="#060608"/><rect x="480" y="340" width="60" height="190" rx="12" fill="#ff2d4f" opacity=".45"/><rect x="570" y="220" width="60" height="310" rx="12" fill="#ff2d4f" opacity=".72"/><rect x="660" y="120" width="60" height="410" rx="12" fill="#ff2d4f"/><circle cx="690" cy="96" r="34" fill="#ff5c74"/><text x="600" y="520" font-family="system-ui,sans-serif" font-weight="700" font-size="38" fill="#f5f5f7" text-anchor="middle">Apex Trading Suite</text><text x="600" y="568" font-family="system-ui,sans-serif" font-size="22" fill="#9696a0" text-anchor="middle">Fully-Hosted AI Trading Bots · Crypto $297 · Forex $497</text></svg>';
app.get('/favicon.svg', (req, res) => { res.setHeader('Content-Type','image/svg+xml'); res.setHeader('Cache-Control','public,max-age=86400'); res.end(_LOGO_SVG); });
app.get('/favicon.ico', (req, res) => { res.setHeader('Content-Type','image/svg+xml'); res.setHeader('Cache-Control','public,max-age=86400'); res.end(_LOGO_SVG); });
app.get('/og.svg', (req, res) => { res.setHeader('Content-Type','image/svg+xml'); res.setHeader('Cache-Control','public,max-age=3600'); res.end(_OG_SVG); });
app.get('/og.png', (req, res) => { res.sendFile(path.join(__dirname, 'html', 'og.png'), { headers: { 'Content-Type': 'image/png', 'Cache-Control': 'public,max-age=86400' } }); });
app.get('/apple-touch-icon.png', (req, res) => { res.setHeader('Content-Type','image/svg+xml'); res.setHeader('Cache-Control','public,max-age=86400'); res.end(_LOGO_SVG); });

// Root — serve AiCash System landing page
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'html', 'index.html'), { headers: { 'Cache-Control': 'no-store' } });
});

// /index and /index.html also serve the landing page (prevent publicPages override)
app.get('/index', (req, res) => {
  res.sendFile(path.join(__dirname, 'html', 'index.html'), { headers: { 'Cache-Control': 'no-store' } });
});
app.get('/index.html', (req, res) => {
  res.sendFile(path.join(__dirname, 'html', 'index.html'), { headers: { 'Cache-Control': 'no-store' } });
});

// Landing sub-pages (served from html/)
['features','strategies','faq','security','promo-16x9'].forEach(p => {
  app.get(`/${p}`, (req, res) => res.sendFile(path.join(__dirname, 'html', `${p}.html`), { headers: { 'Cache-Control': 'no-store' } }));
  app.get(`/${p}.html`, (req, res) => res.sendFile(path.join(__dirname, 'html', `${p}.html`), { headers: { 'Cache-Control': 'no-store' } }));
});

// /intro redirects to the homepage — the old separate intro page is retired;
// the cinematic curtain intro now lives on the homepage itself.
app.get(['/intro', '/intro.html'], (req, res) => res.redirect(301, '/'));

// Configurators (linked from bot delivery emails — license-gated client-side)
app.get('/configurator', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'configurator.html'));
});
app.get('/configurator-forex', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'configurator-forex.html'));
});

// POST /api/demo/generate — public, rate-limited (3 req/IP/day)
const _demoLimiter = rateLimit({ windowMs: 24*60*60*1000, max: 5, standardHeaders: true, legacyHeaders: false,
  handler: (req,res) => res.status(429).json({ error: 'Demo limit reached. Get full access at aicashsystem.space' }) });
app.post('/api/demo/generate', _demoLimiter, async (req, res) => {
  const { desc } = req.body;
  if (!desc || desc.length < 10) return res.status(400).json({ error: 'Describe your automation' });
  const prompt = `You are an expert Make.com automation consultant. Analyze this request and return a plan.
AUTOMATION REQUEST: "${desc.slice(0,300)}"
RULES: Setup price $300-$1500. Monthly retainer min $100/month. Outreach: human, 2-3 sentences, specific.
Return ONLY valid JSON, no markdown:
{"what":"2-3 sentences what this automation does","setupPrice":"$XXX–$XXX","monthlyPrice":"$XXX/month","outreach":"Personalized cold outreach, 2-3 sentences, human tone, mention their specific business"}`;
  try {
    if (OPENAI_KEY) {
      const r = await fetch('https://api.openai.com/v1/chat/completions', {
        method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer '+OPENAI_KEY},
        body: JSON.stringify({ model:'gpt-4o-mini', max_tokens:400, response_format:{type:'json_object'}, messages:[{role:'user',content:prompt}] })
      });
      const d = await r.json();
      if (d.choices?.[0]) { try { return res.json(JSON.parse(d.choices[0].message.content)); } catch(e){} }
    }
    if (anthropic) {
      const msg = await anthropic.messages.create({ model:'claude-haiku-4-5-20251001', max_tokens:400, messages:[{role:'user',content:prompt}] });
      try { return res.json(JSON.parse(msg.content[0].text)); } catch(e){}
    }
    return res.status(500).json({ error: 'AI unavailable' });
  } catch(e) { return res.status(500).json({ error: 'Generation failed' }); }
});

// ── CREATIFY API ROUTES ──
// Credentials can come from env vars OR from client headers (X-Creatify-Id / X-Creatify-Key)
function _creatifyHdrs(req) {
  const id  = req.headers['x-creatify-id']  || CREATIFY_API_ID;
  const key = req.headers['x-creatify-key'] || CREATIFY_API_KEY;
  return { 'X-API-ID': id, 'X-API-KEY': key, 'Content-Type': 'application/json', Accept: 'application/json' };
}
function _creatifyCreds(req) {
  return (req.headers['x-creatify-id'] || CREATIFY_API_ID) &&
         (req.headers['x-creatify-key'] || CREATIFY_API_KEY);
}

app.get('/api/creatify/avatars', async (req, res) => {
  if (!_creatifyCreds(req)) return res.status(503).json({ error: 'no_creds' });
  try {
    const r = await fetch('https://api.creatify.ai/api/ai-avatars/', { headers: _creatifyHdrs(req) });
    const d = await r.json();
    res.json(d);
  } catch(e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/creatify/create', async (req, res) => {
  if (!_creatifyCreds(req)) return res.status(503).json({ error: 'no_creds' });
  const { script, persona_id, aspect_ratio, voice_id } = req.body;
  if (!script || script.length < 10) return res.status(400).json({ error: 'Script too short' });
  try {
    const body = {
      name: 'Blueprint Studio UGC ' + Date.now(),
      script,
      aspect_ratio: aspect_ratio || '9:16',
      ...(persona_id && { persona_id }),
      ...(voice_id   && { voice_id }),
    };
    const r = await fetch('https://api.creatify.ai/api/ai-ads/', {
      method: 'POST', headers: _creatifyHdrs(req), body: JSON.stringify(body)
    });
    const d = await r.json();
    if (!r.ok) return res.status(r.status).json(d);
    res.json(d);
  } catch(e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/creatify/render/:id', async (req, res) => {
  if (!_creatifyCreds(req)) return res.status(503).json({ error: 'no_creds' });
  try {
    const r = await fetch(`https://api.creatify.ai/api/ai-ads/${req.params.id}/render/`, {
      method: 'POST', headers: _creatifyHdrs(req)
    });
    const d = await r.json();
    res.json(d);
  } catch(e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/creatify/status/:id', async (req, res) => {
  if (!_creatifyCreds(req)) return res.status(503).json({ error: 'no_creds' });
  try {
    const r = await fetch(`https://api.creatify.ai/api/ai-ads/${req.params.id}/`, { headers: _creatifyHdrs(req) });
    const d = await r.json();
    res.json(d);
  } catch(e) { res.status(500).json({ error: e.message }); }
});
// ── HEYGEN API ROUTES ──
const _heyHeaders = () => ({ 'X-Api-Key': HEYGEN_KEY, 'Content-Type': 'application/json', 'Accept': 'application/json' });

app.get('/api/heygen/avatars', async (req, res) => {
  if (!HEYGEN_KEY) return res.status(503).json({ error: 'HeyGen key not configured' });
  try {
    const r = await fetch('https://api.heygen.com/v2/avatars', { headers: _heyHeaders() });
    const d = await r.json();
    res.json(d);
  } catch(e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/heygen/voices', async (req, res) => {
  if (!HEYGEN_KEY) return res.status(503).json({ error: 'HeyGen key not configured' });
  try {
    const r = await fetch('https://api.heygen.com/v2/voices', { headers: _heyHeaders() });
    const d = await r.json();
    res.json(d);
  } catch(e) { res.status(500).json({ error: e.message }); }
});

app.post('/api/heygen/generate', async (req, res) => {
  if (!HEYGEN_KEY) return res.status(503).json({ error: 'HeyGen key not configured' });
  const { script, avatar_id, voice_id } = req.body;
  if (!script || script.length < 10) return res.status(400).json({ error: 'Script too short' });
  try {
    const body = {
      video_inputs: [{
        character: { type: 'avatar', avatar_id: avatar_id || 'Eric_public_pro2_20230608', avatar_style: 'normal' },
        voice: { type: 'text', input_text: script, voice_id: voice_id || '2d5b0e6cf36f460aa7fc47e3eee4ba54', speed: 0.95 },
        background: { type: 'color', value: '#060606' }
      }],
      dimension: { width: 720, height: 1280 },
      test: false
    };
    const r = await fetch('https://api.heygen.com/v2/video/generate', {
      method: 'POST', headers: _heyHeaders(), body: JSON.stringify(body)
    });
    const d = await r.json();
    if (d.error) return res.status(400).json({ error: d.error });
    res.json({ video_id: d.data?.video_id || d.video_id });
  } catch(e) { res.status(500).json({ error: e.message }); }
});

app.get('/api/heygen/status/:id', async (req, res) => {
  const key = req.headers['x-heygen-key'] || HEYGEN_KEY;
  if (!key) return res.status(503).json({ error: 'HeyGen key not configured' });
  const hdrs = { 'X-Api-Key': key, 'Accept': 'application/json' };
  try {
    const r = await fetch(`https://api.heygen.com/v1/video_status.get?video_id=${req.params.id}`, { headers: hdrs });
    const d = await r.json();
    res.json(d.data || d);
  } catch(e) { res.status(500).json({ error: e.message }); }
});

// POST /api/heygen/photo-generate — talking photo video from base64 image
// Body: { image_b64, mime_type, script, voice_id }
app.post('/api/heygen/photo-generate', async (req, res) => {
  const key = req.headers['x-heygen-key'] || HEYGEN_KEY;
  if (!key) return res.status(503).json({ error: 'HeyGen key not configured' });
  const { image_b64, mime_type = 'image/jpeg', script, voice_id } = req.body;
  if (!image_b64) return res.status(400).json({ error: 'image_b64 required' });
  if (!script || script.length < 5) return res.status(400).json({ error: 'script required' });
  try {
    const imgBuf = Buffer.from(image_b64, 'base64');

    // Step 1: upload image as binary to HeyGen asset endpoint
    const upResp = await fetch('https://upload.heygen.com/v1/asset', {
      method: 'POST',
      headers: { 'X-Api-Key': key, 'Content-Type': mime_type, 'Accept': 'application/json' },
      body: imgBuf
    });
    const upData = await upResp.json();
    const asset_id = upData.data?.id || upData.id;
    if (!asset_id) return res.status(400).json({ error: 'Photo upload failed', detail: upData });

    // Step 2: generate talking photo video 9:16
    const genBody = {
      video_inputs: [{
        character: { type: 'talking_photo', talking_photo_id: asset_id },
        voice: { type: 'text', input_text: script, voice_id: voice_id || '2d5b0e6cf36f460aa7fc47e3eee4ba54', speed: 0.95 },
        background: { type: 'color', value: '#060606' }
      }],
      dimension: { width: 720, height: 1280 }
    };
    const genResp = await fetch('https://api.heygen.com/v2/video/generate', {
      method: 'POST',
      headers: { 'X-Api-Key': key, 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(genBody)
    });
    const genData = await genResp.json();
    if (genData.error) return res.status(400).json({ error: genData.error });
    res.json({ video_id: genData.data?.video_id || genData.video_id });
  } catch(e) { res.status(500).json({ error: e.message }); }
});

// Explicit HTML page routes
// Public pages — no auth required
// Legacy crypto page (apex-bot.html) described a self-hosted "source code" product
// that no longer matches the fully-hosted offering — redirect to the canonical
// hosted crypto page so buyers never see the stale copy.
app.get(['/apex-bot', '/apex-bot.html'], (req, res) => res.redirect(301, '/index'));

const publicPages = ['access','privacy','terms','impressum','intro-epic','app','demo','try','videos','screen','screens','tiktok-demo','video-maker','video-gen','forex','bot-setup','setup-guide','configurator','configurator-forex','deploy','ad','results','profile','flex','flex2','flex3','heygen','mt5-sim','trading-journal','affiliate','affiliate-dashboard','affiliate-terms','thank-you','thank-you-d24','chart','free','promo','guide'];
publicPages.forEach(p => {
  app.get(`/${p}.html`, (req, res) => res.sendFile(path.join(__dirname, 'public', `${p}.html`), { cacheControl: false, headers: { 'Cache-Control': 'no-store' } }));
  app.get(`/${p}`, (req, res) => res.sendFile(path.join(__dirname, 'public', `${p}.html`), { cacheControl: false, headers: { 'Cache-Control': 'no-store' } }));
});

// ── BOT EMAIL HTML — funcție separată reutilizabilă ──────────────────────────
function _buildBotEmailHtml(safeName, safeEmail, licenseKey = 'APEX-XXXX-XXXX-XXXX') {
  const firstName = safeName.split(' ')[0];
  const step = (n, title, body) => `<tr><td style="padding:0 0 12px"><table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#111114;border:1px solid rgba(255,255,255,0.06);border-radius:14px"><tr><td style="padding:22px 24px"><table cellpadding="0" cellspacing="0" border="0" style="margin:0 0 10px"><tr><td style="background:linear-gradient(135deg,#e63946,#ff6b7a);border-radius:8px;width:28px;height:28px;text-align:center;vertical-align:middle;font-size:13px;font-weight:900;color:#fff;font-family:Arial,sans-serif">${n}</td><td style="padding:0 0 0 12px;font-size:14px;font-weight:800;color:#e4e4e7;font-family:Arial,sans-serif">${title}</td></tr></table><p style="margin:0;font-size:13px;color:#a1a1aa;font-family:Arial,sans-serif;line-height:1.75">${body}</p></td></tr></table></td></tr>`;

  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body,table,td,p,a{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}
table,td{mso-table-lspace:0;mso-table-rspace:0}
body{margin:0;padding:0;background:#09090b}
a{text-decoration:none}
@media only screen and (max-width:600px){
  .key-mono{font-size:17px!important;letter-spacing:2px!important}
  .hero-h1{font-size:26px!important}
  .outer-pad{padding:24px 12px 0!important}
  .inner-pad{padding:28px 20px!important}
  .btn-cta{padding:16px 32px!important;font-size:15px!important}
}
</style></head>
<body style="margin:0;padding:0;background:#09090b">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#09090b;min-height:100vh">
<tr><td class="outer-pad" align="center" style="padding:40px 16px 0">
<table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%">

<tr><td align="center" style="padding:0 0 24px">
  <p style="margin:0;font-size:10px;font-weight:700;letter-spacing:4px;text-transform:uppercase;color:#52525b;font-family:Arial,sans-serif">APEX TRADING SUITE</p>
</td></tr>

<tr><td style="background:#0c0c0f;border:1px solid rgba(255,255,255,0.08);border-bottom:none;border-radius:20px 20px 0 0">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td style="background:linear-gradient(90deg,#e63946,#ff6b7a);height:3px;border-radius:19px 19px 0 0;font-size:0;line-height:0">&nbsp;</td></tr>
    <tr><td class="inner-pad" align="center" style="padding:44px 40px 36px">
      <table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto 28px"><tr><td style="background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);border-radius:24px;padding:7px 20px">
        <p style="margin:0;font-size:11px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#22c55e;font-family:Arial,sans-serif">&#10003;&nbsp; PAYMENT CONFIRMED</p>
      </td></tr></table>
      <p class="hero-h1" style="margin:0 0 8px;font-size:34px;font-weight:900;color:#ffffff;font-family:Arial,sans-serif;letter-spacing:-0.5px;line-height:1.15">Your Crypto bot is ready,</p>
      <p class="hero-h1" style="margin:0 0 24px;font-size:34px;font-weight:900;color:#e63946;font-family:Arial,sans-serif;letter-spacing:-0.5px;line-height:1.15">${firstName}.</p>
      <p style="margin:0;font-size:15px;color:#a1a1aa;font-family:Arial,sans-serif;line-height:1.75;max-width:420px">One tap to activate. Follow the steps below &mdash; you can be trading in under 10 minutes.</p>
    </td></tr>
  </table>
</td></tr>

<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:0 32px 12px;text-align:center">
  <a class="btn-cta" href="https://t.me/ApexTradeBot_official_bot?start=${licenseKey}" style="display:inline-block;background:linear-gradient(135deg,#e63946,#d62839);color:#ffffff;font-family:Arial,sans-serif;font-size:17px;font-weight:900;padding:20px 56px;border-radius:14px;text-decoration:none;letter-spacing:0.3px;box-shadow:0 4px 20px rgba(230,57,70,0.35)">&#128640; Open your Crypto Bot &rarr;</a>
</td></tr>
<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:4px 32px 32px;text-align:center">
  <p style="margin:0;font-size:12px;color:#52525b;font-family:Arial,sans-serif">Tap the button &mdash; Telegram opens and the bot activates automatically</p>
</td></tr>

<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:0 32px 28px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#09090b;border:1px solid rgba(230,57,70,0.2);border-radius:14px"><tr>
    <td style="background:linear-gradient(180deg,#e63946,#d62839);width:4px;border-radius:14px 0 0 14px;font-size:0;line-height:0">&nbsp;</td>
    <td style="padding:24px 24px">
      <p style="margin:0 0 16px;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#ff6b7a;font-family:Arial,sans-serif">YOUR LICENSE KEY</p>
      <p class="key-mono" style="margin:0 0 12px;font-family:'Courier New',Courier,monospace;font-size:22px;font-weight:900;color:#ffffff;letter-spacing:4px;text-align:center;background:#111114;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:18px 14px;word-break:break-all">${licenseKey}</p>
      <p style="margin:0;font-size:11px;color:#71717a;font-family:Arial,sans-serif;text-align:center;line-height:1.6">Save this key &mdash; you'll need it if you contact support</p>
    </td>
  </tr></table>
</td></tr>

<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:0 32px 24px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
    <td style="border-top:1px solid rgba(255,255,255,0.06)"></td>
    <td style="white-space:nowrap;padding:0 14px;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#52525b;font-family:Arial,sans-serif">SETUP STEPS</td>
    <td style="border-top:1px solid rgba(255,255,255,0.06)"></td>
  </tr></table>
</td></tr>

<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:0 32px 20px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
    ${step(1, 'Open the bot on Telegram', 'Press the red button above. The bot sends you a welcome message and activates your license automatically.')}
    ${step(2, 'Connect your cTrader account', 'Send <span style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;color:#e2e8f0;font-family:\'Courier New\',monospace;font-size:11px;font-weight:700">/ctrader</span> in the chat. Log in with your cTID &mdash; the bot guides you step by step.')}
    ${step(3, 'Start trading', 'Send <span style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;color:#e2e8f0;font-family:\'Courier New\',monospace;font-size:11px;font-weight:700">/start</span> to go live on your connected cTrader account &mdash; real signals, real trades from the first run.')}
  </table>
</td></tr>

<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:0 32px 20px">
  <p style="margin:0;font-size:11px;color:#3f3f46;font-family:Arial,sans-serif;line-height:1.8;text-align:center"><strong style="color:#52525b">Risk Disclosure</strong> &mdash; Crypto trading involves substantial risk. Only invest what you can afford to lose. This is an automation tool, not financial advice.</p>
</td></tr>

<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:0 32px 28px">
  <p style="margin:0;font-size:10px;color:#3f3f46;font-family:Arial,sans-serif;line-height:1.8;text-align:center">By completing this purchase you requested immediate supply and waived the 14-day withdrawal right per Art. 16(m) EU Directive 2011/83/EU. All sales final once access is delivered. <a href="https://aicashsystem.space/terms" style="color:#52525b">Terms</a></p>
</td></tr>

<tr><td align="center" style="background:#0c0c0f;border:1px solid rgba(255,255,255,0.08);border-top:1px solid rgba(255,255,255,0.05);border-radius:0 0 20px 20px;padding:28px 40px 32px">
  <p style="margin:0 0 8px;font-size:13px;color:#71717a;font-family:Arial,sans-serif">Need help? We're here for you:</p>
  <a href="mailto:supportaicashsystem@gmail.com" style="color:#ff6b7a;font-size:14px;font-weight:700;font-family:Arial,sans-serif;text-decoration:none">supportaicashsystem@gmail.com</a>
  <p style="margin:20px 0 0;font-size:10px;color:#3f3f46;font-family:Arial,sans-serif">&copy; 2025 Apex Trading Suite &nbsp;&middot;&nbsp; <a href="https://aicashsystem.space" style="color:#3f3f46;text-decoration:none">aicashsystem.space</a></p>
</td></tr>

<tr><td style="height:40px;font-size:0;line-height:0">&nbsp;</td></tr>
</table></td></tr></table></body></html>`;}

// ── FOREX BOT EMAIL ─────────────────────────────────────────────────────────
function _buildForexEmailHtml(safeName, safeEmail, licenseKey = 'FORX-XXXX-XXXX-XXXX') {
  const firstName = safeName.split(' ')[0];
  const step = (n, title, body) => `<tr><td style="padding:0 0 12px"><table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#111114;border:1px solid rgba(255,255,255,0.06);border-radius:14px"><tr><td style="padding:22px 24px"><table cellpadding="0" cellspacing="0" border="0" style="margin:0 0 10px"><tr><td style="background:linear-gradient(135deg,#e63946,#ff6b7a);border-radius:8px;width:28px;height:28px;text-align:center;vertical-align:middle;font-size:13px;font-weight:900;color:#fff;font-family:Arial,sans-serif">${n}</td><td style="padding:0 0 0 12px;font-size:14px;font-weight:800;color:#e4e4e7;font-family:Arial,sans-serif">${title}</td></tr></table><p style="margin:0;font-size:13px;color:#a1a1aa;font-family:Arial,sans-serif;line-height:1.75">${body}</p></td></tr></table></td></tr>`;

  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body,table,td,p,a{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}
table,td{mso-table-lspace:0;mso-table-rspace:0}
body{margin:0;padding:0;background:#09090b}
a{text-decoration:none}
@media only screen and (max-width:600px){
  .key-mono{font-size:17px!important;letter-spacing:2px!important}
  .hero-h1{font-size:26px!important}
  .outer-pad{padding:24px 12px 0!important}
  .inner-pad{padding:28px 20px!important}
  .btn-cta{padding:16px 32px!important;font-size:15px!important}
}
</style></head>
<body style="margin:0;padding:0;background:#09090b">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#09090b;min-height:100vh">
<tr><td class="outer-pad" align="center" style="padding:40px 16px 0">
<table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%">

<tr><td align="center" style="padding:0 0 24px">
  <p style="margin:0;font-size:10px;font-weight:700;letter-spacing:4px;text-transform:uppercase;color:#52525b;font-family:Arial,sans-serif">APEX TRADING SUITE</p>
</td></tr>

<tr><td style="background:#0c0c0f;border:1px solid rgba(255,255,255,0.08);border-bottom:none;border-radius:20px 20px 0 0">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td style="background:linear-gradient(90deg,#e63946,#ff6b7a);height:3px;border-radius:19px 19px 0 0;font-size:0;line-height:0">&nbsp;</td></tr>
    <tr><td class="inner-pad" align="center" style="padding:44px 40px 36px">
      <table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto 28px"><tr><td style="background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);border-radius:24px;padding:7px 20px">
        <p style="margin:0;font-size:11px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#22c55e;font-family:Arial,sans-serif">&#10003;&nbsp; PAYMENT CONFIRMED</p>
      </td></tr></table>
      <p class="hero-h1" style="margin:0 0 8px;font-size:34px;font-weight:900;color:#ffffff;font-family:Arial,sans-serif;letter-spacing:-0.5px;line-height:1.15">Your Forex bot is ready,</p>
      <p class="hero-h1" style="margin:0 0 24px;font-size:34px;font-weight:900;color:#e63946;font-family:Arial,sans-serif;letter-spacing:-0.5px;line-height:1.15">${firstName}.</p>
      <p style="margin:0;font-size:15px;color:#a1a1aa;font-family:Arial,sans-serif;line-height:1.75;max-width:420px">One tap to activate. Follow the steps below &mdash; you can be trading in under 10 minutes.</p>
    </td></tr>
  </table>
</td></tr>

<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:0 32px 12px;text-align:center">
  <a class="btn-cta" href="https://t.me/FOREX_APEX_BOT?start=${licenseKey}" style="display:inline-block;background:linear-gradient(135deg,#e63946,#d62839);color:#ffffff;font-family:Arial,sans-serif;font-size:17px;font-weight:900;padding:20px 56px;border-radius:14px;text-decoration:none;letter-spacing:0.3px;box-shadow:0 4px 20px rgba(230,57,70,0.35)">&#128640; Open your Forex Bot &rarr;</a>
</td></tr>
<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:4px 32px 32px;text-align:center">
  <p style="margin:0;font-size:12px;color:#52525b;font-family:Arial,sans-serif">Tap the button &mdash; Telegram opens and the bot activates automatically</p>
</td></tr>

<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:0 32px 28px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#09090b;border:1px solid rgba(230,57,70,0.2);border-radius:14px"><tr>
    <td style="background:linear-gradient(180deg,#e63946,#d62839);width:4px;border-radius:14px 0 0 14px;font-size:0;line-height:0">&nbsp;</td>
    <td style="padding:24px 24px">
      <p style="margin:0 0 16px;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#ff6b7a;font-family:Arial,sans-serif">YOUR LICENSE KEY</p>
      <p class="key-mono" style="margin:0 0 12px;font-family:'Courier New',Courier,monospace;font-size:22px;font-weight:900;color:#ffffff;letter-spacing:4px;text-align:center;background:#111114;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:18px 14px;word-break:break-all">${licenseKey}</p>
      <p style="margin:0;font-size:11px;color:#71717a;font-family:Arial,sans-serif;text-align:center;line-height:1.6">Save this key &mdash; you'll need it if you contact support</p>
    </td>
  </tr></table>
</td></tr>

<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:0 32px 24px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
    <td style="border-top:1px solid rgba(255,255,255,0.06)"></td>
    <td style="white-space:nowrap;padding:0 14px;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#52525b;font-family:Arial,sans-serif">SETUP STEPS</td>
    <td style="border-top:1px solid rgba(255,255,255,0.06)"></td>
  </tr></table>
</td></tr>

<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:0 32px 20px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
    ${step(1, 'Open the bot on Telegram', 'Press the red button above. The bot sends you a welcome message and activates your license automatically.')}
    ${step(2, 'Connect your cTrader account', 'Send <span style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;color:#e2e8f0;font-family:\'Courier New\',monospace;font-size:11px;font-weight:700">/ctrader</span> in the chat. Log in with your cTID &mdash; the bot guides you step by step.')}
    ${step(3, 'Start trading', 'Send <span style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;color:#e2e8f0;font-family:\'Courier New\',monospace;font-size:11px;font-weight:700">/start</span> to go live on your connected cTrader account &mdash; real signals, real trades from the first run.')}
  </table>
</td></tr>

<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:0 32px 20px">
  <p style="margin:0;font-size:11px;color:#3f3f46;font-family:Arial,sans-serif;line-height:1.8;text-align:center"><strong style="color:#52525b">Risk Disclosure</strong> &mdash; Forex trading involves substantial risk. Only trade capital you can afford to lose. This is an automation tool, not financial advice.</p>
</td></tr>

<tr><td style="background:#0c0c0f;border-left:1px solid rgba(255,255,255,0.08);border-right:1px solid rgba(255,255,255,0.08);padding:0 32px 28px">
  <p style="margin:0;font-size:10px;color:#3f3f46;font-family:Arial,sans-serif;line-height:1.8;text-align:center">By completing this purchase you requested immediate supply and waived the 14-day withdrawal right per Art. 16(m) EU Directive 2011/83/EU. All sales final once access is delivered. <a href="https://aicashsystem.space/terms" style="color:#52525b">Terms</a></p>
</td></tr>

<tr><td align="center" style="background:#0c0c0f;border:1px solid rgba(255,255,255,0.08);border-top:1px solid rgba(255,255,255,0.05);border-radius:0 0 20px 20px;padding:28px 40px 32px">
  <p style="margin:0 0 8px;font-size:13px;color:#71717a;font-family:Arial,sans-serif">Need help? We're here for you:</p>
  <a href="mailto:supportaicashsystem@gmail.com" style="color:#ff6b7a;font-size:14px;font-weight:700;font-family:Arial,sans-serif;text-decoration:none">supportaicashsystem@gmail.com</a>
  <p style="margin:20px 0 0;font-size:10px;color:#3f3f46;font-family:Arial,sans-serif">&copy; 2025 Apex Trading Suite &nbsp;&middot;&nbsp; <a href="https://aicashsystem.space" style="color:#3f3f46;text-decoration:none">aicashsystem.space</a></p>
</td></tr>

<tr><td style="height:40px;font-size:0;line-height:0">&nbsp;</td></tr>
</table></td></tr></table></body></html>`;}

// ── BOT ACCESS — streams a clean ZIP; requires valid HMAC-signed license key
app.get('/bot-access', async (req, res) => {
  const key = req.query.key || req.headers['x-license-key'];
  if (!key) return res.status(403).send('License key required. Add ?key=APEX-XXXX-XXXX-XXXX');
  // Validate HMAC signature — not just format
  if (!verifyLicenseKeyHmac(key)) {
    return res.status(403).send('Invalid license key.');
  }
  console.log('[BOT-ACCESS] download with key:', key.slice(0, 9) + '…');
  const archiver = require('archiver');
  const botDir = path.join(__dirname, 'apex-trade-bot');
  res.setHeader('Content-Disposition', 'attachment; filename="apex-trade-bot.zip"');
  res.setHeader('Content-Type', 'application/zip');
  const archive = archiver('zip', { zlib: { level: 6 } });
  archive.on('error', (err) => {
    console.error('[BOT-ACCESS] archive error:', err.message);
    if (!res.headersSent) res.status(500).send('Could not generate bot package. Contact support.');
  });
  archive.pipe(res);
  // Include src/, package.json, railway.json — no node_modules
  archive.directory(path.join(botDir, 'src'), 'src');
  archive.file(path.join(botDir, 'package.json'), { name: 'package.json' });
  archive.file(path.join(botDir, 'railway.json'), { name: 'railway.json' });
  archive.finalize();
});

// ── EMAIL STATUS — requires owner secret
app.get('/api/email-status', (req, res) => {
  const secret = req.query.secret;
  const expected = process.env.BOT_EMAIL_SECRET;
  if (!expected || secret !== expected) return res.status(403).json({ error: 'Forbidden' });
  res.json({ resend: !!RESEND_API_KEY, brevo: !!BREVO_API_KEY, smtp: !!transporter, sender: SENDER_EMAIL || 'not set' });
});

// ── RESEND DNS RECORDS — requires owner secret
app.get('/api/resend-dns', async (req, res) => {
  const secret = req.query.secret;
  const expected = process.env.BOT_EMAIL_SECRET;
  if (!expected || secret !== expected) return res.status(403).json({ error: 'Forbidden' });
  if (!RESEND_API_KEY) return res.json({ error: 'RESEND_API_KEY not set' });
  try {
    const r = await fetch('https://api.resend.com/domains', {
      headers: { 'Authorization': `Bearer ${RESEND_API_KEY}` },
    });
    const data = await r.json();
    const domain = (data.data || []).find(d => d.name === 'aicashsystem.space');
    if (!domain) return res.json({ error: 'Domain not found in Resend', allDomains: data.data || [], rawResponse: data });
    // Get full domain details
    const r2 = await fetch(`https://api.resend.com/domains/${domain.id}`, {
      headers: { 'Authorization': `Bearer ${RESEND_API_KEY}` },
    });
    const details = await r2.json();
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.send(`=== DNS Records pentru Namecheap ===\n\n` +
      (details.records || []).map(rec =>
        `Type: ${rec.type}\nHost: ${rec.name}\nValue: ${rec.value}\nPriority: ${rec.priority || 'N/A'}\n`
      ).join('\n---\n\n')
    );
  } catch(e) { res.json({ error: e.message }); }
});

// ── DEBUG: test Resend directly — requires owner secret
app.get('/api/test-resend', async (req, res) => {
  const secret = req.query.secret;
  const expected = process.env.BOT_EMAIL_SECRET;
  if (!expected || secret !== expected) return res.status(403).json({ error: 'Forbidden' });
  if (!RESEND_API_KEY) return res.json({ error: 'RESEND_API_KEY not set' });
  const to = req.query.email || 'test@example.com';
  const resendFrom = process.env.RESEND_FROM || 'onboarding@resend.dev';
  try {
    const r = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${RESEND_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: resendFrom, to: [to], subject: 'Test', html: '<p>Test email</p>' }),
      signal: AbortSignal.timeout(12000),
    });
    const body = await r.json();
    res.json({ status: r.status, ok: r.ok, body, from: resendFrom });
  } catch(e) { res.json({ error: e.message }); }
});

// GET /api/test-brevo?email=X — requires owner secret
app.get('/api/test-brevo', async (req, res) => {
  const secret = req.query.secret;
  const expected = process.env.BOT_EMAIL_SECRET;
  if (!expected || secret !== expected) return res.status(403).json({ error: 'Forbidden' });
  const to = req.query.email || SENDER_EMAIL;
  if (!BREVO_API_KEY) return res.json({ error: 'BREVO_API_KEY not set' });
  try {
    const r = await fetch('https://api.brevo.com/v3/smtp/email', {
      method: 'POST',
      headers: { 'api-key': BREVO_API_KEY, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sender: { name: SENDER_NAME, email: SENDER_EMAIL },
        to: [{ email: to }],
        subject: 'Brevo Test',
        htmlContent: '<p>Brevo test email</p>',
      }),
      signal: AbortSignal.timeout(12000),
    });
    const body = await r.text();
    res.json({ status: r.status, ok: r.ok, body, sender: SENDER_EMAIL });
  } catch(e) { res.json({ error: e.message, sender: SENDER_EMAIL }); }
});

// GET /api/test-resend?secret=X&email=Y — debug Resend
app.get('/api/test-resend', async (req, res) => {
  const secret = req.query.secret;
  const expected = process.env.BOT_EMAIL_SECRET;
  if (!expected || secret !== expected) return res.status(403).json({ error: 'Forbidden' });
  const to = req.query.email || SENDER_EMAIL;
  const resendKey = process.env.RESEND_API_KEY;
  const resendFrom = process.env.RESEND_FROM;
  if (!resendKey) return res.json({ error: 'RESEND_API_KEY not set', resendFrom });
  if (!resendFrom) return res.json({ error: 'RESEND_FROM not set', resendKey: resendKey ? 'set' : 'missing' });
  try {
    const r = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${resendKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: resendFrom, to: [to], subject: 'Resend Test', html: '<p>Resend test email</p>' }),
      signal: AbortSignal.timeout(12000),
    });
    const body = await r.text();
    res.json({ status: r.status, ok: r.ok, body, from: resendFrom, to });
  } catch(e) { res.json({ error: e.message, from: resendFrom, to }); }
});

// ── TEST DELIVERY EMAIL — protejat cu secret key, fără plată
// GET  (browser): /api/send-bot-email?secret=X&email=you@gmail.com&name=Alex
// POST (curl):    /api/send-bot-email?secret=X  body: { email, name }
app.get('/api/send-bot-email', async (req, res) => {
  req.body = { email: req.query.email, name: req.query.name, secret: req.query.secret };
  // fall through to shared handler below
  return _sendBotEmailHandler(req, res);
});
app.post('/api/send-bot-email', async (req, res) => {
  req.body.secret = req.body.secret || req.query.secret;
  return _sendBotEmailHandler(req, res);
});
async function _sendBotEmailHandler(req, res) {
  const secret = req.query.secret || req.body.secret;
  const adminSecret = process.env.BOT_EMAIL_SECRET || '';
  const isPreview = req.query.preview === '1';

  if (!adminSecret) {
    return res.status(403).json({ error: 'BOT_EMAIL_SECRET not set in env — add it on Render' });
  }
  if (secret !== adminSecret) {
    return res.status(403).json({ error: 'Wrong secret', hint: `Expected length: ${adminSecret.length} chars, got: ${(secret||'').length} chars` });
  }

  // Preview mode — shows email in browser without actually sending (requires valid secret)
  if (isPreview) {
    const name  = req.query.name || req.body.name || 'Alex';
    const email = req.query.email || req.body.email || 'preview@example.com';
    const previewHtml = _buildBotEmailHtml(_he(name), _he(email), 'APEX-DEMO-PREW-2025');
    return res.send(`<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Preview: Bot Delivery Email</title>
      <style>body{margin:0;background:#1a1a2e;display:flex;flex-direction:column;align-items:center;padding:40px 20px;font-family:sans-serif}
      .bar{background:#2d2d44;border:1px solid #444;border-radius:8px;padding:10px 20px;margin-bottom:24px;color:#aaa;font-size:13px;text-align:center;max-width:600px;width:100%}
      .bar strong{color:#00ff88}</style></head><body>
      <div class="bar">📧 <strong>PREVIEW</strong> — Email received by buyer after purchase.<br>
      <span style="font-size:11px;color:#666">To: ${_he(email)} · Name: ${_he(name)} · Key: APEX-DEMO-PREW-2025</span></div>
      ${previewHtml}</body></html>`);
  }

  const email = req.body.email;
  const name  = req.body.name || 'there';
  if (!email) return res.status(400).json({ error: 'email required' });

  // Generate a real license key for test sends
  const testKey = generateLicenseKey();
  const botEmailHtml = _buildBotEmailHtml(_he(name), _he(email), testKey);

  // Save test license to Supabase
  if (supabase) {
    try { await supabase.from('licenses').insert([{ key: testKey, email: email || '', name }]); }
    catch(e) { /* non-fatal */ }
  }

  const result = await _sendEmail({ to: email, subject: '🤖 Your Apex Trade Bot is ready — access inside', html: botEmailHtml, fromName: 'Apex.Bot' });
  return res.json({ success: result.ok, to: email, licenseKey: testKey, method: result.method, error: result.error });
}

// Protected pages — require any valid course purchase
const protectedPages = ['videos','blueprints','ai-builder','course-starter',
  'module1','module2','module3','module4','module5','module6','module7','module8','module9',
  'module10','module11','module12','module13','module14','chat'];
protectedPages.forEach(p => {
  app.get(`/${p}.html`, requireCourse('any'), (req, res) => res.sendFile(path.join(__dirname, 'public', `${p}.html`)));
  app.get(`/${p}`, requireCourse('any'), (req, res) => res.sendFile(path.join(__dirname, 'public', `${p}.html`)));
});

// Pro-only pages
app.get('/course-pro.html', requireCourse('pro'), (req, res) => res.sendFile(path.join(__dirname, 'public', 'course-pro.html')));
app.get('/course-pro', requireCourse('pro'), (req, res) => res.sendFile(path.join(__dirname, 'public', 'course-pro.html')));

app.get('/tiktok', requireCourse('any'), (req, res) => res.sendFile(path.join(__dirname, 'public', 'videos.html')));

// ════════════════════════════════════════
// AI BUSINESS BUILDER ROUTES
// ════════════════════════════════════════

app.post('/api/builder/plan', auth, _aiLimiter, async (req, res) => {
  const { passions, hours, budget, name } = req.body;
  if (!passions) return res.status(400).json({ error: 'Answers required' });

  const prompt = `You are an expert online business strategist. Based on this user profile, create a complete online business plan. Return ONLY valid JSON, no markdown.

USER:
- Name: ${name || 'Friend'}
- Passions/Skills: ${passions}
- Hours per week: ${hours || '5-10h'}
- Starting budget: ${budget || '$0'}

Return this exact JSON structure:
{
  "business": {
    "model": "specific business model name",
    "description": "2 sentences what they will do daily",
    "why_perfect": "1 sentence why this fits their specific profile",
    "income_potential": "realistic range after 90 days (e.g. $500–$2,000/month)"
  },
  "brand": {
    "name": "brand name (1-2 words, catchy)",
    "tagline": "tagline under 7 words",
    "personality": "3 adjectives",
    "target_audience": "who they sell to"
  },
  "seven_day_plan": [
    {"day": 1, "focus": "Setup & Foundation", "tasks": ["specific task", "specific task", "specific task"]},
    {"day": 2, "focus": "...", "tasks": ["...", "...", "..."]},
    {"day": 3, "focus": "...", "tasks": ["...", "...", "..."]},
    {"day": 4, "focus": "...", "tasks": ["...", "...", "..."]},
    {"day": 5, "focus": "...", "tasks": ["...", "...", "..."]},
    {"day": 6, "focus": "...", "tasks": ["...", "...", "..."]},
    {"day": 7, "focus": "First Outreach", "tasks": ["...", "...", "..."]}
  ],
  "content_hooks": [
    {"platform": "TikTok", "hook": "opening 3 seconds exactly", "script": "30-second script outline"},
    {"platform": "Instagram", "hook": "opening 3 seconds exactly", "script": "caption 100 words"},
    {"platform": "TikTok", "hook": "opening 3 seconds exactly", "script": "30-second script outline"},
    {"platform": "Instagram Reels", "hook": "opening 3 seconds exactly", "script": "script outline"},
    {"platform": "TikTok", "hook": "opening 3 seconds exactly", "script": "30-second script outline"}
  ],
  "ad_copy": {
    "headline": "ad headline under 10 words",
    "body": "50-word ad body text",
    "cta": "button text"
  },
  "daily_routine": [
    {"time": "Morning", "duration": "30 min", "task": "specific task"},
    {"time": "Midday", "duration": "1 hour", "task": "specific task"},
    {"time": "Evening", "duration": "45 min", "task": "specific task"}
  ],
  "logo_prompt": "minimalist vector logo for [brand name], [describe style based on niche], clean lines, white background, professional"
}`;

  try {
    let result;
    if (OPENAI_KEY) {
      const r = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + OPENAI_KEY },
        body: JSON.stringify({ model: 'gpt-4o', max_tokens: 3500, response_format: { type: 'json_object' }, messages: [{ role: 'user', content: prompt }] })
      });
      const d = await r.json();
      if (d.choices?.[0]) result = JSON.parse(d.choices[0].message.content);
    } else if (anthropic) {
      const msg = await anthropic.messages.create({ model: 'claude-sonnet-4-6', max_tokens: 3500, messages: [{ role: 'user', content: prompt }] });
      const text = msg.content[0].text;
      result = JSON.parse(text.replace(/```json\n?|\n?```/g, '').trim());
    }
    if (!result) return res.status(500).json({ error: 'No AI provider configured' });
    addLog(`Business plan generated for ${name || 'user'}`, 'builder', 'success');
    res.json(result);
  } catch (e) {
    console.error('Builder plan error:', e);
    res.status(500).json({ error: 'Generation failed: ' + e.message });
  }
});

app.post('/api/builder/logo', auth, _aiLimiter, async (req, res) => {
  const { prompt } = req.body;
  if (!prompt) return res.status(400).json({ error: 'Prompt required' });
  if (!OPENAI_KEY) return res.status(400).json({ error: 'OpenAI key required for logo generation' });
  try {
    const r = await fetch('https://api.openai.com/v1/images/generations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + OPENAI_KEY },
      body: JSON.stringify({ model: 'dall-e-3', prompt, n: 1, size: '1024x1024', quality: 'standard' })
    });
    const d = await r.json();
    if (d.data?.[0]) { addLog('Logo generated', 'builder', 'success'); return res.json({ url: d.data[0].url }); }
    res.status(500).json({ error: d.error?.message || 'Logo generation failed' });
  } catch (e) {
    res.status(500).json({ error: 'Logo generation failed. Please try again.' });
  }
});


// ════════════════════════════════════════
// ADMIN: SYNC BOT FILES → GitHub repo
// Usage: GET /admin/sync-bot-repo?secret=BOT_EMAIL_SECRET&token=ghp_xxx[&bot=crypto|forex]
// ════════════════════════════════════════
app.get('/admin/sync-bot-repo', async (req, res) => {
  const secret = req.query.secret || '';
  // Token can come from the URL (?token=ghp_...) or, preferably, a Render env
  // var GH_TOKEN so it stays out of browser history and URLs.
  const ghToken = req.query.token || process.env.GH_TOKEN || '';
  const bot = (req.query.bot || 'crypto').toLowerCase();
  const adminSecret = process.env.BOT_EMAIL_SECRET || '';

  if (!adminSecret) return res.status(500).json({ error: 'BOT_EMAIL_SECRET not set' });
  if (secret !== adminSecret) return res.status(403).json({ error: 'Wrong secret' });
  if (!ghToken) return res.status(400).json({ error: 'GitHub token required — add GH_TOKEN in Render env, or pass ?token=ghp_...' });
  if (!['crypto', 'forex'].includes(bot)) return res.status(400).json({ error: "bot must be 'crypto' or 'forex'" });

  const fs = require('fs');
  const OWNER = 'alexgabriel225sefu-dotcom';
  const REPO  = bot === 'forex' ? 'apex-forex-bot' : 'apex-trade-bot';
  const botDir = path.join(__dirname, REPO);

  // Recursively collect deployable source files (skips caches/tests/git noise).
  const SKIP_DIRS = new Set(['node_modules', '__pycache__', '.git', '.claude-flow', 'tests']);
  const KEEP_EXT  = new Set(['.js', '.py', '.json', '.txt', '.yaml', '.yml', '.mq5', '.example']);
  const KEEP_NAME = new Set(['Procfile']);
  function walk(dir, base = '') {
    let out = [];
    let entries = [];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch(_) { return out; }
    for (const e of entries) {
      const rel = base ? `${base}/${e.name}` : e.name;
      if (e.isDirectory()) {
        if (SKIP_DIRS.has(e.name)) continue;
        out = out.concat(walk(path.join(dir, e.name), rel));
      } else if (e.name === 'README.md') {
        continue; // README is generated below
      } else if (KEEP_NAME.has(e.name) || KEEP_EXT.has(path.extname(e.name))) {
        out.push(rel);
      }
    }
    return out;
  }
  const filesToPush = walk(botDir);

  const readmeContent = bot === 'forex' ? `# Apex Forex Bot 🤖

AI-powered forex trading bot (OANDA + MT5 bridge). Deploy with one click on Railway — runs 24/7, never sleeps.

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/${OWNER}/${REPO})

## Setup
The only variable you set is your license key — everything else is configured
on [aicashsystem.space/configurator-forex](https://aicashsystem.space/configurator-forex)
and loaded automatically at startup.

| Variable | Value |
|----------|-------|
| \`LICENSE_KEY\` | Your key from purchase email |

## License
Requires a valid license key. Purchase at [aicashsystem.space](https://aicashsystem.space).
` : `# Apex Trade Bot 🤖

AI-powered crypto trading bot. Deploy with one click on Railway — runs 24/7, never sleeps.

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/${OWNER}/${REPO})

## Setup
The only variable you set is your license key — everything else is configured
on [aicashsystem.space/configurator](https://aicashsystem.space/configurator)
and loaded automatically at startup.

| Variable | Value |
|----------|-------|
| \`LICENSE_KEY\` | Your key from purchase email |

## License
Requires a valid license key. Purchase at [aicashsystem.space](https://aicashsystem.space).
`;

  const results = [];
  let errors = 0;

  // Helper: get current SHA of a file (needed for updates)
  async function getFileSha(filePath) {
    try {
      const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${filePath}`, {
        headers: { Authorization: `Bearer ${ghToken}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' }
      });
      if (r.ok) { const d = await r.json(); return d.sha || null; }
    } catch(_) {}
    return null;
  }

  // Helper: push one file
  async function pushFile(filePath, content) {
    const sha = await getFileSha(filePath);
    const body = {
      message: sha ? `Update ${filePath}` : `Add ${filePath}`,
      content: Buffer.from(content).toString('base64'),
      ...(sha ? { sha } : {}),
    };
    const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${filePath}`, {
      method: 'PUT',
      headers: { Authorization: `Bearer ${ghToken}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const errBody = await r.json().catch(() => ({}));
      return { ok: false, status: r.status, ghError: errBody.message || JSON.stringify(errBody) };
    }
    return { ok: true };
  }

  // Push README.md
  try {
    const res2 = await pushFile('README.md', readmeContent);
    results.push({ file: 'README.md', ...res2 });
    if (!res2.ok) errors++;
  } catch(e) { results.push({ file: 'README.md', ok: false, err: e.message }); errors++; }

  // Push all bot files
  for (const rel of filesToPush) {
    try {
      const content = require('fs').readFileSync(path.join(botDir, rel), 'utf8');
      const res2 = await pushFile(rel, content);
      results.push({ file: rel, ...res2 });
      if (!res2.ok) errors++;
    } catch(e) {
      results.push({ file: rel, ok: false, err: e.message });
      errors++;
    }
  }

  // ── CLEANUP: remove the OTHER bot's folder if it was nested in here by a
  // mistaken earlier push (e.g. apex-forex-bot/ committed inside apex-trade-bot).
  // Each bot must live in its own repo — a nested folder makes Railway build the
  // wrong service. We mirror by deleting any blob under the stray bot dir.
  const strayDir = bot === 'forex' ? 'apex-trade-bot' : 'apex-forex-bot';
  let deleted = 0;
  try {
    const treeRes = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/git/trees/HEAD?recursive=1`, {
      headers: { Authorization: `Bearer ${ghToken}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' }
    });
    if (treeRes.ok) {
      const tree = await treeRes.json();
      const stray = (tree.tree || []).filter(t => t.type === 'blob' && t.path.startsWith(`${strayDir}/`));
      for (const f of stray) {
        const delRes = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${f.path}`, {
          method: 'DELETE',
          headers: { Authorization: `Bearer ${ghToken}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28' },
          body: JSON.stringify({ message: `Remove stray ${f.path} (wrong repo)`, sha: f.sha }),
        });
        if (delRes.ok) { deleted++; results.push({ file: f.path, ok: true, deleted: true }); }
        else { const eb = await delRes.json().catch(() => ({})); results.push({ file: f.path, ok: false, deleted: true, ghError: eb.message }); errors++; }
      }
    }
  } catch(e) { results.push({ cleanup: false, err: e.message }); }

  const allOk = errors === 0;
  res.json({
    success: allOk,
    pushed: results.filter(r => r.ok && !r.deleted).length,
    deleted,
    failed: errors,
    results,
    repoUrl: `https://github.com/${OWNER}/${REPO}`,
    deployFromRepo: `https://railway.com/new — choose "Deploy from GitHub repo" → ${REPO}`,
  });
});

// ════════════════════════════════════════
// BOT CONFIG — save from configurator / fetch by bot
// Table needed: CREATE TABLE bot_configs (license_key TEXT PRIMARY KEY, config TEXT NOT NULL, updated_at TIMESTAMPTZ DEFAULT NOW());
// NOTE: must be registered BEFORE the catch-all 404 below.
// ════════════════════════════════════════
function _botConfigKey() {
  const s = process.env.JWT_SECRET || process.env.COOKIE_SECRET || 'bot-cfg-fallback-change-me';
  return crypto.createHash('sha256').update(s).digest();
}
function encryptBotConfig(obj) {
  const iv = crypto.randomBytes(16);
  const cipher = crypto.createCipheriv('aes-256-cbc', _botConfigKey(), iv);
  const enc = Buffer.concat([cipher.update(JSON.stringify(obj), 'utf8'), cipher.final()]);
  return iv.toString('hex') + ':' + enc.toString('hex');
}
function decryptBotConfig(data) {
  const [ivHex, encHex] = data.split(':');
  const dc = crypto.createDecipheriv('aes-256-cbc', _botConfigKey(), Buffer.from(ivHex, 'hex'));
  return JSON.parse(Buffer.concat([dc.update(Buffer.from(encHex, 'hex')), dc.final()]).toString('utf8'));
}

// POST /api/save-bot-config  — called by configurator when client clicks "Save & Deploy"
app.post('/api/save-bot-config', async (req, res) => {
  const { key, config } = req.body || {};
  if (!key || !config || typeof config !== 'object') return res.status(400).json({ error: 'key and config required' });
  if (!supabase) return res.status(500).json({ error: 'Database not configured' });

  const { data: lic } = await supabase.from('licenses').select('active').eq('key', key).eq('active', true).single();
  if (!lic) return res.status(403).json({ error: 'Invalid or inactive license key' });

  const encrypted = encryptBotConfig(config);
  const { error } = await supabase.from('bot_configs').upsert(
    { license_key: key, config: encrypted, updated_at: new Date().toISOString() },
    { onConflict: 'license_key' }
  );
  if (error) return res.status(500).json({ error: 'Save failed. Run: CREATE TABLE bot_configs (license_key TEXT PRIMARY KEY, config TEXT NOT NULL, updated_at TIMESTAMPTZ DEFAULT NOW());', detail: error.message });
  res.json({ success: true });
});

// GET /api/bot-config?key=APEX-XXXX  — called by bot on startup to fetch remote config
app.get('/api/bot-config', async (req, res) => {
  const key = (req.query.key || '').trim();
  if (!key) return res.status(400).json({ error: 'key required' });
  if (!supabase) return res.status(500).json({ error: 'Database not configured' });

  const { data: lic } = await supabase.from('licenses').select('active').eq('key', key).eq('active', true).single();
  if (!lic) return res.status(403).json({ error: 'Invalid license key' });

  const { data, error } = await supabase.from('bot_configs').select('config').eq('license_key', key).single();
  if (error || !data) return res.status(404).json({ error: 'No config found for this key. Complete the configurator at aicashsystem.space/configurator first.' });

  try {
    const config = decryptBotConfig(data.config);
    res.json({ success: true, config });
  } catch(e) {
    res.status(500).json({ error: 'Config decryption failed' });
  }
});

// ════════════════════════════════════════
// RAILWAY AUTO-DEPLOY — client provides their Railway token,
// we create project + service + variables + deploy for them.
// ════════════════════════════════════════
app.post('/api/railway-deploy', async (req, res) => {
  const { railwayToken, licenseKey, product } = req.body || {};
  if (!railwayToken || !licenseKey) return res.status(400).json({ error: 'railwayToken and licenseKey required' });

  const RAILWAY_API = 'https://backboard.railway.com/graphql/v2';
  const image = product === 'apex-forex'
    ? 'ghcr.io/alexgabriel225sefu-dotcom/apex-forex-bot:latest'
    : 'ghcr.io/alexgabriel225sefu-dotcom/apex-trade-bot:latest';
  const projectName = product === 'apex-forex' ? 'apex-forex-bot' : 'apex-trade-bot';

  async function gql(query, variables) {
    const r = await fetch(RAILWAY_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${railwayToken}` },
      body: JSON.stringify({ query, variables }),
    });
    const t = await r.text();
    try { return JSON.parse(t); } catch { return { parseError: t.slice(0, 500) }; }
  }

  try {
    // 0) Validate token + get teamId (needed for team Railway accounts)
    const meRes = await gql(`query{ me{ id teams{ edges{ node{ id } } } } }`, {});
    const userId = meRes?.data?.me?.id;
    if (!userId) return res.status(400).json({ error: 'Invalid Railway token — generate one at railway.com/account/tokens', detail: JSON.stringify(meRes).slice(0,300) });
    const teamId = meRes?.data?.me?.teams?.edges?.[0]?.node?.id;

    // 1) Create project (include teamId if team account)
    const projInput = teamId ? { name: projectName, teamId } : { name: projectName };
    const proj = await gql(
      `mutation($input:ProjectCreateInput!){ projectCreate(input:$input){ id } }`,
      { input: projInput }
    );
    const projectId = proj?.data?.projectCreate?.id;
    if (!projectId) return res.status(500).json({ error: 'Failed to create Railway project', detail: JSON.stringify(proj).slice(0,500) });

    // 1b) Fetch environment ID separately (Railway does not return it inline at creation)
    const envRes = await gql(
      `query($id:String!){ project(id:$id){ environments{ edges{ node{ id name } } } } }`,
      { id: projectId }
    );
    const envId = envRes?.data?.project?.environments?.edges?.[0]?.node?.id;
    if (!envId) return res.status(500).json({ error: 'Failed to get Railway environment', detail: JSON.stringify(envRes).slice(0,500) });

    // 2) Create service (name only — Docker image set separately via serviceInstanceUpdate)
    const svc = await gql(
      `mutation($projectId:String!,$input:ServiceCreateInput!){ serviceCreate(projectId:$projectId, input:$input){ id } }`,
      { projectId, input: { name: projectName } }
    );
    const serviceId = svc?.data?.serviceCreate?.id;
    if (!serviceId) return res.status(500).json({ error: 'Failed to create Railway service', detail: JSON.stringify(svc).slice(0,300) });

    // 3) Set Docker image via serviceInstanceUpdate
    await gql(
      `mutation($serviceId:String!,$environmentId:String!,$input:ServiceInstanceUpdateInput!){ serviceInstanceUpdate(serviceId:$serviceId, environmentId:$environmentId, input:$input) }`,
      { serviceId, environmentId: envId, input: { dockerImage: image } }
    );

    // 4) Set variables
    const vars = [
      { name: 'LICENSE_KEY', value: licenseKey },
      { name: 'PORT', value: '3000' },
      { name: 'PAPER_TRADING', value: 'true' },
    ];
    for (const v of vars) {
      await gql(`mutation($input:VariableUpsertInput!){ variableUpsert(input:$input) }`,
        { input: { projectId, environmentId: envId, serviceId, name: v.name, value: v.value } });
    }

    // 5) Create public domain
    await gql(`mutation($input:ServiceDomainCreateInput!){ serviceDomainCreate(input:$input){ domain } }`,
      { input: { environmentId: envId, serviceId, targetPort: 3000 } });

    // 6) Deploy
    await gql(`mutation($serviceId:String!,$environmentId:String!){ serviceInstanceDeploy(serviceId:$serviceId, environmentId:$environmentId) }`,
      { serviceId, environmentId: envId });

    res.json({ ok: true, projectId, serviceId, message: 'Bot deployed! Check Railway dashboard for your URL in ~2 minutes.' });
  } catch (e) {
    res.status(500).json({ error: 'Deploy failed: ' + e.message });
  }
});


// ════════════════════════════════════════
// SOCIAL MEDIA INTEGRATIONS — Facebook / Instagram (Meta Graph API) + TikTok
// ════════════════════════════════════════
// Legit, official-API-only automation: scheduled/manual posting to Alex's own
// Page/Business accounts, and auto-reply to inbound DMs on Facebook/Instagram.
// Deliberately does NOT do outbound cold-DM/mass-messaging — that violates
// every platform's ToS and gets accounts banned. See social_accounts,
// social_posts, social_dm_log tables (Supabase).
//
// Required env vars (set in Render once the Meta/TikTok apps exist):
//   META_APP_ID, META_APP_SECRET, META_PAGE_ACCESS_TOKEN, META_PAGE_ID,
//   META_IG_BUSINESS_ID, META_WEBHOOK_VERIFY_TOKEN (any string you pick)
//   TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI
// Admin endpoints are protected by the same owner secret as the payout
// export above (BOT_EMAIL_SECRET), via ?secret= or X-Owner-Secret header.

const _AUTO_REPLY_TEXT = "Hey! Thanks for reaching out 🙌 We're running a free Apex Trading Bot demo for the first testers — no cost, no risk (demo account only). Want in? Reply here and I'll get you set up.";

// ── Facebook/Instagram: post to the Page or IG Business account ──
async function _metaPost(platform, content, mediaUrl) {
  const token = process.env.META_PAGE_ACCESS_TOKEN;
  if (!token) throw new Error('META_PAGE_ACCESS_TOKEN not configured');
  if (platform === 'facebook') {
    const pageId = process.env.META_PAGE_ID;
    if (!pageId) throw new Error('META_PAGE_ID not configured');
    const endpoint = mediaUrl
      ? `https://graph.facebook.com/v20.0/${pageId}/photos`
      : `https://graph.facebook.com/v20.0/${pageId}/feed`;
    const body = mediaUrl
      ? { url: mediaUrl, caption: content, access_token: token }
      : { message: content, access_token: token };
    const r = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await r.json();
    if (data.error) throw new Error(data.error.message || 'Facebook post failed');
    return data.post_id || data.id;
  }
  if (platform === 'instagram') {
    const igId = process.env.META_IG_BUSINESS_ID;
    if (!igId) throw new Error('META_IG_BUSINESS_ID not configured');
    if (!mediaUrl) throw new Error('Instagram posts require an image/video URL (media_url)');
    // Two-step: create a media container, then publish it.
    const createR = await fetch(`https://graph.facebook.com/v20.0/${igId}/media`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_url: mediaUrl, caption: content || '', access_token: token }),
    });
    const created = await createR.json();
    if (created.error) throw new Error(created.error.message || 'IG media container failed');
    const pubR = await fetch(`https://graph.facebook.com/v20.0/${igId}/media_publish`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ creation_id: created.id, access_token: token }),
    });
    const pub = await pubR.json();
    if (pub.error) throw new Error(pub.error.message || 'IG publish failed');
    return pub.id;
  }
  throw new Error('Unknown platform: ' + platform);
}

// POST /api/admin/social/post — { platform: 'facebook'|'instagram', content, media_url? }
app.post('/api/admin/social/post', async (req, res) => {
  if (!_ownerSecretOk(req)) return res.status(403).json({ error: 'Forbidden — secret required' });
  const { platform, content, media_url } = req.body || {};
  if (!['facebook', 'instagram'].includes(platform)) return res.status(400).json({ error: "platform must be 'facebook' or 'instagram'" });
  let postRow = null;
  try {
    if (supabase) {
      const { data } = await supabase.from('social_posts').insert([{ platform, content, media_url: media_url || null, status: 'queued' }]).select().single();
      postRow = data;
    }
    const externalId = await _metaPost(platform, content, media_url);
    if (supabase && postRow) {
      await supabase.from('social_posts').update({ status: 'posted', external_post_id: externalId, posted_at: new Date().toISOString() }).eq('id', postRow.id);
    }
    res.json({ ok: true, external_post_id: externalId });
  } catch (e) {
    if (supabase && postRow) await supabase.from('social_posts').update({ status: 'failed', error: e.message }).eq('id', postRow.id);
    res.status(500).json({ error: e.message });
  }
});

// ── Meta webhook: verification handshake + inbound DM auto-reply ──
// GET is Meta's one-time subscription verification (hub.challenge echo).
app.get('/webhooks/meta', (req, res) => {
  const mode = req.query['hub.mode'];
  const token = req.query['hub.verify_token'];
  const challenge = req.query['hub.challenge'];
  if (mode === 'subscribe' && token === process.env.META_WEBHOOK_VERIFY_TOKEN) {
    return res.status(200).send(challenge);
  }
  res.sendStatus(403);
});

// POST carries real events (messages, comments). Signature-verified so only
// Meta can trigger auto-replies — mirrors _digistore24VerifySignature's
// approach (HMAC over the raw body, compared to the header Meta sends).
function _metaVerifySignature(req) {
  const sig = req.headers['x-hub-signature-256'];
  const secret = process.env.META_APP_SECRET;
  if (!sig || !secret || !req.rawBody) return false;
  const expected = 'sha256=' + crypto.createHmac('sha256', secret).update(req.rawBody).digest('hex');
  try { return crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected)); } catch (e) { return false; }
}

app.post('/webhooks/meta', async (req, res) => {
  if (!_metaVerifySignature(req)) return res.sendStatus(401);
  res.sendStatus(200); // ack immediately — Meta retries on timeout/non-200
  try {
    const entries = (req.body && req.body.entry) || [];
    for (const entry of entries) {
      const messaging = entry.messaging || [];
      for (const evt of messaging) {
        const senderId = evt.sender && evt.sender.id;
        const text = evt.message && evt.message.text;
        if (!senderId || !text) continue;
        const platform = entry.messaging_product === 'instagram' || req.body.object === 'instagram' ? 'instagram' : 'facebook';
        const token = process.env.META_PAGE_ACCESS_TOKEN;
        try {
          await fetch(`https://graph.facebook.com/v20.0/me/messages?access_token=${token}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ recipient: { id: senderId }, message: { text: _AUTO_REPLY_TEXT } }),
          });
          if (supabase) await supabase.from('social_dm_log').insert([{ platform, sender_id: senderId, message_text: text, reply_text: _AUTO_REPLY_TEXT }]);
        } catch (e) { console.error('[Meta webhook] auto-reply failed:', e.message); }
      }
    }
  } catch (e) { console.error('[Meta webhook] processing error:', e.message); }
});

// ── TikTok: OAuth connect + Content Posting API ──
// TikTok requires a real OAuth2 authorization-code flow (no manual long-lived
// token like Meta's Graph API Explorer) — Alex opens /auth/tiktok/start once,
// approves, and the token lands in social_accounts.
app.get('/auth/tiktok/start', (req, res) => {
  const clientKey = process.env.TIKTOK_CLIENT_KEY;
  const redirectUri = process.env.TIKTOK_REDIRECT_URI;
  if (!clientKey || !redirectUri) return res.status(500).send('TikTok not configured — set TIKTOK_CLIENT_KEY / TIKTOK_REDIRECT_URI');
  const state = crypto.randomBytes(16).toString('hex');
  const url = `https://www.tiktok.com/v2/auth/authorize/?client_key=${encodeURIComponent(clientKey)}&scope=video.publish,video.upload&response_type=code&redirect_uri=${encodeURIComponent(redirectUri)}&state=${state}`;
  res.redirect(url);
});

app.get('/auth/tiktok/callback', async (req, res) => {
  const { code } = req.query;
  if (!code) return res.status(400).send('Missing code');
  try {
    const r = await fetch('https://open.tiktokapis.com/v2/oauth/token/', {
      method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        client_key: process.env.TIKTOK_CLIENT_KEY,
        client_secret: process.env.TIKTOK_CLIENT_SECRET,
        code: String(code),
        grant_type: 'authorization_code',
        redirect_uri: process.env.TIKTOK_REDIRECT_URI,
      }),
    });
    const data = await r.json();
    if (data.error) return res.status(500).send('TikTok auth failed: ' + (data.error_description || data.error));
    if (supabase) {
      await supabase.from('social_accounts').upsert([{
        platform: 'tiktok', account_id: data.open_id,
        access_token: data.access_token,
        token_expires_at: new Date(Date.now() + (data.expires_in || 0) * 1000).toISOString(),
      }], { onConflict: 'platform,account_id' });
    }
    res.send('TikTok connected! You can close this tab.');
  } catch (e) { res.status(500).send('TikTok auth error: ' + e.message); }
});

// POST /api/admin/social/tiktok/post — { content } — posts a text-caption video
// draft is NOT supported here (needs a video file upload, not just a URL, per
// TikTok's Content Posting API) — this posts via PULL_FROM_URL for a hosted
// video file. { video_url, content }
app.post('/api/admin/social/tiktok/post', async (req, res) => {
  if (!_ownerSecretOk(req)) return res.status(403).json({ error: 'Forbidden — secret required' });
  const { video_url, content } = req.body || {};
  if (!video_url) return res.status(400).json({ error: 'video_url is required (TikTok posts video, not text/images)' });
  let postRow = null;
  try {
    if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
    const { data: acct } = await supabase.from('social_accounts').select('access_token').eq('platform', 'tiktok').order('connected_at', { ascending: false }).limit(1).maybeSingle();
    if (!acct) return res.status(400).json({ error: 'No TikTok account connected — visit /auth/tiktok/start first' });
    const { data } = await supabase.from('social_posts').insert([{ platform: 'tiktok', content, media_url: video_url, status: 'queued' }]).select().single();
    postRow = data;
    const r = await fetch('https://open.tiktokapis.com/v2/post/publish/video/init/', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${acct.access_token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        post_info: { title: content || '', privacy_level: 'SELF_ONLY' },
        source_info: { source: 'PULL_FROM_URL', video_url },
      }),
    });
    const result = await r.json();
    if (result.error && result.error.code !== 'ok') throw new Error(result.error.message || 'TikTok post init failed');
    const publishId = result.data && result.data.publish_id;
    await supabase.from('social_posts').update({ status: 'posted', external_post_id: publishId, posted_at: new Date().toISOString() }).eq('id', postRow.id);
    res.json({ ok: true, publish_id: publishId, note: 'privacy_level is SELF_ONLY (TikTok default for unaudited apps) — switch to PUBLIC_TO_EVERYONE once your app passes Content Posting API review.' });
  } catch (e) {
    if (supabase && postRow) await supabase.from('social_posts').update({ status: 'failed', error: e.message }).eq('id', postRow.id);
    res.status(500).json({ error: e.message });
  }
});

// ════════════════════════════════════════
// CATCH-ALL 404  (must be after ALL routes)
// ════════════════════════════════════════
app.use((req, res) => {
  res.status(404).json({ error: 'route not found', path: req.path, method: req.method });
});

// GLOBAL ERROR HANDLER — catches any unhandled async throws
app.use((err, req, res, next) => {
  console.error('EXPRESS ERROR:', err.stack || err.message || err);
  if (res.headersSent) return next(err);
  res.status(500).json({ error: 'Internal server error' });
});

// ════════════════════════════════════════
// START SERVER
// ════════════════════════════════════════
const PORT = process.env.PORT || 3000;
app.listen(PORT, '0.0.0.0', () => {
  console.log(`Blueprint Studio server running on port ${PORT} (0.0.0.0)`);
  addLog('Server started', 'system', 'success');
  // Self-test so we can see in Render logs if routes work
  fetch(`http://localhost:${PORT}/ping`)
    .then(r => r.json())
    .then(d => console.log('SELF-TEST OK:', JSON.stringify(d)))
    .catch(e => console.error('SELF-TEST FAIL:', e.message));
});
