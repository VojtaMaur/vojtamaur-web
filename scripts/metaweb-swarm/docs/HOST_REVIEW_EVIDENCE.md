# Posudek a fakta o artefaktech — 0.7.9

## Diagnóza pokračování 20261022-051417-8cb93cc5

Druhý audit navrhl SUBCOMPONENT s neexistujícím output/recovery_seed.json.
Zachycený výstup má cestu prototype/recovery-seed.json. Pozitivní i negativní
citace byly vytvořené ukázky shell/Python kódu, nikoli skutečný zachycený driver.
Skutečný negativní test stále pouze porovnává nulový hash s původním; neposílá
poškozený výstup do validátoru. Funkčnost proto nelze potvrdit.

Host správně odmítl rozpor cesty, ale po třetím pokusu vytvořil nevyřešené REVISE.
Queue čekala na audit, zatímco pending review už test kvůli tomuto záznamu přeskočilo.
Následný stop nesprávně hlásil nedostatek budgetu. To je chyba frameworku.

## Změna

Živý review tool přijímá verdikt, důvod, skutečné pozitivní/negativní citace a u
REVISE konkrétní lokální změnu s defect_code. Model už neposílá observed_recovery,
review_basis ani recovered_path. Host doplní hash/size fakta; pro FULL_MECHANISM
vybere přesnou zachycenou kopii z matching_recovered_outputs. Existence kopie sama
neprokazuje dekódování nebo celý mechanismus. SUBCOMPONENT nevyžaduje shodné bytes
transformovaného výstupu s původním EPUB. Staré explicitní Python volání s vlastními
fakty dál podléhá původním kontrolám.

Schválení stále vyžaduje vlastní čtení zachycených souborů a skutečné citace z
driveru nebo zachycených implementačních helpers, nikoli generovaného reportu.
Framework ověřuje původ citací, nikoli automaticky jejich vědecký význam.
Význam negativního testu posuzuje auditor; host neprohlašuje obecný sémantický oracle.

U SDK Shell tři identické neplatné pokusy končí technickým
PROTOTYPE_REVIEW_EVIDENCE_STALLED bez verdiktu a bez vymyšleného požadavku na opravu
implementace. Platné REVISE pro lokální kontrakt nadále potřebuje doloženou vadu.
Poslední validační problém je součástí další instrukce, nikoli pouze konzolový text.

## Obnovení starého nevyřešeného auditu

Při explicitním run/resume se starý review_unresolved nabídne znovu v existujících
limitech. Historický záznam se nemaže ani nepřepisuje na nový verdikt; přidá se
značka obnovení protokolu. Odemkne se pouze blok vlastníka se stejným test_id a
INDEPENDENT_REVIEW_UNRESOLVED. Ostatní bloky, approvals, credentials a limity zůstávají.
Kontradiktorní staré citace nejsou vloženy zpět do aktivního review packetu jako důkaz.
Starý modelový kontext se jednou archivuje a obnoví pro host-evidence-0.7.9.
Jiný BLOCKED auditor se automaticky neodemyká; explicitní lidské rozhodnutí trvá.

Technicky zablokovaný audit vrací BLOCKED / PROTOTYPE_REVIEW_BLOCKED také tehdy,
když jiná role už vyčerpala svá kola. Skutečné globální token/time/USD/step limity
mají nadále přednost před dispatch a nejsou automaticky prodlouženy.

## Ověření a omezení

Viz validation/REVIEW_RESOLUTION_LIVE_PROOF.json a REVIEW_RESOLUTION_TESTS.txt.
Skutečné payloady obou auditů a hashově ověřené soubory byly přehrány pouze v
oddělené kopii. Vymyšlené citace nevytvořily verdikt; původní doložené REVISE z
prvního auditu prošlo zpět coderovi. Žádný placený request, oprava prototypu nebo
certifikace nebyly provedeny. Změna nemůže garantovat správný úsudek levného modelu.

Pro tento běh stačí ve stávajícím CMD s API klíčem:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\20261022-051417-8cb93cc5" --backend openai
```

Není třeba nový run ani navýšení limitů. Auditor je v checkpointu PENDING; pokud se
znovu technicky zablokuje, zůstane poctivě neuzavřený audit místo fingovaného výsledku.
