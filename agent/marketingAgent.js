// ── Apex Marketing Agent ────────────────────────────────────
// Free, tool-using agent that writes and pushes promo content for Apex.
// LLM brain = Groq's free-tier API (open-source models, no per-call cost
// at normal volume). Get a key at https://console.groq.com/keys.
//
// Loop: gather context -> ask the LLM to write a post -> send it on every
// channel that has credentials configured (Telegram broadcast, email list).

const GROQ_API_KEY = process.env.GROQ_API_KEY;
const GROQ_MODEL = process.env.GROQ_MODEL || 'llama-3.3-70b-versatile';

const MARKETING_TELEGRAM_BOT_TOKEN = process.env.MARKETING_TELEGRAM_BOT_TOKEN;
const MARKETING_TELEGRAM_CHAT_ID = process.env.MARKETING_TELEGRAM_CHAT_ID;

const PRODUCT_BRIEF = process.env.AGENT_PRODUCT_BRIEF || `
Apex este un bot automat de trading (forex prin cTrader, crypto prin Binance) cu
confirmare de semnal prin AI, management de risc (stop loss, take profit, limita
zilnica de pierdere) si dashboard live. Are si mod paper trading (fara bani reali)
pentru testare. Public tinta: traderi retail care vor un bot bazat pe reguli clare,
fara sa stea ei cu ochii pe grafice.
`.trim();

async function groqChat(messages, { temperature = 0.8, max_tokens = 400 } = {}) {
  if (!GROQ_API_KEY) {
    throw new Error('GROQ_API_KEY not set — get a free key at https://console.groq.com/keys');
  }
  const res = await fetch('https://api.groq.com/openai/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${GROQ_API_KEY}`,
    },
    body: JSON.stringify({ model: GROQ_MODEL, messages, temperature, max_tokens }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Groq API error ${res.status}: ${text}`);
  }
  const data = await res.json();
  return (data.choices?.[0]?.message?.content || '').trim();
}

const STYLE_GUIDE = {
  telegram: 'Scurt (3-5 propozitii), 1-2 emoji, ton direct, cu un call-to-action clar la final.',
  email: 'Format scurt de email (sub 150 cuvinte), ton profesional-prietenos.',
};

async function generatePromoPost({ channel = 'telegram', highlight = '' } = {}) {
  const style = STYLE_GUIDE[channel] || STYLE_GUIDE.telegram;
  const messages = [
    {
      role: 'system',
      content:
        'Esti copywriter de marketing pentru un produs fintech, scrii in romana. ' +
        'Reguli obligatorii: nu promiti niciodata castiguri garantate, mentionezi ' +
        'mereu ca tradingul implica risc, ton onest si increzator, fara clickbait agresiv.',
    },
    {
      role: 'user',
      content:
        `Produs:\n${PRODUCT_BRIEF}\n\nStil cerut: ${style}\n` +
        (highlight
          ? `Highlight de inclus azi: ${highlight}`
          : 'Nu ai un highlight specific azi — scrie un mesaj general de brand.') +
        '\n\nScrie doar textul final al mesajului, fara alte comentarii.',
    },
  ];
  return groqChat(messages, { temperature: 0.9, max_tokens: 300 });
}

async function sendTelegramBroadcast(text) {
  if (!MARKETING_TELEGRAM_BOT_TOKEN || !MARKETING_TELEGRAM_CHAT_ID) {
    return { ok: false, skipped: true, error: 'MARKETING_TELEGRAM_BOT_TOKEN / MARKETING_TELEGRAM_CHAT_ID not set' };
  }
  const res = await fetch(`https://api.telegram.org/bot${MARKETING_TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: MARKETING_TELEGRAM_CHAT_ID, text }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.ok) return { ok: false, error: data.description || `HTTP ${res.status}` };
  return { ok: true, message_id: data.result?.message_id };
}

// One full agent cycle: write -> send on every configured channel -> report.
// `sendEmailFn` is injected so this module stays decoupled from server.js's
// email transport (Resend/Brevo/SMTP) and its recipient list.
async function runMarketingCycle({ highlight = '', sendEmailFn = null, emailRecipients = [] } = {}) {
  const log = [];
  let post;
  try {
    post = await generatePromoPost({ channel: 'telegram', highlight });
    log.push({ step: 'generate', ok: true });
  } catch (e) {
    log.push({ step: 'generate', ok: false, error: e.message });
    return { ok: false, error: e.message, log };
  }

  const tgResult = await sendTelegramBroadcast(post);
  log.push({ step: 'telegram_send', ...tgResult });

  let emailResult = { ok: false, skipped: true, error: 'no recipients / sendEmailFn' };
  if (sendEmailFn && emailRecipients.length) {
    try {
      for (const to of emailRecipients) {
        await sendEmailFn({ to, subject: 'Apex — update', html: post.replace(/\n/g, '<br>') });
      }
      emailResult = { ok: true, sent: emailRecipients.length };
    } catch (e) {
      emailResult = { ok: false, error: e.message };
    }
  }
  log.push({ step: 'email_send', ...emailResult });

  return { ok: true, post, log };
}

// Free scheduler: no cron dependency, just setInterval. Runs once on boot
// (after a short delay) then every `intervalHours`.
function startScheduler({ intervalHours = 24, ...cycleOpts } = {}) {
  if (!GROQ_API_KEY) {
    console.warn('[MarketingAgent] GROQ_API_KEY not set — scheduler disabled. Get a free key at https://console.groq.com/keys');
    return null;
  }
  const intervalMs = Math.max(1, intervalHours) * 60 * 60 * 1000;
  console.log(`[MarketingAgent] Scheduler active — every ${intervalHours}h`);

  const tick = () => {
    runMarketingCycle(cycleOpts)
      .then(r => console.log('[MarketingAgent] Cycle:', r.ok ? 'OK' : `FAILED (${r.error})`))
      .catch(e => console.error('[MarketingAgent] Cycle crashed:', e.message));
  };

  const bootTimer = setTimeout(tick, 60 * 1000); // wait 1min after boot
  const interval = setInterval(tick, intervalMs);
  return { stop: () => { clearTimeout(bootTimer); clearInterval(interval); } };
}

module.exports = { runMarketingCycle, generatePromoPost, sendTelegramBroadcast, startScheduler };
