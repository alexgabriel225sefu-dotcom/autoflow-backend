const express = require('express');
const cors = require('cors');
const path = require('path');
const { createClient } = require('@supabase/supabase-js');
const Anthropic = require('@anthropic-ai/sdk');
const nodemailer = require('nodemailer');
const crypto = require('crypto');
const stripe = process.env.STRIPE_SECRET_KEY ? require('stripe')(process.env.STRIPE_SECRET_KEY) : null;

process.on('uncaughtException', err => console.error('UNCAUGHT EXCEPTION:', err.stack || err));
process.on('unhandledRejection', err => console.error('UNHANDLED REJECTION:', err));

const app = express();
app.set('trust proxy', 1);
const rateLimit = require('express-rate-limit');
const _ALLOWED_ORIGINS = new Set([
  'https://aicashsystem.onrender.com', 'https://aicashsystem.space', 'https://www.aicashsystem.space'
]);
// req.headers.origin is client-controlled — never use it directly to build a
// redirect URL. Restrict to the known site origins before it feeds success/
// return/cancel URLs (checkout, Stripe Connect onboarding, etc).
function _safeOrigin(req) {
  const requested = req.headers.origin || '';
  return _ALLOWED_ORIGINS.has(requested) ? requested : 'https://aicashsystem.space';
}
app.use(cors({
  origin: ['https://aicashsystem.onrender.com', 'https://aicashsystem.space', 'https://www.aicashsystem.space'],
  credentials: true
}));
// Skip JSON body parsing where a webhook needs its untouched raw body.
// The Meta webhook needs the raw body preserved too (HMAC signature check in
// _metaVerifySignature can't hash a body that's already been re-serialized).
app.use((req, res, next) => {
  // Stripe needs the untouched raw body Buffer to verify its signature —
  // skip JSON parsing entirely here; the route below applies express.raw() itself.
  if (req.path === '/stripe-webhook') return next();
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
    license_signing_key:  has('BOT_EMAIL_SECRET'),
    supabase_url:         has('SUPABASE_URL'),
    supabase_key:         has('SUPABASE_SERVICE_KEY'),
    supabase_connects:    dbConnect,
    email_delivery:       emailReady,
    // RECOMMENDED — degraded experience if missing, but sale still completes
    ai_fallback:          has('GROQ_API_KEY') || has('ANTHROPIC_API_KEY') || has('GOOGLE_AI_API_KEY'),
    // Still read: it is the Telegram transport _notifyAdminAlert falls back to
    // for OWNER alerts. The affiliate program it was named after is gone.
    admin_alert_bot:      has('AFFILIATE_BOT_TOKEN'),
    stripe_secret_key:         has('STRIPE_SECRET_KEY'),
    stripe_webhook_secret:     has('STRIPE_WEBHOOK_SECRET'),
    session_secrets:      has('JWT_SECRET') && has('COOKIE_SECRET'),
  };

  const critical = ['license_signing_key','supabase_url','supabase_key','supabase_connects','email_delivery'];
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

const SETUP_SYSTEM = `You are a concise support assistant for Apex Forex Bot — an
AI forex trading bot that runs on our servers and is controlled through Telegram.
Help users get started. Be short and direct (2-4 sentences max). No markdown headers. Use plain text.
IMPORTANT: Always reply in the SAME language the user wrote in. Detect it automatically.

THERE IS NOTHING TO DEPLOY. No Railway, no Docker, no exchange API key. The bot
is hosted; the client only opens Telegram.

SETUP STEPS:
1. Open the Telegram link from the purchase email (it carries the licence key).
2. Connect the cTrader account when the bot asks — a demo account is the default.
3. Answer the short setup questions (instrument, style, risk).
4. The bot starts in DEMO. Going live is a separate, explicit step.

WHAT IT TRADES: forex majors with a USD leg, plus metals. Crypto, indices and
stock CFDs are not supported.

COMMON ERRORS:
- "Invalid license key" -> open the key via the Telegram link from the email.
- "Not activated" -> still in demo; live activation is deliberate and separate.
- No trades yet -> normal, forex moves at macro pace (0-3 trades a day).
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

    if (m.includes('license') || m.includes('licenta') || m.includes('cheie') || m.includes('key'))
      return T('Cheia ai primit-o pe email dupa cumparare — deschide linkul de Telegram din acel email si contul se activeaza singur. Daca nu l-ai primit, verifica Spam sau scrie la supportaicashsystem@gmail.com.', 'Your key was emailed after purchase — open the Telegram link in that email and the account activates itself. If it never arrived, check Spam or email supportaicashsystem@gmail.com.');
    if (m.includes('ctrader') || m.includes('broker') || m.includes('cont') || m.includes('account'))
      return T('Conectezi contul cTrader din bot, cand te intreaba. Un cont demo e perfect si e varianta implicita.', 'You connect your cTrader account from inside the bot when it asks. A demo account is fine and is the default.');
    if (m.includes('demo') || m.includes('live') || m.includes('real money') || m.includes('bani reali'))
      return T('Botul porneste in DEMO. Trecerea pe live e un pas separat pe care il faci tu explicit.', 'The bot starts in DEMO. Going live is a separate step you take explicitly.');
    if (m.includes('crypto') || m.includes('bitcoin') || m.includes('btc') || m.includes('stock'))
      return T('Botul tranzactioneaza doar forex (perechi cu USD) si metale. Crypto, indici si actiuni nu sunt suportate.', 'The bot trades forex pairs with a USD leg, plus metals. Crypto, indices and stock CFDs are not supported.');
    if (m.includes('deploy') || m.includes('railway') || m.includes('docker') || m.includes('server'))
      return T('Nu ai nimic de instalat — botul ruleaza pe serverele noastre. Deschizi doar Telegram.', 'There is nothing to deploy — the bot runs on our servers. You only open Telegram.');
    if (m.includes('trade') || m.includes('tranzac') || m.includes('no trades'))
      return T('Normal la inceput: forexul se misca lent, 0-3 tranzactii pe zi.', 'Normal early on: forex moves at macro pace, 0-3 trades a day.');
    if (m.includes('hello') || m.includes('hi') || m.includes('hey') || m.includes('salut') || m.includes('buna') || m.includes('help'))
      return T('Salut! Sunt asistentul Apex Forex Bot. Te pot ajuta cu activare, conectare cTrader, demo vs live.', 'Hi! I am the Apex Forex Bot assistant. I can help with activation, connecting cTrader, demo vs live.');
    if (m.includes('support') || m.includes('contact') || m.includes('email') || m.includes('suport'))
      return T('Suport direct: supportaicashsystem@gmail.com.', 'Direct support: supportaicashsystem@gmail.com.');
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
const _IS_PROD = process.env.NODE_ENV === 'production' || process.env.RENDER === 'true';

// Every secret whose ABSENCE is unsafe or silently destructive, checked in ONE
// pass so a failed boot names all of them at once. Failing on the first would
// mean discovering the list one deploy at a time, with the service down in
// between — which is precisely the outage this is meant to prevent.
//
// Deliberately NOT everything the service uses. A missing Stripe key breaks
// checkout loudly and the site still serves; refusing to boot over it would
// turn a degraded service into no service. These two are different: without
// them the service keeps working while being WRONG.
function _requireProductionSecrets() {
  const required = [
    ['JWT_SECRET',
     'signs sessions AND derives the key that encrypts client bot configs at ' +
     'rest (_botConfigKey). Generating one per process silently orphans every ' +
     'stored config on restart and across instances.'],
    ['BOT_EMAIL_SECRET',
     'signs licence keys. Without it they are signed with a constant published ' +
     'in this repository, so anyone reading the source can mint a valid ' +
     'signature.'],
  ];
  const missing = required.filter(([k]) => !String(process.env[k] || '').trim());
  if (!_IS_PROD || missing.length === 0) return;
  console.error('\n[FATAL] This is production and required secrets are missing:\n');
  for (const [k, why] of missing) console.error(`  • ${k} — ${why}\n`);
  console.error('Set them in the Render dashboard, then redeploy. render.yaml\n' +
                'already declares JWT_SECRET with generateValue: true.\n');
  process.exit(1);
}
_requireProductionSecrets();
const JWT_SECRET = process.env.JWT_SECRET || (() => {
  const fallback = require('crypto').randomBytes(32).toString('hex');
  console.warn('[WARN] JWT_SECRET not set — generated a random secret for this DEV session. Sessions reset on restart and stored bot configs will not decrypt.');
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
// single visitor reloading the page doesn't inflate the visit count. ──
const _recentClicks = new Map();
const _CLICK_DEDUPE_MS = 30 * 60 * 1000;

// ── IN-MEMORY LOGS ──
const logs = [];
function addLog(msg, type = 'info', status = 'success') {
  logs.unshift({ msg, type, status, time: new Date().toISOString() });
  if (logs.length > 200) logs.pop();
}
// Mask a customer email before it goes into the (dashboard-readable) log store.
function _maskEmail(email) {
  const s = String(email || '');
  const at = s.indexOf('@');
  if (at <= 0) return s ? '***' : '';
  return `${s[0]}***${s.slice(at)}`;
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
// Forex keys: FORX-XXXX-XXXX-XXXX — HMAC-SHA256 over a random body.
// The retired crypto product's APEX- keys are no longer minted or verified:
// the bot they unlocked does not exist, so accepting one would authorise
// access to nothing.
const _KEY_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // 32 chars, no 0/O/1/I
// Pre-BOT_EMAIL_SECRET keys were signed with this constant. It is published in
// this repository, so anyone reading the source can forge a signature with it —
// which is why it is NOT usable for signing and startup refuses it in
// production (see _requireProductionSecrets). It survives only so that a key
// issued back then can still be RECOGNISED in development; the licences row,
// not the signature, is what actually authorises anything.
const _LEGACY_LIC_SALT = 'apex-forex-2025-v1';

function _licSecrets(product = 'apex-forex') {
  const env = process.env.BOT_EMAIL_SECRET;
  return env ? [`${env}-${product}`] : [_LEGACY_LIC_SALT];
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

function generateForexKey()   { return _generateKey('FORX', 'apex-forex'); }

// Returns { valid, product } — product is 'apex-bot' | 'apex-forex' | null
function verifyLicenseKeyHmac(key) {
  if (!key) return { valid: false, product: null };
  const k = key.toUpperCase();
  const prefixMap = { FORX: 'apex-forex' };
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
  console.log(`[LEAD] ${email}${ref ? ' (ref ' + ref + ')' : ''} via ${source}`);
  res.json({ ok: true });
});

async function _notifyAdminAlert(text, subject = 'Apex Trading Suite — alertă') {
  const hook = process.env.MAKE_ALERT_WEBHOOK;
  if (hook) {
    try {
      const r = await fetch(hook, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subject, text, site: 'aicashsystem.space', at: new Date().toISOString() }),
        signal: AbortSignal.timeout(10000)
      });
      if (r.ok) return;
      addLog(`Admin alert: Make webhook rejected (HTTP ${r.status}) — trying next channel`, 'system', 'warn');
    } catch (e) { addLog(`Admin alert: Make webhook error: ${e.message} — trying next channel`, 'system', 'warn'); }
  }

  // No hardcoded operator identity. These used to fall back to one person's
  // Telegram id and personal email address, which meant an unconfigured
  // deployment silently delivered another operator's payment and licence
  // alerts to them — and made ADMIN_CHAT_ID look optional when it is not.
  const botToken = process.env.AFFILIATE_BOT_TOKEN;
  const adminChatId = process.env.ADMIN_CHAT_ID;
  if (botToken && adminChatId) {
    try {
      const r = await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat_id: adminChatId, text }),
        signal: AbortSignal.timeout(10000)
      });
      if (r.ok) return;
      addLog(`Admin alert: Telegram rejected (HTTP ${r.status}) — trying email`, 'system', 'warn');
    } catch (e) { addLog(`Admin alert: Telegram error: ${e.message} — trying email`, 'system', 'warn'); }
  }

  const adminEmail = process.env.ADMIN_EMAIL;
  if (!adminEmail) {
    // Loud, because an alert nobody receives is worse than no alert system:
    // the operator believes they are being told about failed fulfilments.
    addLog('Admin alert UNDELIVERABLE — no ADMIN_CHAT_ID and no ADMIN_EMAIL configured. ' +
           `Alert text: ${text.slice(0, 200)}`, 'system', 'error');
    return;
  }
  try {
    const res = await _sendEmail({
      to: adminEmail, subject, fromName: 'Apex Alerts',
      html: `<pre style="font:14px/1.6 -apple-system,Segoe UI,sans-serif;white-space:pre-wrap">${_he(text)}</pre>`
    });
    if (!res.ok) addLog(`Admin alert undeliverable on every channel: ${res.error}`, 'system', 'error');
  } catch (e) { addLog(`Admin alert email error: ${e.message}`, 'system', 'error'); }
}

function _ownerSecretOk(req) {
  const secret = req.query.secret || req.headers['x-owner-secret'];
  return process.env.BOT_EMAIL_SECRET && secret === process.env.BOT_EMAIL_SECRET;
}
app.get('/api/owner-license', async (req, res) => {
  const secret = req.query.secret || req.headers['x-owner-secret'];
  const expected = process.env.BOT_EMAIL_SECRET;
  if (!expected || secret !== expected) return res.status(403).json({ error: 'Forbidden — secret required' });
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const product = 'apex-forex';
  const key = generateForexKey();
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

// POST /api/admin/grant-license?secret=... — { email, name?, product: 'apex-forex' }
// Manually grants full, non-expiring access to anyone the owner chooses — no
// checkout involved. Mints a real license key per product (same format/
// verification path as a paid one) and sends the exact same activation email
// a paying customer gets, so the recipient's experience (license + the
// "Open your bot on Telegram" button) is identical either way.
app.post('/api/admin/grant-license', async (req, res) => {
  if (!_ownerSecretOk(req)) return res.status(403).json({ error: 'Forbidden — secret required' });
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const email = String(req.body?.email || '').trim().slice(0, 200);
  const name = String(req.body?.name || 'there').trim().slice(0, 100) || 'there';
  const want = String(req.body?.product || '').toLowerCase();
  // FOREX ONLY. This defaulted an unrecognised `product` to the crypto bot, so
  // a typo minted an APEX- key and emailed a link to a bot that is gone.
  // Unknown product is a refusal now, not a fallback.
  if (want && want !== 'apex-forex') {
    return res.status(400).json({ error: "Unknown product — only 'apex-forex' is sold." });
  }
  const products = ['apex-forex'];
  if (!email) return res.status(400).json({ error: 'email is required' });

  const results = [];
  for (const product of products) {
    const key = generateForexKey();
    const { error } = await supabase.from('licenses').insert([{
      key, email, name, active: true, activated_at: null, product, trial: false
    }]);
    if (error) {
      addLog(`Grant-license DB error (${product}) for ${_maskEmail(email)}: ${error.message}`, 'license', 'error');
      results.push({ product, error: error.message });
      continue;
    }
    const html = _buildForexEmailHtml(_he(name), _he(email), key);
    const subject = '🤖 Your Apex Forex Bot — License Key inside';
    const sent = await _sendEmail({ to: email, subject, html, fromName: 'Apex.Bot' });
    const botHandle = 'FOREX_APEX_BOT';
    addLog(`Granted ${product} license: ${key} for ${_maskEmail(email)}${sent.ok ? '' : ' (email FAILED to send)'}`, 'license', sent.ok ? 'success' : 'warn');
    results.push({ product, key, emailSent: sent.ok, telegramLink: `https://t.me/${botHandle}?start=${key}` });
  }
  res.json({ email, results });
});

// Why the licence store could not be read. A missing TABLE and a missing
// NETWORK are both "cannot read", but they need opposite responses: one is a
// deployment pointed at the wrong (or unmigrated) database and will never fix
// itself, the other clears on its own. Reporting both as "temporarily
// unavailable" sends the operator hunting a connectivity fault that does not
// exist — verified by booting this server against a real Supabase project with
// no `licenses` table: it answered "try again in a few minutes", forever.
function _licenceStoreFault(err) {
  const code = String(err?.code || '');
  const msg = String(err?.message || err || '');
  const schema = code === '42P01' || code === 'PGRST205'
    || /does not exist|schema cache|relation .* does not exist/i.test(msg);
  return schema ? 'SCHEMA' : 'UNREACHABLE';
}

function _licenceStoreDenial(res, err, where) {
  const fault = _licenceStoreFault(err);
  const detail = String(err?.message || err || '').slice(0, 200);
  if (fault === 'SCHEMA') {
    addLog(`verify-license: licence store MISCONFIGURED at ${where} — ${detail}`,
           'license', 'error');
    _notifyAdminAlert(
      `🚨 The licence table cannot be read, and this will NOT clear on its own.\n\n` +
      `Where: ${where}\nError: ${detail}\n\n` +
      `SUPABASE_URL is pointing at a database with no \`licenses\` table — the ` +
      `wrong project, or one that was never migrated. Every activation is being ` +
      `refused until it is fixed.`,
      'Apex — licence store misconfigured');
  } else {
    addLog(`verify-license: licence store unreachable at ${where} — ${detail}`,
           'license', 'error');
  }
  return res.status(503).json({
    valid: false,
    message: fault === 'SCHEMA'
      ? 'Licence checks are unavailable — our team has been alerted. Please contact support.'
      : 'Licence service temporarily unavailable — please try again in a few minutes.',
  });
}

// POST /api/verify-license — called by the bot on every startup
// Body: { key, product? }  — product is 'apex-bot' | 'apex-forex'
// Primary: HMAC signature check (no DB). Fallback: Supabase for legacy keys.
app.post('/api/verify-license', _licenseLimiter, async (req, res) => {
  const { key, product: claimedProduct } = req.body || {};
  if (!key) return res.json({ valid: false, message: 'No license key provided' });

  // 1. Signature, then the ONLY authority on whether it was paid for.
  //
  // A valid HMAC proves this server minted the key. It does NOT prove the key
  // was paid for, is still paid for, or was not refunded — a refunded
  // customer, an expired trial and an abandoned checkout all keep a
  // permanently valid signature. Only the licences row knows, and the payment
  // webhook is the only thing that writes active:true to it.
  //
  // So ALL of these must hold: signature valid, row exists, product matches,
  // active, not refunded, not expired. Anything missing is a denial, and an
  // unreadable store is a denial too.
  const hmacResult = verifyLicenseKeyHmac(key);
  if (hmacResult.valid) {
    if (claimedProduct && hmacResult.product && claimedProduct !== hmacResult.product) {
      return res.json({ valid: false, message: `Wrong license type. This key is for ${hmacResult.product}. Purchase the correct bot at aicashsystem.space` });
    }
    // No database configured at all is not the same as a database that cannot
    // be read: it is a deployment that never records payments, so there is
    // nothing to consult and nothing to grant. Refuse rather than invent an
    // entitlement.
    if (!supabase) {
      addLog('verify-license: no licence store configured — DENYING', 'license', 'error');
      return res.status(503).json({ valid: false, message: 'Licence service is not configured — please contact support.' });
    }
    let row, rowErr;
    try {
      ({ data: row, error: rowErr } = await supabase.from('licenses')
        .select('active,refunded,trial,expires_at,product').eq('key', key).maybeSingle());
    } catch (e) {
      rowErr = e;
    }
    // supabase-js reports a network/permission failure in `error` and does NOT
    // always throw, so checking only the thrown case left the endpoint
    // fail-open for the most common outage shape. Verified by booting this
    // server against an unreachable SUPABASE_URL. maybeSingle() reports no
    // error for zero rows, so any error here is a real failure to read.
    // 503 rather than {valid:false}: the bot reads any 5xx as "cannot check
    // right now", where a false would tell a paying customer their licence is
    // bad. _licenceStoreDenial also tells the OPERATOR which kind of fault it
    // is, because a missing table and a missing network need opposite fixes.
    if (rowErr) return _licenceStoreDenial(res, rowErr, 'signed lookup');
    if (!row) {
      // NO ROW = NOT SOLD. This used to fall through to allow, as a
      // "legacy/manual key". Combined with the auto-upsert that used to sit
      // below, a signature alone both granted access AND wrote itself an
      // active licence — verification minting its own entitlement.
      // This is the ONE denial that might be a real customer rather than an
      // attacker: every path that mints a key also writes its row, so a signed
      // key with no row is either forged or predates the licences table. The
      // operator cannot tell those apart from a log line nobody reads, and the
      // customer's version of this event is "the bot stopped working", so it
      // is surfaced rather than merely recorded.
      addLog(`verify-license: signed key with no licence row — DENYING (${String(key).slice(0, 9)}…)`, 'license', 'warn');
      _notifyAdminAlert(
        `⚠️ A correctly-signed licence key was refused because it has no row in ` +
        `the licences table.\n\nKey: ${String(key).slice(0, 9)}…\n\n` +
        `Every path that issues a key also writes its row, so this is either a ` +
        `forged signature (ignore it) or a key issued before that table existed ` +
        `(a real customer, now locked out — add their row).`
      );
      return res.json({ valid: false, message: 'This licence is not registered. If you have just paid, wait a minute and tap the link in your email.' });
    }
    if (row.refunded === true) {
      return res.json({ valid: false, message: 'This license was refunded and is no longer active. Repurchase at aicashsystem.space' });
    }
    if (row.active !== true) {
      return res.json({ valid: false, message: 'Payment not completed yet. If you just paid, wait a minute and tap the link in your email.' });
    }
    if (row.expires_at && new Date(row.expires_at).getTime() <= Date.now()) {
      supabase.from('licenses').update({ active: false }).eq('key', key)
        .then(() => {}).catch(() => {});
      return res.json({ valid: false, message: row.trial === true
        ? 'Your free trial has ended. For full access, get your bot at aicashsystem.space'
        : 'This licence has expired. Renew at aicashsystem.space' });
    }
    if (claimedProduct && row.product && claimedProduct !== row.product) {
      return res.json({ valid: false, message: `Wrong license type. This key is for ${row.product}.` });
    }
    // Deliberately NO upsert here. Verification must not create or reactivate
    // an entitlement; the payment webhook is the only writer of active:true.
    return res.json({ valid: true, message: 'License valid', product: hmacResult.product });
  }

  // 2. Supabase fallback — for legacy keys or manual inserts.
  //
  // First: a key that does not even have this product's shape cannot be a
  // legacy key of ours, so it is definitively invalid and no database is
  // needed to say so. Without this short-circuit an outage turned every
  // typo — and every APEX- key from the retired crypto product — into "try
  // again in a few minutes", which is both unhelpful and untrue.
  //
  // A key that DOES have the shape but fails the signature check may still be
  // a legacy key issued before BOT_EMAIL_SECRET existed; only the database
  // knows. That case genuinely cannot be answered while the store is down, so
  // it gets the 503 below rather than a false "invalid".
  if (!/^FORX-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$/.test(String(key).toUpperCase())) {
    return res.json({ valid: false, message: 'Invalid license key. Purchase at aicashsystem.space' });
  }
  if (!supabase) {
    addLog('verify-license: no licence store configured — DENYING legacy lookup', 'license', 'error');
    return res.status(503).json({ valid: false, message: 'Licence service is not configured — please contact support.' });
  }
  let lrow, lerr;
  try {
    // maybeSingle(), not single(): single() reports "no rows" as an error, so
    // a genuine read failure and an ordinary miss arrived down the same path
    // and had to be told apart by an error code. maybeSingle() gives null for
    // a miss and an error only for a real failure.
    ({ data: lrow, error: lerr } = await supabase.from('licenses')
      .select('active,product,refunded,expires_at,trial').eq('key', key).maybeSingle());
  } catch (e) {
    // The old code swallowed this with `catch (_) {}` and fell through to
    // "Invalid license key" — the safe direction, but it told a paying
    // customer their key was bad and logged nothing for the operator.
    lerr = e;
  }
  if (lerr) return _licenceStoreDenial(res, lerr, 'legacy lookup');
  if (lrow) {
    // The legacy path answers the SAME questions as the signed path. Checking
    // only `active` here would have let a refunded or expired legacy key
    // through on a route that skips the signature entirely.
    if (lrow.refunded === true) {
      return res.json({ valid: false, message: 'This license was refunded and is no longer active. Repurchase at aicashsystem.space' });
    }
    if (lrow.active !== true) {
      return res.json({ valid: false, message: 'Payment not completed yet. If you just paid, wait a minute and tap the link in your email.' });
    }
    if (lrow.expires_at && new Date(lrow.expires_at).getTime() <= Date.now()) {
      supabase.from('licenses').update({ active: false }).eq('key', key)
        .then(() => {}).catch(() => {});
      return res.json({ valid: false, message: lrow.trial === true
        ? 'Your free trial has ended. For full access, get your bot at aicashsystem.space'
        : 'This licence has expired. Renew at aicashsystem.space' });
    }
    if (claimedProduct && lrow.product && claimedProduct !== lrow.product) {
      return res.json({ valid: false, message: `Wrong license type. This key is for ${lrow.product}.` });
    }
    return res.json({ valid: true, message: 'License valid (legacy)', product: lrow.product });
  }

  return res.json({ valid: false, message: 'Invalid license key. Purchase at aicashsystem.space' });
});

// POST /api/admin/trial/issue?secret=... — { email, product, days? } -> { key, telegramLink, expiresAt }
// Issues a free-trial license: same key format/verification path as a paid one,
// but flagged trial:true with an expires_at that /api/verify-license enforces.
app.post('/api/admin/trial/issue', async (req, res) => {
  if (!_ownerSecretOk(req)) return res.status(403).json({ error: 'Forbidden — secret required' });
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const email = String(req.body?.email || '').trim().slice(0, 200);
  const product = 'apex-forex';
  const days = Math.min(Math.max(parseInt(req.body?.days, 10) || 5, 1), 30);
  const key = generateForexKey();
  const expiresAt = new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString();
  const { error } = await supabase.from('licenses').insert([{
    key, email, active: true, activated_at: null, product, trial: true, expires_at: expiresAt
  }]);
  if (error) return res.status(500).json({ error: error.message });
  const botHandle = 'FOREX_APEX_BOT';
  addLog(`Trial issued: ${key} (${product}, ${days}d) for ${email || 'no email'}`, 'license', 'success');
  res.json({ key, product, expiresAt, telegramLink: `https://t.me/${botHandle}?start=${key}` });
});

// POST /api/admin/trial/finish?secret=... — cuts off every still-active trial license at once.
// The bot's next /api/verify-license check (on startup/restart) will then reject them with
// the "trial ended, get full access at aicashsystem.space" message.
app.post('/api/admin/trial/finish', async (req, res) => {
  if (!_ownerSecretOk(req)) return res.status(403).json({ error: 'Forbidden — secret required' });
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const { data: rows } = await supabase.from('licenses')
    .select('key,email,product').eq('trial', true).eq('active', true);
  if (rows?.length) {
    const keys = rows.map(r => r.key);
    await supabase.from('licenses').update({ active: false }).in('key', keys);
  }
  addLog(`Trial /finish: cut off ${rows?.length || 0} active trial(s)`, 'license', 'success');
  res.json({ cutOff: rows?.length || 0, licenses: rows || [] });
});

// ── STRIPE CHECKOUT ─────────────────────────────────────────────────────────
// We are the merchant of record here (unlike D24) — Stripe just processes the
// card. Below the Romanian VAT-exemption threshold this needs no special tax
// handling; see the PFA discussion elsewhere for when that changes.
// Stripe is the primary/default processor now — ApexTradingSuite (acct_1TSAWQGpBbs5xtI5),
// business profile corrected to match what's actually sold, live and charges_enabled.
// Price IDs default to the ones created on that account; override via env if recreated.
// FOREX ONLY. The 'apex-crypto' SKU is removed, not disabled: the bot it
// delivered no longer exists, so a completed checkout would take money for
// something that cannot be shipped.
const STRIPE_PRICE_IDS = {
  'apex-forex': process.env.STRIPE_PRICE_FOREX || 'price_1Tge4PGpBbs5xtI5jAjgndKZ'
};
// Matches the one_time_price unit_amount on each Stripe Price above — used to
// price the order without an extra API round-trip.
const STRIPE_PRODUCT_AMOUNTS_CENTS = { 'apex-forex': 49700 };

// POST /api/checkout/create-session — { product: 'apex-forex', ref? } -> { url }
app.post('/api/checkout/create-session', _authLimiter, async (req, res) => {
  const product = String(req.body?.product || '');
  const ref = String(req.body?.ref || '').toLowerCase().trim().slice(0, 40);
  const origin = _safeOrigin(req);

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

      // `ref` is kept as plain provenance — where the buyer came from — and is
      // no longer an attribution key: there is no affiliate program to pay.
      sessionParams.metadata = { product, ref };

      const session = await stripe.checkout.sessions.create(sessionParams);
      return res.json({ url: session.url });
    } catch (e) {
      addLog(`[Stripe] Checkout session error: ${e.message}`, 'payment', 'error');
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

// Shared fulfillment: licence generation and the licence email. `provider` only
// controls the log/alert prefix, so a second processor can reuse this without a
// second copy of the fulfillment logic.
async function _fulfillOrder({ provider, piRef, product, email, buyerName, amountCents, ref }) {
  // Money has already changed hands here, so an unknown product must not be
  // silently fulfilled as the retired crypto bot — that delivers a key for
  // something that does not exist. Refuse loudly and alert the operator.
  if (product !== 'apex-forex') {
    addLog(`[${provider}] REFUSED fulfilment for unknown product ${product} — ref ${piRef}`, 'payment', 'error');
    _notifyAdminAlert(
      `⚠️ A payment (${provider}) arrived for product "${product}", which is no ` +
      `longer sold. NOTHING was delivered and no key was minted.\n\n` +
      `Email: ${email}\nRef: ${piRef}\n\nRefund or handle manually.`
    );
    return;
  }
  let licenseKey;
  if (supabase) {
    const { data: existing } = await supabase.from('licenses').select('key').eq('payment_intent_id', piRef).maybeSingle();
    if (existing?.key) licenseKey = existing.key;
  }
  const isNew = !licenseKey;
  if (!licenseKey) licenseKey = generateForexKey();

  if (supabase) {
    const { error } = await supabase.from('licenses').upsert([{
      key: licenseKey, active: true, activated_at: new Date().toISOString(),
      email: email || '', name: buyerName || 'there', product, payment_intent_id: piRef
    }], { onConflict: 'key' });
    if (error) addLog(`[${provider}] License DB error: ${error.message}`, 'license', 'error');
  }
  addLog(`[${provider}] License activated: ${licenseKey} for ${_maskEmail(email)} (${product})`, 'license', 'success');

  if (isNew && email) {
    const html = _buildForexEmailHtml(_he(buyerName || 'there'), _he(email), licenseKey);
    const subject = '🤖 Your Apex Forex Bot — License Key inside';
    const result = await _sendEmail({ to: email, subject, html, fromName: 'Apex.Bot' });
    if (!result.ok) {
      addLog(`[${provider}] Email NOT sent for ${_maskEmail(email)} — ${result.error}`, 'email', 'error');
      _notifyAdminAlert(
        `⚠️ Customer paid (${provider}) but the license email FAILED to send.\n\n` +
        `Product: Forex\nEmail: ${email}\nRef: ${piRef}\n` +
        `License key: ${licenseKey}\nError: ${result.error}\n\nSend the key to them manually until this is fixed.`
      );
    } else addLog(`[${provider}] Forex email sent to ${email}`, 'email', 'success');
  }
  if (isNew) addLog(`[${provider}] Forex Bot sold: ${email} — key: ${licenseKey}`, 'payment', 'success');
}
const _fulfillStripeOrder = (args) => _fulfillOrder({ provider: 'Stripe', ...args });

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
      if (STRIPE_PRICE_IDS[product]) {
        if (!session.payment_intent) {
          addLog(`[Stripe] session=${session.id} has no payment_intent — refund revocation will not match`, 'payment', 'warn');
        }
        const piRef = `stripe_${session.payment_intent || session.id}`;
        const email = session.customer_details?.email || '';
        const buyerName = session.customer_details?.name || 'there';
        const amountCents = Number(session.amount_total || 0);
        await _fulfillStripeOrder({ piRef, product, email, buyerName, amountCents, ref });
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
      }
    }
    res.json({ received: true });
  } catch (e) {
    console.error('[Stripe] Webhook error:', e);
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
const _OG_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630"><rect width="1200" height="630" fill="#060608"/><rect x="480" y="340" width="60" height="190" rx="12" fill="#ff2d4f" opacity=".45"/><rect x="570" y="220" width="60" height="310" rx="12" fill="#ff2d4f" opacity=".72"/><rect x="660" y="120" width="60" height="410" rx="12" fill="#ff2d4f"/><circle cx="690" cy="96" r="34" fill="#ff5c74"/><text x="600" y="520" font-family="system-ui,sans-serif" font-weight="700" font-size="38" fill="#f5f5f7" text-anchor="middle">Apex Trading Suite</text><text x="600" y="568" font-family="system-ui,sans-serif" font-size="22" fill="#9696a0" text-anchor="middle">Fully-Hosted AI Forex Trading Bot · $497</text></svg>';
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

// Configurator (linked from the delivery email — license-gated client-side).
// The crypto configurator that used to sit beside this one is gone with its
// product; /configurator now 301s to the homepage further down.
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
// apex-bot.html sold the retired crypto product. The product is gone, so the
// page is redirected rather than served — a live sales page for something that
// cannot be delivered is worse than a 301.
app.get(['/apex-bot', '/apex-bot.html', '/configurator', '/configurator.html',
         '/bot-setup', '/bot-setup.html', '/deploy', '/deploy.html'],
       (req, res) => res.redirect(301, '/index'));

// 'configurator', 'bot-setup' and 'deploy' are gone with the crypto product:
// they configured Binance keys and walked a client through deploying the
// retired Railway image. Serving them would hand a buyer instructions for a
// product that cannot be delivered. 'configurator-forex' is the live one.
const publicPages = ['access','privacy','terms','impressum','intro-epic','app','demo','try','videos','screen','screens','tiktok-demo','video-maker','video-gen','forex','setup-guide','configurator-forex','ad','results','profile','flex','flex2','flex3','heygen','mt5-sim','trading-journal','thank-you','chart','free','promo','guide'];
publicPages.forEach(p => {
  app.get(`/${p}.html`, (req, res) => res.sendFile(path.join(__dirname, 'public', `${p}.html`), { cacheControl: false, headers: { 'Cache-Control': 'no-store' } }));
  app.get(`/${p}`, (req, res) => res.sendFile(path.join(__dirname, 'public', `${p}.html`), { cacheControl: false, headers: { 'Cache-Control': 'no-store' } }));
});

// ── BOT EMAIL HTML — funcție separată reutilizabilă ──────────────────────────
// _buildBotEmailHtml — the crypto bot's delivery email — removed with the product.

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

// ── BOT ACCESS — REMOVED.
// This streamed a ZIP of apex-trade-bot/ (the retired crypto product) to any
// holder of an HMAC-valid key. That directory no longer exists, so the route
// could only 500 — and shipping self-hosted trading source is an execution
// path outside the canonical architecture regardless. The Forex product is
// delivered through Telegram, never as source.

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
    const previewHtml = _buildForexEmailHtml(_he(name), _he(email), 'FORX-DEMO-PREW-2025');
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
  const testKey = generateForexKey();
  const botEmailHtml = _buildForexEmailHtml(_he(name), _he(email), testKey);

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
// Usage: GET /admin/sync-bot-repo?secret=BOT_EMAIL_SECRET&token=ghp_xxx
// ════════════════════════════════════════
app.get('/admin/sync-bot-repo', async (req, res) => {
  const secret = req.query.secret || '';
  // Token can come from the URL (?token=ghp_...) or, preferably, a Render env
  // var GH_TOKEN so it stays out of browser history and URLs.
  const ghToken = req.query.token || process.env.GH_TOKEN || '';
  const adminSecret = process.env.BOT_EMAIL_SECRET || '';

  if (!adminSecret) return res.status(500).json({ error: 'BOT_EMAIL_SECRET not set' });
  if (secret !== adminSecret) return res.status(403).json({ error: 'Wrong secret' });
  if (!ghToken) return res.status(400).json({ error: 'GitHub token required — add GH_TOKEN in Render env, or pass ?token=ghp_...' });

  const fs = require('fs');
  const OWNER = 'alexgabriel225sefu-dotcom';
  const REPO  = 'apex-forex-bot';
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

  const readmeContent = `# Apex Forex Bot 🤖

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
  const strayDir = 'apex-trade-bot';
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
  // No committed fallback. This literal used to be `bot-cfg-fallback-change-me`,
  // published in this repository — anyone who could read the bot_configs table
  // could decrypt every client's stored configuration with a key taken from
  // the source. Refusing is the only safe answer when no real secret exists.
  const s = process.env.JWT_SECRET || process.env.COOKIE_SECRET;
  if (!s) throw new Error('bot config encryption unavailable: JWT_SECRET/COOKIE_SECRET not set');
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
  // One image. The apex-trade-bot image was the retired crypto product; it is
  // no longer built or published, so defaulting an unknown `product` to it
  // would deploy an image that does not exist.
  if (product && product !== 'apex-forex') {
    return res.status(400).json({ error: 'Unknown product — this deploys the Forex bot only.' });
  }
  const image = 'ghcr.io/alexgabriel225sefu-dotcom/apex-forex-bot:latest';
  const projectName = 'apex-forex-bot';

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
// Admin endpoints are protected by the owner secret
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
// Meta can trigger auto-replies — mirrors the payment webhook's
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
