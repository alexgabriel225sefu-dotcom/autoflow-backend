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
  // 1. Find existing apex-trade-bot project
  summary('Looking for existing Railway projects...');
  const projsRes = await gql(`query { projects { edges { node { id name } } } }`);
  summary('projects query: ' + JSON.stringify(projsRes.json).slice(0, 2000));
  const projects = projsRes.json.data?.projects?.edges || [];
  summary(`Found ${projects.length} projects: ${projects.map(e => e.node.name).join(', ')}`);

  // Use the apex-trade project (not forex)
  const proj = projects.find(e => /^apex.trade$/i.test(e.node.name)) ||
               projects.find(e => /apex.trade/i.test(e.node.name) && !/forex/i.test(e.node.name)) ||
               projects[0];
  const projNode = proj?.node;
  if (!projNode) { summary('NO PROJECT FOUND'); process.exit(1); }
  summary(`Using project: id=${projNode.id} name=${projNode.name}`);

  // 3. Inspect project services
  const projRes2 = await gql(`
    query($id: String!) {
      project(id: $id) {
        environments { edges { node { id name } } }
        services { edges { node { id name source { repo image } } } }
      }
    }`, { id: projNode.id });
  summary('project detail: ' + JSON.stringify(projRes2.json.data?.project).slice(0, 2000));

  const envId = projRes2.json.data?.project?.environments?.edges[0]?.node?.id;
  if (!envId) { summary('ENV NOT FOUND'); process.exit(1); }
  summary(`Environment: id=${envId}`);

  const existingSvcs = projRes2.json.data?.project?.services?.edges || [];
  summary(`Existing services: ${existingSvcs.map(e => e.node.name).join(', ')}`);

  // 5. Generate template from project using existing services (with GitHub source)
  const genRes = await gql(`
    mutation($input: TemplateGenerateInput!) {
      templateGenerate(input: $input) { id code }
    }`, {
    input: { projectId: projNode.id, environmentId: envId },
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

  // 7. No cleanup — we used an existing project, don't delete it

  summary('');
  summary(`=== DONE ===`);
  summary(`Deploy URL: https://railway.com/deploy/${tpl.code}`);
  summary(`Template ID: ${tpl.id}`);
}

main().catch(e => { summary('FATAL: ' + e.message); process.exit(1); });
