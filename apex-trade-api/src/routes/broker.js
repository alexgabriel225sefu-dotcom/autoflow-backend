const express = require('express');
const { createClient } = require('@supabase/supabase-js');

const router = express.Router();

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY
);

// POST /broker/connect
router.post('/connect', async (req, res) => {
  const { broker, apiKey, apiSecret, sandbox = true } = req.body;
  const userId = req.user.id;

  if (!broker || !apiKey || !apiSecret) {
    return res.status(400).json({ error: 'Câmpuri obligatorii lipsă' });
  }

  const SUPPORTED_BROKERS = ['binance', 'alpaca', 'oanda', 'interactive_brokers'];
  if (!SUPPORTED_BROKERS.includes(broker)) {
    return res.status(400).json({ error: 'Broker nesuportat' });
  }

  try {
    // Validate API keys (simplified — în producție faci request real)
    // For now, just store encrypted
    const { error } = await supabase.from('broker_connections').upsert({
      user_id: userId,
      broker,
      api_key_encrypted: Buffer.from(apiKey).toString('base64'),
      api_secret_encrypted: Buffer.from(apiSecret).toString('base64'),
      sandbox,
      connected_at: new Date().toISOString(),
      status: 'active',
    }, { onConflict: 'user_id' });

    if (error) throw error;

    // Update user broker status
    await supabase.from('users').update({ broker_connected: true }).eq('id', userId);

    return res.json({
      message: `${broker} conectat cu succes${sandbox ? ' (mod testare)' : ''}`,
      broker,
      sandbox,
    });
  } catch (err) {
    console.error('[Broker Connect]', err);
    return res.status(500).json({ error: 'Eroare la conectarea brokerului' });
  }
});

// DELETE /broker/disconnect
router.delete('/disconnect', async (req, res) => {
  const userId = req.user.id;
  try {
    await supabase.from('broker_connections').delete().eq('user_id', userId);
    await supabase.from('users').update({ broker_connected: false }).eq('id', userId);
    return res.json({ message: 'Broker deconectat' });
  } catch (err) {
    return res.status(500).json({ error: 'Eroare la deconectare' });
  }
});

// GET /broker/status
router.get('/status', async (req, res) => {
  const userId = req.user.id;
  try {
    const { data } = await supabase
      .from('broker_connections')
      .select('broker, sandbox, status, connected_at')
      .eq('user_id', userId)
      .single();

    return res.json(data || { connected: false });
  } catch {
    return res.json({ connected: false });
  }
});

// POST /broker/order — place order
router.post('/order', async (req, res) => {
  const { symbol, side, type, quantity, price, market } = req.body;

  if (!symbol || !side || !type || !quantity || !market) {
    return res.status(400).json({ error: 'Câmpuri obligatorii lipsă' });
  }

  if (!['buy', 'sell'].includes(side)) {
    return res.status(400).json({ error: 'Side invalid (buy/sell)' });
  }

  try {
    // În producție: execute via broker API (Binance, Alpaca, etc.)
    // Simulăm execuția
    const order = {
      id: `ord_${Date.now()}`,
      symbol,
      side,
      type,
      quantity,
      price: price || null,
      market,
      status: 'filled',
      filledAt: new Date().toISOString(),
      filledPrice: price || (Math.random() * 1000 + 100),
    };

    return res.json(order);
  } catch (err) {
    return res.status(500).json({ error: 'Eroare la plasarea ordinului' });
  }
});

// DELETE /broker/order/:id
router.delete('/order/:id', async (req, res) => {
  return res.json({ message: 'Ordin anulat', orderId: req.params.id });
});

// GET /broker/orders
router.get('/orders', async (req, res) => {
  return res.json([]);
});

module.exports = router;
