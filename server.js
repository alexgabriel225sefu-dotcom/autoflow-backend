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
    let finalPrompt = prompt;
    Object.entries(variables).forEach(([key, val]) => {
      finalPrompt = finalPrompt.replace(new RegExp('{{'+key+'}}', 'g'), val);
    });
    const completion = await openai.chat.completions.create({
      model: 'gpt-4o',
      messages: [{ role: 'user', content: finalPrompt }],
      max_tokens: 500
    });
    res.json({ success: true, output: completion.choices[0].message.content });
  } catch(err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/email/ai-followup', async (req, res) => {
  try {
    const { name, email, problem } = req.body;
    const OpenAI = require('openai');
    const nodemailer = require('nodemailer');
    const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
    const completion = await openai.chat.completions.create({
      model: 'gpt-4o',
      messages: [{ role: 'user', content: 'Write a short friendly follow-up email to '+name+' about: '+problem+'. Max 80 words.' }],
      max_tokens: 200
    });
    const aiBody = completion.choices[0].message.content;
    const transporter = nodemailer.createTransport({
      service: 'gmail',
      auth: { user: process.env.GMAIL_USER, pass: process.env.GMAIL_APP_PASSWORD }
    });
    await transporter.sendMail({
      from: process.env.GMAIL_USER,
      to: email,
      subject: 'Hey '+name+', quick follow-up!',
      text: aiBody
    });
    res.json({ success: true, to: email, preview: aiBody.slice(0, 100) });
  } catch(err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/', (req, res) => {
  res.send('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/><title>AutoFlow AI Platform</title><link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet"/><style>*{margin:0;padding:0;box-sizing:border-box}body{background:#070710;color:#E8E4FF;font-family:Outfit,sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:24px}body::before{content:"";position:fixed;inset:0;background:radial-gradient(ellipse 60% 50% at 50% 0%,rgba(124,92,252,0.15) 0%,transparent 70%);pointer-events:none}.logo{width:72px;height:72px;border-radius:20px;background:linear-gradient(135deg,#4A3A9A,#7C5CFC);display:flex;align-items:center;justify-content:center;font-size:32px;margin:0 auto 24px;box-shadow:0 0 40px rgba(124,92,252,0.4)}h1{font-size:clamp(36px,6vw,60px);font-weight:800;margin-bottom:16px;background:linear-gradient(135deg,#fff,#9B7FFF);-webkit-background-
