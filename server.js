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
      finalPrompt = finalPrompt.replace(new RegExp(`{{${key}}}`, 'g'), val);
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
      messages: [{ role: 'user', content: `Write a short friendly follow-up email to ${name} about: ${problem}. Max 80 words.` }],
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
      subject: `Hey ${name}, quick follow-up!`,
      text: aiBody
    });

    res.json({ success: true, to: email, preview: aiBody.slice(0, 100) });
  } catch(err) {
    res.status(500).json({ error: err.message });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`AutoFlow running on port ${PORT}`));
