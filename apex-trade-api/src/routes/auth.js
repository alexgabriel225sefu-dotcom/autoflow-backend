const express = require('express');
const bcrypt = require('bcryptjs');
const { createClient } = require('@supabase/supabase-js');
const { generateToken, authenticate } = require('../middleware/auth');

const router = express.Router();

function getSupabase() {
  if (!process.env.SUPABASE_URL || !process.env.SUPABASE_SERVICE_KEY) {
    throw new Error('SUPABASE_URL and SUPABASE_SERVICE_KEY env vars are required');
  }
  return createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_KEY);
}

let _supabase = null;
function supabase() {
  if (!_supabase) _supabase = getSupabase();
  return _supabase;
}

// POST /auth/register
router.post('/register', async (req, res) => {
  const { email, password, name } = req.body;
  if (!email || !password || !name) {
    return res.status(400).json({ error: 'Câmpuri lipsă' });
  }
  if (password.length < 8) {
    return res.status(400).json({ error: 'Parola trebuie să aibă minim 8 caractere' });
  }

  try {
    // Check existing user
    const { data: existing } = await supabase()
      .from('users')
      .select('id')
      .eq('email', email.toLowerCase())
      .single();

    if (existing) {
      return res.status(409).json({ error: 'Email-ul este deja înregistrat' });
    }

    const passwordHash = await bcrypt.hash(password, 12);

    const { data: user, error } = await supabase()
      .from('users')
      .insert({
        email: email.toLowerCase().trim(),
        password_hash: passwordHash,
        name: name.trim(),
        plan: 'free',
        broker_connected: false,
      })
      .select()
      .single();

    if (error) throw error;

    const token = generateToken(user);
    return res.status(201).json({
      token,
      user: {
        id: user.id,
        email: user.email,
        name: user.name,
        plan: user.plan,
        brokerConnected: user.broker_connected,
      },
    });
  } catch (err) {
    console.error('[Register]', err);
    return res.status(500).json({ error: 'Eroare la înregistrare' });
  }
});

// POST /auth/login
router.post('/login', async (req, res) => {
  const { email, password } = req.body;
  if (!email || !password) {
    return res.status(400).json({ error: 'Câmpuri lipsă' });
  }

  try {
    const { data: user } = await supabase()
      .from('users')
      .select('*')
      .eq('email', email.toLowerCase())
      .single();

    if (!user) {
      return res.status(401).json({ error: 'Email sau parolă incorectă' });
    }

    const valid = await bcrypt.compare(password, user.password_hash);
    if (!valid) {
      return res.status(401).json({ error: 'Email sau parolă incorectă' });
    }

    const token = generateToken(user);
    return res.json({
      token,
      user: {
        id: user.id,
        email: user.email,
        name: user.name,
        plan: user.plan,
        brokerConnected: user.broker_connected,
      },
    });
  } catch (err) {
    console.error('[Login]', err);
    return res.status(500).json({ error: 'Eroare la autentificare' });
  }
});

// GET /auth/me
router.get('/me', authenticate, async (req, res) => {
  try {
    const { data: user } = await supabase()
      .from('users')
      .select('id, email, name, plan, broker_connected')
      .eq('id', req.user.id)
      .single();

    if (!user) return res.status(404).json({ error: 'User negăsit' });

    return res.json({
      id: user.id,
      email: user.email,
      name: user.name,
      plan: user.plan,
      brokerConnected: user.broker_connected,
    });
  } catch (err) {
    return res.status(500).json({ error: 'Eroare server' });
  }
});

// POST /auth/logout
router.post('/logout', authenticate, (req, res) => {
  res.json({ message: 'Deconectat cu succes' });
});

module.exports = router;
