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

// Health check — first route, no deps, always responds
app.get('/health', (req, res) => res.json({ ok: true, node: process.version, time: new Date().toISOString() }));
app.get('/ping', (req, res) => res.json({ ok: true, version: 'v6-email-fix', time: new Date().toISOString() }));
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

// ── ENV VARIABLES ──
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_KEY;
const ANTHROPIC_KEY = process.env.ANTHROPIC_API_KEY;
const OPENAI_KEY = process.env.OPENAI_API_KEY;
const HEYGEN_KEY = process.env.HEYGEN_API_KEY;
const CREATIFY_API_ID  = process.env.CREATIFY_API_ID  || '';
const CREATIFY_API_KEY = process.env.CREATIFY_API_KEY || '';
const JWT_SECRET = process.env.JWT_SECRET || (() => { console.warn('[WARN] JWT_SECRET not set — using insecure default. Set this env var in Render.'); return 'autoflow-secret-2024-change-me'; })();
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
    // Use verified Resend domain if custom domain not verified yet
    const resendFrom = process.env.RESEND_FROM || `${from} <onboarding@resend.dev>`;
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

  // 3. SMTP fallback
  if (transporter) {
    try {
      await Promise.race([
        transporter.sendMail({ from: `"${from}" <${sender}>`, to, subject, html }),
        new Promise((_, rej) => setTimeout(() => rej(new Error('SMTP timeout')), 12000)),
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

// ── BREVO SMTP TRANSPORTER ──
const BREVO_USER = process.env.BREVO_SMTP_USER;
const BREVO_PASS = process.env.BREVO_SMTP_PASS;
let transporter = null;
try {
  if (BREVO_USER && BREVO_PASS) transporter = nodemailer.createTransport({ host: 'smtp-relay.brevo.com', port: 587, secure: false, auth: { user: BREVO_USER, pass: BREVO_PASS } });
} catch(e) { console.error('Nodemailer init error:', e.message); }

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
const VALID_AMOUNTS = [3700, 9700, 19700]; // $37 starter, $97 pro, $197 apex-bot (in cents)
app.post('/create-payment-intent', async (req, res) => {
  const { amount, currency, email, name, product } = req.body;
  const safeAmount = VALID_AMOUNTS.includes(Number(amount)) ? Number(amount) : 3700;
  try {
    if (!process.env.STRIPE_SECRET_KEY) return res.status(500).json({ error: 'Stripe not configured' });
    const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
    const paymentIntent = await stripe.paymentIntents.create({
      amount: safeAmount,
      currency: currency || 'usd',
      automatic_payment_methods: { enabled: true },
      receipt_email: email || undefined,
      metadata: {
        product: product || (safeAmount === 19700 ? 'apex-bot' : 'course'),
        email: email || '',
        name: name || ''
      }
    });
    res.json({ clientSecret: paymentIntent.client_secret });
  } catch (e) {
    res.status(500).json({ error: 'Payment processing failed' });
  }
});

// ── LICENSE KEY HELPERS ──────────────────────────────────────────────────────
function generateLicenseKey() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // no 0/O/1/I confusion
  const seg = () => Array.from({ length: 4 }, () => chars[Math.floor(Math.random() * chars.length)]).join('');
  return `APEX-${seg()}-${seg()}-${seg()}`;
}

// POST /api/verify-license — called by the bot on every startup
app.post('/api/verify-license', async (req, res) => {
  const { key } = req.body || {};
  if (!key) return res.json({ valid: false, message: 'No license key provided' });
  if (!supabase) return res.json({ valid: false, message: 'License server not configured — contact support' });
  try {
    const { data, error } = await supabase
      .from('licenses')
      .select('id, email, active, activated_at')
      .eq('key', key)
      .eq('active', true)
      .single();
    if (error || !data) return res.json({ valid: false, message: 'Invalid license key. Purchase at aicashsystem.space' });
    if (!data.activated_at) {
      await supabase.from('licenses').update({ activated_at: new Date().toISOString() }).eq('key', key);
    }
    return res.json({ valid: true, email: data.email });
  } catch (e) {
    return res.json({ valid: false, message: 'Verification error — try again or contact support' });
  }
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
      const email = pi.metadata?.email || pi.receipt_email;
      const product = pi.metadata?.product || 'course';
      const buyerName = pi.metadata?.name || 'there';

      // ── APEX BOT DELIVERY ──
      if (product === 'apex-bot') {
        // Generate unique license key
        const licenseKey = generateLicenseKey();
        if (supabase) {
          try {
            await supabase.from('licenses').insert([{ key: licenseKey, email: email || '', name: buyerName }]);
          } catch(e) { addLog(`License store failed: ${e.message}`, 'license', 'error'); }
        }
        if (email) {
          const botEmailHtml = _buildBotEmailHtml(_he(buyerName), _he(email), licenseKey);
          const result = await _sendEmail({
            to: email,
            subject: '🤖 Your Apex Trade Bot is ready — access inside',
            html: botEmailHtml,
            fromName: 'Apex.Bot',
          });
          if (!result.ok) addLog(`Apex Bot email NOT sent for ${email} — ${result.error}`, 'email', 'error');
          else addLog(`Apex Bot email sent via ${result.method} to ${email}`, 'email', 'success');
        }
        addLog(`Apex Bot sold: ${email} — $197`, 'payment', 'success');
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

// Root redirect — cinematic intro first
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'intro-epic.html'));
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
  if (!HEYGEN_KEY) return res.status(503).json({ error: 'HeyGen key not configured' });
  try {
    const r = await fetch(`https://api.heygen.com/v1/video_status.get?video_id=${req.params.id}`, { headers: _heyHeaders() });
    const d = await r.json();
    res.json(d.data || d);
  } catch(e) { res.status(500).json({ error: e.message }); }
});

// Explicit HTML page routes
// Public pages — no auth required
const publicPages = ['index','access','privacy','terms','intro-epic','app','demo','try','videos','screen','screens','tiktok-demo','video-maker','video-gen','apex-bot','bot-setup'];
publicPages.forEach(p => {
  app.get(`/${p}.html`, (req, res) => res.sendFile(path.join(__dirname, 'public', `${p}.html`)));
  app.get(`/${p}`, (req, res) => res.sendFile(path.join(__dirname, 'public', `${p}.html`)));
});

// ── BOT EMAIL HTML — funcție separată reutilizabilă ──────────────────────────
function _buildBotEmailHtml(safeName, safeEmail, licenseKey = 'APEX-XXXX-XXXX-XXXX') {
  const firstName = safeName.split(' ')[0];
  const chip = (t,c='#00ff88') => `<span style="display:inline-block;background:${c}18;border:1px solid ${c}44;border-radius:5px;padding:2px 8px;color:${c};font-family:'Courier New',monospace;font-size:11px;font-weight:700;letter-spacing:.3px">${t}</span>`;

  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
@keyframes glow-pulse{0%,100%{opacity:.5;transform:scale(1)}50%{opacity:1;transform:scale(1.08)}}
@keyframes shimmer{0%{background-position:-400% center}100%{background-position:400% center}}
@keyframes dot-pulse{0%,100%{box-shadow:0 0 0 0 rgba(0,255,136,.6)}70%{box-shadow:0 0 0 12px rgba(0,255,136,0)}}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
@keyframes fade-up{from{opacity:0;transform:translateY(24px)}to{opacity:1;transform:translateY(0)}}
@keyframes border-shine{0%,100%{border-color:rgba(0,255,136,.15)}50%{border-color:rgba(0,255,136,.5)}}
@keyframes scan{0%{top:-10%}100%{top:110%}}
body{background:#08080f;font-family:'Inter',sans-serif;padding:0;margin:0;color:#e2e8f0;-webkit-font-smoothing:antialiased}
.wrap{max-width:620px;margin:0 auto;background:#08080f}

/* ─ HERO ─ */
.hero{position:relative;overflow:hidden;padding:0;background:radial-gradient(ellipse 80% 60% at 50% 0%,rgba(0,255,136,.07) 0%,transparent 70%),linear-gradient(180deg,#080f0b 0%,#08080f 100%);border-bottom:1px solid rgba(0,255,136,.1)}
.hero-scan{position:absolute;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,rgba(0,255,136,.4),transparent);animation:scan 4s linear infinite;pointer-events:none}
.hero-grid{position:absolute;inset:0;background-image:linear-gradient(rgba(0,255,136,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,136,.03) 1px,transparent 1px);background-size:40px 40px;pointer-events:none}
.hero-inner{position:relative;z-index:2;padding:52px 44px 48px;text-align:center}
.status-badge{display:inline-flex;align-items:center;gap:10px;background:rgba(0,255,136,.06);border:1px solid rgba(0,255,136,.2);border-radius:100px;padding:8px 20px;margin-bottom:32px;animation:border-shine 3s ease infinite}
.status-dot{width:8px;height:8px;border-radius:50%;background:#00ff88;flex-shrink:0;animation:dot-pulse 2s infinite}
.status-text{font-size:11px;font-weight:800;color:#00ff88;letter-spacing:3px;text-transform:uppercase}
.hero-icon{font-size:56px;margin-bottom:24px;display:block;animation:float 4s ease-in-out infinite}
.hero-title{font-size:13px;font-weight:700;color:rgba(255,255,255,.3);letter-spacing:4px;text-transform:uppercase;margin-bottom:12px}
.hero-name{font-size:42px;font-weight:900;line-height:1.05;letter-spacing:-2px;margin-bottom:18px;background:linear-gradient(135deg,#fff 30%,rgba(255,255,255,.55) 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hero-sub{font-size:38px;font-weight:900;line-height:1.05;letter-spacing:-1.5px;margin-bottom:24px;background:linear-gradient(90deg,#00ff88,#00d4aa,#00ff88);background-size:200% auto;-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;animation:shimmer 4s linear infinite}
.hero-desc{font-size:15px;color:rgba(255,255,255,.4);line-height:1.7;max-width:420px;margin:0 auto}

/* ─ CTA ─ */
.cta-wrap{padding:0 44px;margin-top:-1px;background:linear-gradient(180deg,rgba(0,255,136,.03) 0%,transparent 100%);border-bottom:1px solid rgba(255,255,255,.05)}
.cta-inner{padding:36px 0;text-align:center}
.cta-label{font-size:10px;font-weight:800;color:rgba(255,255,255,.3);letter-spacing:3px;text-transform:uppercase;margin-bottom:20px}
.cta-btn{display:inline-block;position:relative;overflow:hidden;background:#00ff88;color:#000;font-size:16px;font-weight:900;padding:18px 48px;border-radius:12px;text-decoration:none;letter-spacing:-.3px;box-shadow:0 0 40px rgba(0,255,136,.3),0 8px 32px rgba(0,0,0,.5);transition:all .3s}
.cta-btn-shine{position:absolute;top:-50%;left:-70%;width:50%;height:200%;background:linear-gradient(105deg,transparent,rgba(255,255,255,.28),transparent);transform:skewX(-20deg);animation:shimmer 2.5s ease-in-out infinite}
.cta-hint{margin-top:16px;font-size:12px;color:rgba(255,255,255,.22);line-height:1.7}
.cta-hint b{color:rgba(255,255,255,.4)}

/* ─ BODY ─ */
.body{padding:12px 44px 44px}

/* ─ SECTION CARD ─ */
.card{border-radius:16px;padding:28px;margin-bottom:14px;position:relative;overflow:hidden}
.card-green{background:linear-gradient(135deg,rgba(0,255,136,.05) 0%,rgba(0,255,136,.02) 100%);border:1px solid rgba(0,255,136,.12)}
.card-dark{background:linear-gradient(135deg,rgba(255,255,255,.03) 0%,rgba(255,255,255,.01) 100%);border:1px solid rgba(255,255,255,.07)}
.card-blue{background:linear-gradient(135deg,rgba(129,140,248,.05) 0%,rgba(99,102,241,.02) 100%);border:1px solid rgba(129,140,248,.15)}
.card-yellow{background:linear-gradient(135deg,rgba(245,158,11,.05) 0%,rgba(245,158,11,.02) 100%);border:1px solid rgba(245,158,11,.15)}
.card-red{background:rgba(239,68,68,.03);border:1px solid rgba(239,68,68,.1)}
.card-corner{position:absolute;top:0;right:0;width:80px;height:80px;border-radius:0 16px 0 100%;opacity:.06}
.card-corner-green{background:#00ff88}.card-corner-blue{background:#818cf8}.card-corner-yellow{background:#f59e0b}
.card-tag{font-size:10px;font-weight:800;letter-spacing:3px;text-transform:uppercase;margin-bottom:22px;display:flex;align-items:center;gap:10px}
.card-tag-green{color:#00ff88}.card-tag-blue{color:#818cf8}.card-tag-yellow{color:#f59e0b}.card-tag-dim{color:rgba(255,255,255,.3)}
.card-tag-line{flex:1;height:1px;background:currentColor;opacity:.15}

/* ─ STEPS ─ */
.step{display:flex;gap:16px;padding:16px 0;border-bottom:1px solid rgba(255,255,255,.04);align-items:flex-start}
.step:last-child{border:none;padding-bottom:0}
.step-n{min-width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:900;flex-shrink:0}
.step-n-g{background:rgba(0,255,136,.12);border:1px solid rgba(0,255,136,.3);color:#00ff88}
.step-n-b{background:rgba(129,140,248,.12);border:1px solid rgba(129,140,248,.3);color:#818cf8}
.step-n-y{background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.3);color:#f59e0b}
.step-title{font-size:13px;font-weight:700;color:#fff;margin-bottom:6px;line-height:1.3}
.step-body{font-size:12px;color:rgba(255,255,255,.4);line-height:1.9}
.step-body a{color:#00ff88;text-decoration:none}
.step-body b,.step-body strong{color:rgba(255,255,255,.65);font-weight:600}

/* ─ VAR TABLE ─ */
.vt{width:100%;border-collapse:collapse}
.vt tr{border-bottom:1px solid rgba(255,255,255,.04)}
.vt tr:last-child{border:none}
.vt td{padding:11px 0;vertical-align:top}
.vt-k{color:#00ff88;font-family:'Courier New',monospace;font-size:11px;font-weight:700;white-space:nowrap;padding-right:18px;padding-top:14px;min-width:160px}
.vt-v{font-size:12px;color:rgba(255,255,255,.38);line-height:1.75}
.vt-v b,.vt-v strong{color:rgba(255,255,255,.6)}
.vt-v a{color:#00ff88;text-decoration:none}

/* ─ FOOTER ─ */
.footer{border-top:1px solid rgba(255,255,255,.05);padding:28px 44px;text-align:center;background:rgba(0,0,0,.3)}
.footer-q{font-size:12px;color:rgba(255,255,255,.2);margin-bottom:8px}
.footer-email{color:#00ff88;font-size:14px;font-weight:700;text-decoration:none}
.footer-copy{font-size:10px;color:rgba(255,255,255,.1);margin-top:16px}
</style></head>
<body>
<div class="wrap">

<!-- ══════ HERO ══════ -->
<div class="hero">
  <div class="hero-scan"></div>
  <div class="hero-grid"></div>
  <div class="hero-inner">
    <div class="status-badge">
      <span class="status-dot"></span>
      <span class="status-text">Access Granted</span>
    </div>
    <span class="hero-icon">🤖</span>
    <div class="hero-title">Welcome,&nbsp; ${firstName}</div>
    <div class="hero-name">Apex Trade Bot</div>
    <div class="hero-sub">is yours.</div>
    <p class="hero-desc">Your AI-powered crypto trading bot is ready to deploy. Follow the steps below and you'll be live in under 10 minutes.</p>
  </div>
</div>

<!-- ══════ LICENSE KEY ══════ -->
<div style="max-width:580px;margin:0 auto;padding:0 20px">
  <div style="background:rgba(0,255,136,.06);border:2px solid rgba(0,255,136,.35);border-radius:16px;padding:24px 28px;margin-bottom:0">
    <div style="font-size:11px;font-weight:800;color:#00ff88;letter-spacing:2.5px;text-transform:uppercase;margin-bottom:10px">🔐 Your License Key</div>
    <div style="font-family:'Courier New',monospace;font-size:22px;font-weight:900;color:#fff;letter-spacing:3px;background:#000;border:1px solid rgba(0,255,136,.25);border-radius:10px;padding:14px 20px;text-align:center;margin-bottom:10px">${licenseKey}</div>
    <p style="font-size:12px;color:rgba(255,255,255,.45);margin:0;text-align:center">Copy this key — you'll add it to Railway Variables as <span style="color:#00ff88;font-family:'Courier New',monospace">LICENSE_KEY</span></p>
  </div>
</div>

<!-- ══════ CTA ══════ -->
<div class="cta-wrap">
  <div class="cta-inner">
    <div class="cta-label">One-click deploy — bot live in 2 minutes</div>
    <a href="https://aicashsystem.space/bot-setup" class="cta-btn">
      <span class="cta-btn-shine"></span>
      Open Setup Guide →
    </a>
    <p class="cta-hint">Click above → Railway deploy button → add your License Key + API keys → done</p>
  </div>
</div>

<!-- ══════ BODY ══════ -->
<div class="body">

<!-- ─ BINANCE API ─ -->
<div class="card card-green">
  <div class="card-corner card-corner-green"></div>
  <div class="card-tag card-tag-green">🔑 Step 2 — Binance API Key <span class="card-tag-line"></span></div>
  <div class="step">
    <div class="step-n step-n-g">1</div>
    <div><div class="step-title">Create a Binance account</div>
    <div class="step-body">Go to <a href="https://binance.com">binance.com</a> → Sign up. Complete identity verification (ID required) to unlock spot trading. Binance works globally including EU.</div></div>
  </div>
  <div class="step">
    <div class="step-n step-n-g">2</div>
    <div><div class="step-title">Open API Management</div>
    <div class="step-body">Click your profile icon (top right) → <b>API Management</b> → <b>Create API</b> → choose <b>System-generated</b></div></div>
  </div>
  <div class="step">
    <div class="step-n step-n-g">3</div>
    <div><div class="step-title">Set the correct permissions</div>
    <div class="step-body">
      ✅ <b>Enable Reading</b><br>
      ✅ <b>Enable Spot &amp; Margin Trading</b><br>
      ❌ Leave <b>Withdrawals</b> unchecked — never needed<br>
      IP restriction: leave <b>unrestricted</b> (Railway uses dynamic IPs)
    </div></div>
  </div>
  <div class="step">
    <div class="step-n step-n-g">4</div>
    <div><div class="step-title">Save your keys — Secret shown only once!</div>
    <div class="step-body">Complete 2FA. Copy both your <b>API Key</b> and <b>Secret Key</b> immediately and store them safely. <span style="color:#f87171;font-weight:600">The Secret disappears after you close the page.</span></div></div>
  </div>
</div>

<!-- ─ RAILWAY DEPLOY ─ -->
<div class="card card-dark">
  <div class="card-tag card-tag-dim">🚀 Step 3 — Deploy on Railway (Free) <span class="card-tag-line"></span></div>
  <div class="step">
    <div class="step-n step-n-g">1</div>
    <div><div class="step-title">Create a Railway account</div>
    <div class="step-body">Go to <a href="https://railway.app">railway.app</a> → <b>Login with GitHub</b></div></div>
  </div>
  <div class="step">
    <div class="step-n step-n-g">2</div>
    <div><div class="step-title">Create a new project</div>
    <div class="step-body">Click <b>New Project → Deploy from GitHub repo</b> → select the repository you downloaded</div></div>
  </div>
  <div class="step">
    <div class="step-n step-n-g">3</div>
    <div><div class="step-title">Set Root Directory</div>
    <div class="step-body">Go to project <b>Settings</b> → <b>Root Directory</b> → type exactly: ${chip('apex-trade-bot')}<br>This tells Railway to run only the bot, not the whole repo.</div></div>
  </div>
  <div class="step">
    <div class="step-n step-n-g">4</div>
    <div><div class="step-title">Add environment variables</div>
    <div class="step-body">Go to the <b>Variables</b> tab → add all keys from the table below → Railway redeploys automatically.</div></div>
  </div>
</div>

<!-- ─ ENV VARS ─ -->
<div class="card card-dark">
  <div class="card-tag card-tag-dim">📋 Railway Variables — Add These <span class="card-tag-line"></span></div>
  <table class="vt">
    <tr><td class="vt-k">LICENSE_KEY</td><td class="vt-v">Your key from above — ${chip(licenseKey,'#a78bfa')}</td></tr>
    <tr><td class="vt-k">EXCHANGE</td><td class="vt-v">Set to ${chip('binance')} — works globally including EU</td></tr>
    <tr><td class="vt-k">BINANCE_API_KEY</td><td class="vt-v">The API Key from Step 2 above</td></tr>
    <tr><td class="vt-k">BINANCE_API_SECRET</td><td class="vt-v">The Secret Key from Step 2 — <b>only shown once at creation</b></td></tr>
    <tr><td class="vt-k">GROQ_API_KEY</td><td class="vt-v">Free AI key — go to <a href="https://console.groq.com">console.groq.com</a> → API Keys → <b>Create API Key</b> (no card needed)</td></tr>
    <tr><td class="vt-k">PAPER_TRADING</td><td class="vt-v">Set to ${chip('true')} to start safely with simulated money. Change to ${chip('false','#f59e0b')} when ready to go live.</td></tr>
    <tr><td class="vt-k">PAPER_BALANCE</td><td class="vt-v">Simulated balance. Default: ${chip('10')} (= $10 USDT)</td></tr>
    <tr><td class="vt-k">TRADE_SYMBOL</td><td class="vt-v">Optional. Override with ${chip('DOGEUSDT')} or ${chip('SOLUSDT')}. Default: auto-scanner picks best coin.</td></tr>
    <tr><td class="vt-k">TELEGRAM_BOT_TOKEN</td><td class="vt-v">Optional — real-time alerts on your phone (setup below)</td></tr>
    <tr><td class="vt-k">TELEGRAM_CHAT_ID</td><td class="vt-v">Optional — your Telegram chat ID (setup below)</td></tr>
  </table>
</div>

<!-- ─ TELEGRAM ─ -->
<div class="card card-blue">
  <div class="card-corner card-corner-blue"></div>
  <div class="card-tag card-tag-blue">📱 Step 4 — Telegram Alerts <span class="card-tag-line"></span></div>
  <div class="step">
    <div class="step-n step-n-b">1</div>
    <div><div class="step-title">Create your Telegram bot</div>
    <div class="step-body">Open Telegram → search <b>@BotFather</b> → send ${chip('/newbot','#818cf8')} → pick any name → BotFather gives you a token like ${chip('7123456:AAFxxx...','#818cf8')} — copy it.</div></div>
  </div>
  <div class="step">
    <div class="step-n step-n-b">2</div>
    <div><div class="step-title">Get your Chat ID</div>
    <div class="step-body">Send any message to your new bot. Then open in browser:<br>
    ${chip('https://api.telegram.org/bot&lt;TOKEN&gt;/getUpdates','#818cf8')}<br>
    Find <b>"chat":{"id":123456789}</b> — that number is your Chat ID.</div></div>
  </div>
  <div class="step">
    <div class="step-n step-n-b">3</div>
    <div><div class="step-title">Add to Railway Variables</div>
    <div class="step-body">Paste the token as ${chip('TELEGRAM_BOT_TOKEN','#818cf8')} and the number as ${chip('TELEGRAM_CHAT_ID','#818cf8')}.<br>You'll get live trade alerts, 30-min heartbeats, and risk-stop notifications instantly on your phone.</div></div>
  </div>
</div>

<!-- ─ GO LIVE ─ -->
<div class="card card-yellow">
  <div class="card-corner card-corner-yellow"></div>
  <div class="card-tag card-tag-yellow">💰 Step 5 — Go Live <span class="card-tag-line"></span></div>
  <div class="step">
    <div class="step-n step-n-y">1</div>
    <div><div class="step-title">Test with Paper Trading first</div>
    <div class="step-body">With ${chip('PAPER_TRADING=true','#f59e0b')}, the bot trades simulated money — zero risk. Run it for 24–48h and check your Telegram alerts look correct before going live.</div></div>
  </div>
  <div class="step">
    <div class="step-n step-n-y">2</div>
    <div><div class="step-title">Deposit USDT on Binance Spot</div>
    <div class="step-body">Fund your <b>Binance Spot</b> wallet with at least $20 USDT (recommended: $20–50 to start). <span style="color:#fbbf24;font-weight:600">Never risk more than you can afford to lose entirely.</span></div></div>
  </div>
  <div class="step">
    <div class="step-n step-n-y">3</div>
    <div><div class="step-title">Flip the switch to Live</div>
    <div class="step-body">In Railway → <b>Variables</b> → change ${chip('PAPER_TRADING','#f59e0b')} from ${chip('true','#f59e0b')} → ${chip('false','#f59e0b')} → click <b>Save</b>. Railway redeploys in seconds. Your bot is now live and trading with real funds. 🚀</div></div>
  </div>
</div>

<!-- ─ RISK ─ -->
<div class="card card-red">
  <p style="font-size:11px;color:rgba(255,255,255,.3);line-height:1.9;margin:0">
    <span style="color:rgba(248,113,113,.7);font-weight:700">⚠ Risk Disclosure</span> — Cryptocurrency trading involves substantial risk of loss and is not suitable for all investors. Always start with paper trading. Only invest funds you can afford to lose completely. Past performance is not indicative of future results. Apex Trade Bot is an automation tool — not financial advice. You are solely responsible for your trading decisions.
  </p>
</div>

</div><!-- /body -->

<!-- ══════ FOOTER ══════ -->
<div class="footer">
  <p class="footer-q">Questions? We respond within 24 hours.</p>
  <a href="mailto:supportaicashsystem@gmail.com" class="footer-email">supportaicashsystem@gmail.com</a>
  <p class="footer-copy">© 2025 AI Cash Systems &nbsp;·&nbsp; <a href="https://aicashsystem.space" style="color:rgba(255,255,255,.15);text-decoration:none">aicashsystem.space</a></p>
</div>

</div></body></html>`;}

// ── BOT ACCESS — streams a clean ZIP of ONLY the bot folder (no server.js, no other files)
app.get('/bot-access', (req, res) => {
  const { execFile } = require('child_process');
  const os = require('os');
  const fs = require('fs');
  const botDir = path.join(__dirname, 'apex-trade-bot');
  const tmpZip = path.join(os.tmpdir(), `apex-trade-bot-${Date.now()}.zip`);

  // Build zip: src/ + package.json + railway.json — no node_modules
  execFile('zip', ['-r', tmpZip, 'src', 'package.json', 'railway.json'], { cwd: botDir }, (err) => {
    if (err) {
      console.error('[BOT-ACCESS] zip error:', err.message);
      return res.status(500).send('Could not generate bot package. Please contact support.');
    }
    res.setHeader('Content-Disposition', 'attachment; filename="apex-trade-bot.zip"');
    res.setHeader('Content-Type', 'application/zip');
    const stream = fs.createReadStream(tmpZip);
    stream.pipe(res);
    stream.on('end', () => fs.unlink(tmpZip, () => {}));
    stream.on('error', () => res.status(500).end());
  });
});

// ── EMAIL STATUS (no auth needed) — check config instantly
app.get('/api/email-status', (req, res) => {
  res.json({ resend: !!RESEND_API_KEY, brevo: !!BREVO_API_KEY, smtp: !!transporter, sender: SENDER_EMAIL || 'not set' });
});

// ── RESEND DNS RECORDS — afișează valorile complete pentru Namecheap
app.get('/api/resend-dns', async (req, res) => {
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

// ── DEBUG: test Resend directly
app.get('/api/test-resend', async (req, res) => {
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

  // Preview mode — afișează emailul direct în browser fără auth/email
  if (isPreview) {
    const name  = req.query.name || req.body.name || 'Alex';
    const email = req.query.email || req.body.email || 'preview@example.com';
    const _he = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    const previewHtml = _buildBotEmailHtml(_he(name), _he(email), 'APEX-DEMO-PREW-2025');
    return res.send(`<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Preview: Bot Delivery Email</title>
      <style>body{margin:0;background:#1a1a2e;display:flex;flex-direction:column;align-items:center;padding:40px 20px;font-family:sans-serif}
      .bar{background:#2d2d44;border:1px solid #444;border-radius:8px;padding:10px 20px;margin-bottom:24px;color:#aaa;font-size:13px;text-align:center;max-width:600px;width:100%}
      .bar strong{color:#00ff88}</style></head><body>
      <div class="bar">📧 <strong>PREVIEW</strong> — Asta e emailul pe care îl primește clientul după cumpărare.<br>
      <span style="font-size:11px;color:#666">Towards: ${_he(email)} · Name: ${_he(name)} · Key: APEX-DEMO-PREW-2025</span></div>
      ${previewHtml}</body></html>`);
  }

  if (!adminSecret) {
    return res.status(403).json({ error: 'BOT_EMAIL_SECRET not set in env — add it on Render' });
  }
  if (secret !== adminSecret) {
    return res.status(403).json({ error: 'Wrong secret', hint: `Expected length: ${adminSecret.length} chars, got: ${(secret||'').length} chars` });
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
// ADMIN: SYNC BOT FILES → apex-trade-bot repo
// Usage: GET /admin/sync-bot-repo?secret=BOT_EMAIL_SECRET&token=ghp_xxx
// ════════════════════════════════════════
app.get('/admin/sync-bot-repo', async (req, res) => {
  const secret = req.query.secret || '';
  const ghToken = req.query.token || '';
  const adminSecret = process.env.BOT_EMAIL_SECRET || '';

  if (!adminSecret) return res.status(500).json({ error: 'BOT_EMAIL_SECRET not set' });
  if (secret !== adminSecret) return res.status(403).json({ error: 'Wrong secret' });
  if (!ghToken) return res.status(400).json({ error: 'GitHub token required (?token=ghp_...)' });

  const OWNER = 'alexgabriel225sefu-dotcom';
  const REPO  = 'apex-trade-bot';
  const botDir = path.join(__dirname, 'apex-trade-bot');

  const filesToPush = [
    'src/ai.js', 'src/backtest.js', 'src/binance.js', 'src/bybit.js',
    'src/config.js', 'src/index.js', 'src/indicators.js', 'src/logger.js',
    'src/state.js', 'src/strategies.js', 'src/telegram.js',
    'package.json', 'railway.json', '.env.example',
  ];

  const readmeContent = `# Apex Trade Bot 🤖

AI-powered crypto trading bot. Deploy with one click on Railway.

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/${OWNER}/${REPO})

## Setup
After deploying, add these variables in Railway → Variables:

| Variable | Value |
|----------|-------|
| \`LICENSE_KEY\` | Your key from purchase email |
| \`EXCHANGE\` | \`binance\` |
| \`BINANCE_API_KEY\` | Your Binance API key |
| \`BINANCE_API_SECRET\` | Your Binance API secret |
| \`GROQ_API_KEY\` | Free key from console.groq.com |
| \`PAPER_TRADING\` | \`true\` (start safe) |
| \`PAPER_BALANCE\` | \`100\` |

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
    return r.ok;
  }

  // Push README.md
  try {
    const ok = await pushFile('README.md', readmeContent);
    results.push({ file: 'README.md', ok });
    if (!ok) errors++;
  } catch(e) { results.push({ file: 'README.md', ok: false, err: e.message }); errors++; }

  // Push all bot files
  for (const rel of filesToPush) {
    try {
      const content = require('fs').readFileSync(path.join(botDir, rel), 'utf8');
      const ok = await pushFile(rel, content);
      results.push({ file: rel, ok });
      if (!ok) errors++;
    } catch(e) {
      results.push({ file: rel, ok: false, err: e.message });
      errors++;
    }
  }

  const allOk = errors === 0;
  res.json({
    success: allOk,
    pushed: results.filter(r => r.ok).length,
    failed: errors,
    results,
    repoUrl: `https://github.com/${OWNER}/${REPO}`,
    railwayButton: `https://railway.app/new/template?template=https://github.com/${OWNER}/${REPO}`,
  });
});

// ════════════════════════════════════════
// CATCH-ALL 404
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
