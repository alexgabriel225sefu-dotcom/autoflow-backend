// Discover existing projects/services/environments + ServiceInstanceUpdateInput schema,
// so we can re-point the existing forex service at the Docker image (no new resources).
const API = 'https://backboard.railway.com/graphql/v2';
const TOKEN = process.env.RAILWAY_TOKEN;
const SUMMARY_FILE = process.env.GITHUB_STEP_SUMMARY;
if (!TOKEN) { console.error('RAILWAY_TOKEN missing'); process.exit(1); }
function out(m){ console.log(m); if (SUMMARY_FILE) require('fs').appendFileSync(SUMMARY_FILE, m+'\n'); }
async function gql(query, variables){
  const r = await fetch(API,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${TOKEN}`},body:JSON.stringify({query,variables})});
  const t = await r.text(); try{return JSON.parse(t);}catch{return {parseError:t.slice(0,2000)};}
}
function tn(t){ return t.name || t.ofType?.name || t.ofType?.ofType?.name || t.kind; }
async function main(){
  const proj = await gql(`query{ projects{ edges{ node{
    id name
    environments{ edges{ node{ id name } } }
    services{ edges{ node{ id name } } }
  } } } }`);
  out('=== PROJECTS ===');
  out(JSON.stringify(proj?.data?.projects||proj, null, 2).slice(0, 5000));

  const t = await gql(`query($n:String!){ __type(name:$n){ inputFields{ name type{ name kind ofType{ name kind ofType{ name kind } } } } } }`,{n:'ServiceInstanceUpdateInput'});
  out('=== ServiceInstanceUpdateInput ===');
  const fs = t?.data?.__type?.inputFields||[];
  for(const f of fs){ out(`  ${f.name}: ${tn(f.type)}`); }
}
main().catch(e=>{out('FATAL: '+e.message);process.exit(1);});
