/**
 * Digistore24 — affiliate activity + commission report
 * =====================================================
 * Rulează cu: DIGISTORE24_API_KEY=xxx node scripts/digistore-affiliates.js [days]
 *
 * Listează vânzările pe ultimele N zile (implicit 90) via API-ul Digistore24
 * (listPurchases), le grupează pe afiliat și afișează: nr. vânzări, comision
 * total, ultima vânzare — răspunsul direct la "sunt afiliații activi?".
 *
 * IMPORTANT — nu am putut testa asta live (digistore24.com e blocat din
 * mediul în care am scris codul). Sunt sigur pe structura generală a
 * API-ului (endpoint /api/call/{method}/, JSON, autentificare prin header),
 * dar dacă primul rulaj dă eroare de autentificare sau de parametri, cel mai
 * probabil trebuie ajustat DOAR blocul _call() de mai jos (headerul exact
 * sau numele parametrilor) — restul (agregarea, afișarea) nu depinde de asta.
 */

const API_BASE = 'https://www.digistore24.com/api/call';
const API_KEY = process.env.DIGISTORE24_API_KEY;

if (!API_KEY) {
  console.error('Lipsește DIGISTORE24_API_KEY. Rulează: DIGISTORE24_API_KEY=xxx node scripts/digistore-affiliates.js');
  process.exit(1);
}

const days = parseInt(process.argv[2], 10) || 90;

async function _call(method, params = {}) {
  const url = `${API_BASE}/${method}/`;
  const body = new URLSearchParams({ ...params, output_format: 'json' });
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'X-DS-API-KEY': API_KEY,
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body,
  });
  const text = await res.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    throw new Error(`Digistore24 a răspuns cu ceva ne-JSON (HTTP ${res.status}):\n${text.slice(0, 500)}`);
  }
  if (json.error || json.error_code) {
    throw new Error(`Digistore24 API error [${method}]: ${json.error || json.error_code} — ${json.error_msg || json.message || ''}`);
  }
  return json;
}

function fmtMoney(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}

async function main() {
  const to = new Date();
  const from = new Date(to.getTime() - days * 24 * 60 * 60 * 1000);
  const fmt = d => d.toISOString().slice(0, 10);

  console.log(`Digistore24 — activitate afiliați, ${fmt(from)} → ${fmt(to)}\n`);

  const res = await _call('listPurchases', {
    'purchase.created_at_from': fmt(from),
    'purchase.created_at_to': fmt(to),
  });

  const purchases = res.data || res.purchases || [];
  if (!Array.isArray(purchases)) {
    console.log('Răspuns neașteptat de la Digistore24 — verifică manual formatul:');
    console.log(JSON.stringify(res, null, 2).slice(0, 2000));
    return;
  }

  const byAffiliate = new Map();
  let noAffiliate = 0;

  for (const p of purchases) {
    const affName = p.affiliate_name || p.affiliate?.name || p.affiliate_id || null;
    if (!affName) {
      noAffiliate++;
      continue;
    }
    const commission = Number(p.affiliate_commission_amount || p.commission_amount_cents || 0);
    const createdAt = p.created_at || p.purchase_date || '';
    if (!byAffiliate.has(affName)) {
      byAffiliate.set(affName, { sales: 0, commissionCents: 0, lastSale: '' });
    }
    const row = byAffiliate.get(affName);
    row.sales += 1;
    row.commissionCents += commission;
    if (createdAt > row.lastSale) row.lastSale = createdAt;
  }

  if (byAffiliate.size === 0) {
    console.log(`Niciun afiliat nu a generat vânzări în ultimele ${days} zile.`);
    console.log(`(${purchases.length} vânzări totale în perioadă, ${noAffiliate} fără afiliat asociat — vânzări directe.)`);
    return;
  }

  const rows = [...byAffiliate.entries()].sort((a, b) => b[1].sales - a[1].sales);

  console.log(`${rows.length} afiliați activi (cu cel puțin o vânzare în ${days} zile):\n`);
  console.log('Afiliat'.padEnd(30), 'Vânzări'.padStart(8), 'Comision'.padStart(12), 'Ultima vânzare');
  console.log('-'.repeat(75));
  for (const [name, row] of rows) {
    console.log(
      String(name).slice(0, 29).padEnd(30),
      String(row.sales).padStart(8),
      fmtMoney(row.commissionCents).padStart(12),
      row.lastSale.slice(0, 10)
    );
  }

  const totalCommission = rows.reduce((s, [, r]) => s + r.commissionCents, 0);
  console.log('-'.repeat(75));
  console.log(`Total comisioane plătite afiliaților: ${fmtMoney(totalCommission)}`);
  console.log(`Vânzări directe (fără afiliat): ${noAffiliate}`);
}

main().catch(err => {
  console.error('Eroare:', err.message);
  process.exit(1);
});
