// Check which of GROQ_API_KEY / BROKER / TWELVE_DATA_KEY / LICENSE_KEY are
// actually set on the forex service bf56d162 (prints presence only, not values).
const API = 'https://backboard.railway.com/graphql/v2';
const TOKEN = process.env.RAILWAY_TOKEN;
const SUMMARY_FILE = process.env.GITHUB_STEP_SUMMARY;
if (!TOKEN) { console.error('RAILWAY_TOKEN missing'); process.exit(1); }
function out(m){ console.log(m); if (SUMMARY_FILE) require('fs').appendFileSync(SUMMARY_FILE, m+'\n'); }
async function gql(query, variables){
  const r = await fetch(API,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${TOKEN}`},body:JSON.stringify({query,variables})});
  const t = await r.text(); try{return JSON.parse(t);}catch{return {parseError:t.slice(0,2000)};}
}
const SERVICE_ID = 'bf56d162-43fb-42b0-99f0-bfaf778a041d';
const ENV_ID = 'fdc10f11-f4b2-4773-87a0-7e9f66cd8a55';
const PROJECT_ID = '82186fe2-60ea-47ea-8767-6be58ae717fa';
async function main(){
  const vars = await gql(`
    query($projectId:String!,$environmentId:String!,$serviceId:String!){
      variables(projectId:$projectId, environmentId:$environmentId, serviceId:$serviceId)
    }`, { projectId: PROJECT_ID, environmentId: ENV_ID, serviceId: SERVICE_ID });
  const obj = vars?.data?.variables;
  if (!obj) { out('query error: '+JSON.stringify(vars).slice(0,800)); return; }
  const names = Object.keys(obj);
  const check = ['LICENSE_KEY','BYPASS_LICENSE','GROQ_API_KEY','BROKER','TWELVE_DATA_KEY'];
  out('=== presence on forex service bf56d162 (apex-forex-bot in project apex-trade) ===');
  for (const k of check) out(`  ${k}: ${names.includes(k) ? 'SET' : 'MISSING'}`);
  out(`  (total custom-ish names: ${names.filter(n=>!n.startsWith('RAILWAY_')).join(', ')})`);
}
main().catch(e => { out('FATAL: ' + e.message); process.exit(1); });
