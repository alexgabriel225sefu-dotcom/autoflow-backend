// Creates and publishes the Apex Trade Bot Railway template via GraphQL API.
// Flow: create project → add service from GitHub → generate template → publish
// Env: RAILWAY_TOKEN (required)

const API = 'https://backboard.railway.com/graphql/v2';
const TOKEN = process.env.RAILWAY_TOKEN;
const SUMMARY_FILE = process.env.GITHUB_STEP_SUMMARY;
const GITHUB_OUTPUT = process.env.GITHUB_OUTPUT;

if (!TOKEN) { console.error('RAILWAY_TOKEN missing'); process.exit(1); }

function summary(msg) {
  console.log(msg);
  if (SUMMARY_FILE) require('fs').appendFileSync(SUMMARY_FILE, msg + '\n');
  if (GITHUB_OUTPUT && msg.startsWith('DEPLOY_URL=')) require('fs').appendFileSync(GITHUB_OUTPUT, msg + '\n');
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
  // 1. Test token with a simple query
  const meRes = await gql(`query { me { id name email } }`);
  if (!meRes.json.data) {
    summary('me query failed (maybe scope issue), trying projectCreate directly...');
  } else {
    const me = meRes.json.data.me;
    summary(`Authenticated as ${me.email || me.name} (id=${me.id})`);
  }

  // 2. Create a Railway project
  const projRes = await gql(`
    mutation($input: ProjectCreateInput!) {
      projectCreate(input: $input) { id name }
    }`, {
    input: { name: 'apex-trade-bot-template-source' },
  });
  const proj = projRes.json.data?.projectCreate;
  if (!proj) { summary('PROJECT CREATE FAILED: ' + JSON.stringify(projRes.json).slice(0, 1000)); process.exit(1); }
  summary(`Project created: id=${proj.id} name=${proj.name}`);

  // 3. Get the default environment ID
  const envRes = await gql(`query($id: String!) { project(id: $id) { environments { edges { node { id name } } } } }`, { id: proj.id });
  const envId = envRes.json.data?.project?.environments?.edges[0]?.node?.id;
  if (!envId) { summary('ENV NOT FOUND: ' + JSON.stringify(envRes.json).slice(0, 500)); process.exit(1); }
  summary(`Environment: id=${envId}`);

  // 4. Create service from GitHub repo
  const svcRes = await gql(`
    mutation($input: ServiceCreateInput!) {
      serviceCreate(input: $input) { id name }
    }`, {
    input: {
      projectId: proj.id,
      name: 'apex-trade-bot',
      source: { repo: 'alexgabriel225sefu-dotcom/apex-trade-bot' },
    },
  });
  const svc = svcRes.json.data?.serviceCreate;
  if (!svc) { summary('SERVICE CREATE FAILED: ' + JSON.stringify(svcRes.json).slice(0, 1000)); process.exit(1); }
  summary(`Service created: id=${svc.id}`);

  // 5. Generate template from project
  const genRes = await gql(`
    mutation($input: TemplateGenerateInput!) {
      templateGenerate(input: $input) { id code }
    }`, {
    input: { projectId: proj.id, environmentId: envId },
  });
  const tpl = genRes.json.data?.templateGenerate;
  if (!tpl) { summary('TEMPLATE GENERATE FAILED: ' + JSON.stringify(genRes.json).slice(0, 1000)); process.exit(1); }
  summary(`Template generated: id=${tpl.id} code=${tpl.code}`);
  summary(`DEPLOY_URL=https://railway.com/deploy/${tpl.code}`);

  // 6. Publish template
  const pubRes = await gql(`
    mutation($id: String!, $input: TemplatePublishInput!) {
      templatePublish(id: $id, input: $input)
    }`, {
    id: tpl.id,
    input: {
      category: 'Other',
      description: 'AI crypto trading bot — RSI, MACD, legendary trader strategies, trailing stop, Telegram alerts.',
      readme: 'AI-powered crypto trading bot. Purchase a license at https://aicashsystem.space then add your license key, Binance API keys, and a free Groq key. Starts in paper-trading (simulated) mode by default.',
    },
  });
  summary('templatePublish result: ' + JSON.stringify(pubRes.json).slice(0, 500));

  // 7. Clean up temp project (optional — comment out if you want to keep it)
  await gql(`mutation($id: String!) { projectDelete(id: $id) }`, { id: proj.id });
  summary('Temp project deleted.');

  summary('');
  summary(`=== DONE ===`);
  summary(`Deploy URL: https://railway.com/deploy/${tpl.code}`);
  summary(`Template ID: ${tpl.id}`);
}

main().catch(e => { summary('FATAL: ' + e.message); process.exit(1); });
