const express = require('express');
const cors = require('cors');
const path = require('path');
const { createClient } = require('@supabase/supabase-js');
const Anthropic = require('@anthropic-ai/sdk');
const nodemailer = require('nodemailer');
const crypto = require('crypto');

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public'), { index: false }));

// ── ENV VARIABLES ──
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_KEY;
const ANTHROPIC_KEY = process.env.ANTHROPIC_API_KEY;
const OPENAI_KEY = process.env.OPENAI_API_KEY;
const GMAIL_USER = process.env.GMAIL_USER;
const GMAIL_PASS = process.env.GMAIL_PASS;
const JWT_SECRET = process.env.JWT_SECRET || 'autoflow-secret-2024';

// ── CLIENTS ──
const supabase = SUPABASE_URL && SUPABASE_KEY ? createClient(SUPABASE_URL, SUPABASE_KEY) : null;
const anthropic = ANTHROPIC_KEY ? new Anthropic({ apiKey: ANTHROPIC_KEY }) : null;

// ── BREVO SMTP TRANSPORTER ──
const BREVO_USER = process.env.BREVO_SMTP_USER;
const BREVO_PASS = process.env.BREVO_SMTP_PASS;
const transporter = BREVO_USER && BREVO_PASS ? nodemailer.createTransport({
  host: 'smtp-relay.brevo.com',
  port: 587,
  secure: false,
  auth: { user: BREVO_USER, pass: BREVO_PASS }
}) : null;

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

// GET /api/test — public test endpoint
app.get('/api/test', (req, res) => {
  res.json({
    status: 'ok',
    openai: !!OPENAI_KEY,
    anthropic: !!anthropic,
    email: !!transporter,
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

// ANY /webhook/:id — receive webhook data
app.all('/webhook/:id', (req, res) => {
  const hook = webhooks.find(w => w.id === req.params.id);
  if (!hook) return res.status(404).json({ error: 'Webhook not found' });
  hook.hits++;
  hook.lastHit = new Date().toISOString();
  addLog(`Webhook hit: ${hook.name} — ${JSON.stringify(req.body).slice(0, 100)}`, 'webhook', 'success');
  res.json({ received: true, webhook: hook.name, time: hook.lastHit });
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
      if (data) return res.json({ success: true, plan: data.plan || 'starter', redirect: data.plan === 'pro' ? '/course-pro.html' : '/course-starter.html' });
    }
    return res.status(401).json({ error: 'Invalid access code.' });
  } catch (e) {
    res.status(500).json({ error: 'Server error' });
  }
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
app.get('/videos.html', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'videos.html'));
});
app.get('/tiktok', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'videos.html'));
});
app.get('/index.html', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});
app.get('/blueprints.html', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'blueprints.html'));
});
app.get('/blueprints', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'blueprints.html'));
});

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
// START SERVER
// ════════════════════════════════════════
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`AutoFlow server running on port ${PORT}`);
  addLog('Server started', 'system', 'success');
});
