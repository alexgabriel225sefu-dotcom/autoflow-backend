# Rezumat: testul cu cumpărători simulați (agenți) pentru Apex4Traders

## Ce am testat
Am pus 20 de cumpărători simulați (agenți AI, fiecare cu alt venit, vârstă și obiecție) în fața ofertei Apex4Traders, în două runde. Ținta era 100, am oprit la 20 pentru cost (fiecare agent a consumat ~123.000 de tokeni).

| Rundă | Oferta | Rezultat |
|---|---|---|
| A | $497 o dată, lifetime, live trading oprit | 0 din 20 ar cumpăra |
| B | $297 o dată, refund 30 zile, live trading pornit | 0 din 19 ar cumpăra |

Toți ar lua demo-ul gratuit de 14 zile, dar niciunul n-ar plăti.

## De ce refuză (runda B)
- **Încredere, 12:** „nu plătesc până nu văd oameni reali cu rezultate reale", au mai plătit servicii de semnale care n-au mers.
- **Obișnuință cu MetaTrader, 4:** nu vor să treacă pe cTrader.
- **Preț, 2:** cTrader are deja boți gratis.
- **Altele, 1.**
La $497, motivele erau încredere 9, „live trading e oprit" 5, „nu am nevoie" 3.

## Ce ar schimba răspunsul
Rezultate verificabile de la traderi reali pe cont live, o echipă cu nume, un refund clar, suport pentru MetaTrader, și dovada că face ceva ce boții gratuiți din cTrader nu pot (de exemplu Risk Guard).

## Prețul spus de ei
- Rundă A: interval acceptabil $49–$350, „la ofertă" ~$197.
- Rundă B: interval acceptabil $50–$219, „la ofertă" ~$129.
Pe baza lor am recomandat de testat $149 / $199 lifetime și $29 pe lună.

## Verdictul consiliului (3 lentile)
2 „finanțează cu condiții" și 1 „nu", scor mediu 3,3 din 10. Riscuri comune: lipsa încrederii, niciun avantaj clar față de unelte gratuite, partea plătită nu se poate vinde cât timp live trading e oprit.

## Limite
- Cumpărători simulați, nu clienți reali: pot descoperi obiecții, dar nu prezic cumpărarea. Au tendința să fie prea agreabili, deci 0% e probabil chiar un rezultat optimist.
- Doar 20 de răspunsuri din 100 planificate, deci intervalele de preț sunt orientative.
- Testul real: o pagină cu preț, o pre-vânzare plătită, clienți reali.

## Fișiere
Rezultate complete: panel/results.md (runda A), panelB/results.md (runda B), pricing.md, board.md, competitors.md, cfo.md.
