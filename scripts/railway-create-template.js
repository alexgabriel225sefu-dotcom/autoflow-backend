// Create a Railway template that deploys the forex bot Docker image with
// LICENSE_KEY + BYPASS_LICENSE pre-filled, yielding a one-click deploy URL.
// Env: RAILWAY_TOKEN (required)
const crypto = require('crypto');
const API = 'https://backboard.railway.com/graphql/v2';
const TOKEN = process.env.RAILWAY_TOKEN;
const SUMMARY_FILE = process.env.GITHUB_STEP_SUMMARY;
if (!TOKEN) { console.error('RAILWAY_TOKEN missing'); process.exit(1); }

function out(msg) {
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
  catch { return { status: r.status, json: { parseError: text.slice(0, 4000) } }; }
}

const IMAGE = 'ghcr.io/alexgabriel225sefu-dotcom/apex-forex-bot:latest';
const serviceId = crypto.randomUUID();

const serializedConfig = {
  services: {
    [serviceId]: {
      name: 'apex-forex-bot',
      deploy: { restartPolicyType: 'ON_FAILURE', restartPolicyMaxRetries: 10 },
      source: { image: IMAGE },
      variables: {
        LICENSE_KEY:    { isOptional: false, defaultValue: 'FORX-RZNN-FPCN-UJ9N' },
        BYPASS_LICENSE: { isOptional: true,  defaultValue: 'true' },
        GROQ_API_KEY:   { isOptional: true },
      },
      networking: { serviceDomains: { '<hasDomain>': {} } },
    },
  },
};

async function main() {
  const res = await gql(`
    mutation($input: TemplateCreateInput!) {
      templateCreate(input: $input) { id code name }
    }`, {
    input: {
      name: 'Apex Forex Bot',
      description: 'AI forex trading bot — paper trading by default. Add your license key.',
      category: 'Other',
      serializedConfig,
    },
  });
  out('=== templateCreate result ===');
  out(JSON.stringify(res.json, null, 2).slice(0, 6000));

  const code = res.json?.data?.templateCreate?.code;
  if (code) {
    out('');
    out('=== ONE-CLICK URL ===');
    out(`https://railway.com/template/${code}`);
  }
}
main().catch(e => { out('FATAL: ' + e.message); process.exit(1); });
