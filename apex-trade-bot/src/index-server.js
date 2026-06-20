/**
 * APEX TRADE BOT — Multi-Tenant Server Entry Point
 * Run with: node src/index-server.js (or npm run server)
 *
 * Required env vars:
 *   TELEGRAM_BOT_TOKEN  — your bot token from @BotFather
 *   ANTHROPIC_API_KEY   — OR GROQ_API_KEY (free)
 *   MASTER_KEY          — AES-256 key for encrypting user API keys (change in prod!)
 *
 * Optional:
 *   USER_DATA_DIR       — directory for user JSON files (default: /tmp/apex-users)
 */
require('dotenv').config();
process.stdout.write('[APEX SERVER] Starting multi-tenant bot server...\n');

// Global safety net — log and survive instead of crashing
process.on('uncaughtException',  err => console.error('[CRASH] uncaughtException:', err.message, err.stack));
process.on('unhandledRejection', err => console.error('[CRASH] unhandledRejection:', err?.message || err));

const tg = require('./telegram-mt');

// ─── Validate required env vars ────────────────────────────────
const hasAnthropic = !!process.env.ANTHROPIC_API_KEY;
const hasGroq      = !!process.env.GROQ_API_KEY;

if (!hasAnthropic && !hasGroq) {
  console.error('❌  No AI key! Set ANTHROPIC_API_KEY or GROQ_API_KEY in your .env');
  process.exit(1);
}

if (!process.env.TELEGRAM_BOT_TOKEN) {
  console.error('❌  TELEGRAM_BOT_TOKEN not set!');
  process.exit(1);
}

if (!process.env.MASTER_KEY) {
  console.warn('⚠️  MASTER_KEY not set — using default key. Set a strong random key in production!');
}

console.log(`✅  AI: ${hasAnthropic ? 'Anthropic' : ''}${hasAnthropic && hasGroq ? ' + ' : ''}${hasGroq ? 'Groq (fallback)' : ''}`);
console.log(`✅  Telegram token: ...${process.env.TELEGRAM_BOT_TOKEN.slice(-6)}`);
console.log('🚀  Starting Telegram polling...\n');

tg.startPolling().catch(e => {
  console.error('Fatal:', e.message);
  process.exit(1);
});
