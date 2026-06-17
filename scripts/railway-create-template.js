// Deploy the forex bot Docker image into the EXISTING empty "apex-trade" project,
// avoiding the free-plan "new project" limit. Creates a service from the image
// with LICENSE_KEY + BYPASS_LICENSE, then deploys it.
// Env: RAILWAY_TOKEN (required)
const API = 'https://backboard.railway.com/graphql/v2';
const TOKEN = process.env.RAILWAY_TOKEN;
const SUMMARY_FILE = process.env.GITHUB_STEP_SUMMARY;
if (!TOKEN) { console.error('RAILWAY_TOKEN missing'); process.exit(1); }
function out(m){ console.log(m); if (SUMMARY_FILE) require('fs').appendFileSync(SUMMARY_FILE, m+'\n'); }
async function gql(query, variables){
  const r = await fetch(API,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${TOKEN}`},body:JSON.stringify({query,variables})});
  const t = await r.text(); try{return JSON.parse(t);}catch{return {parseError:t.slice(0,2000)};}
}

const IMAGE = 'ghcr.io/alexgabriel225sefu-dotcom/apex-forex-bot:latest';
// Existing empty project "apex-trade" + its production environment.
const PROJECT_ID = '82186fe2-60ea-47ea-8767-6be58ae717fa';
const ENV_ID = 'fdc10f11-f4b2-4773-87a0-7e9f66cd8a55';
const VARIABLES = { LICENSE_KEY: 'FORX-RZNN-FPCN-UJ9N', BYPASS_LICENSE: 'true' };

async function main(){
  const svc = await gql(`
    mutation($input: ServiceCreateInput!){
      serviceCreate(input:$input){ id name }
    }`, {
    input: {
      projectId: PROJECT_ID,
      environmentId: ENV_ID,
      name: 'apex-forex-bot',
      source: { image: IMAGE },
      variables: VARIABLES,
    },
  });
  out('=== serviceCreate ===');
  out(JSON.stringify(svc, null, 2).slice(0, 3000));
  const serviceId = svc?.data?.serviceCreate?.id;
  if (!serviceId) { out('No service created — see errors above.'); process.exit(1); }

  const dep = await gql(`
    mutation($serviceId:String!, $environmentId:String!){
      serviceInstanceDeploy(serviceId:$serviceId, environmentId:$environmentId)
    }`, { serviceId, environmentId: ENV_ID });
  out('=== serviceInstanceDeploy ===');
  out(JSON.stringify(dep).slice(0, 1500));

  out('');
  out('=== RESULT ===');
  out(`serviceId=${serviceId}`);
  out(`Project URL: https://railway.com/project/${PROJECT_ID}`);
}
main().catch(e => { out('FATAL: ' + e.message); process.exit(1); });
