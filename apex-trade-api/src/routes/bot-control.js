const express = require('express');
const { getEngine } = require('../services/trading-engine');

const router = express.Router();

// GET /bot/status
router.get('/status', (req, res) => {
  const engine = getEngine();
  if (!engine) {
    return res.json({ running: false, message: 'Botul nu a fost pornit (lipsă variabile de mediu).' });
  }
  res.json(engine.getStatus());
});

// POST /bot/stop — Emergency stop via HTTP (plus Telegram /stop)
router.post('/stop', async (req, res) => {
  const engine = getEngine();
  if (!engine) return res.status(404).json({ error: 'Bot inactiv' });
  await engine.emergencyStop();
  res.json({ success: true, message: 'Bot oprit, toate ordinele anulate.' });
});

// GET /bot/trades
router.get('/trades', (req, res) => {
  const engine = getEngine();
  if (!engine) return res.json([]);
  res.json(engine.getStatus().trades || []);
});

// GET /bot/strategies — list available strategies
router.get('/strategies', (req, res) => {
  const { STRATEGIES } = require('../services/strategies/index');
  res.json(
    Object.entries(STRATEGIES).map(([id, s]) => ({
      id,
      name: s.name,
      description: s.description,
      risk: s.risk,
    }))
  );
});

module.exports = router;
