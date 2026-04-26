const express=require('express');
const cors=require('cors');
const dotenv=require('dotenv');
dotenv.config();
const app=express();
app.use(cors());
app.use(express.static('public'));
app.use('/webhook',express.raw({type:'application/json'}));
app.use(express.json());

app.get('/api/health',(req,res)=>{res.json({status:'ok'});});

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
await sendCourseEmail(email,name,product);
}
res.json({received:true});
});

async function sendCourseEmail(email,name,product){
const nodemailer=require('nodemailer');
const transporter=nodemailer.createTransport({service:'gmail',auth:{user:process.env.GMAIL_USER,pass:process.env.GMAIL_APP_PASSWORD}});
const isStarter=product==='starter';
const courseUrl=isStarter
?'https://autoflow-backend-p9pc.onrender.com/course-starter.html'
:'https://autoflow-backend-p9pc.onrender.com/course-pro.html';
const subject=isStarter
?'Your AI Cash Systems Starter Course — Access Inside'
:'Your AI Cash Systems PRO Course + AutoFlow App — Access Inside';
const html=`
<div style="background:#080808;padding:40px;font-family:sans-serif;max-width:560px;margin:0 auto;">
<div style="font-family:Georgia,serif;font-size:24px;color:#C8A96E;margin-bottom:8px;">AI Cash Systems</div>
<div style="height:1px;background:rgba(200,169,110,0.2);margin-bottom:32px;"></div>
<p style="color:#F5F0E8;font-size:18px;margin-bottom:8px;">Welcome, ${name}! 🎉</p>
<p style="color:#C8BEA8;font-size:14px;line-height:1.7;margin-bottom:24px;">
Your payment was successful. You now have lifetime access to ${isStarter?'the AI Cash Systems Starter Course':'the AI Cash Systems PRO Course + AutoFlow App'}.
</p>
<div style="background:#161616;border:1px solid rgba(200,169,110,0.2);border-radius:12px;padding:24px;margin-bottom:24px;">
<p style="color:#C8A96E;font-size:12px;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px;">Your Access Link</p>
<a href="${courseUrl}" style="display:block;padding:14px 24px;background:linear-gradient(135deg,#8A6A2E,#E8CB8A);border-radius:8px;color:#080808;font-weight:700;text-decoration:none;text-align:center;font-size:14px;letter-spacing:1px;text-transform:uppercase;">
Access Your Course →
</a>
</div>
${!isStarter?`<div style="background:#161616;border:1px solid rgba(200,169,110,0.2);border-radius:12px;padding:24px;margin-bottom:24px;">
<p style="color:#C8A96E;font-size:12px;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">AutoFlow App Access</p>
<p style="color:#C8BEA8;font-size:13px;margin-bottom:8px;">Login at: <strong style="color:#F5F0E8;">https://autoflow-backend-p9pc.onrender.com/app.html</strong></p>
<p style="color:#C8BEA8;font-size:13px;">Access Code: <strong style="color:#C8A96E;font-size:16px;">AF2024PRO</strong></p>
</div>`:''}
<p style="color:#7A7060;font-size:12px;line-height:1.6;">
Questions? Email us at <a href="mailto:support@aicashsystems.com" style="color:#C8A96E;">support@aicashsystems.com</a><br>
© 2025 AI Cash Systems. All rights reserved.
</p>
</div>
`;
await transporter.sendMail({from:'"AI Cash Systems" <'+process.env.GMAIL_USER+'>',to:email,subject,html});
}

const PORT=process.env.PORT||3000;
app.listen(PORT,()=>console.log('Server running on port '+PORT));
