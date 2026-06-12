// Creates and publishes the Apex Trade Bot template on Railway via GraphQL API.
// Runs inside GitHub Actions (sandbox has no egress to backboard.railway.com).
// Env: RAILWAY_TOKEN (required), MODE = inspect | create | full (default: full)

const API = 'https://backboard.railway.com/graphql/v2';
const TOKEN = process.env.RAILWAY_TOKEN;
const MODE = process.env.MODE || 'full';

if (!TOKEN) { console.error('RAILWAY_TOKEN missing'); process.exit(1); }

async function gql(query, variables) {
  const r = await fetch(API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${TOKEN}` },
    body: JSON.stringify({ query, variables }),
  });
  const text = await r.text();
  let json;
  try { json = JSON.parse(text); } catch { json = { parseError: text.slice(0, 2000) }; }
  return { status: r.status, json };
}

function typeName(t) {
  // unwrap NON_NULL / LIST wrappers
  let s = '';
  while (t) {
    if (t.kind === 'NON_NULL') { s += '!'; t = t.ofType; }
    else if (t.kind === 'LIST') { s += '[]'; t = t.ofType; }
    else { return (t.name || '?') + s; }
  }
  return '?' + s;
}

async function inspect() {
  const q = `query { __schema { mutationType { fields { name args { name type { kind name ofType { kind name ofType { kind name ofType { kind name } } } } } } } } }`;
  const { status, json } = await gql(q);
  if (!json.data) { console.log('INTROSPECTION FAILED', status, JSON.stringify(json).slice(0, 3000)); return []; }
  const fields = json.data.__schema.mutationType.fields.filter(f => /template/i.test(f.name));
  console.log('=== TEMPLATE MUTATIONS ===');
  const inputTypes = new Set();
  for (const f of fields) {
    const args = f.args.map(a => {
      const tn = typeName(a.type);
      const base = tn.replace(/[!\[\]]/g, '');
      if (/Input/i.test(base)) inputTypes.add(base);
      return `${a.name}: ${tn}`;
    });
    console.log(`${f.name}(${args.join(', ')})`);
  }
  for (const tn of inputTypes) {
    const tq = `query { __type(name: "${tn}") { inputFields { name type { kind name ofType { kind name ofType { kind name ofType { kind name } } } } } } }`;
    const { json: tj } = await gql(tq);
    const ifs = tj.data && tj.data.__type && tj.data.__type.inputFields;
    if (!ifs) continue;
    console.log(`--- input ${tn} ---`);
    for (const f of ifs) console.log(`  ${f.name}: ${typeName(f.type)}`);
  }
  return fields.map(f => f.name);
}

const SERIALIZED_CONFIG = {
  services: {
    'apex-trade-bot': {
      name: 'apex-trade-bot',
      icon: 'https://devicons.railway.com/i/nodejs.svg',
      source: { repo: 'https://github.com/alexgabriel225sefu-dotcom/apex-trade-bot' },
      variables: {
        LICENSE_KEY: { description: 'Your license key from the purchase email', isOptional: false },
        EXCHANGE: { description: 'Exchange to trade on', defaultValue: 'binance', isOptional: true },
        BINANCE_API_KEY: { description: 'Binance API key (enable Reading + Spot Trading, leave Withdrawals OFF)', isOptional: false },
        BINANCE_API_SECRET: { description: 'Binance API secret — shown only once when created', isOptional: false },
        GROQ_API_KEY: { description: 'Free AI key from console.groq.com', isOptional: false },
        PAPER_TRADING: { description: 'Start with true (simulated money). Switch to false to go live.', defaultValue: 'true', isOptional: true },
        PAPER_BALANCE: { description: 'Simulated balance in USDT for paper trading', defaultValue: '100', isOptional: true },
        TELEGRAM_BOT_TOKEN: { description: 'Optional — trade alerts on Telegram', isOptional: true },
      },
    },
  },
};

async function tryMutation(label, query, variables) {
  const { status, json } = await gql(query, variables);
  console.log(`=== ${label} (HTTP ${status}) ===`);
  console.log(JSON.stringify(json, null, 2).slice(0, 5000));
  return json;
}

async function main() {
  await inspect();
  if (MODE === 'inspect') return;

  // Attempt 1: templateCreate with serializedConfig
  const create = await tryMutation('templateCreate', `
    mutation($input: TemplateCreateInput!) {
      templateCreate(input: $input) { id code name }
    }`, {
    input: {
      name: 'Apex Trade Bot',
      description: 'AI crypto trading bot — RSI, MACD, legendary trader strategies, trailing stop, Telegram alerts.',
      serializedConfig: SERIALIZED_CONFIG,
    },
  });

  const tpl = create.data && create.data.templateCreate;
  if (!tpl) { console.log('CREATE FAILED — see introspection above for correct input shape'); return; }

  console.log(`TEMPLATE CREATED: id=${tpl.id} code=${tpl.code}`);
  console.log(`DEPLOY URL: https://railway.com/deploy/${tpl.code}`);

  // Attempt publish
  await tryMutation('templatePublish', `
    mutation($id: String!, $input: TemplatePublishInput!) {
      templatePublish(id: $id, input: $input)
    }`, {
    id: tpl.id,
    input: {
      category: 'Other',
      description: 'AI crypto trading bot — RSI, MACD, legendary trader strategies, trailing stop, Telegram alerts.',
      readme: 'AI-powered crypto trading bot. Add your license key, Binance API keys and a free Groq key, then deploy. Starts in paper-trading mode by default. Purchase a license at https://aicashsystem.space',
    },
  });
}

main().catch(e => { console.error('FATAL', e); process.exit(1); });
