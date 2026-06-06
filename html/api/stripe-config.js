module.exports = (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.json({ pk: process.env.STRIPE_PUBLISHABLE_KEY || '' });
};
