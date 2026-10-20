# Dokončení lokálního testu a reportu (0.6.12)

Posouzení receipt od 0.6.13 doplňuje [EVIDENCE_REVIEW](EVIDENCE_REVIEW.md):
auditor čte i výstupy, cituje skutečné executable cases a pro úplnou obnovu
kontroluje recovered artifact proti původním bajtům.

Běh `20261014-051545-9660ea73`: auditor uložil dva REVISE verdikty a skončil
za dvě kola. Tři Docker execution měly exit=0, ale žádný test receipt nebo
deposit. První script nevytvořil deklarovaný CBOR soubor, druhý pouze kontroloval
manifest a jeho `.out` byl předem napsaný placeholder. Orchestrátorovi blokoval
delegování text „Do not propose WACZ/WARCZ“. Reporter zaměňoval nehotový výzkum
za nehotový report. Dedupe rozlišilo pointer od uložení celého exportu u konkrétního
hostitele; tento rozdíl není automatická deduplikační chyba.

## Spuštění

Ve složce `G:\vojtamaur-web\scripts\metaweb-swarm` spusť v CMD nový research run:

```cmd
run-http.cmd
```

Model tiers, 40 kol / 3M tokenů / hodina, Docker network none a external human
approval zůstávají stejné. Placený běh se instalací opravy automaticky nespouští.

## Delegování a owner zákazy

Na **delegation request** se ignoruje jen úzká explicitní záporná věta typu
`Do not propose WACZ/WARCZ or recurring-payment-dependent options.`
Kladný návrh v mission/question/role/expertise/output zůstává zamítnutý.
Věta s výjimkou (`unless`, `except`) není povolenou zápornou klauzulí.
Globální owner pravidla se nezměnila a kandidáty stále kontroluje původní
striktní `owner_rejection`; negace ve skutečném IDEA návrhu zákaz neobchází.

## Cena před prototypováním služby

Discovery má nejprve přečíst primární pricing dokumentaci. Trial není trvale
FREE. UNKNOWN nápad zůstává pro výzkum/audit, ale nepřiděluje se prototyperovi
a propojený experiment jej neobejde. Zjištěné předplatné má discovery uložit
na stejný provider variant jako RECURRING / requires_ongoing_payments=true;
stávající policy jej zamítne, nikoli celý obecný preservation mechanism.
FREE/ONE_TIME lze prototypovat; skutečná platba stále vyžaduje approval.

Nejde o seznam provider connectorů nebo automatický webový pricing klasifikátor.
Úsudek o ceně je stále práce agentů nad skutečnými podklady. Například
[Transistor pricing](https://transistor.fm/pricing/) uváděl při kontrole
2026-10-14 předplatné od $19/mo a 14denní trial; nejde o free archivní cestu.

## Plán → jedna execution → receipt → nezávislé posouzení

1. Materializovat skutečný export a použít vrácenou workspace cestu.
2. Napsat script, který provede skutečný pozitivní a negativní test a **zapíše**
   deklarované output soubory. Omezení „netestuje hosting“ patří do limitations,
   ne do negative_assertion; místo toho testovat například odmítnutí corrupt input.
3. Uložit `record_prototype_plan` a spustit `run_experiment` s tímto IDEA ID.
4. Přečíst `prototype_readiness`. READY_FOR_TEST_RECEIPT znamená zavolat
   `record_test` se **stejným experiment_id**. Host sám připojí a zahashuje
   přesně script a plánované výstupy; není třeba registrace a bookkeeping rerun.
5. Nezávislý auditor čte neměnný script a posoudí FULL/SUBCOMPONENT/REVISE.

Host sleduje stav/hash/mtime výstupů před a po execution. Chybějící soubor nebo
předem napsaný nezměněný placeholder není generated specimen. Oprava znamená
změnit script, aktualizovat plán a znovu **skutečně** spustit kód. Chybové hlášky
obsahují missing_paths a unchanged_outputs. Tři opakované chyby u stejného
scriptu odloží úlohu, aniž by vymyslely test nebo rejection. Script změněný při
execution a artefakt změněný po execution nelze potvrdit starým receiptem.

Tato evidence dokládá pozorované vytvoření/změnu souboru, ne sémantickou
správnost, původ všech dat nebo poctivost scriptu. Scope musí pořád posoudit
auditor. Úspěšná execution ani automatická registrace neuděluje PROTOTYPED.
Staré neuložené execution potřebují nové spuštění podle nového capture contractu;
existující audit/test receipts se nemažou. Legacy/unplanned smoke postup zůstává.

## Report může být hotový i při neúspěšném výzkumu

Reporter přečte `get_research_task`, potom uloží `record_research_report` se
všemi současnými IDEA IDs (prázdný běh `[]`), závěrem a limitations. Host
zaznamená aktuální revizi a skutečné počty/statusy. Toto dokončí **reporter roli**,
nikoli run, kandidáty nebo externí uložení. Otevřená práce jde do handoff_leads.
Nová evidence může report znovu otevřít v původním allowance. Závěr je v reportu,
manifestu a checkpointu; raw audit zachovává původní modelové tvrzení.

## Ověření

Regresní testy ověřují také slova zákazu ve skutečně kladném zadání, chybějící
a předem vytvořené výstupy, změnu captured bytes, UNKNOWN pricing a skutečný SDK
dispatch reportera bez úspěšného depositu. Docker QA odděleně ověřuje skutečný
write/capture/receipt průchod. Simulované/modelově formulované assertions nejsou
důkazem nového archivního mechanismu. Konkrétní výsledky jsou v VALIDATION.md.
