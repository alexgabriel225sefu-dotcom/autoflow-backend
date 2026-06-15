const Anthropic = require('@anthropic-ai/sdk');
const axios     = require('axios');
const cfg       = require('./config');

// ─── Anthropic client (lazy) ──────────────────────────────
let anthropicClient = null;
function getAnthropic() {
  if (!anthropicClient) anthropicClient = new Anthropic({ apiKey: cfg.ANTHROPIC_API_KEY });
  return anthropicClient;
}

// ─── Groq (gratuit — fallback) ────────────────────────────
async function callGroq(prompt) {
  const key = process.env.GROQ_API_KEY || '';
  if (!key) throw new Error('GROQ_API_KEY lipsă');

  const { data } = await axios.post(
    'https://api.groq.com/openai/v1/chat/completions',
    {
      model: 'llama-3.3-70b-versatile',  // model gratuit puternic
      messages: [{ role: 'user', content: prompt }],
      max_tokens: 400,
      temperature: 0,
    },
    {
      headers: {
        'Authorization': `Bearer ${key}`,
        'Content-Type': 'application/json',
      },
      timeout: 15000,
    }
  );
  const text  = data.choices[0].message.content.trim();
  const match = text.match(/\{[\s\S]*\}/);
  if (!match) throw new Error('No JSON in Groq response');
  console.log('[AI] ✅ Groq (gratuit) — semnal generat');
  return JSON.parse(match[0]);
}

// ─── Anthropic (plătit) ───────────────────────────────────
async function callAnthropic(prompt) {
  const MODELS = [
    'claude-haiku-4-5-20251001',
    'claude-3-5-haiku-20241022',
    'claude-3-haiku-20240307',
  ];
  for (const model of MODELS) {
    try {
      const msg = await getAnthropic().messages.create({
        model, max_tokens: 400, temperature: 0,
        messages: [{ role: 'user', content: prompt }],
      });
      const text  = msg.content[0].text.trim();
      const match = text.match(/\{[\s\S]*\}/);
      if (!match) throw new Error('No JSON in response');
      console.log(`[AI] ✅ Anthropic ${model}`);
      return JSON.parse(match[0]);
    } catch (err) {
      const status = err.status || err.response?.status || 'N/A';
      console.error(`[AI ❌] Anthropic ${model} | Status: ${status} | ${err.message}`);
      // Credit insuficient sau key invalid — nu mai încearca alte modele
      if (status === 400 || status === 401) break;
    }
  }
  throw new Error('Anthropic unavailable');
}

async function getSignal(indicators, balance, openPosition, strategyData = null) {
  const rsi   = parseFloat(indicators.rsi);
  const srsiK = parseFloat(indicators.stochRsiK);
  const macdH = parseFloat(indicators.macdHist);
  const volR  = parseFloat(indicators.volumeRatio);
  const bbPos = parseFloat(indicators.bb_position);

  // ─── Legendary Traders section (only if data provided) ───
  let legendarySection = '';
  if (strategyData) {
    const { turtle, livermore, soros, session } = strategyData;
    legendarySection = `
## LEGENDARY TRADERS ANALYSIS
### 🐢 Turtle Trading (Richard Dennis / Eckhardt)
- Breakout signal: ${turtle.signal ?? 'NONE'} | Putere: ${turtle.breakoutStr}
- High 20 perioade: ${turtle.high20} | Low 20 perioade: ${turtle.low20}
- Near breakout: ${turtle.nearSignal ?? 'NO'}

### 📐 Jesse Livermore (Pivot Structure)
- Trend structură: ${livermore.trend} (${livermore.reason ?? 'N/A'})
- Putere semnal: ${livermore.strength !== undefined ? (livermore.strength * 100).toFixed(0) + '%' : 'N/A'}
- Regula: dacă trend=BULLISH → confirmă BUY; dacă BEARISH → confirmă SELL; NEUTRAL → prudent

### 💡 George Soros (Reflexivity / Momentum)
- Direcție momentum: ${soros.direction}
- Bullish candles: ${soros.momentum !== undefined ? (soros.momentum * 100).toFixed(0) + '%' : 'N/A'} din ultimele 8
- Velocity preț: ${soros.velocity !== undefined ? soros.velocity.toFixed(3) + '%' : 'N/A'}

### 📊 Sesiune curentă (Ed Seykota rules)
- Pierderi consecutive: ${session.consecutiveLosses} (stop la 3)
- Câștiguri consecutive: ${session.consecutiveWins}
- Tranzacții azi: ${session.dailyTrades}/10
- PnL zilnic: ${session.dailyPnL >= 0 ? '+' : ''}$${session.dailyPnL.toFixed(4)}`;
  }

  const prompt = `Ești un trader profesionist cu 20 ani experiență. Aplici regulile marilor traideri: Turtle breakout, Livermore structure, Soros momentum, PTJ defense. Analizează TOATE datele și dă un semnal precis.

## MARKET DATA — ${cfg.SYMBOL} (${cfg.TIMEFRAME})
### Preț & Trend
- Preț curent: $${indicators.price}
- EMA 20: ${indicators.ema20} | EMA 50: ${indicators.ema50} | EMA 200: ${indicators.ema200}
- Trend EMA20/50: ${indicators.emaTrend} | Trend EMA50/200: ${indicators.ema200Trend}
- Preț vs EMA20: ${indicators.priceVsEma20}
- Structura pieței: ${indicators.marketStructure}

### Momentum
- RSI (14): ${indicators.rsi} ${rsi < 30 ? '⚡ OVERSOLD EXTREM' : rsi < 40 ? '📉 Oversold' : rsi > 70 ? '🔥 OVERBOUGHT EXTREM' : rsi > 60 ? '📈 Overbought' : '⚖️ Neutru'}
- Stoch RSI K: ${indicators.stochRsiK} | D: ${indicators.stochRsiD} ${srsiK < 20 ? '⚡ Oversold' : srsiK > 80 ? '🔥 Overbought' : ''}
- MACD Histogram: ${indicators.macdHist} ${macdH > 0 ? '▲ Bullish' : '▼ Bearish'}
- Divergență RSI: ${indicators.divergence} ${indicators.divergence !== 'NONE' ? '⚡ SEMNAL PUTERNIC!' : ''}

### Volatilitate & Volum
- ATR: ${indicators.atrPct}% din preț
- BB Bandwidth: ${indicators.bb_bandwidth}% | Poziție în BB: ${indicators.bb_position}% ${bbPos < 15 ? '📉 La lower band' : bbPos > 85 ? '📈 La upper band' : ''}
- Volum ratio: ${indicators.volumeRatio}× ${volR > 1.5 ? '⚡ VOLUM MARE' : volR < 0.7 ? '⚠️ Volum mic' : ''}
- High recent (8h): ${indicators.high24h} | Low recent (8h): ${indicators.low24h}

### Ultimele 5 lumânări
${indicators.recentCandles.map((c, i) => `${i+1}. ${c.direction} O:${c.open} H:${c.high} L:${c.low} C:${c.close} (body: ${c.bodyPct}%)`).join('\n')}
${legendarySection}
## CONT
- Balanță: $${balance.toFixed(2)} USDT
- Poziție deschisă: ${openPosition ? `${openPosition.side} @ $${openPosition.entryPrice} | PnL: ${openPosition.pnlPct?.toFixed(2)}%` : 'NICIUNA'}

## REGULI DE INTRARE
- SL: ${cfg.STOP_LOSS_PCT * 100}% | TP: ${cfg.TAKE_PROFIT_PCT * 100}% | Risc: ${cfg.RISK_PER_TRADE * 100}%
- Minimum confidence: ${cfg.MIN_CONFIDENCE}%
- CRITERII BUY (min 3/5): trend bullish, RSI<50 sau div.bullish, MACD▲, volum>1.2×, preț sub EMA20
- CRITERII SELL (min 3/5): trend bearish, RSI>50 sau div.bearish, MACD▼, volum>1.2×, preț peste EMA20
- BONUS +1 criteriu dacă Turtle=STRONG BUY/SELL SAU Livermore confirmă direcția SAU Soros momentum alininat
- Nu tranzacționa contra trendului Livermore cu putere >0.8

Răspunde DOAR cu JSON valid:
{"action":"BUY"|"SELL"|"HOLD"|"CLOSE","confidence":<0-100>,"reasoning":"<max 2 prop română>","riskLevel":"LOW"|"MEDIUM"|"HIGH","keyFactors":["f1","f2","f3"],"criteriaScore":<0-5>}`;

  // Încearcă Anthropic, dacă nu merge → Groq (gratuit)
  try { return sanitize(await callAnthropic(prompt)); } catch {}
  try { return sanitize(await callGroq(prompt)); } catch (err) {
    console.error('[AI ❌] Groq failed:', err.message);
  }

  console.error('[AI ❌] All AI sources failed — HOLD');
  return { action: 'HOLD', confidence: 0, reasoning: 'AI error', riskLevel: 'HIGH', keyFactors: [], criteriaScore: 0 };
}

// Validare strictă a JSON-ului de la LLM. Fără asta, "confidence":"high"
// devine NaN și NaN < MIN_CONFIDENCE e false — gate-ul ar trece pe date corupte.
const VALID_ACTIONS = ['BUY', 'SELL', 'HOLD', 'CLOSE'];
function sanitize(raw) {
  const action     = VALID_ACTIONS.includes(raw?.action) ? raw.action : 'HOLD';
  const confidence = Number(raw?.confidence);
  const criteria   = Number(raw?.criteriaScore);
  if (action === 'HOLD' || !Number.isFinite(confidence) || !Number.isFinite(criteria)) {
    if (action !== 'HOLD') console.warn('[AI ⚠️] Răspuns AI malformat (confidence/criteriaScore non-numeric) → HOLD');
    return { action: 'HOLD', confidence: 0, reasoning: String(raw?.reasoning ?? 'malformed'),
             riskLevel: 'HIGH', keyFactors: [], criteriaScore: 0 };
  }
  return {
    action,
    confidence:    Math.min(100, Math.max(0, confidence)),
    criteriaScore: Math.min(5, Math.max(0, criteria)),
    reasoning:     String(raw.reasoning ?? ''),
    riskLevel:     ['LOW', 'MEDIUM', 'HIGH'].includes(raw.riskLevel) ? raw.riskLevel : 'MEDIUM',
    keyFactors:    Array.isArray(raw.keyFactors) ? raw.keyFactors.slice(0, 5) : [],
  };
}

module.exports = { getSignal, sanitize };
