/**
 * Stripe payment verification (read-only, no extra deps).
 *
 * The website creates each PaymentIntent with metadata.pendingKey = <random token>
 * and returns that token to the buyer's browser. After paying, the buyer opens
 *   https://t.me/<BOT>?start=<token>
 * which makes Telegram send the bot:  /start <token>
 *
 * The bot then asks Stripe (with its secret key) whether a SUCCEEDED payment
 * exists for that token. If yes → grant access. No shared database needed.
 */
const axios = require('axios');

const STRIPE_KEY = (process.env.STRIPE_SECRET_KEY || '').trim();

function enabled() { return !!STRIPE_KEY; }

/**
 * @returns {Promise<boolean>} true if a succeeded payment exists for this token.
 * Note: Stripe Search is eventually consistent (a freshly succeeded payment can
 * take a few seconds to be indexed) — the caller should offer a retry.
 */
async function verifyPaidToken(token) {
  if (!STRIPE_KEY || !token) return false;
  // Only accept tokens shaped like our license keys (defensive against injection).
  // License keys look like APEX-XXXX-XXXX-XXXX / FORX-XXXX-XXXX-XXXX.
  if (!/^[A-Za-z0-9_-]{8,80}$/.test(token)) return false;

  try {
    const query = `metadata['pendingKey']:'${token}' AND status:'succeeded'`;
    const { data } = await axios.get('https://api.stripe.com/v1/payment_intents/search', {
      params: { query, limit: 1 },
      headers: { Authorization: `Bearer ${STRIPE_KEY}` },
      timeout: 9000,
    });
    return Array.isArray(data?.data) && data.data.length > 0;
  } catch (e) {
    console.warn('[Stripe] verify error:', e.response?.data?.error?.message || e.message);
    return false;
  }
}

module.exports = { enabled, verifyPaidToken };
