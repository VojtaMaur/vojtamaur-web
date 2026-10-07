# Kandidáti, testy a cílený Docker běh — 0.3.3

## Deduplikace pouze v aktuálním běhu

Každý SDK submit_idea prochází společným hostovým zápisem. Existující přesná
hostem známá identita/exaktní text nebo explicitní update ID nevyvolá další modelové volání. Samotný agentem vymyšlený mechanism_key pro neznámou rodinu shodu nedokazuje. Nejasný nový
návrh porovná jediné krátké structured-output volání modelu model_tiers.cheap
s kandidáty tohoto běhu. Nejde o novou roli, handoff ani agenta ve scheduleru.
Porovnává transport/custody, ukládaný payload a způsob obnovy, ne shodu titulků.
Návrhy jsou nedůvěryhodná data; hodnotitel nemá nástroje ani externí oprávnění.

SAME připojí příspěvek k existujícímu ID, včetně autorství, původního wording a
evidence. Není to REJECTED. DISTINCT vytvoří samostatné ID a vyžaduje vysvětlení
věcného rozdílu. UNCERTAIN uchová návrh v pending_candidate_reviews v checkpointu,
manifestu/reportu a auditu; nevytvoří nafouknuté další IDEA. Agent může dodat
konkrétní rozdíl a znovu předložit návrh. Registry digest odmítne rozhodnutí nad
zastaralým stavem při souběhu. Limit porovnání je 32 aktuálních IDEA; větší registr
vyžaduje zúžení/ruční revizi, ne tiché vynechání starších kandidátů.
Nad 90 000 znaky porovnávacího vstupu se návrh odloží jako UNCERTAIN; popisy se
potichu nezkracují, aby se neztratil věcný rozdíl na jejich konci.

Volání hodnotitele má strop 800 output tokenů, žádné nástroje/search a jeden tah.
Používá stejný globální token/USD/runtime limit, durable reservation a účetnictví
pod skutečným cheap modelem. Neznámá spotřeba blokuje další dispatch stejně jako
u běžného modelového požadavku. Nesmí přepsat pracovní historii výzkumníka.
Host ověří návratový tvar, ID a aktuálnost; semantický závěr stále může být chybný
a jeho důvod se ukládá k revizi v auditu. Kontrola ARCHIVE.txt zůstává oddělená.

Nové research běhy mají semantic_dedupe=true a prior_work_policy=continue.
Předchozí generace jsou jen kontext, ne součást nového porovnávacího rozhodnutí
ani automatická stopka. Starší runy/ID/audit se zpětně nepřepisují.

## Co znamená PROTOTYPED

Uložený artefakt zůstává draftem v INVESTIGATING. Samotné tvrzení PROTOTYPED
host sníží. Správné pořadí: vytvořit soubory → submit_idea s jejich cestami →
run_experiment(argv, idea_id) → record_test(idea_id, experiment_id, assertions).
Host vyžaduje úspěšnou Docker execution stejného agenta/IDEA a inventář skutečných
deklarovaných artefaktů, jehož bajty odpovídají okamžiku experimentu. Export sám
je vstup, nikoli vytvořený prototyp. Změněné či dodatečně přidané soubory vyžadují
update a nové spuštění. Po record_test může host přidělit PROTOTYPED.

Receipt dokládá provedení a zachycené bajty. Správnost/význam assertions je třeba
posoudit; exit zero není nezávislá certifikace archivního mechanismu. PROTOTYPED
není deposit; COMPLETED kandidáta nadále vyžaduje hostem ověřené externí uložení.

## První test s levným modelem

V CMD s nastaveným OPENAI_API_KEY a běžícím Docker Desktop:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-smoke.cmd
```

Vytvoří nový izolovaný run. Prototyper + Reporter, gpt-5.4-mini ve všech tierech,
autonomous/sandbox-only, PyPI enabled, 4 kola celkem, 18 tahů/kolo, 500 000 tokenů,
20 minut aktivního času, maximálně dvě instalace. Bez live fetch nebo externích
depositů. Nejde o výzkum nového mechanismu: cílem je zpracovat skutečný export
pomocí cbor2, ověřit CBOR round-trip, skutečný hash a odmítnutí poškozených dat.

Úspěch vyžaduje v reportu skutečně dokončenou instalaci, úspěšný Docker experiment,
test receipt s konkrétními assertions a PROTOTYPED/prototype_tested=true.
Pouhé COMPLETED u agenta nebo počet vytvořených souborů nestačí. Pokud se proces
zastaví, pro pokračování použij resume s přesnou cestou vypsaného runu; další
run-smoke.cmd vždy vytvoří fresh run. Chybějící export má skončit konkrétním BLOCKED.

Po tomto cíleném testu pokračuj run-sandbox.cmd. Research profil nyní má 40 kol,
12 SDK tahů/kolo, Prototyper 6 kol, coordinator/reporter po 2 kolech. Tokeny
3 000 000 a aktivní čas 3600 sekund se nezvýšily. Delší tahy stále podléhají
420sekundovému timeoutu kola a globálním limitům.

## Ověření bez API klíče

Regrese používají skutečné Agents SDK a řízený lokální model pro rozhodnutí,
provenance, concurrency/stale registry a budget accounting. Další integrační
test dispatchoval SDK tools do skutečného PyPI a Dockeru: cbor2, skutečný 5282-byte
TXT export, round-trip/hash a odmítnutí poškození. Dva experimenty, jeden test
receipt, ověřený audit, žádné placené inference. Receipt v
validation/SDK_DOCKER_CHAIN.json. Ověřuje zapojení nástrojů, ne autonomní úsudek
gpt-5.4-mini; ten ověří následující run-smoke.cmd.

SDK structured output vychází z [OpenAI Docs](https://developers.openai.com/api/docs/guides/agents/define-agents).

## Smoke 0.3.5
Dokončený Reporter předává zbývající výzkum do handoff místo opakování reportu. Nezměněné exporty jsou vstupy a do prototype receipt se nepočítají, ani po přejmenování. Před finálním experimentem doplň na stejné IDEA skript a vytvořený specimen; jejich bajty musí odpovídat experimentu. Viz RUN_REVIEW_20261007_102933.md.

## 0.3.8 — méně evidence bookkeeping
run_experiment zachytí také spuštěný lokální .py skript a až 128 souborů jeho pracovní podsložky. Výstup lze přidat na stejnou IDEA po experimentu a pak použít jeho ID pro record_test, pokud se zachycené bajty shodují. Skript v kořeni zachytí jen skript, ne celý projekt; výstupy proto vytvářej v samostatné podsložce. Nezachycené nebo později změněné soubory stále vyžadují nový experiment. Exporty zůstávají vstupy. Skutečný SDK/PyPI/Docker test tohoto postupu je v validation/CAPTURE_DOCKER.log; provider byl řízený, bez placené inference.
