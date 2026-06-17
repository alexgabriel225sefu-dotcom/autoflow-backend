// Diagnose current Railway service config and force update to latest image
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
  // 1) Check current service instance config
  const svc = await gql(`query($serviceId:String!,$environmentId:String!){
    serviceInstance(serviceId:$serviceId, environmentId:$environmentId){
      dockerImage source buildCommand startCommand domains{ edges{ node{ domain } } }
    }
  }`, { serviceId: SERVICE_ID, environmentId: ENV_ID });
  out('=== Current service config ===');
  out(JSON.stringify(svc?.data?.serviceInstance || svc, null, 2).slice(0, 1000));

  // 2) Check current variables
  const vars = await gql(`query($projectId:String!,$environmentId:String!,$serviceId:String!){
    variables(projectId:$projectId, environmentId:$environmentId, serviceId:$serviceId)
  }`, { projectId: PROJECT_ID, environmentId: ENV_ID, serviceId: SERVICE_ID });
  const v = vars?.data?.variables || {};
  out('=== Key variables ===');
  out('BROKER=' + (v.BROKER||'(not set)'));
  out('MULTI_SYMBOL=' + (v.MULTI_SYMBOL||'(not set)'));
  out('BYPASS_LICENSE=' + (v.BYPASS_LICENSE||'(not set)'));

  // 3) Force update dockerImage to :latest and redeploy
  const image = 'ghcr.io/alexgabriel225sefu-dotcom/apex-forex-bot:latest';
  const upd = await gql(`
    mutation($serviceId:String!,$environmentId:String!,$input:ServiceInstanceUpdateInput!){
      serviceInstanceUpdate(serviceId:$serviceId, environmentId:$environmentId, input:$input)
    }`, { serviceId: SERVICE_ID, environmentId: ENV_ID, input: { dockerImage: image } });
  out('image set to :latest → ' + JSON.stringify(upd).slice(0,200));

  const dep = await gql(`mutation($serviceId:String!,$environmentId:String!){
    serviceInstanceDeploy(serviceId:$serviceId, environmentId:$environmentId)
  }`, { serviceId: SERVICE_ID, environmentId: ENV_ID });
  out('redeploy → ' + JSON.stringify(dep).slice(0,200));
}
main().catch(e => { out('FATAL: ' + e.message); process.exit(1); });
