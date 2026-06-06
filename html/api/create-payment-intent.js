const Stripe = require('stripe');
const crypto = require('crypto');

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }
  if (req.method !== 'POST') { res.status(405).json({ error: 'Method not allowed' }); return; }

  const { amount, currency, email, name, product } = req.body;
  if (!email || !name) { res.status(400).json({ error: 'Missing required fields.' }); return; }

  if (!process.env.STRIPE_SECRET_KEY) {
    res.status(500).json({ error: 'Payment not configured.' }); return;
  }

  try {
    const stripe = Stripe(process.env.STRIPE_SECRET_KEY);
    const pendingKey = crypto.randomBytes(16).toString('hex');
    const intent = await stripe.paymentIntents.create({
      amount: amount ?? 29700,
      currency: currency ?? 'usd',
      receipt_email: email,
      metadata: { name, email, product: product ?? 'apex-bot', pendingKey },
      automatic_payment_methods: { enabled: true },
    });
    res.json({ clientSecret: intent.client_secret, pendingKey });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
};
