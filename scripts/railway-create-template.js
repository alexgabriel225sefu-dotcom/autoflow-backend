// Fix malformed variable NAMES (trailing whitespace/newline) on the forex
// service: copy each value to the correctly-spelled name, then redeploy.
// Values are read from Railway and re-set via API — never printed or committed.
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
const WANT = ['GROQ_API_KEY','BROKER','TWELVE_DATA_KEY'];

async function main(){
  const res = await gql(`
    query($projectId:String!,$environmentId:String!,$serviceId:String!){
      variables(projectId:$projectId, environmentId:$environmentId, serviceId:$serviceId)
    }`, { projectId: PROJECT_ID, environmentId: ENV_ID, serviceId: SERVICE_ID });
  const obj = res?.data?.variables;
  if (!obj) { out('query error: '+JSON.stringify(res).slice(0,800)); process.exit(1); }

  for (const want of WANT) {
    // find any existing key whose trimmed name equals the wanted name
    const raw = Object.keys(obj).find(k => k.trim() === want);
    if (raw === undefined) { out(`${want}: no source value found — SKIP`); continue; }
    const value = (obj[raw] ?? '').trim();           // also trim stray whitespace in the value
    const up = await gql(`
      mutation($input: VariableUpsertInput!){ variableUpsert(input:$input) }`, {
      input: { projectId: PROJECT_ID, environmentId: ENV_ID, serviceId: SERVICE_ID, name: want, value },
    });
    out(`${want}: upserted (clean name)  ${up?.data?.variableUpsert===true?'OK':JSON.stringify(up).slice(0,200)}`);
  }

  const dep = await gql(`
    mutation($serviceId:String!, $environmentId:String!){
      serviceInstanceDeploy(serviceId:$serviceId, environmentId:$environmentId)
    }`, { serviceId: SERVICE_ID, environmentId: ENV_ID });
  out('redeploy: ' + JSON.stringify(dep).slice(0,200));
}
main().catch(e => { out('FATAL: ' + e.message); process.exit(1); });
