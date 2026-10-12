# 0.5.3 — nedokončená položka web search a rezervace

Run 20261012-090514-8e491a42 zastavila RESERVATION_BOUND_EXCEEDED, nikoli vyčerpání USD/tokenů. Má 3 modelové odpovědi, 37 535 tokenů, nulové HTTP požadavky/uploady a žádnou přijatou IDEA. Discovery vybral FilePost a provedl lokální screen; skutečné přečtení API přes read_document ani kvalifikace dokončeny nebyly. Claims z konečné odpovědi modelu jsou zatím tvrzení ze search, ne nezávislé ověření.

Třetí odpověď má 1 completed search + další searching search se zdrojem. Konzervativní classifier správně neprohlašuje položku se zdroji za zdarma/ignorovanou: účetní počet je 2. Dosavadní settlement však porovnal 2 s rezervovaným cap 1 a označil celý požadavek UNKNOWN, i když API odpověď/usage byly známé. Tím se zastavily ostatní role.

## Oprava

Host pozná pouze úzký případ: přesně stanovený počet completed searches a následující unfinished searching/search položky. Obě se dál konzervativně účtují. Settlement je může uzavřít jen pokud:
- skutečné vstupní/výstupní/celkové tokeny jsou ve svých původních rezervovaných mezích,
- celé překročení počtu vysvětlují takové hostem zjištěné unfinished položky,
- známá rezervovaná cenová maxima umožní spočítat konzervativní cenu všech položek,
- tato cena je nejvýše původní rezervované USD.

Žádná rezervace/limit se nezvětšuje. Skutečné completed overage, neznámé statusy, pending před cap, chybějící usage/ceny, skutečné token/USD překročení a staré UNKNOWN zůstávají blokované. Model nemá reconciliation nástroj. API max_tool_calls se dál posílá se stejnou hodnotou.

Audit má search_accounting_overage v settlementu, samostatnou událost a vysvětlení v reportu/manifestu. Provider billing není z těchto dat potvrzen. API dokumentace pro max_tool_calls: https://developers.openai.com/api/docs/guides/deep-research#best-practices

## Další běh

Z existujícího CMD se správně nastaveným API klíčem:
~~~cmd
run-deposit-trial.cmd
~~~

Jde o nový run. Předchozí UNKNOWN se automaticky nepřepíše ani neodblokuje. Původní agentní history, report a audit zůstávají. Modely, grants, approval, 1,5M tokenů, 40 minut a $5 jsou zachovány.

Regrese jsou lokální, bez placené inference: skutečné SDK s kontrolovanou odpovědí, host accounting, replay tvaru z tohoto runu a negativní finanční/tokenové/unknown hranice. Nevznikl další veřejný upload ani žádný placený smoke.
