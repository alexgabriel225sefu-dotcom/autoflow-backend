// Switch forex service back to Twelve Data mode (BROKER=td) and redeploy.
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

async function upsert(name, value){
  const r = await gql(`mutation($input:VariableUpsertInput!){ variableUpsert(input:$input) }`,
    { input: { projectId: PROJECT_ID, environmentId: ENV_ID, serviceId: SERVICE_ID, name, value } });
  out(`${name}=${value}: ` + (r?.data?.variableUpsert===true?'OK':JSON.stringify(r).slice(0,200)));
}

async function main(){
  await upsert('BROKER', 'td');
  await upsert('MULTI_SYMBOL', 'false');  // single pair only — stay under 8 credits/min

  const dep = await gql(`mutation($serviceId:String!,$environmentId:String!){ serviceInstanceDeploy(serviceId:$serviceId, environmentId:$environmentId) }`,
    { serviceId: SERVICE_ID, environmentId: ENV_ID });
  out('redeploy: ' + JSON.stringify(dep).slice(0,200));
}
main().catch(e => { out('FATAL: ' + e.message); process.exit(1); });
