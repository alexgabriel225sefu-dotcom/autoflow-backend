const express = require('express');
const cors = require('cors');
const dotenv = require('dotenv');
dotenv.config();
const app = express();
app.use(cors());
app.use(express.json());
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', message: 'AutoFlow is running!' });
});
app.post('/api/ai/generate', async (req, res) => {
  try {
    const { prompt, variables = {} } = req.body;
    const OpenAI = require('openai');
    const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
    let p = prompt;
    Object.entries(variables).forEach(([k, v]) => { p = p.replace(new RegExp('{{'+k+'}}','g'), v); });
    const c = await openai.chat.completions.create({ model: 'gpt-4o', messages: [{ role: 'user', content: p }], max_tokens: 500 });
    res.json({ success: true, output: c.choices[0].message.content });
  } catch(e) { res.status(500).json({ error: e.message }); }
});
app.post('/api/email/ai-followup', async (req, res) => {
  try {
    const { name, email, problem } = req.body;
    const OpenAI = require('openai');
    const nodemailer = require('nodemailer');
    const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
    const c = await openai.chat.completions.create({ model: 'gpt-4o', messages: [{ role: 'user', content: 'Write a follow-up email to '+name+' about: '+problem+'. Max 80 words.' }], max_tokens: 200 });
    const body = c.choices[0].message.content;
    const t = nodemailer.createTransport({ service: 'gmail', auth: { user: process.env.GMAIL_USER, pass: process.env.GMAIL_APP_PASSWORD } });
    await t.sendMail({ from: process.env.GMAIL_USER, to: email, subject: 'Hey '+name+', quick follow-up!', text: body });
    res.json({ success: true, to: email, preview: body.slice(0,100) });
  } catch(e) { res.status(500).json({ error: e.message }); }
});
app.get('/', (req, res) => {
  res.send('<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AutoFlow AI</title><link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&display=swap" rel="stylesheet"><style>*{margin:0;padding:0;box-sizing:border-box}body{background:#070710;color:#E8E4FF;font-family:Outfit,sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:24px}.logo{width:72px;height:72px;border-radius:20px;background:linear-gradient(135deg,#4A3A9A,#7C5CFC);display:flex;align-items:center;justify-content:center;font-size:32px;margin:0 auto 20px;box-shadow:0 0 40px rgba(124,92,252,0.4)}.badge{display:inline-flex;align-items:center;gap:8px;background:rgba(0,212,170,0.1);border:1px solid rgba(0,212,170,0.3);border-radius:100px;padding:8px 20px;font-size:13px;color:#00D4AA;margin-bottom:24px}.dot{width:8px;height:8px;border-radius:50%;background:#00D4AA;animation:p 2s infinite}@keyframes p{0%,100%{opacity:1}50%{opacity:.4}}h1{font-size:clamp(32px,6vw,56px);font-weight:800;margin-bottom:14px;background:linear-gradient(135deg,#fff,#9B7FFF);-webkit-background-clip:text;-webkit-text-fill-color:transparent}p{color:#8B87B0;max-width:480px;line-height:1.7;margin-bottom:32px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;max-width:700px;width:100%;margin-bottom:32px}.card{background:rgba(255,255,255,0.04);border:1px solid rgba(124,92,252,0.15);border-radius:12px;padding:20px;text-align:left}.ci{font-size:22px;margin-bottom:8px}.ct{font-size:13px;font-weight:600;margin-bottom:4px}.cd{font-size:11px;color:#8B87B0;line-height:1.5}.btn{padding:13px 30px;background:linear-gradient(135deg,#4A3A9A,#7C5CFC);border:none;border-radius:10px;color:#fff;font-family:Outfit,sans-serif;font-size:13px;font-weight:600;cursor:pointer;text-decoration:none;box-shadow:0 4px 20px rgba(124,92,252,0.3)}</style></head><body><div class="logo">&#9889;</div><div class="badge"><div class="dot"></div>All systems operational</div><h1>AutoFlow<br>AI Platform</h1><p>Your AI automation backend is live. Build powerful automations with GPT-4o, Gmail, WhatsApp and more.</p><div class="cards"><div class="card"><div class="ci">&#129302;</div><div class="ct">AI Generation</div><div class="cd">GPT-4o powered content with custom prompts</div></div><div class="card"><div class="ci">&#128231;</div><div class="ct">Email Automation</div><div class="cd">AI writes and sends emails via Gmail instantly</div></div><div class="card"><div class="ci">&#9889;</div><div class="ct">Lead Follow-Up</div><div class="cd">Form to AI reply in under 60 seconds</div></div><div class="card"><div class="ci">&#128279;</div><div class="ct">API Ready</div><div class="cd">Connect any app via REST API and webhooks</div></div></div><a class="btn" onclick="fetch('/api/health').then(onclick="fetch('/api/health').then(r=>r.json()).then(d=>alert('✅ '+d.message))"">Check API Status</a></body></html>');
});app.post('/api/stripe/create-payment', async (req, res) => {
  try {
    const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
    const { amount, currency, email, name, product } = req.body;
    const paymentIntent = await stripe.paymentIntents.create({
      amount, currency, receipt_email: email, metadata: { name, product }
    });
    res.json({ clientSecret: paymentIntent.client_secret });
  } catch(err) { res.status(500).json({ error: err.message }); }
});app.post('/api/stripe/create-payment', async (req, res) => {
  try {
    const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
    const { amount, currency, email, name, product } = req.body;
    const paymentIntent = await stripe.paymentIntents.create({
      amount, currency, receipt_email: email, metadata: { name, product }
    });
    res.json({ clientSecret: paymentIntent.client_secret });
  } catch(err) { res.status(500).json({ error: err.message }); }
});



const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log('AutoFlow on port ' + PORT));
