const Anthropic = require('@anthropic-ai/sdk');
const axios     = require('axios');
const cfg       = require('./config');

// ─── Anthropic client (lazy) ──────────────────────────────
let anthropicClient = null;
function getAnthropic() {
  if (!anthropicClient) anthropicClient = new Anthropic({ apiKey: cfg.ANTHROPIC_API_KEY });
  return anthropicClient;
}

// ─── Groq (free fallback) ────────────────────────────────
async function callGroq(prompt) {
  const key = process.env.GROQ_API_KEY || '';
  if (!key) throw new Error('GROQ_API_KEY missing');

  const { data } = await axios.post(
    'https://api.groq.com/openai/v1/chat/completions',
    {
      model: 'llama-3.3-70b-versatile',
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
  console.log('[AI] ✅ Groq — signal generated');
  return JSON.parse(match[0]);
}

// ─── Anthropic (paid, optional) ──────────────────────────
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
      // Invalid key or insufficient credits — stop trying other models
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
- Breakout signal: ${turtle.signal ?? 'NONE'} | Strength: ${turtle.breakoutStr}
- High 20 periods: ${turtle.high20} | Low 20 periods: ${turtle.low20}
- Near breakout: ${turtle.nearSignal ?? 'NO'}

### 📐 Jesse Livermore (Pivot Structure)
- Trend structure: ${livermore.trend} (${livermore.reason ?? 'N/A'})
- Signal strength: ${livermore.strength !== undefined ? (livermore.strength * 100).toFixed(0) + '%' : 'N/A'}
- Rule: if trend=BULLISH → confirms BUY; if BEARISH → confirms SELL; NEUTRAL → caution

### 💡 George Soros (Reflexivity / Momentum)
- Momentum direction: ${soros.direction}
- Bullish candles: ${soros.momentum !== undefined ? (soros.momentum * 100).toFixed(0) + '%' : 'N/A'} of last 8
- Price velocity: ${soros.velocity !== undefined ? soros.velocity.toFixed(3) + '%' : 'N/A'}

### 📊 Current session (Ed Seykota rules)
- Consecutive losses: ${session.consecutiveLosses} (stop at 3)
- Consecutive wins: ${session.consecutiveWins}
- Trades today: ${session.dailyTrades}/10
- Daily PnL: ${session.dailyPnL >= 0 ? '+' : ''}$${session.dailyPnL.toFixed(4)}`;
  }

  const prompt = `You are a professional trader with 20 years of experience. Apply the rules of legendary traders: Turtle breakout, Livermore structure, Soros momentum, PTJ defense. Analyze ALL data and give a precise signal.

## MARKET DATA — ${cfg.SYMBOL} (${cfg.TIMEFRAME})
### Price & Trend
- Current price: $${indicators.price}
- EMA 20: ${indicators.ema20} | EMA 50: ${indicators.ema50} | EMA 200: ${indicators.ema200}
- EMA20/50 trend: ${indicators.emaTrend} | EMA50/200 trend: ${indicators.ema200Trend}
- Price vs EMA20: ${indicators.priceVsEma20}
- Market structure: ${indicators.marketStructure}

### Momentum
- RSI (14): ${indicators.rsi} ${rsi < 30 ? '⚡ EXTREME OVERSOLD' : rsi < 40 ? '📉 Oversold' : rsi > 70 ? '🔥 EXTREME OVERBOUGHT' : rsi > 60 ? '📈 Overbought' : '⚖️ Neutral'}
- Stoch RSI K: ${indicators.stochRsiK} | D: ${indicators.stochRsiD} ${srsiK < 20 ? '⚡ Oversold' : srsiK > 80 ? '🔥 Overbought' : ''}
- MACD Histogram: ${indicators.macdHist} ${macdH > 0 ? '▲ Bullish' : '▼ Bearish'}
- RSI Divergence: ${indicators.divergence} ${indicators.divergence !== 'NONE' ? '⚡ STRONG SIGNAL!' : ''}

### Volatility & Volume
- ATR: ${indicators.atrPct}% of price
- BB Bandwidth: ${indicators.bb_bandwidth}% | BB Position: ${indicators.bb_position}% ${bbPos < 15 ? '📉 At lower band' : bbPos > 85 ? '📈 At upper band' : ''}
- Volume ratio: ${indicators.volumeRatio}× ${volR > 1.5 ? '⚡ HIGH VOLUME' : volR < 0.7 ? '⚠️ Low volume' : ''}
- Recent high (8h): ${indicators.high24h} | Recent low (8h): ${indicators.low24h}

### Last 5 candles
${indicators.recentCandles.map((c, i) => `${i+1}. ${c.direction} O:${c.open} H:${c.high} L:${c.low} C:${c.close} (body: ${c.bodyPct}%)`).join('\n')}
${legendarySection}
## ACCOUNT
- Balance: $${balance.toFixed(2)} USDT
- Open position: ${openPosition ? `${openPosition.side} @ $${openPosition.entryPrice} | PnL: ${openPosition.pnlPct?.toFixed(2)}%` : 'NONE'}

## ENTRY RULES
- SL: ${cfg.STOP_LOSS_PCT * 100}% | TP: ${cfg.TAKE_PROFIT_PCT * 100}% | Risk: ${cfg.RISK_PER_TRADE * 100}%
- Minimum confidence: ${cfg.MIN_CONFIDENCE}%
- BUY CRITERIA (min 3/5): bullish trend, RSI<50 or bullish div, MACD▲, volume>1.2×, price below EMA20
- SELL CRITERIA (min 3/5): bearish trend, RSI>50 or bearish div, MACD▼, volume>1.2×, price above EMA20
- BONUS +1 criterion if Turtle=STRONG BUY/SELL OR Livermore confirms direction OR Soros momentum aligned
- Do not trade against Livermore trend with strength >0.8

Respond ONLY with valid JSON:
{"action":"BUY"|"SELL"|"HOLD"|"CLOSE","confidence":<0-100>,"reasoning":"<max 2 sentences>","riskLevel":"LOW"|"MEDIUM"|"HIGH","keyFactors":["f1","f2","f3"],"criteriaScore":<0-5>}`;

  // Try Anthropic first, fall back to Groq (free)
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
