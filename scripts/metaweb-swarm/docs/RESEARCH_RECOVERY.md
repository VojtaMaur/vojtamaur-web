# Opravy výzkumných úloh (0.6.11)

Aktuální doplnění: [FLOW_COMPLETION 0.6.12](FLOW_COMPLETION.md) zjednodušuje planned output capture a dokončení reportu a opravuje negované owner zákazy při delegování.

Běh `20261013-130738-d39be211` měl dvě DISCOVERED hypotézy, dva Docker
experimenty (jeden exit=0, druhý exit=1), žádný zaznamenaný test ani deposit.
Dedupe sloučilo další DNS návrh do stejného IDEA. Auditor opakoval PASS po
přečtení jediného RFC; prototyper odkazoval na nematerializovaný původní název,
pak místo opravy lokálního plánu použil nástroj pro deposit. QR script četl JSON
přímo pomocí `cbor2.loads` a spadl. Globální limity nebyly vyčerpány.

## Konkrétní další krok

V CMD ve složce `G:\vojtamaur-web\scripts\metaweb-swarm` založí nový běh:

```cmd
run-http.cmd
```

Všechny model tiers zůstávají `gpt-5.4-mini`, stejně jako 40 kol, 3M tokenů,
hodina a externí human approval. Tato oprava nepouští placený běh automaticky.
Resume používá původní run config a role allowances; nic nenavyšuje samo:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\CESTA_BEHU" --backend openai
```

## Auditor

`get_review_task` / `get_research_task` vrací `missing_documents` a
`own_read_urls`. PASS stále vyžaduje vlastní čtení všech citovaných zdrojů;
vlastní zachycený redirect může doložit přečtení cílové dokumentace. Pouhý
podobný URL název, jiný query/path nebo čtení jiného agenta nejsou alias.
`RESEARCH_PRIMARY_EVIDENCE_REQUIRED` vrací přesné chybějící URL a rozsahy,
takže agent nemusí odhadovat, který zdroj framework očekává.

Nedostatek podkladů lze uzavřít jako agentní REVISE s EVIDENCE_GAP. Framework
nepřiděluje PASS ani REJECT. Tři stejné nevyřešené validační pokusy odloží
danou úlohu bez verdiktu, zachovají její detaily a nechají další kandidáty
pokračovat v původních rozpočtech. Opakované čtení již přečteného dokumentu
se nepočítá jako pokrok; přečtení skutečně chybějícího zdroje ano.

## Lokální prototyper

Pořadí: `materialize_export` → `read_file` / kontrola formátu → `write_file`
test scriptu → `record_prototype_plan` → propojená Docker execution →
artefakty → `record_test` → nezávislé posouzení rozsahu.

V scriptu i `input_path` musí být **workspace path vrácená materialize_export**,
ne původní export filename. Chybějící input/script vrátí opravitelné DEFERRED,
konkrétní pole a existující materializované cesty. Oprava probíhá novým
voláním `record_prototype_plan` po opravě scriptu/cest. Není k tomu deposit
draft. Během LOCAL_IDEA nejsou nabízené deposit draft opravné nástroje, dokud
agent nemá vlastní draft pro tuto IDEA. Obecné HTTP, upload a approval nástroje
zůstávají dostupné se stejnými policy kontrolami; vytvoření vlastního draftu
zpřístupní jeho opravy v dalším bounded round. Nejde o nové omezení externích
oprávnění.

Format hint vychází z původního filename, nikoli z hostem potvrzeného obsahu.
JSON se čte `json.loads`; CBOR test nejprve použije `cbor2.dumps`, potom
`cbor2.loads`. Úspěšné importy nebo exit=0 stále nejsou důkazem mechanismu.
Chybně napsaný script agent opravuje; host nepíše automaticky jeho implementaci.

Tři stejné validační chyby odloží místní úlohu a přidělí další IDEA. Skutečnou
technickou překážku agent zaznamenává pomocí `record_research_blocker`.
Kandidát zůstává zachovaný bez falešného PROTOTYPED či REJECTED.

## Checkpoint a audit

`research_repairs` a `research_task_blocks` jsou v checkpointu, reportu a
manifestu. Identita opravy obsahuje IDEA revizi a počet operator notes. Resume
neotevírá zaseknutou nezměněnou úlohu automaticky. `unblock --note` nebo změna
skutečného zadání umožní další pokus v přidělených limitech. Odložený úkol
pořád znamená BLOCKED roli, i když jiné úlohy byly hotové.

Z pracovní historie se archivují jen prokazatelně odmítnuté datové plánovací
a critique calls. Úplné originály jsou v auditu. HTTP/experiment a UNKNOWN
outcomes tento filtr neodstraňuje a nikdy z něj nevyplývá oprávnění je opakovat.
Konzole ukáže krátkou hlášku při první opravě a při odložení úlohy.
