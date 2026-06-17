// Inspect an existing Railway template's serialized config to learn the schema
// so we can create a Docker-image-based template programmatically.
// Env: RAILWAY_TOKEN (required)
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

async function main() {
  const TEMPLATE_ID = '15133712-3b51-4b03-9b83-be257e7912bc';
  // Dump the full template including serializedConfig so we can mirror its shape.
  const res = await gql(`
    query($id: String!) {
      template(id: $id) {
        id code name status
        serializedConfig
      }
    }`, { id: TEMPLATE_ID });
  out('=== TEMPLATE DUMP ===');
  out(JSON.stringify(res.json, null, 2).slice(0, 8000));
}
main().catch(e => { out('FATAL: ' + e.message); process.exit(1); });
