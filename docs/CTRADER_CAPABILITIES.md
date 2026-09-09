# cTrader — ce folosim și ce nu

**Sursă:** introspecție directă a `ctrader-open-api==0.9.2` instalate, comparată
cu `apex-forex-bot/apex/brokers/ctrader.py`. Nu sunt presupuneri — fiecare câmp
de mai jos a fost citit din descriptorul protobuf.

| | |
|---|---|
| Tipuri de cereri oferite de API | **40** |
| Folosite | **15** |
| Câmpuri în `ProtoOANewOrderReq` | **23** |
| Folosite | **8** |
| Tipuri de ordine | **6** (`MARKET`, `LIMIT`, `STOP`, `STOP_LOSS_TAKE_PROFIT`, `MARKET_RANGE`, `STOP_LIMIT`) |
| Folosite | **1** (`MARKET`) |
| Limitare de rată în conector | **niciuna** |

**Concluzia:** platforma nu e limitată de cTrader. Folosește ~37% din el.

---

# PARTEA 1 — Câmpuri de ordin nefolosite

Cea mai mare valoare pentru cel mai puțin efort: sunt câmpuri pe un mesaj pe
care conectorul îl trimite deja. Nicio instalație nouă, niciun endpoint nou.

| Câmp | Ce face | De ce contează |
|---|---|---|
| `guaranteedStopLoss` | brokerul **garantează** prețul de ieșire, chiar și peste gap | răspunsul direct la incidentul NFP din 4 sept: stop depășit cu 11,1 pips (**51% peste**). Cu stop garantat, ieșirea era la preț. **Cel mai vandabil câmp din listă.** |
| `trailingStopLoss` | trailing gestionat **de broker** | acum bucla mută stopul manual (evenimentele `STOP_MOVED`, la câteva minute). Cu trailing la broker: mai puține cereri API, și **trailing-ul continuă când botul e oprit sau se redeployează** |
| `slippageInPoints` + `baseSlippagePrice` | alunecare maximă acceptată (cu `MARKET_RANGE`) | ordinul **refuză** să se execute la preț prost în loc să înghită orice |
| `clientOrderId` | cheie de idempotență **la broker** | registrul de idempotență există deja în cod; brokerul o oferă nativ. Dublă protecție contra ordinelor duplicate |
| `label` / `comment` | etichetă pe ordin | ordinele devin identificabile în interfața cTrader și în rapoartele brokerului — clientul își vede trade-urile marcate |
| `limitPrice` / `stopPrice` | preț pentru ordine în așteptare | vezi Partea 3 |
| `timeInForce` / `expirationTimestamp` | cât trăiește ordinul | ordin care expire singur dacă setup-ul nu se materializează |
| `stopTriggerMethod` | declanșare pe bid / ask / trade | evită declanșări false pe spread lărgit |
| `relativeStopLoss` / `relativeTakeProfit` | SL/TP relativ la fill | **atenție:** comentariul din cod spune că au eșuat cu „invalid precision" pe non-FX. De aceea se face amend absolut după fill. Verifică înainte să reîncerci. |

---

# PARTEA 2 — Cele 25 de cereri nefolosite

Câmpurile obligatorii sunt cele reale din descriptor. `ctidTraderAccountId` e
implicit peste tot (conectorul îl are ca `self._ctid()`).

## Prioritate ÎNALTĂ — închid buguri sau vând platforma

### `ProtoOAOrderListReq` → `Res`
`fromTimestamp`, `toTimestamp`
Istoricul **ordinelor**, inclusiv respinse și anulate.
**De ce contează:** jurnalul citește doar **deal-uri**. Un ordin respins nu
produce deal, deci e invizibil — exact de ce cele două ordine USDCHF din
6 septembrie au dispărut în tăcere. Asta le-ar fi arătat imediat.

### `ProtoOAExpectedMarginReq` → `Res`
`symbolId`, opțional `volume`
Marja necesară **înainte** de trimiterea ordinului.
**De ce contează:** ar fi prins depășirea de pe XAUUSD (3,01% risc real față de
2,48% țintă, din cauza lotului minim) **înainte** de intrare, nu după.

### `ProtoOAMarginCallListReq` → `Res` · `ProtoOAMarginCallUpdateReq` → `Res`
`marginCall` (pentru update)
Pragurile de margin call ale brokerului, și actualizarea lor.
**De ce contează:** plasă de siguranță reală, verificabilă, pe care o poți
afirma onest în marketing. Nu e o promisiune de profit — e o protecție.

### `ProtoOACashFlowHistoryListReq` → `Res`
`fromTimestamp`, `toTimestamp`
Depuneri, retrageri, **swap, comisioane**.
**De ce contează:** fără el, P&L-ul e incomplet. Swap-ul peste noapte și
comisioanele nu apar nicăieri în jurnal. Un client care își verifică cifrele
față de extrasul brokerului va găsi diferențe.

### `ProtoOASubscribeLiveTrendbarReq` → `Res`
`period`, `symbolId`
Lumânări **împinse** de server, nu cerute.
**De ce contează:** elimină majoritatea presiunii pe limita de 5 cereri
istorice/secundă. Condiție practică pentru mai mulți clienți.

## Prioritate MEDIE — capacități noi

### `ProtoOASubscribeDepthQuotesReq` / `ProtoOAUnsubscribeDepthQuotesReq`
opțional `symbolId`
Adâncimea carnetului de ordine.
**De ce contează:** măsori lichiditatea reală înainte de intrare și refuzi
trade-uri pe care piața nu le poate absorbi. **Niciun bot retail nu face asta.**

### `ProtoOAAmendOrderReq` / `ProtoOACancelOrderReq` → eveniment (nu `Res`)
`orderId`; amend acceptă `volume`, `limitPrice`, `stopPrice`, `expirationTimestamp`
Modifici sau anulezi un ordin în așteptare.
**Atenție:** răspund cu `ProtoOAExecutionEvent`, nu cu un `Res` — folosiți
aceeași așteptare de eveniment terminal ca `place_order`.

### `ProtoOAGetTickDataReq` → `Res`
`symbolId`, `type`, `fromTimestamp`, `toTimestamp`
Istoric la nivel de tick.
**De ce contează:** backtesting real. Cel actual folosește lumânări.

### `ProtoOADealListByPositionIdReq` · `ProtoOAOrderListByPositionIdReq`
`positionId` (+ interval pentru primul)
Toate deal-urile/ordinele unei poziții.
**De ce contează:** o poziție construită din mai multe fill-uri e acum
reconstruită prin ghicit. Astea o dau exact.

### `ProtoOADealOffsetListReq` → `Res`
`dealId`
Ce deal a închis ce deal.
**De ce contează:** necesar pentru raport fiscal corect (FIFO). Fără el,
raportul e o aproximare.

### `ProtoOAAssetListReq` · `ProtoOAAssetClassListReq` · `ProtoOASymbolCategoryListReq`
doar contul
Universul complet de instrumente.
**De ce contează:** tranzacționezi **8 perechi**. Conectorul descarcă deja
lista întreagă de la broker (`ProtoOASymbolsListReq`, linia ~389) și o aruncă:
indici, mărfuri, acțiuni CFD. Extinderea universului e configurare, nu cod nou.

## Prioritate JOASĂ — utilitare

| Cerere | Câmpuri | Notă |
|---|---|---|
| `ProtoOASymbolsForConversionReq` | `firstAssetId`, `lastAssetId` | conversie valutară corectă pentru conturi non-USD |
| `ProtoOAGetCtidProfileByTokenReq` | `accessToken` | profilul clientului (nume, id) |
| `ProtoOAOrderDetailsReq` | `orderId` | detaliile unui singur ordin |
| `ProtoOAUnsubscribeSpotsReq` / `UnsubscribeLiveTrendbarReq` | `symbolId` / `period` | dezabonare — igienă la schimbarea universului |
| `ProtoOAAccountLogoutReq` | contul | deconectare curată |
| `ProtoOAVersionReq` | — | versiunea API |
| `ProtoOARefreshTokenReq` | `refreshToken` | **deja tratat** în `apex/ctrader_oauth.py` — nu e o lipsă |

---

# PARTEA 3 — Tipurile de ordine

Se folosește doar `MARKET`.

| Tip | Ce permite |
|---|---|
| `MARKET_RANGE` | ordin de piață care refuză execuția peste alunecarea maximă |
| `LIMIT` | intrare la un preț mai bun, **păzită de broker** |
| `STOP` | intrare pe breakout peste un nivel |
| `STOP_LIMIT` | breakout, dar cu preț maxim acceptat |
| `STOP_LOSS_TAKE_PROFIT` | ordin pur de protecție |

**Schimbarea de arhitectură:** acum botul trebuie să fie **treaz exact în
momentul potrivit**, iar bucla rulează la câteva secunde. Cu ordine în
așteptare, strategia pune ordinul la nivel și **brokerul așteaptă**. Mai puține
setup-uri ratate, mai puțină dependență de uptime, mai puține cereri API.

---

# PARTEA 4 — ⚠️ Gaura care trebuie astupată prima

**Conectorul nu are nicio limitare de rată.** Zero.

cTrader impune **5 cereri istorice/secundă** și 50 non-istorice/secundă
**per conexiune, indiferent de câți clienți** o folosesc.

Cu un utilizator merge din noroc. Nu e o funcționalitate de adăugat mai târziu
— e condiția ca platforma să suporte al doilea client.

---

# ORDINEA DE LUCRU RECOMANDATĂ

| # | Ce | De ce acum |
|---|---|---|
| 1 | **Limitator de rată** | condiție de supraviețuire, blochează tot ce urmează |
| 2 | **`guaranteedStopLoss` + `slippageInPoints`** | un câmp fiecare, cea mai mare valoare vizibilă |
| 3 | **`trailingStopLoss` la broker** | scoate bucla `STOP_MOVED`; trailing-ul supraviețuiește repornirilor |
| 4 | **`ProtoOAOrderListReq` în jurnal** | face vizibile ordinele respinse; închide clasa de bug USDCHF |
| 5 | **`ProtoOAExpectedMarginReq`** înainte de fiecare ordin | prinde depășirile de risc înainte de intrare |
| 6 | **`clientOrderId`** | idempotență la broker, peste cea din cod |
| 7 | **Ordine în așteptare** (`LIMIT`/`STOP`) | schimbarea de arhitectură |
| 8 | **`CashFlowHistoryList`** | P&L complet, cu swap și comisioane |

Pașii 2–6 sunt câmpuri și cereri pe infrastructură care există deja. OAuth,
protobuf, reconectarea și paginarea sunt scrise și testate.

## Reguli pentru agenți

- **Zona:** tot ce ține de asta e în `apex-forex-bot/apex/brokers/`.
  Un singur agent acolo o dată.
- **`gates.authorize_order` / `authorize_close` rămân singurele porți** spre un
  ordin. Nicio capabilitate nouă nu le ocolește.
- Fiecare capabilitate nouă are nevoie de test în `tests/`, nu în `apex/`.
- Suita completă trebuie să treacă înainte de commit.
- Mesajele care răspund cu **eveniment** (`AmendOrder`, `CancelOrder`) au
  nevoie de aceeași așteptare de eveniment terminal ca `place_order` — vezi
  `_is_terminal_execution`.
