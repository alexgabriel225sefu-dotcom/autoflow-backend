const express=require('express');
const stripe=require('stripe')(process.env.STRIPE_SECRET_KEY);
const path=require('path');
const app=express();
app.use(express.json());
app.use(express.static(path.join(__dirname,'public')));
app.get('/health',(req,res)=>res.json({status:'ok'}));
app.post('/create-payment-intent',async(req,res)=>{
try{
const{amount,currency='usd',name,email,product}=req.body;
if(!amount||!email)return res.status(400).json({error:'Missing data'});
const pi=await stripe.paymentIntents.create({amount,currency,receipt_email:email,metadata:{name,email,product}});
res.json({clientSecret:pi.client_secret});
}catch(err){
console.error(err.message);
res.status(500).json({error:err.message});
}
});
app.get('*',(req,res)=>res.sendFile(path.join(__dirname,'public','index.html')));
const PORT=process.env.PORT||3000;
app.listen(PORT,()=>console.log('Server running on port '+PORT));
