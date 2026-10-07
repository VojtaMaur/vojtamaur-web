# Metaweb swarm — průběžný stav

## 0.3.4: Windows bind mounts a Reporter

První živý smoke odhalil nepodporované chmod na G: při exportu wheelu. pip nyní
build/install provádí na nativním kontejnerovém tmpfs, výsledné bajty přenáší do
private workspace. Reálný SDK/PyPI/Docker test na G: prošel. Reporter dostává
jen observation tools a samostatné zadání, nepřebírá implementaci Prototypera.
[Audit a další test](RUN_REVIEW_20261007_093936.md).

## 0.3.3: aktuální run, poctivý prototyp a cílený test

- Run-local submission gate: přesné shody kódem, nejasné jedním krátkým cheap
  modelovým voláním; provenance obou autorů zůstává, UNCERTAIN se uchovává k revizi.
- Historical dedupe se nerozšiřuje; nový research profil používá continue.
- PROTOTYPED až po host-linked Docker testu a artefaktech odpovídajících jeho bajtům.
- Research: 40 kol, 12 SDK tahů, 6 kol pro Prototyper. Tokenový/runtime strop beze změny.
- Nový run-smoke.cmd: dvě role s gpt-5.4-mini, PyPI/CBOR a skutečný export.
- Skutečný SDK→PyPI→Docker test s řízeným modelem již prošel; autonomní cheap model
  je další test, nikoli předstíraně hotové ověření. [Postup](CANDIDATES_AND_SMOKE.md).

Aktualizace 2026-10-07. Tento soubor patří frameworku pod `scripts/metaweb-swarm`.
Do dokumentace vojtamaur.cz se zatím nic nevkládá. Instalace: [README](../README.md);
oprávnění: [EXECUTION_MODES](EXECUTION_MODES.md); Docker: [DOCKER_SETUP](DOCKER_SETUP.md).

## Revize 2026-10-07 a modelové tiery

První živý autonomous sandbox run byl zkontrolován podle auditu a kódu:
[RUN_REVIEW_20261007.md](RUN_REVIEW_20261007.md). Docker fungoval; kvalita prototypů
je neúplná (pseudo-CBOR/JSON, neprovedená QR karta, duplicitní IDEA, nedokončená
syntéza). Tyto výsledky nejsou nově implementované baseline archivy.

Verze 0.3.0 přidává spouštěče přímo v projektu a [START_HERE.md](START_HERE.md),
modelové tiery po rolích (Loophole Archivist má flag; zatím vše mini), spotřebu a
cenové stropy po modelech, stručný průběh v konzoli, dvě dedup regrese a povinné
testované artefakty/exports. Koordinační, lokální a syntetické role nemají hosted
search; globální rozpočty se nezvětšují. Další levný acceptance teprve potvrdí
věcnou kvalitu výsledků a ukončování rolí. Veřejná dokumentace webu se nemění.

## Cíl

Verze 0.3.1 přidává [libovolné pojmenované PyPI packages](PACKAGES.md): online
build bez projektu/exports, offline instalaci do soukromé `.packages`, limity,
checkpointy, stručné konzolové zprávy a auditní receipts. Skutečný Docker test
Pillow/qrcode/cbor2 prošel včetně QR PNG, CBOR round-trip a přetrvání po reopen.
Tato změna nespustila placený výzkumný run ani nezvýšila jeho rozpočty.

Zadat čas a rozpočet, nechat roj hledat a uskutečňovat nové preservation mechanisms
a vrátit se k reportu odlišujícímu návrhy, ověření, zamítnutí, prototypy, testy a
skutečně uložené kopie. Prioritou jsou veřejné buildy a hotové exporty webu;
úpravy produkčních zdrojů se vracejí pouze jako reviewable patch.

## Základ a nově doplňovaná vrstva

- Soukromé kopie agentů, seed/emergentní role, zachycený vlastnický kontext,
  checkpointy/pause-resume, SQLite audit a samostatný report.
- Evidence novosti přes konkrétní podklady; Piql/AWA a další existující vrstvy
  nejsou nové objevy. Vlastníkova odmítnutí v `REJECTED_IDEAS.json` jsou trvalý vstup.
- Canonical mechanism keys a zachované příspěvky jednotlivých agentů řeší
  opakované S3 Object Lock/ORCID kandidáty. Neznámé podobné texty se nefúzují jen
  podle neurčité podobnosti; lze jim dát stabilní key/scope a kontrolovat konflikt.
- Import veřejných exportů s hashy a krátká paměť minulých běhů bez změn starých ledgerů.
- Nezávislé supervised/autonomous, sandbox-only/external a approval nastavení.
  Zaznamenaná kritika, navázané testy, rezervace akcí a read-back receipts.
- První free connectory: oddělená složka a konfigurovaný HTTP PUT endpoint.
  Účty, platby a specifické poskytovatelské integrace zatím nejsou implementovány.
- Docker Desktop a připravený image jsou nainstalované; skutečný Linux sandbox
  prošel sedmi kontrolami izolace, výstupů, limitů a úklidu bez API volání.
  Podrobnosti a receipts jsou v Docker dokumentu. Broker následně prošel živým
  dependency smoke testem na běžícím Dockeru.

## Ověřování před dražšími modely

Revize 0.3.2: [běh 071555](RUN_REVIEW_20261007_071555.md) skončil před všemi
Docker prototypy kvůli započtení ignorovaného pending search po capu jako
čtvrtého hledání. Opraven společný SDK/host čítač, stop scheduleru při skutečném
UNKNOWN, composite QR/XMP dedup a [strukturovaná paměť generací](GENERATION_MEMORY.md).
Výzkumný profil je novelty-first; dobré nerealizované hypotézy zůstávají retained,
ne REJECTED. Koordinace nezasévá opakované discovery kandidáty. Modely/budget
se nemění. Kvalitu levného modelu musí ještě potvrdit nový placený acceptance run.

Pořadí: skutečný Docker smoke test → supervised výzkum bez realizace → autonomous
sandbox prototyp/test → neškodný externí test do vlastní oddělené složky/loopback
serveru → limity → pause/resume → kontrola auditních receipts a reportu.

Regrese používají lokální fixtures a skutečné SDK schema bez placeného modelu.
Lokální HTTP test není důkaz dostupnosti archivní služby; mock není živý Docker test.
Výsledky konkrétní instalace a každého živého testu se přidávají do auditních artefaktů.
Aktuální dokončené testy a instalaci je nutné hodnotit podle těchto receipts, nikoli
jen podle seznamu schopností v dokumentaci.

## Otevřené věci

- Doplňovat image pro potřebné systémové knihovny/kompilátory. Python závislosti
  již instaluje broker; experimenty nemají Internet ani hostitelské credentials.
- Vynutit skutečnou diskovou kvótu writable prostoru; nyní není implementována.
- Ověřit celý realizující flow na levném modelu; až poté zvyšovat model a rozpočet.
- Doplňovat concrete providery a resource capabilities podle skutečných nápadů,
  s ověřitelným deposit/read-back. Obecný executor účtů/plateb není hotový.
- Cenové stropy a rezervace poskytují rozpočtový odhad; skutečná faktura není
  nezávisle měřena. U nového modelu aktualizovat konzervativní jednotkové ceny.

Loophole Archivist má hledat, jak hotový web „v nějaké podobě narvat do škvír
internetu“: konkrétní příležitost, payload, obnovu a důkaz, ne jen znovu pojmenovat
repozitář. Kreativita sama nezaručí úspěšný mechanismus.

## 0.3.5 — actual smoke review
Successful live cbor2/Docker/export round-trip. Fixed finished Reporter reopening and input-only prototype receipts; clarified historical/current smoke scope. See RUN_REVIEW_20261007_102933.md. Budgets and model tiers unchanged.

## 0.3.6 — smoke completion acceptance
Live 0.3.5 produced the specimen but omitted record_test after correcting artifact paths. Smoke completion now requires the actual host test receipt; compact reporting context contains test/experiment receipts. See RUN_REVIEW_20261007_104559.md.

## 0.3.7 — recoverable test receipt errors
Run 20261007-105654-feb8a73b: Docker passed, but agent reused the old experiment after updating artifacts. Receipt correctly refused; Reporter accurately reported no test. record_test now returns RETRY_REQUIRED with explicit new-experiment instructions for artifact-capture errors. Pending recovery prevents a smoke BLOCKED decision from prematurely ending repair, within existing round/token/runtime limits. Genuine package or execution blockers remain BLOCKED. Historical run unchanged.

## 0.3.8 — capture script output at execution
Run 20261007-110705-87b045a2 again updated artifacts after execution without rerunning. Experiment now captures local .py script and files in its confined subdirectory (bounded 128 paths), enabling post-execution artifact declaration with exact hash binding. Root scripts capture only the script to avoid scanning the whole project. Files changed afterward still require a fresh experiment. Unchanged exports remain inputs. No receipt is invented for old experiments.
