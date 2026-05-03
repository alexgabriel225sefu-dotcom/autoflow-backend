const express = require(‘express’);
const cors = require(‘cors’);
const path = require(‘path’);
const { createClient } = require(’@supabase/supabase-js’);
const Anthropic = require(’@anthropic-ai/sdk’);
const nodemailer = require(‘nodemailer’);
const crypto = require(‘crypto’);

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, ‘public’)));

// ── ENV VARIABLES ──
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_KEY;
const ANTHROPIC_KEY = process.env.ANTHROPIC_API_KEY;
const OPENAI_KEY = process.env.OPENAI_API_KEY;
const GMAIL_USER = process.env.GMAIL_USER;
const GMAIL_PASS = process.env.GMAIL_PASS;
const JWT_SECRET = process.env.JWT_SECRET || ‘autoflow-secret-2024’;

// ── CLIENTS ──
const supabase = SUPABASE_URL && SUPABASE_KEY ? createClient(SUPABASE_URL, SUPABASE_KEY) : null;
const anthropic = ANTHROPIC_KEY ? new Anthropic({ apiKey: ANTHROPIC_KEY }) : null;

// ── GMAIL TRANSPORTER ──
const transporter = GMAIL_USER && GMAIL_PASS ? nodemailer.createTransport({
service: ‘gmail’,
auth: { user: GMAIL_USER, pass: GMAIL_PASS }
}) : null;

// ── IN-MEMORY LOGS ──
const logs = [];
function addLog(msg, type = ‘info’, status = ‘success’) {
logs.unshift({ msg, type, status, time: new Date().toISOString() });
if (logs.length > 200) logs.pop();
}

// ── SIMPLE JWT ──
function createToken(user) {
const payload = Buffer.from(JSON.stringify({ id: user.id, email: user.email, exp: Date.now() + 30*24*60*60*1000 })).toString(‘base64’);
return payload;
}
function verifyToken(token) {
try {
const payload = JSON.parse(Buffer.from(token, ‘base64’).toString());
if (payload.exp < Date.now()) return null;
return payload;
} catch { return null; }
}

// ── AUTH MIDDLEWARE ──
function auth(req, res, next) {
const header = req.headers.authorization;
if (!header) return res.status(401).json({ error: ‘No token’ });
const token = header.replace(’Bearer ’, ‘’);
const payload = verifyToken(token);
if (!payload) return res.status(401).json({ error: ‘Invalid token’ });
req.user = payload;
next();
}

// ════════════════════════════════════════
// AUTH ROUTES
// ════════════════════════════════════════

// POST /api/auth/login
app.post(’/api/auth/login’, async (req, res) => {
const { email, code } = req.body;
if (!email || !code) return res.status(400).json({ error: ‘Email and code required’ });

try {
// Check in Supabase first
if (supabase) {
const { data, error } = await supabase
.from(‘users’)
.select(’*’)
.eq(‘email’, email.toLowerCase())
.eq(‘code’, code.toUpperCase())
.single();

```
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
```

} catch (e) {
console.error(‘Login error:’, e);
return res.status(500).json({ error: ‘Server error. Please try again.’ });
}
});

// POST /api/auth/create-user (admin only)
app.post(’/api/auth/create-user’, auth, async (req, res) => {
const { email, name, plan } = req.body;
if (!email) return res.status(400).json({ error: ‘Email required’ });
const code = crypto.randomBytes(4).toString(‘hex’).toUpperCase();
try {
if (supabase) {
const { data, error } = await supabase.from(‘users’).insert([{ email: email.toLowerCase(), name, code, plan: plan || ‘starter’ }]).select().single();
if (error) return res.status(400).json({ error: error.message });
addLog(`New user created: ${email}`, ‘auth’, ‘success’);
return res.json({ success: true, email, code, plan: plan || ‘starter’ });
}
res.json({ success: true, email, code, plan: plan || ‘starter’ });
} catch (e) {
res.status(500).json({ error: ‘Failed to create user’ });
}
});

// ════════════════════════════════════════
// AI ROUTES
// ════════════════════════════════════════

// POST /api/ai/generate — single prompt generation
app.post(’/api/ai/generate’, auth, async (req, res) => {
const { prompt } = req.body;
if (!prompt) return res.status(400).json({ error: ‘Prompt required’ });

try {
// Try OpenAI first
if (OPENAI_KEY) {
const response = await fetch(‘https://api.openai.com/v1/chat/completions’, {
method: ‘POST’,
headers: { ‘Content-Type’: ‘application/json’, ‘Authorization’: ’Bearer ’ + OPENAI_KEY },
body: JSON.stringify({
model: ‘gpt-4o’,
max_tokens: 2000,
messages: [{ role: ‘user’, content: prompt }]
})
});
const data = await response.json();
if (data.choices && data.choices[0]) {
const output = data.choices[0].message.content;
addLog(‘AI generation completed’, ‘ai’, ‘success’);
return res.json({ output });
}
}

```
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
```

} catch (e) {
console.error(‘AI generate error:’, e);
addLog(’AI generation failed: ’ + e.message, ‘ai’, ‘error’);
res.status(500).json({ error: ’AI generation failed: ’ + e.message });
}
});

// POST /api/ai/chat — multi-turn conversation
app.post(’/api/ai/chat’, auth, async (req, res) => {
const { messages } = req.body;
if (!messages || !messages.length) return res.status(400).json({ error: ‘Messages required’ });

try {
// Try OpenAI first
if (OPENAI_KEY) {
const response = await fetch(‘https://api.openai.com/v1/chat/completions’, {
method: ‘POST’,
headers: { ‘Content-Type’: ‘application/json’, ‘Authorization’: ’Bearer ’ + OPENAI_KEY },
body: JSON.stringify({
model: ‘gpt-4o’,
max_tokens: 2000,
messages: messages
})
});
const data = await response.json();
if (data.choices && data.choices[0]) {
const output = data.choices[0].message.content;
addLog(‘AI chat response sent’, ‘ai’, ‘success’);
return res.json({ output });
}
}

```
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
```

} catch (e) {
console.error(‘AI chat error:’, e);
addLog(’AI chat failed: ’ + e.message, ‘ai’, ‘error’);
res.status(500).json({ error: ’AI chat failed: ’ + e.message });
}
});

// ════════════════════════════════════════
// EMAIL ROUTES
// ════════════════════════════════════════

// POST /api/email/send
app.post(’/api/email/send’, auth, async (req, res) => {
const { to, subject, body, fromName } = req.body;
if (!to || !subject || !body) return res.status(400).json({ error: ‘To, subject and body are required’ });

try {
if (transporter) {
await transporter.sendMail({
from: `"${fromName || 'AutoFlow Agency'}" <${GMAIL_USER}>`,
to,
subject,
text: body,
html: body.replace(/\n/g, ‘<br>’)
});
addLog(`Email sent to ${to}: ${subject}`, ‘email’, ‘success’);
return res.json({ success: true, message: ’Email sent successfully to ’ + to });
}

```
// If no Gmail configured — simulate success and log
addLog(`[DEMO] Email would be sent to ${to}: ${subject}`, 'email', 'success');
return res.json({ success: true, message: 'Email logged (configure GMAIL_USER and GMAIL_PASS in Render to actually send)' });
```

} catch (e) {
console.error(‘Email error:’, e);
addLog(`Email failed to ${to}: ${e.message}`, ‘email’, ‘error’);
res.status(500).json({ error: ’Failed to send email: ’ + e.message });
}
});

// ════════════════════════════════════════
// WEBHOOK ROUTES
// ════════════════════════════════════════

const webhooks = [];

// GET /api/webhooks
app.get(’/api/webhooks’, auth, (req, res) => {
res.json(webhooks);
});

// POST /api/webhooks/create
app.post(’/api/webhooks/create’, auth, (req, res) => {
const { name } = req.body;
const id = crypto.randomBytes(8).toString(‘hex’);
const url = `${req.protocol}://${req.get('host')}/webhook/${id}`;
const webhook = { id, name: name || ‘Webhook’, url, hits: 0, lastHit: null, createdAt: new Date().toISOString() };
webhooks.push(webhook);
addLog(`Webhook created: ${name}`, ‘webhook’, ‘success’);
res.json(webhook);
});

// ANY /webhook/:id — receive webhook data
app.all(’/webhook/:id’, (req, res) => {
const hook = webhooks.find(w => w.id === req.params.id);
if (!hook) return res.status(404).json({ error: ‘Webhook not found’ });
hook.hits++;
hook.lastHit = new Date().toISOString();
addLog(`Webhook hit: ${hook.name} — ${JSON.stringify(req.body).slice(0, 100)}`, ‘webhook’, ‘success’);
res.json({ received: true, webhook: hook.name, time: hook.lastHit });
});

// ════════════════════════════════════════
// LOGS ROUTES
// ════════════════════════════════════════

// GET /api/logs
app.get(’/api/logs’, auth, (req, res) => {
res.json(logs.slice(0, 100));
});

// ════════════════════════════════════════
// COURSE ACCESS ROUTES
// ════════════════════════════════════════

// POST /api/verify-code — verify course access code
app.post(’/api/verify-code’, async (req, res) => {
const { email, code } = req.body;
if (!email || !code) return res.status(400).json({ error: ‘Email and code required’ });
try {
if (supabase) {
const { data, error } = await supabase
.from(‘purchases’)
.select(’*’)
.eq(‘email’, email.toLowerCase())
.eq(‘code’, code.toUpperCase())
.single();
if (data) return res.json({ success: true, plan: data.plan || ‘starter’, redirect: data.plan === ‘pro’ ? ‘/course-pro.html’ : ‘/course-starter.html’ });
}
return res.status(401).json({ error: ‘Invalid access code.’ });
} catch (e) {
res.status(500).json({ error: ‘Server error’ });
}
});

// POST /create-payment-intent — Stripe
app.post(’/create-payment-intent’, async (req, res) => {
const { amount, currency } = req.body;
try {
if (!process.env.STRIPE_SECRET_KEY) return res.status(500).json({ error: ‘Stripe not configured’ });
const stripe = require(‘stripe’)(process.env.STRIPE_SECRET_KEY);
const paymentIntent = await stripe.paymentIntents.create({
amount: amount || 3700,
currency: currency || ‘usd’,
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
app.post(’/stripe-webhook’, express.raw({ type: ‘application/json’ }), async (req, res) => {
const sig = req.headers[‘stripe-signature’];
try {
if (!process.env.STRIPE_SECRET_KEY || !process.env.STRIPE_WEBHOOK_SECRET) {
return res.json({ received: true });
}
const stripe = require(‘stripe’)(process.env.STRIPE_SECRET_KEY);
const event = stripe.webhooks.constructEvent(req.body, sig, process.env.STRIPE_WEBHOOK_SECRET);

```
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
      from: `"AI Cash Systems" <${GMAIL_USER}>`,
      to: email,
      subject: '🎉 Your AI Cash Systems Access Code',
      html: `<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:32px;background:#0a0a0a;color:#F5F0E8">
        <h2 style="color:#C8A96E;font-family:Georgia,serif">Welcome to AI Cash Systems!</h2>
        <p>Your ${plan.toUpperCase()} course access is ready.</p>
        <p><strong>Your Access Code:</strong></p>
        <div style="background:#161616;border:1px solid #C8A96E;border-radius:8px;padding:16px;font-size:24px;font-weight:bold;color:#C8A96E;text-align:center;letter-spacing:4px">${code}</div>
        <p style="margin-top:20px">Access your course here:</p>
        <a href="https://autoflow-backend-p9pc.onrender.com/access.html" style="background:#C8A96E;color:#000;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block;font-weight:bold">Access Course →</a>
        <p style="color:#7A7060;font-size:12px;margin-top:24px">Enter your email and the code above to access your course.</p>
      </div>`
    });
  }

  addLog(`Payment succeeded: ${email} — ${plan} plan — Code: ${code}`, 'payment', 'success');
}
res.json({ received: true });
```

} catch (e) {
console.error(‘Webhook error:’, e);
res.status(400).json({ error: e.message });
}
});

// ════════════════════════════════════════
// CATCH ALL — serve index.html
// ════════════════════════════════════════
app.get(’*’, (req, res) => {
res.sendFile(path.join(__dirname, ‘public’, ‘index.html’));
});

// ════════════════════════════════════════
// START SERVER
// ════════════════════════════════════════
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
console.log(`AutoFlow server running on port ${PORT}`);
addLog(‘Server started’, ‘system’, ‘success’);
});
