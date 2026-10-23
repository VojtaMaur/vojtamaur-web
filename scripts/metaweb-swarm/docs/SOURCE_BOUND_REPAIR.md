# Jedna zdrojová citace pro požadavek na opravu — 0.7.11

Auditor round 4 v runu 20261022-051417-8cb93cc5 už po opravě kontextu přečetl
skutečný driver a výstup. Správně navrhl REVISE: tamper test pouze nastaví nulový
hash a dvakrát zkontroluje stejnou rovnost, ale nepošle poškozená data do validátoru.
Úplný vadný úsek skutečně citoval v negative_code. Do dalšího defect_code napsal
slovní vysvětlení místo opakované citace; host požadavek třikrát odmítl. To je
zbytečná duplicita rozhraní, nikoli chybějící důkaz vady.

Živé SDK rozhraní už nemá defect_code. REVISE stále vyžaduje konkrétní
required_local_change a zdrojovou citaci deficientní větve v negative_code,
případně positive_code při vadě pozitivní cesty. Host hledá tuto již dodanou
citaci pouze v zachyceném driveru/implementačních helpers, nikdy v reportech.
Uloží defect_evidence s původním polem, cestou, SHA256 a citací. Interní defect_code
je hostem doplněný alias této citace pro existující coding handoff; není druhým
modelem vyplňovaným důkazem. Původní Python API dál kontroluje explicitní citaci.

Žádný verdikt se neodvozuje z textu důvodu. Bez citace ze skutečného zdroje a bez
konkrétní změny se oprava nepředá. Schválení FULL/SUBCOMPONENT nadále potřebuje
pozitivní i negativní evidenci. Změna neopravuje test sama ani nepotvrzuje mechanismus.
Citace pro opravu používají stejný limit 8000 znaků jako ostatní code evidence.

Protokol source-bound-review-0.7.11 archivuje starý kontext a znovu vyžádá skutečné
zdroje. Limity, účty a approval gates se nemění. Aktuálně BLOCKED auditor potřebuje
explicitní operátorovo odblokování, nikoli nový run:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py unblock "G:\metaweb-swarm-runs\20261022-051417-8cb93cc5" AGENT-006 --note "Odstranena duplicitni citace vady; dokoncit audit a predat opravu negativniho testu"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\20261022-051417-8cb93cc5" --backend openai
```

Přesné argumenty ze skutečného round 4 byly bez nového generování odpovědi přehrány
přes skutečný SDK tool v oddělené kopii. Zachovaný negative_code se navázal na
hashovaný script, REVISE se předalo coderovi. Původní checkpoint a budgety
nezměněny, žádný placený request nebo oprava prototypu se nespustily.
Viz validation/SOURCE_BOUND_REVIEW_LIVE_PROOF.json a SOURCE_BOUND_REVIEW_TESTS.txt.
Budoucí úsudek modelu tím není garantovaný.
