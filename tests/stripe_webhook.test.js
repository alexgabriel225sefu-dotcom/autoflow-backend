'use strict';

process.env.APEX_NO_LISTEN = 'true';
process.env.STRIPE_SECRET_KEY = 'sk_test_unit_only';
process.env.STRIPE_WEBHOOK_SECRET = 'whsec_unit_only';
process.env.SUPABASE_URL = '';
process.env.SUPABASE_SERVICE_KEY = '';

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const crypto = require('node:crypto');
const { app, _internal } = require('../server.js');

const { _processStripeEvent, _resetStripeClaims } = _internal;

function event(overrides = {}) {
  return {
    id: overrides.id || `evt_${Math.random().toString(36).slice(2)}`,
    type: overrides.type || 'checkout.session.completed',
    data: {
      object: {
        id: overrides.sessionId || `cs_${Math.random().toString(36).slice(2)}`,
        status: 'complete',
        payment_status: 'paid',
        amount_total: 49700,
        currency: 'usd',
        payment_intent: overrides.paymentIntentId || 'pi_unit_only',
        metadata: { product: 'apex-forex', ref: 'unit' },
        customer_details: { email: 'buyer@example.com', name: 'Buyer' },
        ...overrides.session,
      },
    },
  };
}

function stripeClient(paymentIntent = { status: 'succeeded', amount: 49700, currency: 'usd' }) {
  let lookups = 0;
  return {
    paymentIntents: {
      retrieve: async () => {
        lookups += 1;
        return paymentIntent;
      },
    },
    get lookups() { return lookups; },
  };
}

async function processWithSpy(input, payment = undefined) {
  const stripe = stripeClient(payment);
  let fulfilled = 0;
  const result = await _processStripeEvent(input, {
    stripeClient: stripe,
    claim: async () => ({ duplicate: false, licenseKey: 'FORX-UNIT-CLAIM' }),
    fulfill: async () => { fulfilled += 1; },
  });
  return { result, fulfilled, lookups: stripe.lookups };
}

function postWebhook(body, signature) {
  return new Promise((resolve, reject) => {
    const server = app.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      const req = http.request({
        host: '127.0.0.1', port, path: '/stripe-webhook', method: 'POST',
        headers: {
          'content-type': 'application/json',
          'content-length': Buffer.byteLength(body),
          ...(signature ? { 'stripe-signature': signature } : {}),
        },
      }, res => {
        let data = '';
        res.setEncoding('utf8');
        res.on('data', chunk => { data += chunk; });
        res.on('end', () => { server.close(); resolve({ status: res.statusCode, data }); });
      });
      req.on('error', error => { server.close(); reject(error); });
      req.end(body);
    });
    server.on('error', reject);
  });
}

function signatureFor(body) {
  const timestamp = Math.floor(Date.now() / 1000);
  const digest = crypto.createHmac('sha256', process.env.STRIPE_WEBHOOK_SECRET)
    .update(`${timestamp}.${body}`, 'utf8').digest('hex');
  return `t=${timestamp},v1=${digest}`;
}

test('unsigned webhook request is rejected with 400', async () => {
  const response = await postWebhook(JSON.stringify(event()), null);
  assert.equal(response.status, 400);
});

test('unpaid or incomplete checkout is not fulfilled', async () => {
  for (const session of [
    { payment_status: 'unpaid' },
    { status: 'open' },
  ]) {
    const out = await processWithSpy(event({ session }));
    assert.equal(out.fulfilled, 0);
    assert.equal(out.lookups, 0);
  }
});

test('wrong amount is not fulfilled', async () => {
  const out = await processWithSpy(event({ session: { amount_total: 100 } }));
  assert.equal(out.fulfilled, 0);
  assert.equal(out.lookups, 0);
});

test('wrong currency is not fulfilled', async () => {
  const out = await processWithSpy(event({ session: { currency: 'eur' } }));
  assert.equal(out.fulfilled, 0);
  assert.equal(out.lookups, 0);
});

test('missing payment_intent is not fulfilled', async () => {
  const out = await processWithSpy(event({ session: { payment_intent: null } }));
  assert.equal(out.fulfilled, 0);
  assert.equal(out.lookups, 0);
});

test('an unsucceeded or mismatched payment intent is not fulfilled', async () => {
  for (const payment of [
    { status: 'requires_payment_method', amount: 49700, currency: 'usd' },
    { status: 'succeeded', amount: 100, currency: 'usd' },
    { status: 'succeeded', amount: 49700, currency: 'eur' },
  ]) {
    const out = await processWithSpy(event(), payment);
    assert.equal(out.fulfilled, 0);
    assert.equal(out.lookups, 1);
  }
});

test('duplicate event claims once and fulfils once', async () => {
  let claims = 0;
  let fulfilled = 0;
  const input = event({ id: 'evt_duplicate', sessionId: 'cs_duplicate', paymentIntentId: 'pi_duplicate' });
  const claim = async () => {
    claims += 1;
    return { duplicate: claims > 1, licenseKey: 'FORX-UNIT-CLAIM' };
  };
  const options = {
    stripeClient: stripeClient(), claim,
    fulfill: async () => { fulfilled += 1; },
  };
  await _processStripeEvent(input, options);
  const second = await _processStripeEvent(input, options);
  assert.equal(claims, 2);
  assert.equal(fulfilled, 1);
  assert.equal(second.duplicate, true);
});

test('happy path retrieves the payment intent and fulfils once', async () => {
  const out = await processWithSpy(event());
  assert.equal(out.result.accepted, true);
  assert.equal(out.fulfilled, 1);
  assert.equal(out.lookups, 1);
});

test('unknown event types are acknowledged without side effects', async () => {
  let claimed = 0;
  let fulfilled = 0;
  const result = await _processStripeEvent(event({ type: 'invoice.created' }), {
    stripeClient: stripeClient(),
    claim: async () => { claimed += 1; return { duplicate: false }; },
    fulfill: async () => { fulfilled += 1; },
  });
  assert.deepEqual(result, { accepted: false, ignored: true });
  assert.equal(claimed, 0);
  assert.equal(fulfilled, 0);
});

test('unknown signed event is acknowledged with 200', async () => {
  const body = JSON.stringify(event({ type: 'invoice.created' }));
  const response = await postWebhook(body, signatureFor(body));
  assert.equal(response.status, 200);
});

test('the durable claim is recorded before the caller can fulfil', async () => {
  _resetStripeClaims();
  const args = {
    sessionId: 'cs_claim', piRef: 'stripe_pi_claim', product: 'apex-forex',
    email: 'buyer@example.com', buyerName: 'Buyer',
  };
  const first = await _internal._claimStripeFulfillment(args);
  const second = await _internal._claimStripeFulfillment(args);
  assert.equal(first.duplicate, false);
  assert.equal(second.duplicate, true);
  _resetStripeClaims();
});

test('a failed fulfilment can be retried without becoming a permanent duplicate', async () => {
  _resetStripeClaims();
  const input = event({ id: 'evt_retry', sessionId: 'cs_retry', paymentIntentId: 'pi_retry' });
  let attempts = 0;
  const options = {
    stripeClient: stripeClient(),
    fulfill: async () => {
      attempts += 1;
      if (attempts === 1) throw new Error('temporary test failure');
    },
  };
  await assert.rejects(() => _processStripeEvent(input, options));
  const second = await _processStripeEvent(input, options);
  assert.equal(second.accepted, true);
  assert.equal(attempts, 2);
  _resetStripeClaims();
});

