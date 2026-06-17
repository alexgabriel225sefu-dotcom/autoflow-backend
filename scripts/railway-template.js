// Publish existing Railway template by known ID
// Env: RAILWAY_TOKEN (required)

const API = 'https://backboard.railway.com/graphql/v2';
const TOKEN = process.env.RAILWAY_TOKEN;
const SUMMARY_FILE = process.env.GITHUB_STEP_SUMMARY;

if (!TOKEN) { console.error('RAILWAY_TOKEN missing'); process.exit(1); }

function summary(msg) {
  console.log(msg);
  if (SUMMARY_FILE) require('fs').appendFileSync(SUMMARY_FILE, msg + '\n');
}

async function gql(query, variables) {
  const r = await fetch(API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${TOKEN}` },
    body: JSON.stringify({ query, variables }),
  });
  const text = await r.text();
  try { return { status: r.status, json: JSON.parse(text) }; }
  catch { return { status: r.status, json: { parseError: text.slice(0, 2000) } }; }
}

async function main() {
  const TEMPLATE_ID = '15133712-3b51-4b03-9b83-be257e7912bc';
  const TEMPLATE_CODE = 'UMCVOQ';

  summary(`Publishing template id=${TEMPLATE_ID} code=${TEMPLATE_CODE}`);

  // Try templatePublish
  const pubRes = await gql(`
    mutation($id: String!, $input: TemplatePublishInput!) {
      templatePublish(id: $id, input: $input) { id code activeProjects }
    }`, {
    id: TEMPLATE_ID,
    input: {
      category: 'Other',
      description: 'AI crypto trading bot — RSI, MACD, legendary trader strategies, trailing stop, Telegram alerts.',
      readme: 'AI-powered crypto trading bot. Purchase a license at https://aicashsystem.space then add your license key, Binance API keys, and a free Groq key. Starts in paper-trading (simulated) mode by default.',
    },
  });
  summary('templatePublish result: ' + JSON.stringify(pubRes.json).slice(0, 2000));

  // Also check what URL formats exist
  const tplRes = await gql(`
    query($id: String!) {
      template(id: $id) { id code name status activeProjects }
    }`, { id: TEMPLATE_ID });
  summary('template query: ' + JSON.stringify(tplRes.json).slice(0, 2000));

  summary('');
  summary('=== URLS TO TRY ===');
  summary(`https://railway.com/template/${TEMPLATE_CODE}`);
  summary(`https://railway.com/deploy/${TEMPLATE_CODE}`);
  summary(`https://railway.com/new/template/${TEMPLATE_CODE}`);
}

main().catch(e => { summary('FATAL: ' + e.message); process.exit(1); });
