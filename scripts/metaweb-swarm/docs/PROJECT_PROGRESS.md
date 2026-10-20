## 0.6.18 — opravný cyklus vlastní framework

- Model-facing plán nemá opravná ID; host je odvodí z aktuálního vlastního úkolu.
- Auditor před Dockerem čte zmrazený skript a kontroluje skutečný mechanismus.
- execute_prototype spojuje spuštění se zachycením testovacího záznamu.
- Čekání neplatí další LOCAL polling, dvě kola bez kódu/execution končí technickým odložením.
- Skutečný Docker replay původního WebVTT selhání a opravy, s reálným Metaweb EPUBem; skriptovaná rozhodnutí, bez placené inference.
- [Podrobný postup a meze](PROTOTYPE_WORKFLOW.md).

# Metaweb swarm — průběžný stav

## 0.6.4: opravitelné plánování a stage review

- Strukturované opravy header/binding/raw-body chyb a bounded retry stejného IDEA.
- Chybějící dedicated grant lze pojmenovat a uložit v plánu; execution zůstává zakázaný.
- Hotová planning-only role končí i při account/resource blokátorech kandidáta.
- PRE_DEPLOYMENT review nevyžaduje budoucí upload receipt; nevhodné kritérium se opravuje bez auto-PASS.
- Starý konkrétní header tool error aktuálního runu je rozpoznatelný při resume, žádné nové kolo discovery není nutné.
- Modely, grants, rozpočty a konfigurace zůstávají. [Detaily a CMD](PLAN_RECOVERY.md).


## 0.6.3: PDF jako skutečně přečtený podklad

- read_document / shared audit / negativní quote umí hashově ověřené textové PDF.
- Bounded proces bez děděných credentials; cache a receipts se source hash a čísly stran.
- Stejný cache GET může po doplnění parseru změnit SCREENED lead na doložený směr k auditu.
- Offline kopie skutečného OpenDrive PDF: 109 stran; handoff se obnovil, původní run nezměněn.
- Původní modely, configy, approval a rozpočty zůstávají. OCR není součástí.
- [Instalace, meze a CMD resume](PDF_DOCUMENTS.md).


## 0.6.2: rozpracované leads a předávání

- Povolený screen uloží LEAD; skutečné document reads připojí zdrojové receipts.
- Discovery zaznamená zjištění, otevřené otázky a další krok i před kvalifikací.
- Auditor posoudí doložený neúplný směr; setup není zamítnutí a QUALIFY není PASS.
- Skutečná ID vrací list_discovery_state; smyšlené QUAL ID vede k opravitelnému DEFERRED.
- Nové podklady zneplatní staré posouzení; follow-up jen jednou a v původním rozpočtu.
- Report + discovery_leads.jsonl + manifest + checkpoint + audit zachovají provenance.
- Stejné modely, USD/token/runtime limity, approval a externí oprávnění.
- [Podrobnosti a CMD](DISCOVERY_LEADS.md). Živý levný model zatím tímto novým průchodem neověřen.


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

## 0.4.0 — provider-independent HTTP hands
Generic public HTTPS request/JSON/multipart/raw file upload/download, scoped dedicated credentials, default approval with real opt-out, common external action budgets, HTTP body/request/runtime bounds, exact read-back evidence, pause/crash audit. No browser or ambient computer credentials. Hard forbidden mutations: GitHub/GitLab/Codeberg and production website. Legacy PUT uses same protections. Docs HTTP_ACCESS.md and project launcher run-http.cmd. 289-test suite passed (1 Windows privilege skip); additional final HTTP tests include unresolvedpayment and read-backtruthfulness. Real public HTTPS read of ARCHIVE.txt succeeded without anycredential or modelcall. Live model autonomous discovery/upload remains the next user-run validation.

Final 0.4.0 validation: 291 tests, 290 passed and one Windows symlink privilege skip; 20 final HTTP focused tests passed. Legacy credential/upload path also guarded. No paid inference or public writes were used for validation. HTTP read proof: validation/HTTP_PUBLIC_GET.json.

## 0.4.1 — targeted generic HTTP live-model smoke
Broad run 20261007-130930-03a208cf made zero generic HTTP requests; another broad replay would not validate the new tool. Added project-contained run-http-smoke.cmd and config.http-smoke.json: Prototyper learns ephemeral local service protocol, uploads/downloads harmless bytes and requests host SHA256 receipt; Reporter reads current observations. Completion requires observed docs GET + full read before upload + successful separate GET + exact byte equality. Local integration receipts do not create discovery candidates or inflate preservation deposits. Service/object lifecycle supports pause/resume; requests outside the fixture, credentials and other realization tools are blocked. No Docker, package installation, public uploads or browser. General research model tiers and budgets unchanged. Offline SDK/scripted-model tests pass; live-model behavior is the next operator validation.

0.4.1 validation: 297 tests ran, 296 passed, one Windows symlink privilege skip. Six new smoke tests include the real Agents SDK with a local scripted provider and real HTTP service, strict scope/receipt guards and durable restart/pause. No paid inference. See validation/HTTP_SMOKE_REGRESSIONS.log.

Live 0.4.1 validation: run 20261008-072242-11fc39f6 passed with gpt-5.4-mini, docs GET, upload, download and matching stored hashes; 2 rounds, 26,631 tokens, 9 model requests, 91 valid audit events. Zero archival candidates/deposits.

## 0.4.2 — public HTTPS interoperability smoke
Added configurable service docs/terms/origin grant without provider connectors. Agent constructs generic multipart upload, reads returned info/download URLs and requests host SHA256 receipt. One harmless synthetic TXT upload attempt per run; docs/terms must be fetched/read before upload, out-of-origin requests and other payloads/credentials forbidden. Old local smoke and general HTTP approval defaults retained. Host preflight performed one real public tmpfiles.org upload/read-back (115 bytes), no account/model/API key. Live agent test is the next operator step, run-http-public-smoke.cmd. Prepared dedicated guide HTTP_PUBLIC_SMOKE.md; public transfer success is not permanence/novelty.

0.4.2 regression validation: 303 tests ran, 302 passed and one Windows symlink privilege skip. Twelve focused local/public smoke tests include actual SDK scripted-provider dispatch, arbitrary multipart parameter learning, receipt/scope/one-attempt guards and paginated docs coverage. See validation/HTTP_PUBLIC_SMOKE_REGRESSIONS.log. No paid inference used.

## 0.4.3 — failed public smoke diagnostics
Run 20261008-075301-f0c7fcfa stopped before upload: both documentation/terms GET raised pre-response HttpTransportError; no public mutation occurred. Immediate repeat of the exact GET headers succeeded in the operator environment, so the original network fault is not reproducible. Old diagnostics suppressed the underlying connection/TLS cause. Added sanitized connect/TLS cause and known-before-send FAILED classification; UNKNOWN remains for uncertain effects and unclassified exceptions. Existing historical audit left intact; no TLS bypass or retries added.

0.4.3 validation: 305 tests ran, 304 passed, one Windows privilege skip. Exact original Accept headers replayed via ToolAPI: both API/ToS GET succeeded with HTTP 200, no uploads or paid calls. See validation/HTTP_DOC_DIAGNOSTIC_PROOF.json and HTTP_DIAGNOSTIC_REGRESSIONS.log.

## 0.4.4 — noncommercial test context and reporter handoff
Run 20261008-081608-919cf255 fetched/read API and ToS successfully, but Prototyper broadened the quoted commercial-automation restriction into all automation and stopped without upload. Public smoke assignment now explicitly states personal noncommercial use and asks the model to preserve restriction qualifiers; genuine applicable bans still block. Reporter now receives current role summaries and stopping reasons, not only HTTP metadata, so it can explain the actual blocker. No network permission/budget/approval changes, no provider connector or automatic override of a blocked decision. Historical run preserved.

## 0.4.5 — input preflight and explicit same-origin round trip
Run 20261008-082521-83618d8a correctly read terms as not prohibiting the noncommercial test, then stopped on an unchecked input availability claim; Reporter successfully read that input. Host now validates the private workspace specimen and exposes availability/size/hash before the model round. Assignment tells the agent to inspect the file before claiming it is missing and explicitly authorizes local inspection plus upload/download on the granted service. No extra permission gate, provider connector, budget increase or forced upload.

## Úspěšný živý veřejný test — 2026-10-08
Run `20261008-084548-bd404437` s gpt-5.4-mini dokončil čtení API/ToS, vlastní multipart POST, inspekci HTML informační stránky, samostatný download a host SHA256 receipt. Skutečné vstupní a stažené bajty se shodují (115 B); 5 HTTP požadavků, 2 agentní kola, 14 modelových požadavků, 105 380 tokenů, 140 ověřených auditních událostí. Oba agenti COMPLETED; žádné kandidáty ani preservation deposit nevytváří. Prokázána obecná veřejná HTTP práce živého levného modelu bez connectoru či účtu. Dočasná služba a malý syntetický vstup neprokazují dlouhodobé uchování, velké exporty ani schopnost samostatně vybrat neznámou službu.


2026-10-08: Připraven cílený real-export profil a projektový CMD spouštěč se čtyřmi cheap rolemi, $5 odhadovým API stropem, 40 minutami a jedním schvalovaným HTTP uploadem. Zadání se zachová v checkpointu přes operator_objective. Živý běh tohoto profilu zatím neproveden.


2026-10-08 / 0.4.7: první cílený trial bez uploadu; opraven crash smíšených HTTP/search source záznamů a konflikt explicitního zadání s obecnými rolemi. Limity beze změn. Viz [review](RUN_REVIEW_20261008_091804.md).


2026-10-08 / 0.4.8: Trial povoluje explicitně přidělené samostatné účty roje. Chybějící credentials znamenají konkrétní setup požadavek, ne zamítnutý mechanismus. Auditor má vlastní fázi před realizací; discovery nemůže udělit vlastní PASS, před uploadem se kontroluje nezávislé review. Žádné osobní účty/tokeny se nečtou; automatická registrace zatím není implementovaná.


2026-10-08 / 0.4.9: Run 20261008-102712-f4d9d5c7 stál odhadem $0.33385125 a bez uploadu zkoumal GitLab navzdory zákazu forge zápisů; kandidáta doplnil až Auditor. Přidána no-network kvalifikace konkrétního HTTP cíle/exportu/grantu, admission pouze od discovery s QUAL receipt, odlišení forbidden/setup/resource/baseline blockers, audit vázaný na plán a finální kontrola přesných export bytes před approval. Bez splněných předpokladů se nepouštějí zbytečné downstream modelové role. Testy zahrnují skutečný SDK a lokální HTTP upload/download/checkpoint s kontrolovaným providerem; žádné placené modelové volání nebo veřejný upload při vývoji.


## 2026-10-08 — 0.5.0: pracovní zadání a dokumentace, místo dalšího smoke

Run 20261008-110509-041e5dae spotřeboval 18 model requests / 248 759 tokenů, žádný search ani HTTP. Objevitel jen četl lokální stav a paměť; připravené admission/audit gates neměly co zpracovat. Oprava odděluje konkrétní úkoly a nástroje rolí a zkracuje kontext cíleného běhu. Obecná nová capability read_document kombinuje chráněný HTTP GET, čitelný text a auditní receipt, bez provider-specific integrace/browseru. Nové --task/--task-file umožní uživatelské výzkumné cíle uložené v checkpointu. Stávající modely, granty, approval a rozpočet zachovány. Následující run je opět reálný výzkum/upload plán; další smoke cyklus není požadován. [Spuštění a hranice](FOCUSED_TASKS.md).


## 2026-10-08 — 0.5.1: konkrétní kvalifikace a čtení podkladů mezi rolemi

Run 20261008-113459-2fb32e3b: 17 requests, 187 564 tokenů, 1 search, 5 HTTP (4 úspěšné), odhad $0.163693. Externí dokumentace už funguje. Kvalifikace však skončila ValueError kvůli chybějící upload_url/přidanému qualification_id v JSON stringu; objevitel zkoumal zakázaný GitHub a reporter hledal jiného agenta response_path ve svém workspace. Opraven typed named-fields kvalifikační tool, poctivé unresolved endpoint/auth receipts, baseline gap u nepodloženého KNOWN_CARRIER, konkrétní forbidden cíle ze skutečné executor policy a shared read-only hash-checked HTTP evidence. Opravy zachovávají resources/grants/approval a vlastní nezávislé čtení auditora. [Návod](SHARED_AUDIT.md). Další krok je znovu skutečný výzkum, nikoli opakování infrastruktury smoke.


## 2026-10-08 — 0.5.2: rychlá kontrola služby a uložená změna směru

Run 20261008-123103-808f0f46 zkoumal známý ArDrive i po ALREADY_KNOWN_BASELINE; žádná IDEA ani upload. Doplněn no-network screen konkrétní služby před dokumentací, konzervativní rozlišení registrovaného nasazení od zmínky a explicitní improvement. Odmítnutý nezměněný směr vyžaduje změnu služby v aktuálním kole a toto zadání přežije resume. Dokument reader vrací bezpečný Location jako konkrétní další GET, bez automatického následování nebo obejití TLS. Modely, budget a approval zachovány. [Spuštění, config a hranice](CARRIER_ROUTING.md); [run review](LAST_RUN_REVIEW.md).


## 2026-10-12 — 0.5.3: účetní settlement nejasného search po cap

Run 20261012-090514-8e491a42: 37 535 tokenů / 3 odpovědi, bez HTTP/IDEA/uploadu. Native API vrátilo extra searching item se zdrojem; konzervativní účetní počet 2 překročil deklarovaný search cap 1. Nový úzký settlement zachovává započítání, ale při známé odpovědi a token/USD spotřebě uvnitř původní rezervace tuto nejasnost uzavře. Reálné překročení/unknown zůstává blokované. [Podrobnosti, audit a spuštění](SEARCH_ACCOUNTING.md).


## 2026-10-12 — 0.5.4: uložený setup kandidát a návaznosti při resume

NudgeHost QUAL byl admissible=true/ACCOUNT_SETUP_REQUIRED, ale discovery jej neuložil a resume neobnovilo dříve přeskočené role. Host nyní na checkpointu zachová neověřený kandidátský draft, opakované předání využije stejné IDEA/provenance, návaznosti se přepočítají a reporter dostane novou evidenci. Nové operation_steps počítá celý protokol; tři operace nelze vydávat za jednu. Vícekrokový kvalifikovaný executor ještě není implementován a je poctivě označen MULTI_STEP_EXECUTION_UNAVAILABLE. Účty/limity/approval nezměněny. [Contract a pokračování](DEPOSIT_HANDOFF.md).


## 2026-10-12 — 0.5.5: audit jako hotová práce, protokol jako záznam

Resume obnovilo auditora/reportera, ale discovery jen opakovalo starý závěr a auditor proměnil REVISE na REJECT kvůli chybějícímu setupu. Nový typed review contract odlišuje mezery od doloženého mechanism failure a zachová původní requested verdict. Dokončený aktuální audit končí nezávisle na stavu kandidáta. record_deposit_flow je malý povinný první tool pro pending flow ve focused continuation, s explicitní UNKNOWN alternativou a host guardem proti pouhé naraci. Modely/peníze/tokeny/oprávnění zůstávají. [Contract a aktuální překážky](REVIEW_AND_FLOW.md).

## 2026-10-12 — 0.6.0: skutečné vícekrokové provedení bez provider connectorů

Přidán datový HTTP realizátor: zarezervovat, navázat JSON ID/signed URL, poslat exact-byte export, finalizovat, anonymně stáhnout a porovnat SHA256. Typed plán s přesnými originy vytváří novou kvalifikaci; staré PASS nestačí. Jeden konkrétní approval před první akcí řeší krátkou platnost upload URL, false nemá druhou lidskou brzdu. Celý zbývající postup má durable resource lease, každý HTTP pokus je předem svázán s FLOW/krokem. Pause/restart přeskočí dokončené operace, neznámé/expirující/chybné zastaví; žádný automatický rollback či slepé opakování. Podepsané odpovědi jsou v host-only vaultu (Windows DPAPI), mimo report/workspace. deposit-plan/deposit-execute dovolují datový postup připravit/vykonat bez inference. Ověřeno lokálními HTTP operacemi, restartem, SDK fake providerem a regresní sadou; žádný veřejný upload ani placený model. Stávající skutečný run, credentials, profily a limity se nezměnily. [Použití a hranice](DEPOSIT_EXECUTOR.md).

## 2026-10-12 — 0.6.1: provider-bound routing a nové služby

Run 20261012-120434-827d6ccf: žádná IDEA/QUAL/FLOW nebo upload, odhad $0,19555425. Zenodo registrované v ARCHIVE prošlo přes tři vyplněná improvement pole; jeho screen pokryl i neregistrované čtení známého Figshare. Cílený deposit profil nyní vylučuje všechny registrované služby i jako generic improvements. Read/qualification gate vyžaduje vlastní správný provider/origin screen, včetně dalších docs/API domén; auditor zůstává nezávislý. Jednoznačné DNS aliasy zachovají původní registry evidence. FREE versus autentizace odděleno v rolích; chybějící dedicated grant je BLOCKED setup kandidát. Prototyper instrukce odpovídají vícekrokovému executorovi a stávajícímu action cap 1. Modely, rozpočty, grants a approvals zachovány; skutečný run nezměněn. [Návod](CARRIER_SCOPE.md).


## 2026-10-13 — 0.6.6: opravy jednotlivých kroků a konec stejné chyby

Poslední čtyři paid rounds opravily prompt cap, ale opakovaly odkaz na neexistující reserve; celý-plan fingerprint po kosmetické změně resetoval guard. Nyní soukromý revision-bound draft, redigované čtení jednoho kroku a field edit s validací celé sekvence. Diagnostika ukazuje missing/available source IDs a vadný JSON. Tři stejné unresolved issues nebo dvě kola bez editace (i SDK yield) končí BLOCKED, automatická recovery je neotevře. Report uvádí konkrétní repair stav. Starý draft lze při resume obnovit jen z přesného fingerprintu již zaznamenaných argumentů. Na kopii skutečného běhu oprava source ID odkryla malformed confirm body; nejde o schválený upload plán. Žádná provider integrace, veřejný upload, přidělení credentials nebo změna rozpočtu. [Nástroje a pokračování](PLAN_EDITS.md).


## 2026-10-13 — 0.6.7: strukturované reference místo chybné syntaxe

Přidán obecný bind_deposit_step_response: source ID, response pointer a cílové pole jsou oddělené; host sestaví URL/JSON binding a znovu validuje celou sekvenci. Existující draft poskytuje strict SDK source enum. Literal path/query části se escapují stejným executorem. Staré prověřeně odmítnuté datové calls a draft reads se při SDK round archivují bez opakování v pracovním kontextu; externí/unknown operace nejsou tímto filtrem vybírány. Aktuální kvalifikace/permissions a úplný audit zůstávají. Popisy toolů už nenabízejí vymyšlené source IDs. Modely, profily a rozpočty nezměněny; starý run zůstává zastavený, další pokus lze založit běžným CMD launcherem. [Contract a spuštění](STRUCTURED_BINDINGS.md).


## 2026-10-13 — 0.6.8: konkrétní nezávislý review packet

Běh 084733 měl jen LEADy; auditor nepřečetl jejich primární sources a zkusil critique prázdného IDEA ID. Host nyní přiděluje jedno ID/revizi, exact doc URLs a relevantní rozsahy; SDK nástroje a URL enum odpovídají aktuálnímu zadání. Independent reads/coverage vedou k triage, zaznamenané triage uzavírá roli i s otevřenou kvalifikací. 404/TLS/parser failure končí technickým BLOCKED, nikoli mechanism rejection. Vlastní coverage/assignment přežijí resume. Web discovery a IDEA critique nejsou v LEAD packetu dostupné. Nejde o automatický verdict, nový connector ani upload. Modely/perms/globální budget nezměněny. [Contract a pokračování](REVIEW_TASKS.md).


## 2026-10-13 — 0.6.9: obecný výzkum a aktuální IDEA handoffs

Běh 094554 měl dvě IDEA, ale focused-only review tool vrátil NONE; CBOR pokus nebyl propojený a reporter vybral historický Google Drive lead. Obecné profily nyní zapínají research_handoffs: auditor dostane skutečné ID/revizi, prototyper registruje vlastní artefakty na přidělené IDEA a dokončí až s test receipt nebo konkrétním blockerem. Coordinator má roster/coverage, reporter aktuální ledger. Nové zadání může role znovu otevřít v původních limitech. Pořadí audit → prototype → report; bez external qualification pro lokální hypotézu. Scope, credentials, approvals, modely a globální rozpočty beze změn; žádný veřejný upload ani placené inference při ověření opravy. [Návod a contract](RESEARCH_HANDOFFS.md).


## 2026-10-13 — 0.6.10: aktuální task context a skutečný scope prototypu

Běh 112205 ukázal stale modelové zadání, JS testy v Python kontejneru, nefunkční JSON/fountain placeholder a nesouvisející QR test vedený pod Arweave. Nové task identity archivují předchozí historii a předávají čistý aktuální kontext. Prototype plan váže reálný export, script, specimen a pozitivní/negativní assertions; successful execution je oddělené od FULL_MECHANISM/SUBCOMPONENT/REVISE peer review. Vlastní celé script reads a neměnné SHA256 audit snapshots brání potvrzení pouze z agentního summary. Známá ARCHIVE vrstva musí být improvement, ne nový discovery. Evidence Auditor 2→6 kol; globální budgets, models a external approval/grants beze změn. [Contract a spuštění](PROTOTYPE_REVIEW.md).

## 2026-10-14 — 0.6.11: opravitelné chyby a omezené opakování

Běh 130738 sloučil DNS duplicitu, ale auditor opakoval PASS bez všech vlastních zdrojů a prototyper zaměnil export filename/workspace path a sáhl po deposit edit toolu. Audit packet a odmítnutý PASS nyní ukazují přesné chybějící URL; uznávají jen vlastní pozorované redirecty. Lokální plán vrací konkrétní opravitelné path chyby a materializované inputy, včetně format hint. LOCAL_IDEA nabídne deposit draft opravy až s vlastním draftem pro tuto IDEA; obecné HTTP/approval/upload nástroje zůstávají. Tři stejné unresolved validation issues odloží pouze aktuální úlohu bez vymyšleného verdiktu/testu a uvolní ostatní kandidáty. Data-only rejection history se archivuje; externí/unknown výsledky zůstávají. Checkpoint/report zachovává nezpracované úlohy. Modely, globální rozpočty a approvals nezměněny. [Návod](RESEARCH_RECOVERY.md).
## 2026-10-14 — 0.6.12: chybějící specimen není host porucha, neúspěšný výzkum není nehotový report

Běh 051545 měl dva REVISE audity, tři exit-zero execution a nula testů/depositů. Úzký delegation filtr rozlišuje explicitní zákaz od kladného zadání bez oslabení IDEA owner guardu. Planned capture sleduje přesné script/output soubory, jejich vznik/změnu při execution a následnou byte integrity; record_test provede registraci, bez bookkeeping rerun. Negative assertion nemůže být pouhá věta o netestovaných omezeních. UNKNOWN pricing je retained discovery/audit úloha, nikoli local implementation. record_research_report završuje report i s otevřenými kandidáty a nulovým výsledkem; nové evidence jej mohou znovu otevřít. Žádné nové provider connectors, modely, budgety, permissions či externí akce. [Návod](FLOW_COMPLETION.md).



## 2026-10-14 — 0.6.13: výstupy a skutečné cases před kladným scope review

Běh 070113 měl dva executed tests, ale první report říkal recovery_probe=False a
druhý neměl assertions a změnil původní CRLF bytes. Positive scope review nyní
vyžaduje vlastní čtení výstupů, skutečné Python executable cases a pro FULL
také captured recovered artifact se shodným original SHA256/size. Tři opakované
unsupported endorsements vedou k test REVISE, ne mechanism REJECTED; identický
REVISE script se znovu nespouští. Host syntax/read/hash guards nedokazují význam
nebo vykonání citované větve; independent judgment zůstává nutný. Přirozené
negace v delegování neblokují legitimní role a known-layer deferral předává
DISCOVERY_PIVOT se zachováním raw historie/permissions/budgetu. Modely,
globální limity a externí approval nezměněny. [Contract](EVIDENCE_REVIEW.md).


## 2026-10-14 — 0.6.14: povinné auditní volání a relevance lokálních testů

Běh 084150 měl čtyři execution a tři receipts bez jediného prototype verdictu;
auditor dočetl jen část prvního výsledku a skončil slovním endorsement. Host nyní
před každým SDK požadavkem určuje exact missing artifact range, pak požaduje
review_prototype_test i přes SDK tool-choice reset. Verdict vybírá auditor;
request accounting, čas/token/USD limity a externí oprávnění se nemění. Scheduler
upřednostní zaznamenané testy, chrání known review queue a poslední reporter kolo.
Auditor v nových research/http profilech 6→10 kol v původním globálním budgetu.
Ve stejném pre-audit critique určí mechanism-specific local_test_scope/goal nebo
DEFER. Tím se neověřený repository nenahrazuje manifest-copy testem, zachovává
se výzkumná hypotéza a external approval je oddělený. Explicitní report counts
pending/FULL/SUBCOMPONENT/REVISE odlišují execution od funkčního pokrytí.
Žádné provider-specific connectors, credentials, placená inference ani upload.
[Contract a spuštění](REVIEW_FINISH.md).


## 2026-10-14 — 0.6.15: selhaný kód dostává skutečnou diagnózu a opravu

Běh 105648 neměl RS decoder; tři pokusy opravovaly parser, nikoli chybějící
algoritmus. Nonzero planned LOCAL execution nyní ukládá immutable source +
traceback a předá řízení před dalším modelovým requestem. Stávající auditor
povinně čte zdroj a uloží diagnózu/kroky/decisive check; čekající lokální role
nespotřebovává další paid dispatch. REPAIR ji znovu otevře v původním budgetu,
DEFER uchová hypotézu bez rejection. Nový repair plán musí mít skutečně změněný
script (nebo novou instalaci chybějící knihovny) a explicitní vazbu/notes/check
k předchozímu failure. Context reset
archivuje staré parser guesses. V sandboxu je obecný implement/debug playbook
s reálnou RS recipe. Prototyper 6→8 v research/http profilech; modely, globální
40 kol / 3M tokens / hodina a external approval nezměněny.

Konkrétní použitelný artefakt zachoval celý skutečný EPUB (1 294 314 bytes),
obnovil jej z osmi errors i 24 indexed erasures na každý RS codeword a odmítl
beyond-capacity corruption. Nejde o otestovaný tisk/skenování nebo veřejnou
custody. Kód a modelové judgments v QA dodal Codex přes local fake SDK model.
Artefakt je mimo produkci v runs-root/manual-artifacts. [Návod](PROTOTYPE_DEBUG.md).


## 2026-10-15 — 0.6.16: REVISE je opravný úkol, reporter dostává stručný přehled

Dnešní běh měl exit-zero Commons fixture, ale auditor dal REVISE. Sedm dalších
kol prototypera nepřineslo opravu; reporter načetl 170 046 znaků v jediném
výstupu nástroje. Nový LOCAL_REVISION archivuje staré deklarace hotového testu,
vyžaduje vlastní čtení zmrazeného kódu/posudku a změněný script s explicitní
vazbou na původní test. Dvě kola bez změny implementace nebo nového výsledku
odloží lokální úkol a umožní další IDEA; hypotéza není REJECTED. Úspěšný opravný
běh se směruje na record_test, nikoli další run pro bookkeeping.

Reporter dostává omezené aktuální claims a přesné počty; plné jednotlivé
záznamy jsou dostupné stránkováním. Historické submissions/revisions a HTTP
headers nenafukují modelový kontext. Lokální packet také neopakuje historii
kandidáta. Modely, global/role budgets, oprávnění a dependencies beze změny.

Read-only replay skutečného běhu dokončil report a přešel z Commons na PWA.
Skutečný Docker/SDK průchod ověřil i implementovanou opravu a nový receipt,
s bezpečně omezeným SUBCOMPONENT úsudkem. Žádná placená inference ani veřejný
upload; kód/judgments v QA dodal Codex. [Návod](REVISION_AND_REPORT.md).


## 2026-10-20 — 0.6.17: skutečný payload a faktické posouzení lokální práce

Běh 061731 už správně přepínal úkoly a dokončil report; peer také úspěšně
opravil reálný Docker code bug. Další zásek způsobilo používání descriptoru
místo dostupného EPUB, přijaté phantom repair ID a nekonzistentní posudek
byte recovery/relevance. Nový prepare_prototype_input kopíruje skutečný
vhodný zachycený payload; FULL plán s descriptor-only vstupem je vrácen
k opravě scope nebo vstupu. Repair reference se kontrolují proti skutečným
vlastním aktuálním receipts před uložením a při další execution.

Reviewer po vlastních čteních dostává host identity/byte facts. Vyžaduje se
explicitní acknowledgment shody a konkrétní basis REVISE; external gap sám
nepopírá lokální komponentu. Rozpor se vrací k opravě; opakovaný rozpor je
technický INDEPENDENT_REVIEW_UNRESOLVED, nikoli code bug nebo scientific
rejection. Původní evidence gate, scoped judgment a external approval beze změn.

Read-only replay reálného běhu ověřil typed fact conflict/correction a actual
1.29MB EPUB copy. Starý descriptor-only test zůstává omezenou komponentou,
nikoli novou ověřenou archivní vrstvou. Žádná placená inference, public upload
ani změna configů, modelů, budgetů a původních výsledků. [Návod](PAYLOAD_AND_REVIEW_FACTS.md).
