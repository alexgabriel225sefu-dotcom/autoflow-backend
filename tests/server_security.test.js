/**
 * Licence, session, configuration-crypto, SSRF and owner-secret checks.
 *
 * Findings pinned here:
 *
 *   LICENCE ENTROPY   keys carried 8 characters of randomness. That looked
 *                     like 64 bits because it started from randomBytes(8),
 *                     but `b % 32` keeps five bits per byte — so 40 bits.
 *
 *   LICENCE AS BEARER /api/bot-config?key=LICENSE_KEY used a permanent,
 *                     emailed, never-expiring credential as the authorisation
 *                     for reading stored broker configuration, in a query
 *                     string where every proxy log could see it.
 *
 *   UNAUTHENTICATED   configuration was sealed with AES-256-CBC, which
 *   CIPHERTEXT        encrypts but does not authenticate.
 *
 *   SSRF              the callback guard compared the hostname STRING against
 *                     private prefixes, which every numeric encoding of
 *                     127.0.0.1 walks straight past.
 *
 *   OWNER SECRET      ten routes took ?secret=<BOT_EMAIL_SECRET> — the value
 *                     the licence-signing key is derived from.
 *
 * Run: npm test
 */
'use strict';

process.env.APEX_NO_LISTEN = 'true';
process.env.JWT_SECRET = process.env.JWT_SECRET || 'test-jwt-secret-0123456789abcdef0123';
process.env.BOT_EMAIL_SECRET = process.env.BOT_EMAIL_SECRET || 'test-bot-email-secret-0123456789';

const test = require('node:test');
const assert = require('node:assert');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const { _internal } = require('../server.js');
const {
  generateForexKey, verifyLicenseKeyHmac,
  encryptBotConfig, decryptBotConfig,
  _issueBotSession, _botSession, _revokeBotSessionsFor,
  assertPublicHttpUrl, _isPublicIp,
  _ownerSecretOk,
} = _internal;

const KEY_ALPHABET = 32;               // A-Z minus O/I, 2-9
const BITS_PER_CHAR = Math.log2(KEY_ALPHABET);

const SERVER_PATH = path.join(__dirname, '..', 'server.js');
const rawSource = () => fs.readFileSync(SERVER_PATH, 'utf8');

// Source with comments removed. Scanning raw text finds the words in the
// comment that EXPLAINS a removal — which is how a check like this quietly
// starts asserting on its own documentation.
const serverCode = () =>
  rawSource().replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

// ── Licence key entropy ────────────────────────────────────────────────
test('a licence key carries at least 128 bits of randomness', () => {
  const body = generateForexKey().split('-').slice(1).join('');
  const randomChars = body.length - 4;             // last 4 are the checksum
  const bits = randomChars * BITS_PER_CHAR;
  assert.ok(bits >= 128, `only ${bits} bits of entropy (${randomChars} chars)`);
});

test('keys are drawn from the CSPRNG, not from time or a counter', () => {
  // Two keys minted in the same millisecond must not share a prefix. A
  // timestamp-derived key does; a counter-derived key does; randomBytes does not.
  const a = generateForexKey().split('-').slice(1).join('');
  const b = generateForexKey().split('-').slice(1).join('');
  assert.notStrictEqual(a, b);
  let shared = 0;
  while (shared < a.length && a[shared] === b[shared]) shared++;
  assert.ok(shared < 6, `two keys shared a ${shared}-character prefix`);
});

test('50,000 keys collide zero times and use the whole alphabet', () => {
  const seen = new Set(), symbols = new Set();
  for (let i = 0; i < 50000; i++) {
    const k = generateForexKey();
    seen.add(k);
    for (const c of k.split('-').slice(1).join('')) symbols.add(c);
  }
  assert.strictEqual(seen.size, 50000, 'a collision occurred');
  assert.strictEqual(symbols.size, KEY_ALPHABET, `only ${symbols.size} symbols appear`);
});

test('symbol distribution is unbiased (256 % 32 === 0)', () => {
  const counts = new Map();
  let total = 0;
  for (let i = 0; i < 4000; i++) {
    for (const c of generateForexKey().split('-').slice(1).join('').slice(0, 26)) {
      counts.set(c, (counts.get(c) || 0) + 1);
      total++;
    }
  }
  const expected = total / KEY_ALPHABET;
  for (const [sym, n] of counts) {
    const drift = Math.abs(n - expected) / expected;
    assert.ok(drift < 0.15, `symbol ${sym} is ${(drift * 100).toFixed(1)}% off uniform`);
  }
});

test('a minted key verifies, and tampering with any character does not', () => {
  const key = generateForexKey();
  assert.strictEqual(verifyLicenseKeyHmac(key).valid, true);
  assert.strictEqual(verifyLicenseKeyHmac(key).legacy, false);
  const chars = [...key];
  for (let i = 0; i < chars.length; i++) {
    if (chars[i] === '-') continue;
    const swapped = [...chars];
    swapped[i] = swapped[i] === 'A' ? 'B' : 'A';
    assert.strictEqual(verifyLicenseKeyHmac(swapped.join('')).valid, false,
      `a key with position ${i} altered still verified`);
  }
});

test('garbage, empty and injection-shaped keys are refused', () => {
  for (const bad of ['', null, undefined, 'FORX', 'FORX-', 'nope',
                     'FORX-AAAA-AAAA-AAAA', 'FORX-' + 'A'.repeat(200),
                     "FORX-' OR 1=1--", 'FORX-AAAAA-AAAAA-AAAAA-AAAAA-AAAAA-AAAAA',
                     {}, [], 12345]) {
    assert.strictEqual(verifyLicenseKeyHmac(bad).valid, false,
      `${JSON.stringify(bad)} was accepted`);
  }
});

test('legacy 12-character keys still verify, and are reported as legacy', () => {
  // Rebuild an old-format key with the same secret the server uses, so
  // customers holding one are not locked out by the entropy change.
  const CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const secret = `${process.env.BOT_EMAIL_SECRET}-apex-forex`;
  const rnd8 = Array.from(crypto.randomBytes(8)).map(b => CHARS[b % 32]).join('');
  const mac = crypto.createHmac('sha256', secret).update(rnd8).digest();
  const mac4 = [0, 1, 2, 3].map(i => CHARS[mac[i] % 32]).join('');
  const full = rnd8 + mac4;
  const legacyKey = `FORX-${full.slice(0, 4)}-${full.slice(4, 8)}-${full.slice(8, 12)}`;
  const r = verifyLicenseKeyHmac(legacyKey);
  assert.strictEqual(r.valid, true, 'an already-issued key stopped working');
  assert.strictEqual(r.legacy, true, 'a legacy key was not flagged as legacy');
});

// ── Bot sessions ───────────────────────────────────────────────────────
function fakeReq(authHeader) {
  return { get: (h) => (h.toLowerCase() === 'authorization' ? authHeader : undefined) };
}

test('a bot session token is opaque and unguessable', () => {
  const t = _issueBotSession('FORX-TEST', 'apex-forex');
  assert.ok(t.length >= 43, `token is only ${t.length} characters`);
  assert.ok(!t.includes('FORX'), 'the token contains the licence key');
  const tokens = new Set();
  for (let i = 0; i < 5000; i++) tokens.add(_issueBotSession('FORX-TEST', 'apex-forex'));
  assert.strictEqual(tokens.size, 5000, 'token collision');
  _revokeBotSessionsFor('FORX-TEST');
});

test('a valid token authenticates only with the right scope', () => {
  const t = _issueBotSession('FORX-SCOPE', 'apex-forex');
  assert.ok(_botSession(fakeReq(`Bearer ${t}`), 'bot:config:read'));
  assert.strictEqual(_botSession(fakeReq(`Bearer ${t}`), 'admin'), null,
    'a config-read token satisfied an admin scope');
  assert.strictEqual(_botSession(fakeReq(`Bearer ${t}`), 'licence:manage'), null);
  _revokeBotSessionsFor('FORX-SCOPE');
});

test('missing, malformed and wrong tokens are refused', () => {
  const t = _issueBotSession('FORX-BAD', 'apex-forex');
  for (const h of [undefined, '', 'Bearer', 'Bearer ', 'Basic ' + t, t,
                   'Bearer wrong', `Bearer ${t}x`, `Bearer ${t.slice(0, -1)}`]) {
    assert.strictEqual(_botSession(fakeReq(h), 'bot:config:read'), null,
      `header ${JSON.stringify(h)} authenticated`);
  }
  _revokeBotSessionsFor('FORX-BAD');
});

test('an expired token is refused, and a revoked one cannot be reused', () => {
  const t = _issueBotSession('FORX-EXP', 'apex-forex');
  const sess = _botSession(fakeReq(`Bearer ${t}`), 'bot:config:read');
  assert.ok(sess);
  assert.ok(sess.exp - Date.now() <= _internal.BOT_SESSION_TTL_MS,
    'token lifetime exceeds the configured TTL');
  assert.ok(_internal.BOT_SESSION_TTL_MS <= 15 * 60 * 1000,
    'a bot session lives longer than 15 minutes');
  sess.exp = Date.now() - 1;
  assert.strictEqual(_botSession(fakeReq(`Bearer ${t}`), 'bot:config:read'), null,
    'an expired token still authenticated');

  const t2 = _issueBotSession('FORX-REV', 'apex-forex');
  assert.ok(_botSession(fakeReq(`Bearer ${t2}`), 'bot:config:read'));
  _revokeBotSessionsFor('FORX-REV');
  assert.strictEqual(_botSession(fakeReq(`Bearer ${t2}`), 'bot:config:read'), null,
    'a revoked token still authenticated');
});

test('one licence cannot reach another licence config', () => {
  const a = _issueBotSession('FORX-AAA', 'apex-forex');
  const b = _issueBotSession('FORX-BBB', 'apex-forex');
  assert.strictEqual(_botSession(fakeReq(`Bearer ${a}`), 'bot:config:read').licenseKey, 'FORX-AAA');
  assert.strictEqual(_botSession(fakeReq(`Bearer ${b}`), 'bot:config:read').licenseKey, 'FORX-BBB');
  _revokeBotSessionsFor('FORX-AAA');
  assert.strictEqual(_botSession(fakeReq(`Bearer ${a}`), 'bot:config:read'), null);
  assert.ok(_botSession(fakeReq(`Bearer ${b}`), 'bot:config:read'), 'revoking one revoked the other');
  _revokeBotSessionsFor('FORX-BBB');
});

test('the licence key is not accepted from the URL any more', () => {
  const code = serverCode();
  assert.match(code, /LICENCE_IN_URL/, 'a key in the URL is not refused');
  assert.ok(!/req\.query\.key\s*\|\|/.test(code), 'a route still falls back to ?key=');
});

// ── Configuration encryption ───────────────────────────────────────────
const SAMPLE = { RISK_PER_TRADE: '0.01', PAPER_TRADING: 'true', CTRADER_ENV: 'demo' };

test('encrypt/decrypt round-trips, and writes the authenticated format', () => {
  const blob = encryptBotConfig(SAMPLE);
  assert.ok(blob.startsWith('v2:'), `wrote a non-v2 record: ${blob.slice(0, 12)}`);
  const out = decryptBotConfig(blob);
  assert.deepStrictEqual(out.config, SAMPLE);
  assert.strictEqual(out.legacy, false);
});

test('every encryption uses a fresh nonce', () => {
  const ivs = new Set();
  for (let i = 0; i < 3000; i++) ivs.add(encryptBotConfig(SAMPLE).split(':')[1]);
  assert.strictEqual(ivs.size, 3000, 'a nonce was reused');
  assert.strictEqual([...ivs][0].length, 24, 'nonce is not 96 bits');
});

test('the same plaintext encrypts differently each time', () => {
  assert.notStrictEqual(encryptBotConfig(SAMPLE), encryptBotConfig(SAMPLE));
});

test('a modified ciphertext is rejected, not silently decrypted', () => {
  const [v, iv, tag, ct] = encryptBotConfig(SAMPLE).split(':');
  const flip = (hex, i) => {
    const b = Buffer.from(hex, 'hex');
    b[i % b.length] ^= 0x01;
    return b.toString('hex');
  };
  // This is the property CBC did not have. Under CBC a flipped byte produced
  // a different plaintext, and the server used it.
  for (let i = 0; i < 8; i++) {
    assert.throws(() => decryptBotConfig([v, iv, tag, flip(ct, i)].join(':')),
      `a ciphertext with byte ${i} flipped decrypted without complaint`);
  }
});

test('a modified nonce is rejected', () => {
  const [v, iv, tag, ct] = encryptBotConfig(SAMPLE).split(':');
  const b = Buffer.from(iv, 'hex'); b[0] ^= 0xff;
  assert.throws(() => decryptBotConfig([v, b.toString('hex'), tag, ct].join(':')));
});

test('a modified or truncated tag is rejected', () => {
  const [v, iv, tag, ct] = encryptBotConfig(SAMPLE).split(':');
  const b = Buffer.from(tag, 'hex'); b[0] ^= 0xff;
  assert.throws(() => decryptBotConfig([v, iv, b.toString('hex'), ct].join(':')));
  assert.throws(() => decryptBotConfig([v, iv, tag.slice(0, 8), ct].join(':')));
  assert.throws(() => decryptBotConfig([v, iv, '', ct].join(':')));
});

test('corrupt and malformed records are rejected', () => {
  for (const bad of ['', 'v2:', 'v2:a:b', 'v2:a:b:c:d', 'nonsense',
                     'v2:zz:zz:zz', ':::', 'v2:' + 'a'.repeat(24) + ':x:y']) {
    assert.throws(() => decryptBotConfig(bad), `${JSON.stringify(bad)} decrypted`);
  }
});

test('a legacy CBC record still reads, and is flagged for migration', () => {
  const key = crypto.createHash('sha256').update(process.env.JWT_SECRET).digest();
  const iv = crypto.randomBytes(16);
  const c = crypto.createCipheriv('aes-256-cbc', key, iv);
  const enc = Buffer.concat([c.update(JSON.stringify(SAMPLE), 'utf8'), c.final()]);
  const out = decryptBotConfig(iv.toString('hex') + ':' + enc.toString('hex'));
  assert.deepStrictEqual(out.config, SAMPLE, 'an existing config stopped decrypting');
  assert.strictEqual(out.legacy, true, 'a CBC record was not flagged as legacy');
  const migrated = encryptBotConfig(out.config);
  assert.ok(migrated.startsWith('v2:'));
  assert.deepStrictEqual(decryptBotConfig(migrated).config, SAMPLE);
});

test('a wrong key does not decrypt', () => {
  const blob = encryptBotConfig(SAMPLE);
  const saved = process.env.JWT_SECRET;
  process.env.JWT_SECRET = 'a-completely-different-secret-value-01';
  try {
    assert.throws(() => decryptBotConfig(blob), 'decrypted under the wrong key');
  } finally { process.env.JWT_SECRET = saved; }
});

// ── SSRF guard ─────────────────────────────────────────────────────────
test('loopback, private and metadata addresses are not public', () => {
  for (const ip of [
    '127.0.0.1', '127.1.2.3', '0.0.0.0', '10.0.0.1', '10.255.255.255',
    '172.16.0.1', '172.31.255.255', '192.168.1.1', '192.0.0.1',
    '169.254.169.254',            // AWS/GCP/Azure instance metadata
    '100.64.0.1', '100.127.0.1',  // CGNAT
    '224.0.0.1', '255.255.255.255',
    '::1', '::', 'fe80::1', 'fd00::1', 'fc00::1', 'ff02::1',
    '::ffff:127.0.0.1', '::ffff:169.254.169.254',
  ]) {
    assert.strictEqual(_isPublicIp(ip), false, `${ip} was treated as public`);
  }
});

test('ordinary public addresses still are', () => {
  for (const ip of ['8.8.8.8', '1.1.1.1', '93.184.216.34', '172.32.0.1',
                    '172.15.0.1', '100.63.255.255', '100.128.0.1',
                    '2606:4700:4700::1111']) {
    assert.strictEqual(_isPublicIp(ip), true, `${ip} was treated as private`);
  }
});

test('a callback URL cannot reach the loopback, however it is spelled', async () => {
  for (const url of [
    'http://127.0.0.1/x', 'http://localhost/x', 'http://[::1]/x',
    'http://[::ffff:127.0.0.1]/x',
    'http://2130706433/x',          // 127.0.0.1 as a decimal integer
    'http://0177.0.0.1/x',          // octal
    'http://0x7f.0.0.1/x',          // hex
    'http://127.1/x',               // short form
    'http://169.254.169.254/latest/meta-data/',
    'http://[fd00::1]/x', 'http://10.0.0.1/x',
    'http://192.168.0.1/x', 'http://172.20.0.1/x',
  ]) {
    await assert.rejects(() => assertPublicHttpUrl(url), `${url} was allowed`);
  }
});

test('non-http schemes and embedded credentials are refused', async () => {
  for (const url of ['file:///etc/passwd', 'gopher://x/', 'ftp://x/',
                     'data:text/plain,hi', 'not a url', '', null,
                     'http://user:pass@example.com/']) {
    await assert.rejects(() => assertPublicHttpUrl(url), `${url} was allowed`);
  }
});

test('a genuine public URL is allowed', async () => {
  const u = await assertPublicHttpUrl('https://example.com/hook');
  assert.strictEqual(u.hostname, 'example.com');
});

test('the callback fetch refuses to follow a redirect', () => {
  // A guard that checks the URL and then follows a 302 to 127.0.0.1 has
  // checked nothing.
  const src = rawSource();
  const idx = src.indexOf('assertPublicHttpUrl(automation.config.callback_url)');
  assert.ok(idx > 0, 'the callback site does not use the guard');
  assert.match(src.slice(idx, idx + 500), /redirect:\s*'error'/,
    'the callback fetch follows redirects');
});

// ── Owner-secret gate ──────────────────────────────────────────────────
const ownerReq = ({ query = {}, headers = {} } = {}) => ({ query, headers });

test('the owner secret is accepted from a header and refused from a URL', () => {
  const S = process.env.BOT_EMAIL_SECRET;
  assert.strictEqual(_ownerSecretOk(ownerReq({ headers: { 'x-owner-secret': S } })), true);
  // The same correct secret, in the URL, must NOT authenticate: the request
  // has already written it into whatever log sits in front of this service.
  assert.strictEqual(_ownerSecretOk(ownerReq({ query: { secret: S } })), false);
  // …and it must not be rescued by also sending the header.
  assert.strictEqual(
    _ownerSecretOk(ownerReq({ query: { secret: S }, headers: { 'x-owner-secret': S } })),
    false, 'a URL secret was tolerated because the header was also present');
});

test('wrong, empty and near-miss owner secrets are refused', () => {
  const S = process.env.BOT_EMAIL_SECRET;
  for (const v of [undefined, '', 'wrong', S.slice(0, -1), S + 'x', S.toUpperCase(), ' ' + S]) {
    assert.strictEqual(_ownerSecretOk(ownerReq({ headers: { 'x-owner-secret': v } })), false,
      `${JSON.stringify(v)} authenticated`);
  }
});

test('an unset owner secret is a misconfiguration, not permission', () => {
  const saved = process.env.BOT_EMAIL_SECRET;
  delete process.env.BOT_EMAIL_SECRET;
  try {
    assert.strictEqual(_ownerSecretOk(ownerReq({ headers: { 'x-owner-secret': 'anything' } })), false,
      'an unset secret let a request through');
  } finally { process.env.BOT_EMAIL_SECRET = saved; }
});

test('no route reads a credential out of the query string any more', () => {
  const lines = rawSource().split('\n')
    .map((l, i) => [i + 1, l])
    .filter(([, l]) => /req\.query\.(secret|token|key)\b/.test(l))
    // The helpers that DETECT a URL credential are allowed to mention it.
    .filter(([, l]) => !/_ownerSecretPresentInUrl|Boolean\(req\.query|if \(req\.query\.(token|key)\)/.test(l));
  assert.deepStrictEqual(lines, [], `credentials still read from the query: ${JSON.stringify(lines)}`);
});

test('the failure reply carries no length or content of the secret', () => {
  const code = serverCode();
  assert.ok(!/Expected length:/.test(code),
    'the reply still tells the caller how long the secret is');
  assert.ok(!/adminSecret\.length/.test(code));
});

test('the admin repo sync is POST and refuses a token in the URL', () => {
  const src = rawSource();
  assert.ok(src.includes("app.post('/admin/sync-bot-repo'"),
    'the repo-writing route is still a GET, so its credentials sit in browser history');
  assert.ok(!src.includes("app.get('/admin/sync-bot-repo'"));
  assert.match(src.slice(src.indexOf("app.post('/admin/sync-bot-repo'")).slice(0, 900),
    /TOKEN_IN_URL/);
});

test('no raw driver message is returned to a client', () => {
  const src = rawSource();
  const bad = src.split('\n')
    .map((l, i) => [i + 1, l.trim()])
    .filter(([, l]) => /res\.(status\(\d+\)\.)?json\(\{[^}]*\berror: (e|err|error)\.message/.test(l))
    .filter(([n]) => {
      const before = src.split('\n').slice(0, n).reverse();
      const route = before.find(l => /^app\.(get|post|put|delete)\(/.test(l)) || '';
      // These exist to show an operator WHY a mail provider refused. All are
      // behind the owner-secret header or `auth`, and a generic message would
      // remove the only thing they are for. Named individually so a fourth
      // route cannot join the exemption by accident.
      return !["'/api/test-email'", "'/api/test-brevo'", "'/api/test-resend'"]
        .some(r => route.includes(r));
    });
  assert.deepStrictEqual(bad, [], `driver messages reach clients at: ${JSON.stringify(bad)}`);
});

test('security headers are set on every response', () => {
  const code = serverCode();
  for (const h of ['X-Content-Type-Options', 'Referrer-Policy', 'X-Frame-Options',
                   'Permissions-Policy', 'Content-Security-Policy',
                   'Strict-Transport-Security']) {
    assert.match(code, new RegExp(h), `${h} is not set`);
  }
  assert.ok(!/Access-Control-Allow-Origin['"]?\s*[,:]\s*['"]\*/.test(code),
    'a wildcard CORS header is still set');
});

// ── Licence masking in logs (Finding 1) ────────────────────────────────
const { _maskLicence } = _internal;

test('a masked licence discloses the prefix and first group only', () => {
  const key = generateForexKey();
  const masked = _maskLicence(key);
  const parts = key.split('-');
  assert.ok(masked.startsWith(parts[0] + '-' + parts[1] + '-'), masked);
  // Every group after the first is gone.
  for (const g of parts.slice(2)) {
    assert.ok(!masked.includes(g), `group ${g} survived masking: ${masked}`);
  }
  assert.ok(masked !== key, 'masking returned the key unchanged');
});

test('masking handles legacy keys, empty values and odd shapes', () => {
  assert.strictEqual(_maskLicence('FORX-ABCD-EFGH-JKLM'), 'FORX-ABCD-****-****');
  assert.strictEqual(_maskLicence(''), '(none)');
  assert.strictEqual(_maskLicence(null), '(none)');
  assert.strictEqual(_maskLicence(undefined), '(none)');
  assert.ok(!_maskLicence('nodashes-at-all').includes('nodashes-at-all'));
});

test('no log call in server.js interpolates a complete licence key', () => {
  const code = serverCode();
  // addLog / console.* whose template carries a bare ${key} or ${licenseKey}.
  const offenders = code.split('\n')
    .map((l, i) => [i + 1, l.trim()])
    .filter(([, l]) =>
      /(addLog|console\.(log|error|warn))\(/.test(l) &&
      /\$\{\s*(key|licenseKey|licenceKey|revoked\[0\]\.key)\s*\}/.test(l));
  assert.deepStrictEqual(offenders, [],
    `complete licence keys reach logs at: ${JSON.stringify(offenders)}`);
});

test('the five licence lifecycle log sites all mask', () => {
  const code = serverCode();
  for (const marker of ['Granted ${product} license',
                        'Trial issued',
                        'License activated',
                        'Forex Bot sold',
                        'License revoked']) {
    const idx = code.indexOf(marker);
    assert.ok(idx > 0, `log site missing: ${marker}`);
    const line = code.slice(code.lastIndexOf('\n', idx) + 1, code.indexOf('\n', idx));
    assert.match(line, /_maskLicence\(/, `not masked: ${line.trim().slice(0, 110)}`);
  }
});

// ── Scoped config sessions (Finding 2) ─────────────────────────────────
test('read and write are separate scopes, and read cannot write', () => {
  const r = _issueBotSession('FORX-SCOPES', 'apex-forex', 'bot:config:read');
  const w = _issueBotSession('FORX-SCOPES', 'apex-forex', 'bot:config:write');

  assert.ok(_botSession(fakeReq(`Bearer ${r}`), 'bot:config:read'), 'read token cannot read');
  assert.strictEqual(_botSession(fakeReq(`Bearer ${r}`), 'bot:config:write'), null,
    'a READ token satisfied the write scope');

  assert.ok(_botSession(fakeReq(`Bearer ${w}`), 'bot:config:write'), 'write token cannot write');
  assert.strictEqual(_botSession(fakeReq(`Bearer ${w}`), 'bot:config:read'), null,
    'a WRITE token satisfied the read scope — scopes must be disjoint');
  _revokeBotSessionsFor('FORX-SCOPES');
});

test('an unknown scope cannot be issued', () => {
  for (const bad of ['admin', 'bot:config:*', '', 'bot:config:read ', 'root']) {
    assert.throws(() => _issueBotSession('FORX-X', 'apex-forex', bad),
      `scope ${JSON.stringify(bad)} was issued`);
  }
});

test('save-bot-config refuses a licence key as authentication', () => {
  const code = serverCode();
  const idx = code.indexOf("app.post('/api/save-bot-config'");
  assert.ok(idx > 0);
  const route = code.slice(idx, idx + 2600);
  assert.match(route, /LICENCE_NOT_ACCEPTED/,
    'a licence key in the body is not refused');
  assert.match(route, /_botSession\(req,\s*SCOPE_WRITE\)/,
    'the write route does not require the write scope');
  assert.match(route, /INSUFFICIENT_SCOPE/,
    'a read token is not distinguished from no token');
  // The licence written to must come from the session, never the request.
  assert.match(route, /const key = sess\.licenseKey/,
    'the target licence is not taken from the session');
  assert.ok(!/const \{ key, config \} = req\.body/.test(route),
    'the route still destructures a licence key out of the body');
});

test('a session is bound to its own licence — A cannot write B', () => {
  const a = _issueBotSession('FORX-AAAA', 'apex-forex', 'bot:config:write');
  const sess = _botSession(fakeReq(`Bearer ${a}`), 'bot:config:write');
  // The route uses sess.licenseKey and ignores anything in the body, so the
  // only licence this token can ever address is its own.
  assert.strictEqual(sess.licenseKey, 'FORX-AAAA');
  const b = _issueBotSession('FORX-BBBB', 'apex-forex', 'bot:config:write');
  assert.strictEqual(_botSession(fakeReq(`Bearer ${b}`), 'bot:config:write').licenseKey,
    'FORX-BBBB');
  _revokeBotSessionsFor('FORX-AAAA');
  assert.strictEqual(_botSession(fakeReq(`Bearer ${a}`), 'bot:config:write'), null);
  assert.ok(_botSession(fakeReq(`Bearer ${b}`), 'bot:config:write'),
    'revoking one licence revoked another');
  _revokeBotSessionsFor('FORX-BBBB');
});

test('a write session expires like any other', () => {
  const w = _issueBotSession('FORX-EXPW', 'apex-forex', 'bot:config:write');
  const sess = _botSession(fakeReq(`Bearer ${w}`), 'bot:config:write');
  sess.exp = Date.now() - 1;
  assert.strictEqual(_botSession(fakeReq(`Bearer ${w}`), 'bot:config:write'), null,
    'an expired write token still authenticated');
});

test('licence validity is re-checked at write time, not only at issue', () => {
  const route = serverCode().slice(serverCode().indexOf("app.post('/api/save-bot-config'"));
  assert.match(route.slice(0, 2600), /revoked_at/,
    'a licence revoked inside the session window would still write');
  assert.match(route.slice(0, 2600), /_revokeBotSessionsFor\(key\)/,
    'sessions are not revoked when the licence stops being valid');
});

test('the configurator presents the licence once, to the session endpoint', () => {
  const html = require('node:fs').readFileSync(
    require('node:path').join(__dirname, '..', 'public', 'configurator-forex.html'), 'utf8');
  assert.match(html, /\/api\/bot-session/, 'the configurator does not exchange the licence');
  assert.match(html, /scope:\s*'bot:config:write'/, 'it does not request the write scope');
  assert.match(html, /'Authorization':\s*'Bearer '\s*\+\s*token/, 'it does not send the token');
  assert.ok(!/body:JSON\.stringify\(\{key:lk/.test(html),
    'it still sends the licence key as the authorisation');
});

// ── Railway deploy authorisation (Finding 8) ───────────────────────────
test('the railway deploy route verifies the licence before doing anything', () => {
  const code = serverCode();
  const idx = code.indexOf("app.post('/api/railway-deploy'");
  assert.ok(idx > 0, 'route missing');
  const route = code.slice(idx, idx + 2200);
  assert.match(route, /verifyLicenseKeyHmac\(licenseKey\)/,
    'the licence key written into the deployed service is never verified');
  assert.match(route, /from\('licenses'\)/, 'no authoritative licence lookup');
  assert.match(route, /revoked_at/, 'a revoked licence can still deploy');
  assert.match(route, /_authLimiter/, 'the route is not rate limited');
});

test('no upstream Railway response body is returned to the caller', () => {
  const code = serverCode();
  const idx = code.indexOf("app.post('/api/railway-deploy'");
  const route = code.slice(idx, code.indexOf("app.post('/api/railway-deploy'") + 6000);
  // JSON.stringify(<upstream>) in a reply hands the caller that account's ids
  // and team structure, and on a failure path can carry more.
  assert.ok(!/detail:\s*JSON\.stringify\(/.test(route),
    'an upstream response body is still returned');
  assert.ok(!/error:\s*'Deploy failed: '\s*\+\s*e\.message/.test(route),
    'the catch still returns the exception message');
});

test('neither the Railway token nor the licence key is logged', () => {
  const code = serverCode();
  const idx = code.indexOf("app.post('/api/railway-deploy'");
  const route = code.slice(idx, idx + 6000);
  const logged = route.split('\n').filter(l =>
    /(console\.(log|error|warn)|addLog)\(/.test(l) &&
    /\$\{\s*(railwayToken|licenseKey)\s*\}/.test(l));
  assert.deepStrictEqual(logged, [], `credentials logged at: ${JSON.stringify(logged)}`);
  // The token may appear exactly once: in the outbound Authorization header
  // to Railway, which is the whole point of the endpoint.
  const authUses = (route.match(/Bearer \$\{railwayToken\}/g) || []).length;
  assert.strictEqual(authUses, 1, `railwayToken used in ${authUses} header(s)`);
});

// ── bot-config least privilege (Finding 9) ─────────────────────────────
test('bot-config never answers without a scoped session, and never caches', () => {
  const code = serverCode();
  const idx = code.indexOf("app.get('/api/bot-config'");
  const route = code.slice(idx, idx + 2600);
  assert.match(route, /_botSession\(req,\s*SCOPE_READ\)/, 'no scope required');
  assert.match(route, /Cache-Control',\s*'no-store'/, 'the response is cacheable');
  assert.match(route, /LICENCE_IN_URL/, 'a licence key in the URL is not refused');
  // The configuration can contain credentials, so an unauthenticated or
  // wrongly-scoped caller must get nothing at all — not a filtered subset.
  assert.match(route, /Authorization failed/, 'no 401 path');
});

// ── Finding 2: the remaining cases from the audit's own list ───────────
test('a licence key in the query string cannot write configuration', () => {
  const code = serverCode();
  const idx = code.indexOf("app.post('/api/save-bot-config'");
  const route = code.slice(idx, idx + 2600);
  // The route takes its licence from the session and nothing else, so a query
  // parameter has nowhere to land — and a body key is refused outright.
  assert.ok(!/req\.query\.key/.test(route), 'the write route reads ?key=');
  assert.match(route, /body\.key \|\| body\.licenseKey \|\| body\.licenceKey/,
    'a licence key in the body is not detected');
  assert.match(route, /LICENCE_NOT_ACCEPTED/);
});

test('changing configuration revokes the sessions that held the old view', () => {
  const code = serverCode();
  const idx = code.indexOf("app.post('/api/save-bot-config'");
  const route = code.slice(idx, idx + 3400);
  assert.match(route, /_revokeBotSessionsFor\(key\)/,
    'a successful write leaves old sessions valid');
});

test('a licence that stops being valid invalidates its sessions', () => {
  // Both the write path and the session-exchange path re-check the licence, so
  // revocation or expiry inside the window ends the session rather than being
  // noticed only at the next exchange.
  const code = serverCode();
  for (const routeName of ["app.post('/api/save-bot-config'", "app.post('/api/bot-session'"]) {
    const idx = code.indexOf(routeName);
    assert.ok(idx > 0, `${routeName} missing`);
    const route = code.slice(idx, idx + 2600);
    assert.match(route, /revoked_at/, `${routeName} ignores revoked_at`);
    assert.match(route, /expires_at/, `${routeName} ignores expires_at`);
  }
  const save = code.slice(code.indexOf("app.post('/api/save-bot-config'"));
  assert.match(save.slice(0, 3000), /_revokeBotSessionsFor\(key\)/);
});

test('a session issued for one licence carries only that licence', () => {
  const a = _issueBotSession('FORX-OWN-A', 'apex-forex', 'bot:config:write');
  const b = _issueBotSession('FORX-OWN-B', 'apex-forex', 'bot:config:write');
  // The route uses sess.licenseKey, so this IS the ownership boundary.
  assert.strictEqual(_botSession(fakeReq(`Bearer ${a}`), 'bot:config:write').licenseKey, 'FORX-OWN-A');
  assert.strictEqual(_botSession(fakeReq(`Bearer ${b}`), 'bot:config:write').licenseKey, 'FORX-OWN-B');
  const code = serverCode();
  const route = code.slice(code.indexOf("app.post('/api/save-bot-config'"));
  assert.match(route.slice(0, 2600), /const key = sess\.licenseKey/,
    'the write target is not taken from the session');
  _revokeBotSessionsFor('FORX-OWN-A');
  _revokeBotSessionsFor('FORX-OWN-B');
});

// ── Finding 7: the rest of the secret-logging surface ──────────────────
test('no OAuth code, refresh token or Railway token reaches a log call', () => {
  const src = rawSource();
  const offenders = src.split('\n')
    .map((l, i) => [i + 1, l.trim()])
    .filter(([, l]) => /(console\.(log|error|warn)|addLog)\(/.test(l))
    .filter(([, l]) => /\$\{[^}]*\b(railwayToken|refresh_token|refreshToken|access_token|accessToken|authCode|oauthCode|code)\s*\}/.test(l));
  assert.deepStrictEqual(offenders, [],
    `credentials reach logs at: ${JSON.stringify(offenders)}`);
});

test('no environment secret is interpolated into a log call', () => {
  const src = rawSource();
  const offenders = src.split('\n')
    .map((l, i) => [i + 1, l.trim()])
    .filter(([, l]) => /(console\.(log|error|warn)|addLog)\(/.test(l))
    .filter(([, l]) => /\$\{\s*process\.env\.[A-Z_]*(SECRET|TOKEN|KEY|PASSWORD)[A-Z_]*\s*\}/.test(l));
  assert.deepStrictEqual(offenders, [],
    `env secrets reach logs at: ${JSON.stringify(offenders)}`);
});
