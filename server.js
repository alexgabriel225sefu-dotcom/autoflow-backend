const express = require('express');
const cors = require('cors');
const path = require('path');
const { createClient } = require('@supabase/supabase-js');
const Anthropic = require('@anthropic-ai/sdk');
const nodemailer = require('nodemailer');
const crypto = require('crypto');

process.on('uncaughtException', err => console.error('UNCAUGHT EXCEPTION:', err.stack || err));
process.on('unhandledRejection', err => console.error('UNHANDLED REJECTION:', err));

const app = express();
app.set('trust proxy', 1);
const rateLimit = require('express-rate-limit');
app.use(cors({
  origin: ['https://aicashsystem.onrender.com', 'https://aicashsystem.space', 'https://www.aicashsystem.space'],
  credentials: true
}));
// Skip JSON body parsing for Stripe webhook — it needs the raw Buffer for signature verification
app.use((req, res, next) => {
  if (req.path === '/stripe-webhook' || req.path === '/webhook') return next();
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
app.get('/ping', (req, res) => res.json({ ok: true, version: 'v8-audit-fixes', time: new Date().toISOString() }));
app.get('/api/stripe-config', auth, async (req, res) => {
  const key = process.env.STRIPE_SECRET_KEY || '';
  const isLive = key.startsWith('sk_live_');
  const isTest = key.startsWith('sk_test_');
  let accountInfo = null;
  if (key) {
    try {
      const stripe = require('stripe')(key);
      const account = await stripe.accounts.retrieve();
      accountInfo = {
        name: account.settings?.dashboard?.display_name || account.business_profile?.name || 'N/A',
        email: account.email,
        country: account.country,
        payouts_enabled: account.payouts_enabled,
        charges_enabled: account.charges_enabled,
        currency: account.default_currency,
      };
    } catch(e) { accountInfo = { error: e.message }; }
  }
  res.json({
    key_present: !!key,
    mode: isLive ? '🟢 LIVE — banii intra real' : isTest ? '🟡 TEST — banii nu sunt reali' : '❌ Nicio cheie',
    webhook_secret: !!process.env.STRIPE_WEBHOOK_SECRET,
    account: accountInfo,
  });
});
app.get('/api/app-status', auth, (req, res) => res.json({
  ai_openai:       !!process.env.OPENAI_API_KEY,
  ai_anthropic:    !!process.env.ANTHROPIC_API_KEY,
  ai_works:        !!(process.env.OPENAI_API_KEY || process.env.ANTHROPIC_API_KEY),
  email_works:     !!(process.env.BREVO_API_KEY || (process.env.BREVO_SMTP_USER && process.env.BREVO_SMTP_PASS)),
  stripe_live:     (process.env.STRIPE_SECRET_KEY||'').startsWith('sk_live_'),
  stripe_webhook:  !!process.env.STRIPE_WEBHOOK_SECRET,
  supabase:        !!process.env.SUPABASE_URL,
  verdict: !!(process.env.OPENAI_API_KEY || process.env.ANTHROPIC_API_KEY) ? '✅ Aplicatia functioneaza complet' : '❌ Lipseste cheia AI — Wizard/Chat/Email nu merg'
}));
app.get('/api/email-config', auth, (req, res) => res.json({
  brevo_api_key:  !!process.env.BREVO_API_KEY,
  brevo_smtp_user: !!process.env.BREVO_SMTP_USER,
  brevo_smtp_pass: !!process.env.BREVO_SMTP_PASS,
  sender_email:   !!process.env.SENDER_EMAIL,
  supabase:       !!process.env.SUPABASE_URL,
  stripe:         !!process.env.STRIPE_SECRET_KEY,
  email_will_send: !!(process.env.BREVO_API_KEY || (process.env.BREVO_SMTP_USER && process.env.BREVO_SMTP_PASS)),
}));

// GET /api/tg-config — public, used by payment page to build Telegram deep links
app.get('/api/tg-config', (req, res) => {
  res.json({ botUsername: TG_BOT_USERNAME });
});

// ── ENV VARIABLES ──
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_KEY;
const ANTHROPIC_KEY = process.env.ANTHROPIC_API_KEY;
const OPENAI_KEY = process.env.OPENAI_API_KEY;
const HEYGEN_KEY = process.env.HEYGEN_API_KEY;
const CREATIFY_API_ID  = process.env.CREATIFY_API_ID  || '';
const CREATIFY_API_KEY = process.env.CREATIFY_API_KEY || '';
const TG_BOT_USERNAME  = process.env.TELEGRAM_BOT_USERNAME || '';
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

// ── PENDING LICENSES (payment_intent_id → key) — cleared after 2h ──
const _pendingLicenses = new Map();

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

// POST /create-payment-intent — Stripe
const VALID_AMOUNTS = [3700, 9700, 19700, 29700, 49700]; // $37 starter, $97 pro, $197 legacy, $297 crypto, $497 forex (in cents)
app.post('/create-payment-intent', _paymentLimiter, async (req, res) => {
  const { amount, currency, email, name, product, ref } = req.body;
  const affCode = (ref || '').toString().trim().toLowerCase().slice(0, 40);
  const safeAmount = VALID_AMOUNTS.includes(Number(amount)) ? Number(amount) : 3700;
  // Enforce product/amount consistency
  if (product === 'apex-bot'   && safeAmount !== 29700) return res.status(400).json({ error: 'Invalid amount for apex-bot' });
  if (product === 'apex-forex' && safeAmount !== 49700) return res.status(400).json({ error: 'Invalid amount for apex-forex' });
  if (safeAmount === 29700 && product && product !== 'apex-bot')   return res.status(400).json({ error: 'Invalid product for this amount' });
  if (safeAmount === 49700 && product && product !== 'apex-forex') return res.status(400).json({ error: 'Invalid product for this amount' });
  // Server-side email format validation
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return res.status(400).json({ error: 'Invalid email address' });
  const isApexBot   = (product === 'apex-bot')   || safeAmount === 29700;
  const isApexForex = (product === 'apex-forex')  || safeAmount === 49700;
  const isBotProduct = isApexBot || isApexForex;
  try {
    if (!process.env.STRIPE_SECRET_KEY) return res.status(500).json({ error: 'Stripe not configured' });
    const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
    const paymentIntent = await stripe.paymentIntents.create({
      amount: safeAmount,
      currency: currency || 'usd',
      automatic_payment_methods: { enabled: true },
      receipt_email: email || undefined,
      metadata: {
        product: product || (safeAmount === 29700 ? 'apex-bot' : safeAmount === 49700 ? 'apex-forex' : 'course'),
        email: email || '',
        name: name || '',
        ref: affCode
      }
    });

    // Pre-generate license key for bot products so buyer gets it immediately on success
    let pendingKey = null;
    if (isBotProduct) {
      pendingKey = isApexForex ? generateForexKey() : generateLicenseKey();
      _pendingLicenses.set(paymentIntent.id, { key: pendingKey, email: email || '', name: name || '', product: isApexForex ? 'apex-forex' : 'apex-bot' });
      setTimeout(() => _pendingLicenses.delete(paymentIntent.id), 2 * 3600 * 1000);
      if (supabase) {
        const { error: insErr } = await supabase.from('licenses').insert([{
          key: pendingKey, email: email || '', name: name || '', product: isApexForex ? 'apex-forex' : 'apex-bot',
          active: false, payment_intent_id: paymentIntent.id
        }]);
        if (insErr) console.error('Pending license insert error:', insErr.message);
      }
      addLog(`Pending ${isApexForex ? 'forex' : 'crypto'} license generated for ${email} — ${pendingKey}`, 'license', 'success');
    }

    res.json({ clientSecret: paymentIntent.client_secret, pendingKey });
  } catch (e) {
    console.error('create-payment-intent error:', e.message);
    res.status(500).json({ error: 'Payment processing failed' });
  }
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
function _generateAffiliateCode(name) {
  const slug = (name || 'creator').toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 10) || 'creator';
  return `${slug}${crypto.randomBytes(2).toString('hex')}`;
}

// POST /api/affiliates/apply — { name, email, tiktokHandle } -> { code, link }
app.post('/api/affiliates/apply', _authLimiter, async (req, res) => {
  const { name, email, tiktokHandle } = req.body || {};
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return res.status(400).json({ error: 'Invalid email address' });
  if (!supabase) return res.status(500).json({ error: 'Supabase not configured' });
  const cleanEmail = email.toLowerCase().trim();
  try {
    const { data: existing } = await supabase.from('affiliates').select('code').eq('email', cleanEmail).maybeSingle();
    if (existing?.code) return res.json({ code: existing.code, link: `https://aicashsystem.space/apex-bot.html?ref=${existing.code}` });

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
    res.json({ code, link: `https://aicashsystem.space/apex-bot.html?ref=${code}` });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
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
  const { error } = await supabase.from('licenses').insert([{ key, email: 'owner@aicashsystem.space', name: 'Owner', active: true, product }]);
  if (error) return res.status(500).json({ error: error.message, hint: error.hint });
  res.json({ key, product, message: `Add this as LICENSE_KEY for your ${product} bot`, supabase: 'inserted ok' });
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

// ════════════════════════════════════════
// STRIPE WEBHOOK
// ════════════════════════════════════════
// Stripe webhook handler — responds to both /stripe-webhook AND /webhook
// (Stripe Dashboard configured with /webhook; /stripe-webhook kept for backward compat)
async function handleStripeWebhook(req, res) {
  const sig = req.headers['stripe-signature'];
  try {
    if (!process.env.STRIPE_SECRET_KEY || !process.env.STRIPE_WEBHOOK_SECRET) {
      console.error('[STRIPE] Missing keys — webhook rejected');
      return res.status(400).json({ error: 'Webhook not configured' });
    }
    const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
    const event = stripe.webhooks.constructEvent(req.body, sig, process.env.STRIPE_WEBHOOK_SECRET);

    if (event.type === 'payment_intent.succeeded') {
      const pi = event.data.object;
      // Payment Link buyers may not populate receipt_email — check charge billing details too
      const email = pi.metadata?.email || pi.receipt_email
        || pi.charges?.data?.[0]?.billing_details?.email || '';
      // Detect product from metadata (inline checkout) or amount (Payment Link)
      const product = pi.metadata?.product === 'apex-forex' || pi.amount === 49700
        ? 'apex-forex'
        : (pi.metadata?.product === 'apex-bot' || pi.amount === 29700)
          ? 'apex-bot'
          : (pi.metadata?.product || 'course');
      const buyerName = pi.metadata?.name || 'there';

      // ── BOT LICENSE DELIVERY (crypto + forex) ──
      if (product === 'apex-bot' || product === 'apex-forex') {
        const isForex = product === 'apex-forex';
        const pending = _pendingLicenses.get(pi.id);
        let licenseKey;

        if (pending?.key) {
          licenseKey = pending.key;
          _pendingLicenses.delete(pi.id);
        } else if (supabase) {
          const { data: dbRow } = await supabase.from('licenses')
            .select('key').eq('payment_intent_id', pi.id).single();
          if (dbRow?.key) {
            licenseKey = dbRow.key;
            addLog(`License recovered from DB for ${email} — ${licenseKey}`, 'license', 'info');
          }
        }
        if (!licenseKey) {
          licenseKey = isForex ? generateForexKey() : generateLicenseKey();
          addLog(`License generated (last-resort): ${licenseKey} for ${email}`, 'license', 'warn');
        }
        if (supabase) {
          const { error } = await supabase.from('licenses')
            .upsert([{ key: licenseKey, active: true, activated_at: new Date().toISOString(), email: email || '', name: buyerName, product }], { onConflict: 'key' });
          if (error) addLog(`License activate DB error: ${error.message}`, 'license', 'error');
        }
        addLog(`License activated: ${licenseKey} for ${email} (${product})`, 'license', 'success');

        // ── Affiliate commission attribution ──
        const refCode = (pi.metadata?.ref || '').toLowerCase().trim();
        if (refCode && supabase) {
          try {
            const { data: aff } = await supabase.from('affiliates').select('code,commission_percent,status').eq('code', refCode).maybeSingle();
            if (aff && aff.status === 'active') {
              const commission = Math.round(pi.amount * aff.commission_percent / 100);
              await supabase.from('referral_sales').upsert([{
                affiliate_code: aff.code, license_key: licenseKey, payment_intent_id: pi.id,
                product, amount: pi.amount, commission_amount: commission
              }], { onConflict: 'payment_intent_id' });
              addLog(`Affiliate sale: ${aff.code} earned $${(commission / 100).toFixed(2)} on ${product}`, 'affiliate', 'success');
            }
          } catch (e) { addLog(`Affiliate attribution error: ${e.message}`, 'affiliate', 'error'); }
        }

        if (email) {
          const html = isForex
            ? _buildForexEmailHtml(_he(buyerName), _he(email), licenseKey)
            : _buildBotEmailHtml(_he(buyerName), _he(email), licenseKey, TG_BOT_USERNAME);
          const subject = isForex
            ? '🤖 Your Apex Forex Bot — License Key inside'
            : '🤖 Your Apex Trade Bot — License Key inside';
          const result = await _sendEmail({ to: email, subject, html, fromName: 'Apex.Bot' });
          if (!result.ok) addLog(`Bot email NOT sent for ${email} — ${result.error}`, 'email', 'error');
          else addLog(`${isForex ? 'Forex' : 'Crypto'} Bot email sent via ${result.method} to ${email}`, 'email', 'success');
        }
        const price = isForex ? '$497' : '$297';
        addLog(`${isForex ? 'Forex' : 'Crypto'} Bot sold: ${email} — ${price} — key: ${licenseKey}`, 'payment', 'success');
        return res.json({ received: true });
      }

      // ── COURSE DELIVERY (existing) ──
      const plan = pi.amount >= 9700 ? 'pro' : 'starter';
      const code = crypto.randomBytes(4).toString('hex').toUpperCase();

      if (email && supabase) {
        await supabase.from('purchases').insert([{ email, code, plan, amount: pi.amount, created_at: new Date().toISOString() }]);
      }

      // Send access email — use unified _sendEmail() (Resend → Brevo → SMTP)
      if (email) {
        const courseUrl = plan === 'pro' ? 'https://aicashsystem.space/course-pro.html' : 'https://aicashsystem.space/course-starter.html';
        const emailHtml = `<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:32px;background:#0a0a0a;color:#F5F0E8">
            <h2 style="color:#C8A96E;font-family:Georgia,serif">Welcome to AI Cash Systems!</h2>
            <p>Your ${_he(plan.toUpperCase())} course access is ready.</p>
            <p style="margin-top:20px">Click below to access your course anytime:</p>
            <a href="${_he(courseUrl)}" style="background:#C8A96E;color:#000;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block;font-weight:bold">Access My Course →</a>
            <p style="margin-top:24px">Need the access code to log in manually? Use: <strong style="letter-spacing:3px;color:#C8A96E">${_he(code)}</strong></p>
            <p style="color:#7A7060;font-size:12px;margin-top:12px">Enter the code at <a href="https://aicashsystem.space/access.html" style="color:#7A7060">aicashsystem.space/access.html</a> if prompted.</p>
          </div>`;
        const result = await _sendEmail({
          to: email,
          subject: '🎉 Your AI Cash Systems Course Access',
          html: emailHtml,
        });
        if (!result.ok) addLog(`Course email NOT sent for ${email} — ${result.error}`, 'email', 'error');
        else addLog(`Course email sent via ${result.method} to ${email}`, 'email', 'success');
      }

      addLog(`Payment succeeded: ${email} — ${plan} plan — Code: ${code}`, 'payment', 'success');
    }
    res.json({ received: true });
  } catch (e) {
    console.error('Webhook error:', e);
    res.status(400).json({ error: e.message });
  }
}
app.post('/stripe-webhook', express.raw({ type: 'application/json' }), handleStripeWebhook);
app.post('/webhook',        express.raw({ type: 'application/json' }), handleStripeWebhook);

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
const _OG_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630"><rect width="1200" height="630" fill="#060608"/><rect x="480" y="340" width="60" height="190" rx="12" fill="#ff2d4f" opacity=".45"/><rect x="570" y="220" width="60" height="310" rx="12" fill="#ff2d4f" opacity=".72"/><rect x="660" y="120" width="60" height="410" rx="12" fill="#ff2d4f"/><circle cx="690" cy="96" r="34" fill="#ff5c74"/><text x="600" y="520" font-family="system-ui,sans-serif" font-weight="700" font-size="38" fill="#f5f5f7" text-anchor="middle">Apex Trading Suite</text><text x="600" y="568" font-family="system-ui,sans-serif" font-size="22" fill="#9696a0" text-anchor="middle">AI Trading Bot Source Code · Crypto $297 · Forex $497</text></svg>';
app.get('/favicon.svg', (req, res) => { res.setHeader('Content-Type','image/svg+xml'); res.setHeader('Cache-Control','public,max-age=86400'); res.end(_LOGO_SVG); });
app.get('/favicon.ico', (req, res) => { res.setHeader('Content-Type','image/svg+xml'); res.setHeader('Cache-Control','public,max-age=86400'); res.end(_LOGO_SVG); });
app.get('/og.svg', (req, res) => { res.setHeader('Content-Type','image/svg+xml'); res.setHeader('Cache-Control','public,max-age=3600'); res.end(_OG_SVG); });
app.get('/apple-touch-icon.png', (req, res) => { res.setHeader('Content-Type','image/svg+xml'); res.setHeader('Cache-Control','public,max-age=86400'); res.end(_LOGO_SVG); });

// Root — serve AiCash System landing page
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'html', 'index.html'));
});

// /index and /index.html also serve the landing page (prevent publicPages override)
app.get('/index', (req, res) => {
  res.sendFile(path.join(__dirname, 'html', 'index.html'));
});
app.get('/index.html', (req, res) => {
  res.sendFile(path.join(__dirname, 'html', 'index.html'));
});

// Intro animation page
app.get('/intro', (req, res) => {
  res.sendFile(path.join(__dirname, 'html', 'intro.html'));
});
app.get('/intro.html', (req, res) => {
  res.sendFile(path.join(__dirname, 'html', 'intro.html'));
});

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
const publicPages = ['index','access','privacy','terms','intro-epic','app','demo','try','videos','screen','screens','tiktok-demo','video-maker','video-gen','apex-bot','bot-setup','setup-guide','configurator','configurator-forex','deploy','ad','results','profile','flex','flex2','flex3','heygen','mt5-sim','trading-journal'];
publicPages.forEach(p => {
  app.get(`/${p}.html`, (req, res) => res.sendFile(path.join(__dirname, 'public', `${p}.html`)));
  app.get(`/${p}`, (req, res) => res.sendFile(path.join(__dirname, 'public', `${p}.html`)));
});

// ── BOT EMAIL HTML — funcție separată reutilizabilă ──────────────────────────
function _buildBotEmailHtml(safeName, safeEmail, licenseKey = 'APEX-XXXX-XXXX-XXXX', botUsername = '') {
  const firstName = safeName.split(' ')[0];
  const envRow = (k, v) => `<tr>
    <td style="padding:9px 14px 9px 0;font-family:'Courier New',Courier,monospace;font-size:11px;font-weight:700;color:#f59e0b;white-space:nowrap;vertical-align:top;border-bottom:1px solid rgba(255,255,255,0.05)">${k}</td>
    <td style="padding:9px 0;font-size:12px;color:#94a3b8;font-family:Arial,sans-serif;line-height:1.7;vertical-align:top;border-bottom:1px solid rgba(255,255,255,0.05)">${v}</td>
  </tr>`;
  const code = (t) => `<span style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;color:#e2e8f0;font-family:'Courier New',monospace;font-size:11px;font-weight:700">${t}</span>`;
  const pill = (t, c='#f59e0b', bg='rgba(245,158,11,0.12)', br='rgba(245,158,11,0.3)') =>
    `<span style="background:${bg};border:1px solid ${br};border-radius:4px;padding:1px 7px;color:${c};font-family:'Courier New',monospace;font-size:11px;font-weight:700">${t}</span>`;

  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body,table,td,p,a,li,blockquote{-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}
table,td{mso-table-lspace:0;mso-table-rspace:0}
img{border:0;outline:none;text-decoration:none;display:block}
body{margin:0;padding:0;background:#060608}
a{text-decoration:none}
@media only screen and (max-width:600px){
  .key-mono{font-size:18px!important;letter-spacing:2px!important}
  .hero-h1{font-size:26px!important}
  .outer-pad{padding:24px 12px 0!important}
  .inner-pad{padding:28px 20px!important}
}
</style></head>
<body style="margin:0;padding:0;background:#060608">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#060608;min-height:100vh">
<tr><td class="outer-pad" align="center" style="padding:36px 16px 0">

<!-- ── OUTER WRAPPER ── -->
<table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%">

<!-- TOP LABEL -->
<tr><td align="center" style="padding:0 0 20px">
  <p style="margin:0;font-size:10px;font-weight:700;letter-spacing:3.5px;text-transform:uppercase;color:#374151;font-family:Arial,sans-serif">APEX TRADE BOT &nbsp;&bull;&nbsp; PURCHASE CONFIRMATION</p>
</td></tr>

<!-- ── HEADER CARD ── -->
<tr><td style="background:#0a0d18;border:1px solid rgba(255,255,255,0.07);border-bottom:none;border-radius:18px 18px 0 0">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">

    <!-- red top accent bar -->
    <tr><td style="background:linear-gradient(90deg,#ff2d4f,#c9193a);height:3px;border-radius:17px 17px 0 0;font-size:0;line-height:0">&nbsp;</td></tr>

    <!-- header content -->
    <tr><td class="inner-pad" align="center" style="padding:36px 40px 32px">
      <!-- ACCESS GRANTED chip -->
      <table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto 24px">
        <tr><td style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.25);border-radius:20px;padding:5px 16px">
          <p style="margin:0;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#22c55e;font-family:Arial,sans-serif">&#10003;&nbsp; ACCESS GRANTED</p>
        </td></tr>
      </table>
      <!-- headline -->
      <p class="hero-h1" style="margin:0 0 6px;font-size:32px;font-weight:900;color:#ffffff;font-family:Arial,sans-serif;letter-spacing:-0.5px;line-height:1.15">Your bot is ready,</p>
      <p class="hero-h1" style="margin:0 0 20px;font-size:32px;font-weight:900;color:#ff2d4f;font-family:Arial,sans-serif;letter-spacing:-0.5px;line-height:1.15">${firstName}.</p>
      <p style="margin:0;font-size:14px;color:#64748b;font-family:Arial,sans-serif;line-height:1.75;max-width:420px">Apex Trade Bot is fully set up and ready to deploy.<br>Follow the steps below — you can be live in under 10 minutes.</p>
    </td></tr>
  </table>
</td></tr>

<!-- ── LICENSE KEY CARD ── -->
<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:0 32px 28px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#060608;border:1px solid rgba(255,45,79,0.3);border-radius:12px">
    <tr>
      <!-- left red accent line -->
      <td style="background:#ff2d4f;width:4px;border-radius:12px 0 0 12px;font-size:0;line-height:0">&nbsp;</td>
      <td style="padding:22px 24px">
        <p style="margin:0 0 14px;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#ff2d4f;font-family:Arial,sans-serif">YOUR LICENSE KEY &mdash; KEEP THIS SAFE</p>
        <p class="key-mono" style="margin:0 0 14px;font-family:'Courier New',Courier,monospace;font-size:24px;font-weight:900;color:#ffffff;letter-spacing:4px;text-align:center;background:#000000;border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:16px 12px;word-break:break-all">${licenseKey}</p>
        <p style="margin:0;font-size:12px;color:#475569;font-family:Arial,sans-serif;text-align:center;line-height:1.6">Add this to Railway environment variables as ${code('LICENSE_KEY')}</p>
      </td>
    </tr>
  </table>
</td></tr>

<!-- ── PRIMARY CTA ── -->
<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:4px 32px 32px;text-align:center">
  ${botUsername
    ? `<a href="https://t.me/${botUsername}?start=${licenseKey}" style="display:inline-block;background:#ff2d4f;color:#ffffff;font-family:Arial,sans-serif;font-size:15px;font-weight:900;padding:16px 42px;border-radius:10px;text-decoration:none;letter-spacing:0.3px;mso-padding-alt:0">Activate on Telegram &rarr;</a>
       <p style="margin:14px 0 4px;font-size:12px;color:#374151;font-family:Arial,sans-serif">Tap above to link your license and start setup in Telegram</p>
       <a href="https://aicashsystem.space/configurator?key=${licenseKey}" style="font-size:12px;color:#475569;font-family:Arial,sans-serif;text-decoration:underline">or use the web configurator</a>`
    : `<a href="https://aicashsystem.space/configurator?key=${licenseKey}" style="display:inline-block;background:#ff2d4f;color:#ffffff;font-family:Arial,sans-serif;font-size:15px;font-weight:900;padding:16px 42px;border-radius:10px;text-decoration:none;letter-spacing:0.3px">Open Bot Configurator &rarr;</a>
       <p style="margin:14px 0 0;font-size:12px;color:#374151;font-family:Arial,sans-serif">Click above to configure and deploy your bot</p>`}
</td></tr>

<!-- ── SECTION DIVIDER: GETTING STARTED ── -->
<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:0 32px 24px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
    <td style="border-top:1px solid rgba(255,255,255,0.06)"></td>
    <td style="white-space:nowrap;padding:0 14px;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#1e293b;font-family:Arial,sans-serif">SETUP GUIDE</td>
    <td style="border-top:1px solid rgba(255,255,255,0.06)"></td>
  </tr></table>
</td></tr>

<!-- ── STEP 1: DEPLOY TO RAILWAY ── -->
<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:0 32px 16px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#060608;border:1px solid rgba(255,255,255,0.07);border-radius:12px">
    <tr><td style="padding:22px 24px">
      <table cellpadding="0" cellspacing="0" border="0" style="margin:0 0 18px">
        <tr>
          <td style="background:#ff2d4f;border-radius:6px;width:24px;height:24px;text-align:center;vertical-align:middle;font-size:11px;font-weight:900;color:#ffffff;font-family:Arial,sans-serif">1</td>
          <td style="padding:0 0 0 10px;font-size:13px;font-weight:700;color:#ffffff;font-family:Arial,sans-serif;letter-spacing:0.2px">Deploy bot to Railway (3 steps, under 2 min)</td>
        </tr>
      </table>
      <p style="margin:0 0 14px;font-size:12px;color:#64748b;font-family:Arial,sans-serif;line-height:1.8">Railway runs your bot 24/7 in the cloud — no server, no laptop needed. New accounts get $5 free credit. Follow the 3 steps below:</p>
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr><td style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:top">
          <p style="margin:0;font-size:12px;font-weight:700;color:#e2e8f0;font-family:Arial,sans-serif">&#10122; Create a free Railway account</p>
          <p style="margin:3px 0 0;font-size:12px;color:#64748b;font-family:Arial,sans-serif;line-height:1.7">Go to <a href="https://railway.app" style="color:#f59e0b;text-decoration:none;font-weight:700">railway.app</a> &rarr; Sign up with GitHub (free)</p>
        </td></tr>
        <tr><td style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:top">
          <p style="margin:0;font-size:12px;font-weight:700;color:#e2e8f0;font-family:Arial,sans-serif">&#10123; Create a new project from GitHub</p>
          <p style="margin:3px 0 0;font-size:12px;color:#64748b;font-family:Arial,sans-serif;line-height:1.7">Dashboard &rarr; <strong style="color:#e2e8f0">New Project</strong> &rarr; <strong style="color:#e2e8f0">Deploy from GitHub repo</strong> &rarr; search <strong style="color:#f59e0b">apex-trade-bot</strong> &rarr; Deploy Now</p>
        </td></tr>
        <tr><td style="padding:8px 0;vertical-align:top">
          <p style="margin:0;font-size:12px;font-weight:700;color:#e2e8f0;font-family:Arial,sans-serif">&#10124; Add your environment variables (Step 4 below)</p>
          <p style="margin:3px 0 0;font-size:12px;color:#64748b;font-family:Arial,sans-serif;line-height:1.7">In Railway: your project &rarr; <strong style="color:#e2e8f0">Variables</strong> tab &rarr; paste all keys from Step 4</p>
        </td></tr>
      </table>
      <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:16px">
        <tr><td style="text-align:center">
          <a href="https://railway.app/new" style="display:inline-block;background:#ff2d4f;color:#ffffff;font-family:Arial,sans-serif;font-size:14px;font-weight:900;padding:14px 36px;border-radius:10px;text-decoration:none;letter-spacing:0.3px">&#128640; Open Railway &rarr;</a>
        </td></tr>
      </table>
    </td></tr>
  </table>
</td></tr>

<!-- ── STEP 2: BINANCE API ── -->
<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:16px 32px 16px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#060608;border:1px solid rgba(255,255,255,0.07);border-radius:12px">
    <tr><td style="padding:22px 24px">
      <!-- step header -->
      <table cellpadding="0" cellspacing="0" border="0" style="margin:0 0 18px">
        <tr>
          <td style="background:#ff2d4f;border-radius:6px;width:24px;height:24px;text-align:center;vertical-align:middle;font-size:11px;font-weight:900;color:#ffffff;font-family:Arial,sans-serif">2</td>
          <td style="padding:0 0 0 10px;font-size:13px;font-weight:700;color:#ffffff;font-family:Arial,sans-serif;letter-spacing:0.2px">Get your Binance API keys</td>
        </tr>
      </table>
      <!-- sub-steps -->
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr><td style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:top">
          <p style="margin:0;font-size:13px;font-weight:700;color:#e2e8f0;font-family:Arial,sans-serif">Create a Binance account</p>
          <p style="margin:3px 0 0;font-size:12px;color:#64748b;font-family:Arial,sans-serif;line-height:1.7">binance.com &rarr; Sign up &rarr; Complete ID verification to unlock spot trading</p>
        </td></tr>
        <tr><td style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:top">
          <p style="margin:0;font-size:13px;font-weight:700;color:#e2e8f0;font-family:Arial,sans-serif">Open API Management</p>
          <p style="margin:3px 0 0;font-size:12px;color:#64748b;font-family:Arial,sans-serif;line-height:1.7">Profile icon &rarr; API Management &rarr; Create API &rarr; System generated</p>
        </td></tr>
        <tr><td style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:top">
          <p style="margin:0;font-size:13px;font-weight:700;color:#e2e8f0;font-family:Arial,sans-serif">Set permissions correctly</p>
          <p style="margin:3px 0 0;font-size:12px;color:#64748b;font-family:Arial,sans-serif;line-height:1.7">Enable: <strong style="color:#e2e8f0">Reading</strong> + <strong style="color:#e2e8f0">Spot &amp; Margin Trading</strong> &mdash; leave Withdrawals <strong style="color:#f87171">OFF</strong>. IP restriction: unrestricted.</p>
        </td></tr>
        <tr><td style="padding:8px 0;vertical-align:top">
          <p style="margin:0;font-size:13px;font-weight:700;color:#e2e8f0;font-family:Arial,sans-serif">Save both keys immediately</p>
          <p style="margin:3px 0 0;font-size:12px;color:#64748b;font-family:Arial,sans-serif;line-height:1.7">Copy API Key + Secret Key now. <span style="color:#f87171;font-weight:700">The Secret is shown only once.</span></p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</td></tr>

<!-- ── STEP 3: FREE GROQ KEY ── -->
<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:16px 32px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#060608;border:1px solid rgba(255,255,255,0.07);border-radius:12px">
    <tr><td style="padding:22px 24px">
      <table cellpadding="0" cellspacing="0" border="0" style="margin:0 0 16px">
        <tr>
          <td style="background:#ff2d4f;border-radius:6px;width:24px;height:24px;text-align:center;vertical-align:middle;font-size:11px;font-weight:900;color:#ffffff;font-family:Arial,sans-serif">3</td>
          <td style="padding:0 0 0 10px;font-size:13px;font-weight:700;color:#ffffff;font-family:Arial,sans-serif">Get your free Groq AI key</td>
        </tr>
      </table>
      <p style="margin:0;font-size:12px;color:#64748b;font-family:Arial,sans-serif;line-height:1.8">Go to <a href="https://console.groq.com" style="color:#f59e0b;font-weight:700">console.groq.com</a> &rarr; Sign up (free) &rarr; API Keys &rarr; Create Key. <strong style="color:#e2e8f0">No credit card required.</strong> This powers the AI signal engine.</p>
    </td></tr>
  </table>
</td></tr>

<!-- ── STEP 4: RAILWAY ENV VARS ── -->
<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:16px 32px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#060608;border:1px solid rgba(255,255,255,0.07);border-radius:12px">
    <tr><td style="padding:22px 24px">
      <table cellpadding="0" cellspacing="0" border="0" style="margin:0 0 18px">
        <tr>
          <td style="background:#ff2d4f;border-radius:6px;width:24px;height:24px;text-align:center;vertical-align:middle;font-size:11px;font-weight:900;color:#ffffff;font-family:Arial,sans-serif">4</td>
          <td style="padding:0 0 0 10px;font-size:13px;font-weight:700;color:#ffffff;font-family:Arial,sans-serif">Set environment variables in Railway</td>
        </tr>
      </table>
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        ${envRow('LICENSE_KEY', `Your key &mdash; ${pill(licenseKey)}`)}
        ${envRow('EXCHANGE', `Set to ${pill('binance')}`)}
        ${envRow('BINANCE_API_KEY', 'API Key from Step 1')}
        ${envRow('BINANCE_API_SECRET', 'Secret Key from Step 1 &mdash; <strong style="color:#e2e8f0">shown only once</strong>')}
        ${envRow('GROQ_API_KEY', 'Free AI key from Step 2')}
        ${envRow('PAPER_TRADING', `Start with ${pill('true','#22c55e','rgba(34,197,94,0.1)','rgba(34,197,94,0.25)')} (sim money). Change to ${pill('false')} when ready to go live.`)}
        ${envRow('PAPER_BALANCE', `Simulated balance. Default: ${pill('10')} (= $10 USDT)`)}
        ${envRow('TRADE_SYMBOL', `Optional. E.g. ${pill('DOGEUSDT')}. Leave empty &mdash; AI picks best coin.`)}
        <tr>
          <td style="padding:9px 14px 0 0;font-family:'Courier New',Courier,monospace;font-size:11px;font-weight:700;color:#f59e0b;white-space:nowrap;vertical-align:top">TELEGRAM_BOT_TOKEN</td>
          <td style="padding:9px 0 0;font-size:12px;color:#94a3b8;font-family:Arial,sans-serif;vertical-align:top">Optional &mdash; token from @BotFather &rarr; <code style="font-size:11px">/newbot</code></td>
        </tr>
        <tr>
          <td style="padding:6px 14px 0 0;font-family:'Courier New',Courier,monospace;font-size:11px;font-weight:700;color:#f59e0b;white-space:nowrap;vertical-align:top">TELEGRAM_CHAT_ID</td>
          <td style="padding:6px 0 0;font-size:12px;color:#94a3b8;font-family:Arial,sans-serif;vertical-align:top">Optional &mdash; your ID from @userinfobot &rarr; send it <code style="font-size:11px">/start</code></td>
        </tr>
      </table>
    </td></tr>
  </table>
</td></tr>

<!-- ── START WITH PAPER TRADING REMINDER ── -->
<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:16px 32px 28px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:rgba(34,197,94,0.04);border:1px solid rgba(34,197,94,0.18);border-radius:10px">
    <tr><td style="padding:16px 20px">
      <p style="margin:0;font-size:12px;color:#94a3b8;font-family:Arial,sans-serif;line-height:1.8"><strong style="color:#22c55e">&#10003; Start with Paper Trading.</strong> Keep ${code('PAPER_TRADING=true')} for at least 14 days. Watch the signals, verify performance, then switch to live funds only when you're confident.</p>
    </td></tr>
  </table>
</td></tr>

<!-- ── RISK DISCLOSURE ── -->
<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:0 32px 28px">
  <p style="margin:0;font-size:11px;color:#1e293b;font-family:Arial,sans-serif;line-height:1.8;text-align:center"><strong style="color:#374151">Risk Disclosure</strong> &mdash; Crypto trading involves substantial risk of loss. Only invest what you can afford to lose. Apex Trade Bot is an automation tool, not financial advice. You are solely responsible for all trading decisions.</p>
</td></tr>

<!-- ── FOOTER ── -->
<tr><td align="center" style="background:#0a0d18;border:1px solid rgba(255,255,255,0.07);border-top:1px solid rgba(255,255,255,0.05);border-radius:0 0 18px 18px;padding:24px 40px 28px">
  <p style="margin:0 0 6px;font-size:12px;color:#334155;font-family:Arial,sans-serif">Questions? Reply to this email or reach us at:</p>
  <a href="mailto:supportaicashsystem@gmail.com" style="color:#ff2d4f;font-size:13px;font-weight:700;font-family:Arial,sans-serif;text-decoration:none">supportaicashsystem@gmail.com</a>
  <p style="margin:16px 0 0;font-size:10px;color:#0f172a;font-family:Arial,sans-serif">&copy; 2025 AI Cash Systems &nbsp;&middot;&nbsp; <a href="https://aicashsystem.space" style="color:#0f172a;text-decoration:none">aicashsystem.space</a></p>
</td></tr>

<!-- bottom spacing -->
<tr><td style="height:36px;font-size:0;line-height:0">&nbsp;</td></tr>

</table><!-- /wrapper -->
</td></tr>
</table><!-- /outer -->
</body></html>`;}

// ── FOREX BOT EMAIL ─────────────────────────────────────────────────────────
function _buildForexEmailHtml(safeName, safeEmail, licenseKey = 'FORX-XXXX-XXXX-XXXX') {
  const firstName = safeName.split(' ')[0];
  const code = (t) => `<span style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;color:#e2e8f0;font-family:'Courier New',monospace;font-size:11px;font-weight:700">${t}</span>`;
  const pill = (t, c='#f59e0b', bg='rgba(245,158,11,0.12)', br='rgba(245,158,11,0.3)') =>
    `<span style="background:${bg};border:1px solid ${br};border-radius:4px;padding:1px 7px;color:${c};font-family:'Courier New',monospace;font-size:11px;font-weight:700">${t}</span>`;
  const step = (n, title, body) => `<tr><td style="background:#060608;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:22px 24px;margin-bottom:12px"><table width="100%" cellpadding="0" cellspacing="0"><tr><td style="background:#2aabee;border-radius:6px;width:24px;height:24px;text-align:center;vertical-align:middle;font-size:11px;font-weight:900;color:#fff;font-family:Arial,sans-serif">${n}</td><td style="padding:0 0 0 10px;font-size:13px;font-weight:700;color:#fff;font-family:Arial,sans-serif">${title}</td></tr><tr><td colspan="2" style="padding:12px 0 0;font-size:12px;color:#64748b;font-family:Arial,sans-serif;line-height:1.8">${body}</td></tr></table></td></tr><tr><td style="height:12px"></td></tr>`;
  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#060608">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#060608;min-height:100vh">
<tr><td align="center" style="padding:36px 16px 0">
<table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%">

<tr><td align="center" style="padding:0 0 20px">
  <p style="margin:0;font-size:10px;font-weight:700;letter-spacing:3.5px;text-transform:uppercase;color:#374151;font-family:Arial,sans-serif">APEX FOREX BOT &nbsp;&bull;&nbsp; PURCHASE CONFIRMATION</p>
</td></tr>

<tr><td style="background:#0a0d18;border:1px solid rgba(255,255,255,0.07);border-bottom:none;border-radius:18px 18px 0 0">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td style="background:linear-gradient(90deg,#2aabee,#1a8fc9);height:3px;border-radius:17px 17px 0 0;font-size:0;line-height:0">&nbsp;</td></tr>
    <tr><td align="center" style="padding:36px 40px 32px">
      <table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto 24px"><tr><td style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.25);border-radius:20px;padding:5px 16px"><p style="margin:0;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#22c55e;font-family:Arial,sans-serif">&#10003;&nbsp; ACCESS GRANTED</p></td></tr></table>
      <p style="margin:0 0 6px;font-size:32px;font-weight:900;color:#ffffff;font-family:Arial,sans-serif;letter-spacing:-0.5px;line-height:1.15">Your Forex bot is ready,</p>
      <p style="margin:0 0 20px;font-size:32px;font-weight:900;color:#2aabee;font-family:Arial,sans-serif;letter-spacing:-0.5px;line-height:1.15">${firstName}.</p>
      <p style="margin:0;font-size:14px;color:#64748b;font-family:Arial,sans-serif;line-height:1.75;max-width:420px">Apex Forex Bot is ready to deploy. Follow the steps below — you can be trading in under 10 minutes.</p>
    </td></tr>
  </table>
</td></tr>

<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:0 32px 28px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#060608;border:1px solid rgba(42,171,238,0.3);border-radius:12px"><tr>
    <td style="background:#2aabee;width:4px;border-radius:12px 0 0 12px;font-size:0;line-height:0">&nbsp;</td>
    <td style="padding:22px 24px">
      <p style="margin:0 0 14px;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#2aabee;font-family:Arial,sans-serif">YOUR FOREX LICENSE KEY &mdash; KEEP THIS SAFE</p>
      <p style="margin:0 0 14px;font-family:'Courier New',Courier,monospace;font-size:22px;font-weight:900;color:#ffffff;letter-spacing:4px;text-align:center;background:#000000;border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:16px 12px;word-break:break-all">${licenseKey}</p>
      <p style="margin:0;font-size:12px;color:#475569;font-family:Arial,sans-serif;text-align:center;line-height:1.6">Add this to Railway environment variables as ${code('LICENSE_KEY')}</p>
    </td>
  </tr></table>
</td></tr>

<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:4px 32px 32px;text-align:center">
  <a href="https://aicashsystem.space/configurator-forex?key=${licenseKey}" style="display:inline-block;background:#2aabee;color:#ffffff;font-family:Arial,sans-serif;font-size:15px;font-weight:900;padding:16px 42px;border-radius:10px;text-decoration:none;letter-spacing:0.3px">Open Forex Configurator &rarr;</a>
  <p style="margin:14px 0 0;font-size:12px;color:#374151;font-family:Arial,sans-serif">Click above to configure your broker and deploy</p>
</td></tr>

<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:0 32px 24px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
    <td style="border-top:1px solid rgba(255,255,255,0.06)"></td>
    <td style="white-space:nowrap;padding:0 14px;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#1e293b;font-family:Arial,sans-serif">SETUP GUIDE</td>
    <td style="border-top:1px solid rgba(255,255,255,0.06)"></td>
  </tr></table>
</td></tr>

<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:0 32px 16px">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
    ${step(1, 'Open OANDA and create an API key', 'Login to OANDA → Manage Funds → API Access → Generate Token. Keep the token and your Account ID ready.')}
    ${step(2, 'Configure your bot', 'Click the "Open Forex Configurator" button above. Paste your OANDA credentials, choose PAPER mode to start, set your risk (1-2% recommended).')}
    ${step(3, 'Deploy to Railway', 'Click "Save Config &amp; Deploy" in the configurator. The bot starts automatically with just your LICENSE_KEY — all settings are stored securely.')}
    ${step(4, 'Start with Paper Trading', `Keep ${code('PAPER_TRADING=true')} for at least 7 days. Verify signals match your strategy before going live.`)}
  </table>
</td></tr>

<tr><td style="background:#0a0d18;border-left:1px solid rgba(255,255,255,0.07);border-right:1px solid rgba(255,255,255,0.07);padding:0 32px 28px">
  <p style="margin:0;font-size:11px;color:#1e293b;font-family:Arial,sans-serif;line-height:1.8;text-align:center"><strong style="color:#374151">Risk Disclosure</strong> &mdash; Forex trading involves substantial risk of loss. Only trade capital you can afford to lose. Apex Forex Bot is an automation tool, not financial advice.</p>
</td></tr>

<tr><td align="center" style="background:#0a0d18;border:1px solid rgba(255,255,255,0.07);border-top:1px solid rgba(255,255,255,0.05);border-radius:0 0 18px 18px;padding:24px 40px 28px">
  <p style="margin:0 0 6px;font-size:12px;color:#334155;font-family:Arial,sans-serif">Questions? Reply to this email:</p>
  <a href="mailto:supportaicashsystem@gmail.com" style="color:#2aabee;font-size:13px;font-weight:700;font-family:Arial,sans-serif;text-decoration:none">supportaicashsystem@gmail.com</a>
  <p style="margin:16px 0 0;font-size:10px;color:#0f172a;font-family:Arial,sans-serif">&copy; 2025 AI Cash Systems &nbsp;&middot;&nbsp; <a href="https://aicashsystem.space" style="color:#0f172a;text-decoration:none">aicashsystem.space</a></p>
</td></tr>
<tr><td style="height:36px;font-size:0;line-height:0">&nbsp;</td></tr>
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
    const previewHtml = _buildBotEmailHtml(_he(name), _he(email), 'APEX-DEMO-PREW-2025', TG_BOT_USERNAME);
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
  const botEmailHtml = _buildBotEmailHtml(_he(name), _he(email), testKey, TG_BOT_USERNAME);

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
