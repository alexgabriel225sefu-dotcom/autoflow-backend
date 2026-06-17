// Switch forex service to MT5 bridge mode: set BROKER=mt, create a public
// Railway domain (so the ApexBridge EA can reach /api/mt/sync), redeploy.
// MT_BRIDGE_SECRET is set by the user (kept out of public logs).
const API = 'https://backboard.railway.com/graphql/v2';
const TOKEN = process.env.RAILWAY_TOKEN;
const SUMMARY_FILE = process.env.GITHUB_STEP_SUMMARY;
if (!TOKEN) { console.error('RAILWAY_TOKEN missing'); process.exit(1); }
function out(m){ console.log(m); if (SUMMARY_FILE) require('fs').appendFileSync(SUMMARY_FILE, m+'\n'); }
async function gql(query, variables){
  const r = await fetch(API,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${TOKEN}`},body:JSON.stringify({query,variables})});
  const t = await r.text(); try{return JSON.parse(t);}catch{return {parseError:t.slice(0,2000)};}
}
function tn(t){ return t?.name || t?.ofType?.name || t?.ofType?.ofType?.name || t?.kind; }
const SERVICE_ID = 'bf56d162-43fb-42b0-99f0-bfaf778a041d';
const ENV_ID = 'fdc10f11-f4b2-4773-87a0-7e9f66cd8a55';
const PROJECT_ID = '82186fe2-60ea-47ea-8767-6be58ae717fa';

async function main(){
  // 1) BROKER=mt
  const b = await gql(`mutation($input:VariableUpsertInput!){ variableUpsert(input:$input) }`,
    { input: { projectId: PROJECT_ID, environmentId: ENV_ID, serviceId: SERVICE_ID, name: 'BROKER', value: 'mt' } });
  out('BROKER=mt: ' + (b?.data?.variableUpsert===true?'OK':JSON.stringify(b).slice(0,200)));

  // 2) introspect the domain mutation + input so we create it correctly
  const mut = await gql(`query{ __type(name:"Mutation"){ fields{ name args{ name } } } }`);
  const domMut = (mut?.data?.__type?.fields||[]).filter(f=>/serviceDomain(Create|Update)/i.test(f.name)).map(f=>f.name);
  out('domain mutations: ' + domMut.join(', '));
  const inp = await gql(`query{ __type(name:"ServiceDomainCreateInput"){ inputFields{ name type{ name kind ofType{ name kind } } } } }`);
  const fields = inp?.data?.__type?.inputFields||[];
  out('ServiceDomainCreateInput: ' + fields.map(f=>`${f.name}:${tn(f.type)}`).join(', '));

  // 3) attempt to create a public domain (targetPort 3000 — the bot's default web port)
  const dom = await gql(`
    mutation($input: ServiceDomainCreateInput!){
      serviceDomainCreate(input:$input){ domain }
    }`, { input: { environmentId: ENV_ID, serviceId: SERVICE_ID, targetPort: 3000 } });
  out('serviceDomainCreate: ' + JSON.stringify(dom).slice(0, 600));

  // 4) redeploy
  const dep = await gql(`mutation($serviceId:String!,$environmentId:String!){ serviceInstanceDeploy(serviceId:$serviceId, environmentId:$environmentId) }`,
    { serviceId: SERVICE_ID, environmentId: ENV_ID });
  out('redeploy: ' + JSON.stringify(dep).slice(0,200));
}
main().catch(e => { out('FATAL: ' + e.message); process.exit(1); });
