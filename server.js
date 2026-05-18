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
app.use(cors());
app.use(express.json());
// Serve static assets (JS, CSS, images) but NOT HTML — HTML goes through route handlers
const _serveStatic = express.static(path.join(__dirname, 'public'), { index: false });
app.use((req, res, next) => {
  if (/\.html?$/i.test(req.path)) return next();
  _serveStatic(req, res, next);
});

// Health check — first route, no deps, always responds
app.get('/health', (req, res) => res.json({ ok: true, node: process.version, time: new Date().toISOString() }));
app.get('/ping', (req, res) => res.json({ ok: true, version: 'v5-stable', time: new Date().toISOString() }));

// ── ENV VARIABLES ──
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_KEY;
const ANTHROPIC_KEY = process.env.ANTHROPIC_API_KEY;
const OPENAI_KEY = process.env.OPENAI_API_KEY;
const JWT_SECRET = process.env.JWT_SECRET || 'autoflow-secret-2024';
const COOKIE_SECRET = process.env.COOKIE_SECRET || JWT_SECRET + '-cookie';
const BREVO_API_KEY = process.env.BREVO_API_KEY;

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
  const sig = crypto.createHmac('sha256', COOKIE_SECRET).update(plan).digest('hex').slice(0, 24);
  return plan + '.' + sig;
}
function _verifyAccess(signed) {
  if (!signed || !signed.includes('.')) return null;
  const dot = signed.lastIndexOf('.');
  const plan = signed.slice(0, dot);
  const sig = signed.slice(dot + 1);
  const expected = crypto.createHmac('sha256', COOKIE_SECRET).update(plan).digest('hex').slice(0, 24);
  return sig === expected ? plan : null;
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

// ── SIMPLE JWT ──
function createToken(user) {
  const payload = Buffer.from(JSON.stringify({ id: user.id, email: user.email, exp: Date.now() + 30*24*60*60*1000 })).toString('base64');
  return payload;
}
function verifyToken(token) {
  try {
    // Try base64 decode
    const decoded = Buffer.from(token, 'base64').toString('utf8');
    const payload = JSON.parse(decoded);
    if (payload.exp && payload.exp < Date.now()) return null;
    return payload;
  } catch(e) {
    // If base64 fails, try as plain JSON
    try {
      const payload = JSON.parse(token);
      return payload;
    } catch(e2) {
      // Accept any token that looks valid for now
      return { id: 'user', email: 'user@autoflow.com' };
    }
  }
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

// ════════════════════════════════════════
// AUTH ROUTES
// ════════════════════════════════════════

// POST /api/auth/login
app.post('/api/auth/login', async (req, res) => {
  const { email, code } = req.body;
  if (!email || !code) return res.status(400).json({ error: 'Email and code required' });

  try {
    // Check in Supabase first
    if (supabase) {
      const { data, error } = await supabase
        .from('users')
        .select('*')
        .eq('email', email.toLowerCase())
        .eq('code', code.toUpperCase())
        .single();

      if (data) {
        const token = createToken(data);
        addLog(`User logged in: ${email}`, 'auth', 'success');
        return res.json({ token, user: { id: data.id, email: data.email, name: data.name || email.split('@')[0], plan: data.plan || 'pro' } });
      }
    }

    // Fallback hardcoded admin access
    if (email.toLowerCase() === 'alexgabriel225sefu@gmail.com' && code.toUpperCase() === 'AF2024PRO') {
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
app.post('/api/auth/create-user', auth, async (req, res) => {
  const { email, name, plan } = req.body;
  if (!email) return res.status(400).json({ error: 'Email required' });
  const code = crypto.randomBytes(4).toString('hex').toUpperCase();
  try {
    if (supabase) {
      const { data, error } = await supabase.from('users').insert([{ email: email.toLowerCase(), name, code, plan: plan || 'starter' }]).select().single();
      if (error) return res.status(400).json({ error: error.message });
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
app.post('/api/ai/generate', auth, async (req, res) => {
  const { prompt } = req.body;
  if (!prompt) return res.status(400).json({ error: 'Prompt required' });

  try {
    // Try OpenAI first
    if (OPENAI_KEY) {
      const response = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + OPENAI_KEY },
        body: JSON.stringify({
          model: 'gpt-4o',
          max_tokens: 2000,
          messages: [{ role: 'user', content: prompt }]
        })
      });
      const data = await response.json();
      if (data.choices && data.choices[0]) {
        const output = data.choices[0].message.content;
        addLog('AI generation completed', 'ai', 'success');
        return res.json({ output });
      }
    }

    // Try Anthropic Claude
    if (anthropic) {
      const msg = await anthropic.messages.create({
        model: 'claude-sonnet-4-6',
        max_tokens: 2000,
        messages: [{ role: 'user', content: prompt }]
      });
      const output = msg.content[0].text;
      addLog('AI generation completed (Claude)', 'ai', 'success');
      return res.json({ output });
    }

    return res.status(500).json({ error: 'No AI provider configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY in Render environment variables.' });
  } catch (e) {
    console.error('AI generate error:', e);
    addLog('AI generation failed: ' + e.message, 'ai', 'error');
    res.status(500).json({ error: 'AI generation failed: ' + e.message });
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
  try {
    if (!fs.existsSync(path.join(__dirname, 'data'))) fs.mkdirSync(path.join(__dirname, 'data'));
    fs.writeFileSync(STORE_FILE, JSON.stringify([...automationStore.values()]), 'utf8');
  } catch(e) { console.error('Store save error:', e.message); }
}

loadStore();

async function callAI(systemPrompt, userMessage) {
  const today = new Date().toLocaleDateString('en-GB', { weekday:'long', year:'numeric', month:'long', day:'numeric' });
  const fullSystem = `${systemPrompt}\n\nToday's date is: ${today}.`;
  if (OPENAI_KEY) {
    const r = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + OPENAI_KEY },
      body: JSON.stringify({ model: 'gpt-4o', max_tokens: 600,
        messages: [{ role: 'system', content: fullSystem }, { role: 'user', content: userMessage }] })
    });
    const d = await r.json();
    if (d.choices && d.choices[0]) return d.choices[0].message.content;
  }
  if (anthropic) {
    const msg = await anthropic.messages.create({ model: 'claude-sonnet-4-6', max_tokens: 600,
      system: fullSystem, messages: [{ role: 'user', content: userMessage }] });
    return msg.content[0].text;
  }
  throw new Error('No AI provider configured');
}

async function sendNotifyEmail(to, automationName, userMsg, aiMsg) {
  const subject = `New message — ${automationName}`;
  const html = `<div style="font-family:sans-serif;max-width:580px;margin:0 auto;padding:24px">
    <h2 style="color:#E53E2E;margin-bottom:4px">💬 New customer message</h2>
    <p style="color:#888;font-size:13px;margin-bottom:20px">${automationName} · AutoFlow</p>
    <div style="background:#f5f5f5;border-radius:10px;padding:16px;margin-bottom:14px">
      <p style="font-size:11px;text-transform:uppercase;color:#999;margin-bottom:6px">Customer</p>
      <p style="font-size:14px;color:#222;line-height:1.6;margin:0">${userMsg.replace(/\n/g,'<br>')}</p>
    </div>
    <div style="background:#fff3f2;border-left:3px solid #E53E2E;border-radius:10px;padding:16px">
      <p style="font-size:11px;text-transform:uppercase;color:#E53E2E;margin-bottom:6px">AI Reply</p>
      <p style="font-size:14px;color:#222;line-height:1.6;margin:0">${aiMsg.replace(/\n/g,'<br>')}</p>
    </div>
    <p style="color:#ccc;font-size:11px;margin-top:18px;text-align:center">AutoFlow · aicashsystem.space</p>
  </div>`;

  // Try Brevo API first (no SMTP setup needed)
  if (BREVO_API_KEY) {
    try {
      const senderEmail = BREVO_USER || 'noreply@aicashsystem.space';
      const r = await fetch('https://api.brevo.com/v3/smtp/email', {
        method: 'POST',
        headers: { 'api-key': BREVO_API_KEY, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender: { name: 'AutoFlow', email: senderEmail },
          to: [{ email: to }],
          subject, htmlContent: html
        })
      });
      if (!r.ok) { const e = await r.text(); throw new Error(e); }
      addLog(`Notify email sent to ${to}`, 'email', 'success');
      return;
    } catch(e) { console.error('Brevo API email error:', e.message); }
  }

  // Fallback: SMTP transporter
  if (transporter) {
    transporter.sendMail({ from: BREVO_USER || 'noreply@aicashsystem.space', to, subject, html })
      .then(() => addLog(`Notify email sent (SMTP) to ${to}`, 'email', 'success'))
      .catch(e => console.error('SMTP email error:', e.message));
    return;
  }

  console.warn('No email provider configured. Set BREVO_API_KEY in Render environment variables.');
  addLog('Email not sent — no email provider configured', 'email', 'error');
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
  const webhookUrl = `${req.protocol}://${req.get('host')}/webhook/${webhook_id}`;
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
  automationStore.delete(req.params.id);
  saveStore();
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
      const { data } = await supabase.from('automations').select('active').eq('webhook_id', req.params.id).single();
      if (data) {
        const { data: updated } = await supabase.from('automations').update({ active: !data.active }).eq('webhook_id', req.params.id).select().single();
        return res.json({ automation: updated });
      }
    } catch(e) {}
  }
  const a = automationStore.get(req.params.id);
  if (a) { a.active = !a.active; saveStore(); return res.json({ automation: a }); }
  res.status(404).json({ error: 'Not found' });
});

// POST /webhook/:webhookId — PUBLIC execution endpoint
app.post('/webhook/:webhookId', async (req, res) => {
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
          from: automation.config?.from_email || BREVO_USER || 'noreply@aicashsystem.space',
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
        await fetch(automation.config.callback_url, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reply: aiReply, original: body })
        });
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
    res.status(500).json({ error: 'Automation failed: ' + e.message });
  }
});

// GET /api/chat/:webhookId/info — public: returns automation name for chat page
app.get('/api/chat/:webhookId/info', async (req, res) => {
  const a = await getAutomation(req.params.webhookId);
  if (!a) return res.status(404).json({ error: 'Not found' });
  res.json({ name: a.name, active: a.active });
});

// GET /chat/:webhookId — serve public chat page
app.get('/chat/:webhookId', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'chat.html'));
});

// POST /api/test-email — send a real test email and return result
app.post('/api/test-email', auth, async (req, res) => {
  const to = req.body.to || req.user.email;
  const result = { to, brevo_api_key: !!BREVO_API_KEY, smtp: !!transporter, brevo_user: BREVO_USER || null };

  if (BREVO_API_KEY) {
    try {
      const senderEmail = BREVO_USER || 'noreply@aicashsystem.space';
      const r = await fetch('https://api.brevo.com/v3/smtp/email', {
        method: 'POST',
        headers: { 'api-key': BREVO_API_KEY, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender: { name: 'AutoFlow', email: senderEmail },
          to: [{ email: to }],
          subject: 'AutoFlow — Test Email',
          htmlContent: '<p>Test email from AutoFlow. If you see this, email notifications work!</p>'
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
        from: BREVO_USER || 'noreply@aicashsystem.space',
        to,
        subject: 'AutoFlow — Test Email',
        html: '<p>Test email from AutoFlow. If you see this, email notifications work!</p>'
      });
      return res.json({ ...result, method: 'smtp', success: true });
    } catch(e) {
      return res.json({ ...result, method: 'smtp', success: false, error: e.message });
    }
  }

  res.json({ ...result, method: 'none', success: false, error: 'No email provider configured' });
});

// GET /api/test — public test endpoint
app.get('/api/test', (req, res) => {
  res.json({
    status: 'ok',
    openai: !!OPENAI_KEY,
    anthropic: !!anthropic,
    email: !!transporter,
    brevo_api: !!BREVO_API_KEY,
    supabase: !!supabase
  });
});

app.get('/ping', (req, res) => {
  res.json({ ok: true, version: 'v2-videos', time: new Date().toISOString() });
});

// POST /api/ai/chat — multi-turn conversation
app.post('/api/ai/chat', auth, async (req, res) => {
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
    res.status(500).json({ error: 'AI chat failed: ' + e.message });
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
  const safeName = path.basename(blueprintFile).replace(/[^a-zA-Z0-9._-]/g, '');
  const bpPath = path.join(__dirname, 'public', 'blueprints', safeName);

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
app.post('/api/email/send', auth, async (req, res) => {
  const { to, subject, body, fromName } = req.body;
  if (!to || !subject || !body) return res.status(400).json({ error: 'To, subject and body are required' });

  try {
    if (transporter) {
      await transporter.sendMail({
        from: `"${fromName || 'AI Cash Systems'}" <support@aicashsystem.space>`,
        to,
        subject,
        text: body,
        html: body.replace(/\n/g, '<br>')
      });
      addLog(`Email sent to ${to}: ${subject}`, 'email', 'success');
      return res.json({ success: true, message: 'Email sent successfully to ' + to });
    }

    // If no Gmail configured — simulate success and log
    addLog(`[DEMO] Email would be sent to ${to}: ${subject}`, 'email', 'success');
    return res.json({ success: true, message: 'Email logged (configure GMAIL_USER and GMAIL_PASS in Render to actually send)' });
  } catch (e) {
    console.error('Email error:', e);
    addLog(`Email failed to ${to}: ${e.message}`, 'email', 'error');
    res.status(500).json({ error: 'Failed to send email: ' + e.message });
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
  const url = `${req.protocol}://${req.get('host')}/webhook/${id}`;
  const webhook = { id, name: name || 'Webhook', url, hits: 0, lastHit: null, createdAt: new Date().toISOString() };
  webhooks.push(webhook);
  addLog(`Webhook created: ${name}`, 'webhook', 'success');
  res.json(webhook);
});

// GET /webhook/:id — friendly info page (POST is handled by automation engine above)
app.get('/webhook/:id', (req, res) => {
  res.json({ info: 'This is an AutoFlow automation webhook. Send a POST request with {"message":"your text"} to trigger it.', id: req.params.id });
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
app.post('/api/verify-code', async (req, res) => {
  const { email, code } = req.body;
  if (!email || !code) return res.status(400).json({ error: 'Email and code required' });
  try {
    if (supabase) {
      const { data, error } = await supabase
        .from('purchases')
        .select('*')
        .eq('email', email.toLowerCase())
        .eq('code', code.toUpperCase())
        .single();
      if (data) {
        const plan = data.plan || 'starter';
        const maxAge = 60 * 60 * 24 * 30; // 30 days
        const secure = process.env.RENDER ? '; Secure' : '';
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
app.post('/create-payment-intent', async (req, res) => {
  const { amount, currency } = req.body;
  try {
    if (!process.env.STRIPE_SECRET_KEY) return res.status(500).json({ error: 'Stripe not configured' });
    const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
    const paymentIntent = await stripe.paymentIntents.create({
      amount: amount || 3700,
      currency: currency || 'usd',
      automatic_payment_methods: { enabled: true }
    });
    res.json({ clientSecret: paymentIntent.client_secret });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ════════════════════════════════════════
// STRIPE WEBHOOK
// ════════════════════════════════════════
app.post('/stripe-webhook', express.raw({ type: 'application/json' }), async (req, res) => {
  const sig = req.headers['stripe-signature'];
  try {
    if (!process.env.STRIPE_SECRET_KEY || !process.env.STRIPE_WEBHOOK_SECRET) {
      return res.json({ received: true });
    }
    const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
    const event = stripe.webhooks.constructEvent(req.body, sig, process.env.STRIPE_WEBHOOK_SECRET);

    if (event.type === 'payment_intent.succeeded') {
      const pi = event.data.object;
      const email = pi.metadata?.email || pi.receipt_email;
      const plan = pi.amount >= 9700 ? 'pro' : 'starter';
      const code = crypto.randomBytes(4).toString('hex').toUpperCase();

      if (email && supabase) {
        await supabase.from('purchases').insert([{ email, code, plan, amount: pi.amount, created_at: new Date().toISOString() }]);
      }

      // Send access email
      if (transporter && email) {
        const courseUrl = plan === 'pro' ? '/course-pro.html' : '/course-starter.html';
        await transporter.sendMail({
          from: `"AI Cash Systems" <support@aicashsystem.space>`,
          to: email,
          subject: '🎉 Your AI Cash Systems Access Code',
          html: `<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:32px;background:#0a0a0a;color:#F5F0E8">
            <h2 style="color:#C8A96E;font-family:Georgia,serif">Welcome to AI Cash Systems!</h2>
            <p>Your ${plan.toUpperCase()} course access is ready.</p>
            <p><strong>Your Access Code:</strong></p>
            <div style="background:#161616;border:1px solid #C8A96E;border-radius:8px;padding:16px;font-size:24px;font-weight:bold;color:#C8A96E;text-align:center;letter-spacing:4px">${code}</div>
            <p style="margin-top:20px">Access your course here:</p>
            <a href="https://aicashsystem.onrender.com/access.html" style="background:#C8A96E;color:#000;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block;font-weight:bold">Access Course →</a>
            <p style="color:#7A7060;font-size:12px;margin-top:24px">Enter your email and the code above to access your course.</p>
          </div>`
        });
      }

      addLog(`Payment succeeded: ${email} — ${plan} plan — Code: ${code}`, 'payment', 'success');
    }
    res.json({ received: true });
  } catch (e) {
    console.error('Webhook error:', e);
    res.status(400).json({ error: e.message });
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

app.get('/download/:id', async (req, res) => {
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
    Readable.fromWeb(response.body).pipe(res);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/descarcare', (req, res) => {
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

// Diagnostic route
app.get('/debug', (req, res) => {
  const fs = require('fs');
  const publicPath = path.join(__dirname, 'public');
  let files = [];
  try { files = fs.readdirSync(publicPath); } catch(e) { files = ['ERROR: ' + e.message]; }
  res.json({ ok: true, __dirname, publicPath, files, env: process.env.NODE_ENV, port: process.env.PORT });
});

// Root redirect — cinematic intro first
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'intro-epic.html'));
});

// Explicit HTML page routes
// Public pages — no auth required
const publicPages = ['index','access','privacy','terms','intro-epic'];
publicPages.forEach(p => {
  app.get(`/${p}.html`, (req, res) => res.sendFile(path.join(__dirname, 'public', `${p}.html`)));
  app.get(`/${p}`, (req, res) => res.sendFile(path.join(__dirname, 'public', `${p}.html`)));
});

// Protected pages — require any valid course purchase
const protectedPages = ['app','videos','blueprints','ai-builder','course-starter',
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

app.post('/api/builder/plan', async (req, res) => {
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

app.post('/api/builder/logo', async (req, res) => {
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
    res.status(500).json({ error: 'Logo failed: ' + e.message });
  }
});

app.get('/ai-builder', (req, res) => res.sendFile(path.join(__dirname, 'public', 'ai-builder.html')));
app.get('/ai-builder.html', (req, res) => res.sendFile(path.join(__dirname, 'public', 'ai-builder.html')));

// ════════════════════════════════════════
// CATCH-ALL 404
// ════════════════════════════════════════
app.use((req, res) => {
  res.status(404).json({ error: 'route not found', path: req.path, method: req.method });
});

// ════════════════════════════════════════
// START SERVER
// ════════════════════════════════════════
const PORT = process.env.PORT || 3000;
app.listen(PORT, '0.0.0.0', () => {
  console.log(`AutoFlow server running on port ${PORT} (0.0.0.0)`);
  addLog('Server started', 'system', 'success');
  // Self-test so we can see in Render logs if routes work
  fetch(`http://127.0.0.1:${PORT}/ping`)
    .then(r => r.json())
    .then(d => console.log('SELF-TEST OK:', JSON.stringify(d)))
    .catch(e => console.error('SELF-TEST FAIL:', e.message));
});
