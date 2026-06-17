// Introspect Railway GraphQL Mutation for template-related operations + their inputs.
// Env: RAILWAY_TOKEN (required)
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
async function main(){
  const mut = await gql(`query{ __type(name:"Mutation"){ fields{ name args{ name type{ name kind ofType{ name kind } } } } } }`);
  const fields = (mut?.data?.__type?.fields||[]).filter(f=>/template/i.test(f.name));
  out('=== TEMPLATE MUTATIONS ===');
  for(const f of fields){
    const args = f.args.map(a=>{
      const t=a.type; const tn=t.name||t.ofType?.name||t.kind; return `${a.name}:${tn}`;
    }).join(', ');
    out(`- ${f.name}(${args})`);
  }
  out('');
  for(const n of ['TemplateGenerateInput','TemplateCloneInput','TemplateServiceCreateInput','TemplatePublishInput']){
    const t = await inputFields(n);
    out(`=== ${n} ===`);
    if(t&&t.inputFields){ for(const f of t.inputFields){ const tn=f.type.name||f.type.ofType?.name||f.type.kind; out(`  ${f.name}: ${tn}`);} }
    else out('  (not found)');
  }
}
main().catch(e=>{out('FATAL: '+e.message);process.exit(1);});
