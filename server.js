const express=require('express');
const cors=require('cors');
const dotenv=require('dotenv');
const jwt=require('jsonwebtoken');
const{v4:uuidv4}=require('uuid');
dotenv.config();
const app=express();
app.use(cors());
app.use(express.static('public'));
app.use('/webhook',express.raw({type:'application/json'}));
app.use(express.json());

const users={};
const webhookLogs={};
const userWebhooks={};
const JWT_SECRET=process.env.JWT_SECRET||'autoflow-secret-2024';

users['alexgabriel225sefu@gmail.com']={email:'alexgabriel225sefu@gmail.com',code:'AF2024PRO',name:'Alex Gabriel',plan:'pro'};

app.post('/api/auth/login',(req,res)=>{
try{
const{email,code}=req.body;
const user=users[email.toLowerCase()];
if(!user||user.code!==code.toUpperCase())return res.status(401).json({error:'Invalid email or access code'});
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
const{prompt}=req.body;
if(!prompt)return res.status(400).json({error:'No prompt provided'});
console.log('AI request received:',prompt.substring(0,50));
const r=await openai.chat.completions.create({model:'gpt-4o',messages:[{role:'system',content:'You are AutoFlow AI Assistant, expert in AI automation, Make.com, webhooks, GPT integrations. Be helpful and practical.'},{role:'user',content:prompt}],max_tokens:600});
const output=r.choices[0].message.content;
console.log('AI response sent successfully');
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
await t.sendMail({from:`"${fromName||'AutoFlow'}" <${process.env.GMAIL_USER}>`,to,subject,html:`<div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:32px;">${body}</div>`});
if(!webhookLogs[req.user.email])webhookLogs[req.user.email]=[];
webhookLogs[req.user.email].unshift({time:new Date().toISOString(),type:'email',status:'success',msg:`Email sent to ${to}: ${subject}`});
res.json({success:true});
}catch(e){res.status(500).json({error:e.message});}
});

app.post('/api/webhooks/create',auth,(req,res)=>{
const{name}=req.body;
const id=uuidv4().split('-')[0];
const webhook={id,name:name||'Custom Webhook',url:`https://autoflow-backend-p9pc.onrender.com/webhook/receive/${id}`,active:true,hits:0,createdAt:new Date().toISOString()};
if(!userWebhooks[req.user.email])userWebhooks[req.user.email]=[];
userWebhooks[req.user.email].push(webhook);
res.json(webhook);
});

app.get('/api/webhooks',auth,(req,res)=>{
res.json(userWebhooks[req.user.email]||[]);
});

app.post('/webhook/receive/:id',express.json(),(req,res)=>{
const{id}=req.params;
for(const email in userWebhooks){
const wh=userWebhooks[email].find(w=>w.id===id);
if(wh){
wh.hits++;wh.lastHit=new Date().toISOString();wh.lastPayload=req.body;
if(!webhookLogs[email])webhookLogs[email]=[];
webhookLogs[email].unshift({time:new Date().toISOString(),type:'webhook',status:'success',msg:`Webhook "${wh.name}" received: ${JSON.stringify(req.body).substring(0,80)}`});
break;
}
}
res.json({received:true,id,timestamp:new Date().toISOString()});
});

app.get('/api/logs',auth,(req,res)=>{
res.json((webhookLogs[req.user.email]||[]).slice(0,50));
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
if(email&&!users[email.toLowerCase()]){
const code=uuidv4().split('-')[0].toUpperCase();
users[email.toLowerCase()]={email:email.toLowerCase(),code,name:name||email,plan:product==='pro'?'pro':'starter'};
}
await sendCourseEmail(email,name,product);
}
res.json({received:true});
});

async function sendCourseEmail(email,name,product){
const nodemailer=require('nodemailer');
const t=nodemailer.createTransport({service:'gmail',auth:{user:process.env.GMAIL_USER,pass:process.env.GMAIL_APP_PASSWORD}});
const isStarter=product==='starter';
const user=users[email.toLowerCase()];
const accessCode=user?user.code:'AF2024PRO';
const courseUrl=isStarter?'https://autoflow-backend-p9pc.onrender.com/course-starter.html':'https://autoflow-backend-p9pc.onrender.com/course-pro.html';
const subject=isStarter?'Your AI Cash Systems Starter Course — Access Inside':'Your AI Cash Systems PRO Course + AutoFlow App — Access Inside';
const html=`<div style="background:#080808;padding:40px;font-family:sans-serif;max-width:560px;margin:0 auto;"><div style="font-family:Georgia,serif;font-size:24px;color:#C8A96E;margin-bottom:8px;">AI Cash Systems</div><div style="height:1px;background:rgba(200,169,110,0.2);margin-bottom:32px;"></div><p style="color:#F5F0E8;font-size:18px;margin-bottom:8px;">Welcome, ${name}! 🎉</p><p style="color:#C8BEA8;font-size:14px;line-height:1.7;margin-bottom:24px;">Your payment was successful. You now have lifetime access to ${isStarter?'the AI Cash Systems Starter Course':'the AI Cash Systems PRO Course + AutoFlow App'}.</p><div style="background:#161616;border:1px solid rgba(200,169,110,0.2);border-radius:12px;padding:24px;margin-bottom:24px;"><p style="color:#C8A96E;font-size:12px;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px;">Your Access Link</p><a href="${courseUrl}" style="display:block;padding:14px 24px;background:linear-gradient(135deg,#8A6A2E,#E8CB8A);border-radius:8px;color:#080808;font-weight:700;text-decoration:none;text-align:center;font-size:14px;letter-spacing:1px;text-transform:uppercase;">Access Your Course →</a></div>${!isStarter?`<div style="background:#161616;border:1px solid rgba(200,169,110,0.2);border-radius:12px;padding:24px;margin-bottom:24px;"><p style="color:#C8A96E;font-size:12px;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">AutoFlow App Access</p><p style="color:#C8BEA8;font-size:13px;margin-bottom:8px;">Login at: <strong style="color:#F5F0E8;">https://autoflow-backend-p9pc.onrender.com/app.html</strong></p><p style="color:#C8BEA8;font-size:13px;">Your Access Code: <strong style="color:#C8A96E;font-size:18px;">${accessCode}</strong></p></div>`:''}<p style="color:#7A7060;font-size:12px;line-height:1.6;">Questions? <a href="mailto:support@aicashsystems.com" style="color:#C8A96E;">support@aicashsystems.com</a><br>© 2025 AI Cash Systems.</p></div>`;
await t.sendMail({from:'"AI Cash Systems" <'+process.env.GMAIL_USER+'>',to:email,subject,html});
}

const PORT=process.env.PORT||3000;
app.listen(PORT,()=>console.log('AutoFlow server running on port '+PORT));
