const express=require('express');
const cors=require('cors');
const dotenv=require('dotenv');
const jwt=require('jsonwebtoken');
const{v4:uuidv4}=require('uuid');
const{createClient}=require('@supabase/supabase-js');
dotenv.config();

const app=express();
app.use(cors());
app.use('/webhook',express.raw({type:'application/json'}));
app.use(express.json({limit:'10mb'}));

const supabase=createClient(process.env.SUPABASE_URL,process.env.SUPABASE_KEY);
const JWT_SECRET=process.env.JWT_SECRET||'autoflow-secret-2024';

app.get('/',(req,res)=>{
res.sendFile(__dirname+'/public/index.html');
});

app.use(express.static('public'));

app.post('/api/auth/login',async(req,res)=>{
try{
const{email,code}=req.body;
const{data:user}=await supabase.from('users').select('*').eq('email',email.toLowerCase()).eq('code',code.toUpperCase()).single();
if(!user)return res.status(401).json({error:'Invalid email or access code'});
const token=jwt.sign({email:user.email,name:user.name,plan:user.plan},JWT_SECRET,{expiresIn:'30d'});
res.json({token,user:{email:user.email,name:user.name,plan:user.plan}});
}catch(e){res.status(500).json({error:e.message});}
});

function auth(req,res,next){
const a=req.headers.authorization;
if(!a||!a.startsWith('Bearer '))return res.status(401).json({error:'Unauthorized'});
try{req.user=jwt.verify(a.split(' ')[1],JWT_SECRET);next();}
catch(e){res.status(401).json({error:'Invalid token'});}
}

app.post('/api/ai/generate',async(req,res)=>{
try{
const OpenAI=require('openai');
const openai=new OpenAI.OpenAI({apiKey:process.env.OPENAI_API_KEY});
const{prompt,imageBase64}=req.body;
if(!prompt)return res.status(400).json({error:'No prompt provided'});
let messages;
if(imageBase64){
messages=[
{role:'system',content:'You are AutoFlow AI Assistant, expert in AI automation, Make.com, webhooks, WhatsApp bots, Instagram automation, cold email, and building automation agencies. Always respond in the same language the user writes in. When analyzing images, provide clear step-by-step instructions.'},
{role:'user',content:[{type:'image_url',image_url:{url:'data:image/jpeg;base64,'+imageBase64}},{type:'text',text:prompt}]}
];
}else{
messages=[
{role:'system',content:'You are AutoFlow AI Assistant, expert in AI automation, Make.com, webhooks, WhatsApp bots, Instagram automation, cold email, and building automation agencies. Always respond in the same language the user writes in. Be helpful, concise and practical.'},
{role:'user',content:prompt}
];
}
const r=await openai.chat.completions.create({model:'gpt-4o',messages,max_tokens:4000});
const output=r.choices[0].message.content;
res.json({output});
}catch(e){
console.log('AI error:',e.message);
res.status(500).json({error:e.message});
}
});

app.post('/api/email/send',auth,async(req,res)=>{
try{
const nodemailer=require('nodemailer');
const{to,subject,body,fromName}=req.body;
if(!to||!subject||!body)return res.status(400).json({error:'Missing fields'});
const t=nodemailer.createTransport({service:'gmail',auth:{user:process.env.GMAIL_USER,pass:process.env.GMAIL_APP_PASSWORD}});
await t.sendMail({from:'"'+(fromName||'AutoFlow')+'" <'+process.env.GMAIL_USER+'>',to,subject,html:'<div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:32px;">'+body+'</div>'});
await supabase.from('logs').insert({user_email:req.user.email,type:'email',status:'success',msg:'Email sent to '+to+': '+subject});
res.json({success:true});
}catch(e){res.status(500).json({error:e.message});}
});

app.post('/api/webhooks/create',auth,async(req,res)=>{
try{
const{name}=req.body;
const webhookId=uuidv4().split('-')[0];
const url='https://autoflow-backend-p9pc.onrender.com/webhook/receive/'+webhookId;
const{data}=await supabase.from('webhooks').insert({user_email:req.user.email,name:name||'Custom Webhook',webhook_id:webhookId,hits:0}).select().single();
res.json({id:webhookId,name:data.name,url,hits:0,active:true});
}catch(e){res.status(500).json({error:e.message});}
});

app.get('/api/webhooks',auth,async(req,res)=>{
try{
const{data}=await supabase.from('webhooks').select('*').eq('user_email',req.user.email).order('created_at',{ascending:false});
const webhooks=(data||[]).map(w=>({
id:w.webhook_id,name:w.name,
url:'https://autoflow-backend-p9pc.onrender.com/webhook/receive/'+w.webhook_id,
hits:w.hits,lastHit:w.last_hit,active:true
}));
res.json(webhooks);
}catch(e){res.status(500).json({error:e.message});}
});

app.post('/webhook/receive/:id',express.json(),async(req,res)=>{
try{
const{id}=req.params;
const{data:wh}=await supabase.from('webhooks').select('*').eq('webhook_id',id).single();
if(wh){
await supabase.from('webhooks').update({hits:wh.hits+1,last_hit:new Date().toISOString()}).eq('webhook_id',id);
await supabase.from('logs').insert({user_email:wh.user_email,type:'webhook',status:'success',msg:'Webhook "'+wh.name+'" received: '+JSON.stringify(req.body).substring(0,80)});
}
res.json({received:true,id,timestamp:new Date().toISOString()});
}catch(e){res.json({received:true});}
});

app.get('/api/logs',auth,async(req,res)=>{
try{
const{data}=await supabase.from('logs').select('*').eq('user_email',req.user.email).order('created_at',{ascending:false}).limit(50);
const logs=(data||[]).map(l=>({time:l.created_at,type:l.type,status:l.status,msg:l.msg}));
res.json(logs);
}catch(e){res.json([]);}
});

app.get('/api/health',(req,res)=>{res.json({status:'ok',message:'AutoFlow running!'});});

app.post('/create-payment-intent',async(req,res)=>{
try{
const stripe=require('stripe')(process.env.STRIPE_SECRET_KEY);
const{amount,currency,email,name,product}=req.body;
const pi=await stripe.paymentIntents.create({amount,currency,receipt_email:email,metadata:{name,product,email}});
res.json({clientSecret:pi.client_secret});
}catch(e){res.status(500).json({error:e.message});}
});

app.post('/webhook',async(req,res)=>{
const stripe=require('stripe')(process.env.STRIPE_SECRET_KEY);
const sig=req.headers['stripe-signature'];
let event;
try{event=stripe.webhooks.constructEvent(req.body,sig,process.env.STRIPE_WEBHOOK_SECRET);}
catch(e){return res.status(400).send('Webhook Error: '+e.message);}
if(event.type==='payment_intent.succeeded'){
const pi=event.data.object;
const email=pi.metadata.email;
const name=pi.metadata.name;
const product=pi.metadata.product;
if(email){
const emailLower=email.toLowerCase();
const{data:existing}=await supabase.from('users').select('*').eq('email',emailLower).single();
if(!existing){
const uniqueCode=uuidv4().replace(/-/g,'').substring(0,8).toUpperCase();
await supabase.from('users').insert({email:emailLower,code:uniqueCode,name:name||email,plan:product==='pro'?'pro':'starter',product});
await sendCourseEmail(email,name,product,uniqueCode);
}else{
await sendCourseEmail(email,name,product,existing.code);
}
}
}
res.json({received:true});
});

async function sendCourseEmail(email,name,product,accessCode){
const nodemailer=require('nodemailer');
const t=nodemailer.createTransport({service:'gmail',auth:{user:process.env.GMAIL_USER,pass:process.env.GMAIL_APP_PASSWORD}});
const isStarter=product==='starter';
const courseUrl=isStarter?'https://autoflow-backend-p9pc.onrender.com/course-starter.html':'https://autoflow-backend-p9pc.onrender.com/course-pro.html';
const appUrl='https://autoflow-backend-p9pc.onrender.com/app.html';
const subject=isStarter?'Your AI Cash Systems Starter Course — Access Inside':'Your AI Cash Systems PRO Course + AutoFlow App — Access Inside';
const html='<div style="background:#080808;padding:40px;font-family:sans-serif;max-width:560px;margin:0 auto;">'
+'<div style="font-family:Georgia,serif;font-size:24px;color:#C8A96E;margin-bottom:8px;">AI Cash Systems</div>'
+'<div style="height:1px;background:rgba(200,169,110,0.2);margin-bottom:32px;"></div>'
+'<p style="color:#F5F0E8;font-size:18px;margin-bottom:8px;">Welcome, '+name+'! 🎉</p>'
+'<p style="color:#C8BEA8;font-size:14px;line-height:1.7;margin-bottom:24px;">Your payment was successful. You now have lifetime access to '+(isStarter?'the AI Cash Systems Starter Course':'the AI Cash Systems PRO Course + AutoFlow App')+'.</p>'
+'<div style="background:#161616;border:1px solid rgba(200,169,110,0.2);border-radius:12px;padding:24px;margin-bottom:16px;">'
+'<p style="color:#C8A96E;font-size:12px;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px;">Your Course Access</p>'
+'<a href="'+courseUrl+'" style="display:block;padding:14px 24px;background:linear-gradient(135deg,#8A6A2E,#E8CB8A);border-radius:8px;color:#080808;font-weight:700;text-decoration:none;text-align:center;font-size:14px;letter-spacing:1px;text-transform:uppercase;">Access Your Course →</a>'
+'</div>'
+(isStarter?''
:'<div style="background:#161616;border:1px solid rgba(200,169,110,0.2);border-radius:12px;padding:24px;margin-bottom:16px;">'
+'<p style="color:#C8A96E;font-size:12px;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px;">AutoFlow App Access</p>'
+'<p style="color:#C8BEA8;font-size:13px;margin-bottom:6px;">Login at: <strong style="color:#F5F0E8;">'+appUrl+'</strong></p>'
+'<p style="color:#C8BEA8;font-size:13px;">Email: <strong style="color:#F5F0E8;">'+email+'</strong></p>'
+'<p style="color:#C8BEA8;font-size:13px;">Your Unique Code: <strong style="color:#C8A96E;font-size:20px;letter-spacing:2px;">'+accessCode+'</strong></p>'
+'<p style="color:#7A7060;font-size:11px;margin-top:8px;">⚠️ Keep this code private — it is unique to your account.</p>'
+'</div>')
+'<p style="color:#7A7060;font-size:12px;line-height:1.6;">Questions? <a href="mailto:support@aicashsystems.com" style="color:#C8A96E;">support@aicashsystems.com</a><br>© 2025 AI Cash Systems.</p>'
+'</div>';
await t.sendMail({from:'"AI Cash Systems" <'+process.env.GMAIL_USER+'>',to:email,subject,html});
}

const PORT=process.env.PORT||3000;
app.listen(PORT,()=>console.log('AutoFlow running on port '+PORT));
