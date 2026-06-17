// Introspect inputs needed to create a project + service (docker image) + variables.
const API = 'https://backboard.railway.com/graphql/v2';
const TOKEN = process.env.RAILWAY_TOKEN;
const SUMMARY_FILE = process.env.GITHUB_STEP_SUMMARY;
if (!TOKEN) { console.error('RAILWAY_TOKEN missing'); process.exit(1); }
function out(m){ console.log(m); if (SUMMARY_FILE) require('fs').appendFileSync(SUMMARY_FILE, m+'\n'); }
async function gql(query, variables){
  const r = await fetch(API,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${TOKEN}`},body:JSON.stringify({query,variables})});
  const t = await r.text(); try{return JSON.parse(t);}catch{return {parseError:t.slice(0,3000)};}
}
async function inputFields(name){
  const res = await gql(`query($n:String!){ __type(name:$n){ name inputFields{ name type{ name kind ofType{ name kind ofType{ name kind } } } } } }`,{n:name});
  return res?.data?.__type;
}
function tn(t){ return t.name || t.ofType?.name || t.ofType?.ofType?.name || t.kind; }
async function main(){
  // who am I / workspaces
  const me = await gql(`query{ me{ id email workspaces{ id name } } }`);
  out('=== ME ===');
  out(JSON.stringify(me?.data?.me||me, null, 2).slice(0,2000));

  const mut = await gql(`query{ __type(name:"Mutation"){ fields{ name args{ name type{ name kind ofType{ name kind } } } } } }`);
  const fields = (mut?.data?.__type?.fields||[]).filter(f=>/^(projectCreate|serviceCreate|serviceInstanceUpdate|serviceInstanceDeploy|variableUpsert|variableCollectionUpsert|deploymentRedeploy|environmentCreate)$/i.test(f.name));
  out('');
  out('=== KEY MUTATIONS ===');
  for(const f of fields){
    out(`- ${f.name}(${f.args.map(a=>`${a.name}:${tn(a.type)}`).join(', ')})`);
  }
  out('');
  for(const n of ['ProjectCreateInput','ServiceCreateInput','ServiceSourceInput','VariableUpsertInput','VariableCollectionUpsertInput']){
    const t = await inputFields(n);
    out(`=== ${n} ===`);
    if(t&&t.inputFields){ for(const f of t.inputFields){ out(`  ${f.name}: ${tn(f.type)}`);} }
    else out('  (not found)');
  }
}
main().catch(e=>{out('FATAL: '+e.message);process.exit(1);});
