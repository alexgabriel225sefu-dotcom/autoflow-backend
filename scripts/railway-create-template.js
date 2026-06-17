// Deploy the forex bot Docker image as a real Railway project, fully via API:
// projectCreate -> serviceCreate(image + variables). The user touches nothing.
// Env: RAILWAY_TOKEN (required)
const API = 'https://backboard.railway.com/graphql/v2';
const TOKEN = process.env.RAILWAY_TOKEN;
const SUMMARY_FILE = process.env.GITHUB_STEP_SUMMARY;
if (!TOKEN) { console.error('RAILWAY_TOKEN missing'); process.exit(1); }
function out(m){ console.log(m); if (SUMMARY_FILE) require('fs').appendFileSync(SUMMARY_FILE, m+'\n'); }
async function gql(query, variables){
  const r = await fetch(API,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${TOKEN}`},body:JSON.stringify({query,variables})});
  const t = await r.text(); let j; try{j=JSON.parse(t);}catch{j={parseError:t.slice(0,2000)};}
  return j;
}

const IMAGE = 'ghcr.io/alexgabriel225sefu-dotcom/apex-forex-bot:latest';
const VARIABLES = {
  LICENSE_KEY: 'FORX-RZNN-FPCN-UJ9N',
  BYPASS_LICENSE: 'true',
};

async function main(){
  // 1) Create the project (returns its default environment).
  const proj = await gql(`
    mutation($input: ProjectCreateInput!){
      projectCreate(input:$input){ id name environments{ edges{ node{ id name } } } }
    }`, { input: { name: 'Apex Forex Bot' } });
  out('=== projectCreate ===');
  out(JSON.stringify(proj, null, 2).slice(0, 2500));
  const project = proj?.data?.projectCreate;
  if (!project) { out('No project created — aborting.'); process.exit(1); }
  const projectId = project.id;
  const envId = project.environments?.edges?.[0]?.node?.id;
  out(`projectId=${projectId} envId=${envId}`);

  // 2) Create the service from the Docker image, with variables, in that env.
  const svc = await gql(`
    mutation($input: ServiceCreateInput!){
      serviceCreate(input:$input){ id name }
    }`, {
    input: {
      projectId,
      environmentId: envId,
      name: 'apex-forex-bot',
      source: { image: IMAGE },
      variables: VARIABLES,
    },
  });
  out('=== serviceCreate ===');
  out(JSON.stringify(svc, null, 2).slice(0, 2500));
  const serviceId = svc?.data?.serviceCreate?.id;

  // 3) Safety net: explicitly trigger a deploy of the service instance.
  if (serviceId && envId) {
    const dep = await gql(`
      mutation($serviceId:String!, $environmentId:String!){
        serviceInstanceDeploy(serviceId:$serviceId, environmentId:$environmentId)
      }`, { serviceId, environmentId: envId });
    out('=== serviceInstanceDeploy ===');
    out(JSON.stringify(dep).slice(0, 1500));
  }

  out('');
  out('=== RESULT ===');
  out(`Project URL: https://railway.com/project/${projectId}`);
}
main().catch(e => { out('FATAL: ' + e.message); process.exit(1); });
