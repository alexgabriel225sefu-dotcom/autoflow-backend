const express=require('express');
const cors=require('cors');
const dotenv=require('dotenv');
dotenv.config();
const app=express();
app.use(cors());
app.use(express.json());

app.get('/api/health',(req,res)=>{
  res.json({status:'ok',message:'AutoFlow is running!'});
});

app.post('/api/stripe/create-payment',async(req,res)=>{
  try{
    const stripe=require('stripe')(process.env.STRIPE_SECRET_KEY);
    const{amount,currency,email,name,product}=req.body;
    const pi=await stripe.paymentIntents.create({amount,currency,receipt_email:email,metadata:{name,product}});
    res.json({clientSecret:pi.client_secret});
  }catch(e){res.status(500).json({error:e.message});}
  
});
app.get('/',(req,res)=>{
  res.send('<h1 style="font-family:sans-serif;text-align:center;margin-top:100px;color:#C8A96E">AI Cash Systems — Coming Soon</h1>');
});



const PORT=process.env.PORT||3000;
app.listen(PORT,()=>console.log('AutoFlow on port '+PORT));
