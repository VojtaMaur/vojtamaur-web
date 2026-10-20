## 0.6.18 — 2026-10-20

Nové regresní případy: host-owned repair IDs, nezávislá kontrola relevance před
spuštěním, immutable code, automatický a opakovatelný test receipt, zastavení
cyklu bez pokroku a skutečné SDK schéma bez repair ID polí.

Reálný Docker: původní ITEM_DOCUMENT chyba reprodukována; po opravě exit 0,
WebVTT načten ze specimen, obnoven omezený textový fragment a odmítnut vadný
cue. Dvě skutečná spuštění bez sítě, automatické párování i receipt, opakování
bez dalšího Dockeru. Původní run nezměněn. Skriptovaná rozhodnutí nejsou test
autonomní schopnosti modelu. [Důkaz a omezení](docs/PROTOTYPE_WORKFLOW.md).

## 0.6.18 — 2026-10-20

Kompletní offline sada: 579 testů, OK (1 Windows symlink skip). Finální
cílená sada po úpravě přerušení/receiptu: 35 testů, OK; předchozí sada
handoff/review/resume: 41 testů, OK. Testy privátního úložiště byly spuštěny
s funkčním Windows DPAPI; sandbox, který DPAPI blokuje, je neumí dokončit.

Nové regresní případy: host-owned repair IDs, nezávislá kontrola relevance před
spuštěním, immutable code, automatický a opakovatelný test receipt, zastavení
cyklu bez pokroku a skutečné SDK schéma bez repair ID polí.

Reálný Docker: původní ITEM_DOCUMENT chyba reprodukována; po opravě exit 0,
WebVTT načten ze specimen, obnoven omezený textový fragment a odmítnut vadný
cue. Dvě skutečná spuštění bez sítě, automatické párování i receipt, opakování
bez dalšího Dockeru. Původní run nezměněn. Skriptovaná rozhodnutí nejsou test
autonomní schopnosti modelu. [Důkaz a omezení](docs/PROTOTYPE_WORKFLOW.md).

# Validation — 0.3.4, 2026-10-07

Windows bind-mount fix: 262 regression tests, 261 passed, one Windows symlink
privilege skip. Log: docs/validation/BIND_REGRESSIONS.log. New tests simulate
unsupported chmod without ignoring actual byte-copy failures, check native pip
staging/mount isolation, and verify Reporter gets observation tools only.

Real SDK/PyPI/Docker integration on G: passed after the live smoke exposed EPERM
in pip copymode. cbor2 6.1.5 downloaded and installed; byte export tolerated 1
fetch and 16 install mode updates unsupported by the Windows mount. Actual
5282-byte export round-trip/hash/corruption checks succeeded, two experiments,
one test receipt, audit verified. Scripted model, zero paid inference. Receipt:
docs/validation/BIND_SDK_DOCKER.json. New live cheap-model run remains next.

Previous validation:

Candidate upgrade: 259 regression tests, 258 passed, one Windows symlink privilege
skip. Log: docs/validation/CANDIDATE_REGRESSIONS.log. Eight new gate tests cover
actual DNS duplicate wording with retained contributors, materially different
payload (including a misleading identical agent family label), uncertain proposal retention, stale/unknown target, untested draft,
successful promotion and changed artifact refusal, and real SDK cheap-model
accounting/history preservation (scripted responses, no paid inference).

Real SDK tool dispatch to real PyPI/Docker passed: cbor2 installed, actual public
5282-byte TXT export encoded and decoded with SHA256 equality, modified payload
rejected. Two Docker experiments, one test receipt, candidate PROTOTYPED only
after record_test, production input unchanged, network denied/key absent, audit
verified. Receipt: docs/validation/SDK_DOCKER_CHAIN.json. The model decisions were
scripted, not GPT inference. run-smoke.cmd is the next cheap-model autonomy test;
no OPENAI_API_KEY is available in this Codex process. No live research/deposit
or paid model call was performed during this upgrade.

Earlier validation follows as historical evidence:

Generation upgrade: replay of the actual recorded AGENT-005:8 response classifies
three completed searches and the ignored resultless pending attempt after the
configured provider cap. Both real QR/XMP candidate descriptions now resolve to
one card mechanism independently of their embedded ORCID attribution. The latest
bounded prior inventory contains 40 candidate observations with original refs.
Receipts: `docs/validation/GENERATION_REPLAY.json` and final installed
`GENERATION_REGRESSIONS.log`. New tests exercise real SDK tool/schema forwarding,
cross-run deferral versus local continuation, provenance, prior candidates beyond
the first three titles, and stopping UNKNOWN reservations without dispatch cascade.
Actual over-bound, failed, incomplete and orphan usage still fails closed.
Final installed suite: 251 tests, 250 passed and one Windows symlink-permission
skip. Owner rejections remain REJECTED even when the mechanism appears in prior
work; novelty-first never weakens this binding policy.
Models, global token/runtime/USD settings, owner permissions and old ledgers are
preserved. No paid API request was made. A new cheap live run is still required
to assess research quality; replay/regressions cannot establish that quality.

## Historical validation — 0.3.1

The dependency upgrade adds any named PyPI package, extras/version requirements,
an isolated online wheel build and an offline persistent workspace installation.
There is no package whitelist or individual approval after this capability is
enabled. Research profile settings supplied by the owner are preserved.

The real Docker smoke test installed Pillow 12.3.0, qrcode 8.2 and cbor2 6.1.5;
tested a real CBOR round-trip and QR PNG; reopened the workspace in a new
container and imported the packages again. Experiment network access was denied,
credentials/socket were absent, containers were removed, and the production-style
fixture stayed unchanged. Receipts: `docs/validation/PIP_DOCKER_INSTALL.json`,
`PIP_DOCKER_EXPERIMENT.json`, `PIP_DOCKER_REOPEN.json` and `PIP_DOCKER.log`.

New offline coverage exercises SDK argument/schema forwarding, arbitrary names,
invalid URL/path/option rejection, isolated mounts, wheel hashes, bounded output,
limits, supervised selection, cancellation cleanup/error receipts, unfinished
operation blocking, checkpoint/report/manifest persistence and exclusion of
installed libraries from production review patches. The final installed suite
is retained in `docs/validation/PIP_REGRESSIONS.log`: 241 tests, 240 passed and
one Windows symlink-permission skip; junction/reparse guards ran. No paid API calls or
model research run were made during this dependency upgrade. Public website
documentation and historical run ledgers were not edited.

## Historical validation — 0.3.0

Installed framework: `G:\vojtamaur-web\scripts\metaweb-swarm`.
The final complete installed regression suite passed 231 checks: 230 successful,
one symlink creation check skipped because this Windows token lacks permission.
Windows junction/reparse guards ran. Model/pricing/legacy reconciliation checks
and both project-owned launchers were verified against the installed framework.

Receipts are copied into `docs/validation/` so this record survives deletion of
the Codex chat workspace. `REGRESSIONS.log` records the installed suite;
`MODEL_TIERS.log` records latest model/legacy-reconciliation checks;
`SANDBOX_LAUNCHER.log` and `SUPERVISED_LAUNCHER.log` record real Windows CMD
launchers against a separate offline fixture. Sandbox fixture ends BLOCKED due
to deliberate demo human-action examples; supervised fixture completes research
without rejecting deferred implementations. These are not live research runs.

New coverage includes per-agent SDK model routing through three injected local
models, model and usage persistence across reopen, USD prices per actual model,
aggregate/model accounting consistency, safe legacy reconciliation, global CLI
model override, missing-key fail before initialization, reporter completion when
discovery search reservation cannot fit, CC REL scope aliases, exact QR duplicate
claims with differing keys, immutable provenance, and rejection of unbound test
receipts. No paid OpenAI request was made during this upgrade.

Docker daemon/image readiness was checked read-only with normal host permissions:
`metaweb-swarm-experiment:local` is available. No new container was started for
this upgrade. The two actual containers from the reviewed live run and their
prototype limitations are documented in `docs/RUN_REVIEW_20261007.md`.
New model tiers all remain `gpt-5.4-mini`; global budgets and external scope are
unchanged. A fresh cheap live run must still confirm research quality, standards
fidelity and the improved role finishing behavior. These are not proven by mocks.

Reviewable source patch, installation hashes and pre-upgrade backups were also
saved in the original task outputs. This project's launchers/instructions have
no runtime dependency on those files. Public website documentation was untouched.

## Historical validation — 0.2.0


Installed framework: G:\vojtamaur-web\scripts\metaweb-swarm.
217 regression tests: 216 passed, one skipped because this Windows token cannot
create symbolic links. Windows junction/reparse guards were actually exercised.
Receipt: AUTONOMY_INSTALLED_TESTS.txt in the task's outputs directory.

Coverage includes SDK 0.23.1 with a local fake model, independent execution modes,
research completion without implementation, real temporary-file deposits with
approval on/off, loopback PUT/GET read-back, credentials isolation, redirect/error
handling, process deadline against drip-fed HTTP, global request reservations,
unknown/crash recovery, action and byte caps, pause/resume, hash-chain audit,
public export copies over 20 MB, cross-run read-only notes, and S3/ORCID dedup with
provenance and provider/scope separation. Fake model calls cost zero USD.

Docker Desktop 4.94.0 and the local experiment image were installed during setup.
Seven real Docker smoke checks passed at that time: non-root user, no host secrets,
read-only root/network denial/tmp noexec, cgroup limits, timeout/OOM/output bounds,
private-file changes with reviewable patch, and complete container cleanup.
Receipt: DOCKER_SMOKE.json. This is historical evidence; it does not claim the
operator currently has Docker running. No further Docker startup is needed for
this regression suite.

No paid OpenAI request, real archive-provider upload, payment, or production
experiment was made. Live cheap-model acceptance of the new API settings and
the whole discovery-to-deposit flow remains the next test phase. Initial deposit
connectors are free configured local-directory/HTTP PUT resources; account and
payment executors are not implemented. USD enforcement depends on correct
operator price ceilings/search bounds. Writable Docker bind mounts still lack
a hard disk quota. These are open work, not passed tests.


2026-10-08 / 0.5.0: 328 regression tests, OK (one Windows symlink-permission skip), including 7 new focused task/document tests and actual SDK dispatch through a controlled model. No provider inference/public upload. Evidence: docs/validation/FOCUSED_TASKING_REGRESSIONS.log; original focused subset: FOCUSED_TASKING_TARGETED.log (40). New profile requires a user-run real research execution to assess model behavior; transport and task persistence are tested independently.


2026-10-08 / 0.5.1: 336 regression tests, OK (one Windows symlink-permission skip). Named-field qualification including unknown endpoint/auth; shared public HTTP read with hash/tamper/private/traversal checks; SDK dispatch; independent audit and exact approval retained. Actual old-run 20261008-113459-2fb32e3b: all four successful public GET artifacts readable by new legacy reader without modifying the run or HTTP. Evidence: docs/validation/AUDIT_QUALIFICATION_REGRESSIONS.log; old-run proof in Codex outputs/AUDIT_QUALIFICATION_LEGACY_PROOF.json. Subsequent targeted report checks cover shared audit artifact inventory and qualification summary. No paid model inference/public deposit by development process.


## 0.6.9 — obecný výzkum a aktuální IDEA handoffs (2026-10-13)

485 regresních testů prošlo (1 skip). Devět nových kontrol ověřuje broad SDK dispatch, skutečné ID/revize pro audit, vlastní zdroje pro PASS, zákaz unlinked/nesprávného Docker IDEA, nehotový exit-zero placeholder, atomickou registraci a provenance artefaktů, propojený test, checkpoint/blocker recovery a aktuální report. SDK a model response byly simulované, Docker transport v těchto regresích mockovaný; nevydáváme to za důkaz skutečných nových mechanismů. Read-only replay posledního runu vrátil obě skutečná IDEA auditorovi/reportérovi, 0 testů, prompt pod operátorským limitem a kompatibilní lokální SDK. 0 placených API volání a 0 veřejných uploadů. Modely, credentials, oprávnění i globální budgety se nezměnily.


## 0.6.10 — task context, kontrakt a posouzení prototypu (2026-10-13)

Celá regresní sada: 496 testů, 1 skip, prošla. Poslední zpřesnění přímého test command bindingu ověřeno 41 cílenými testy včetně nového případu; aktuální sada obsahuje 497 testů. SDK konstrukce/schema kompatibilní s instalovanými verzemi. Proveden skutečný networkless Docker test nad 5282 bajty zachyceného veřejného exportu: round-trip bytes/SHA256 a odmítnutí tamper payload prošly. Probe potvrdil Python 3.11.17 a absenci Node/npm. Test neměl PROTOTYPED před coverage review; QA simulovala reviewer identity a manuální posouzení kontraktu, nikoli nezávislé placené LLM inference. Neměnné snapshoty a SQL audit ověřeny. Read-only replay posledního reálného runu odstranil nepodložený Arweave prototype claim jen v paměti, zachoval execution receipt a zachytil Arweave jako EXISTING_ARCHIVE_LAYER; původní checkpoint se nezměnil. 0 placených API volání a 0 veřejných uploadů.

## 0.6.11 — konkrétní diagnostika a opravy výzkumu (2026-10-14)

Celá regresní sada: 508 testů prošlo, 1 skip kvůli Windows symlink oprávnění.
Poslední zúžení tool nabídky (HTTP/execute zůstává, deposit draft opravy až s vlastním draftem) následně prošlo 32 cílenými kontrolami včetně skutečného SDK dispatch; globální sadu jsme kvůli tomu neopakovali.
Jedenáct nových kontrol ověřuje vlastní chybějící zdroje, skutečně pozorované
redirect aliasy, odlišné URL/query, omezené opakování bez verdiktu, přechod na
další kandidát, zotavení po pokroku/operator note, přesné materializované cesty,
zákaz unsafe path, checkpoint/report, zachování external/UNKNOWN historie a
skutečný SDK dispatch přes simulovaného providera. Tyto kontroly nevypovídají
o kvalitě modelových nápadů. Log: Codex outputs/RESEARCH_RECOVERY_REGRESSIONS.log.

Skutečný networkless Docker test nad kopií 13 800 bajtů původního veřejného
Metaweb JSON manifestu prošel: chybný input_path vrací opravitelnou diagnostiku,
plán lze znovu uložit se správnou cestou, json.loads načte JSON, envelope
round-trip zachová přesné bajty/SHA256 a poškozený payload je odmítnut.
Review byla manuální host QA se simulovanou reviewer identity, nikoli placené
nezávislé LLM posouzení. Evidence: Codex outputs/RESEARCH_RECOVERY_DOCKER_PROOF.json.

Read-only replay skutečného runu 20261013-130738-d39be211 ukázal šest chybějících
citovaných URL a správnou materializovanou cestu metaweb_manifest.json v nové
diagnostice; původní soubory runu zůstaly stejné. Žádné placené API volání,
veřejný upload ani produkční experiment. Modely, globální budgets a externí
approval/grants se nezměnily. Praktické využití oprav malým modelem ověří
další uživatelem spuštěný research run.

## 0.6.12 — dokončení lokálního testu a reportu (2026-10-14)

Celá regresní sada: 517 testů, 1 Windows symlink skip, prošla. Devět nových
kontrol pokrývá negované versus kladné delegation zadání, zachování owner
zákazů, jeden planned execution + automatickou registraci při record_test,
chybějící výstup a skutečnou opravu scriptu, prewritten placeholder, změnu
captured bytes, negativní assertion versus pouhé limitations, UNKNOWN pricing
a dokončení reportera nad otevřenými kandidáty bez testů/depositů. SDK používá
kontrolovaný fake provider, nikoli placené inference. Log: Codex
outputs/FLOW_COMPLETION_REGRESSIONS.log; cílená sada měla 41 kontrol.

Skutečný networkless Docker QA nad kopií 13 800 bajtů veřejného manifestu:
exit-zero bez specimen byl označen PROTOTYPE_OUTPUTS_REQUIRED; opravený script
provedl JSON parse, exact-byte/SHA256 round-trip a corruption rejection.
Jedna úspěšná specimen execution stačila k test receipt bez manual registration
či bookkeeping rerun. Reporter receipt dokončil roli. Post-execution scope
review byla manuální host QA se simulovanou reviewer identity, ne nezávislé
placené LLM posouzení. Nejnovější read-only replay původního runu potvrdil
opravu skutečné negované delegation, detekci původní neplatné negative assertion,
UNKNOWN payment defer a uzavření reportera; soubory runu se nezměnily.

Přenosná evidence: docs/validation/FLOW_COMPLETION_PROOF.json. Žádné placené
API volání, veřejný deposit, zápis produkčního experimentu, přidělení credentials
nebo změna modelů/globálních budgets/externích oprávnění. Kvalitu dalšího
výzkumu malým modelem musí ukázat nový uživatelem spuštěný run.


## 0.6.13 — skutečné output evidence (2026-10-14)

Celá offline regresní sada: 528 testů, 1 Windows symlink skip, prošla. Jedenáct
nových kontrol pokrývá přirozené negace versus pozitivní/exception delegation,
quoted executable cases, script-only read, skutečný failed probe v textu/JSON,
bounded unsupported approval -> REVISE, raw-byte mismatch, FULL recovered path,
identický failed-script rerun, známý směr/future note a archivovaný pivot context
se zachovanou UNKNOWN externí akcí. SDK schema/interface check: openai-agents
0.23.1, openai 3.24.0, pydantic 2.13.5; bez síťového provider volání. Finální
cílená sada po doplnění exception negací: 32 testů prošlo.

Skutečný networkless Docker QA použil 28 865 bajtů kopie retained manifestu s
CRLF. Encoder/decoder obnovil původní bytes+SHA256 a záměrně pozměněný encoded
payload byl odmítnut. Jedna execution vytvořila immutable script, specimen,
recovered file a report; script-only approval selhalo a approval prošlo až po
output reads a executable cases. Scope verdict bylo ruční host QA se simulovanou
reviewer identity, nikoli placené nezávislé LLM posouzení nebo nový mechanismus.
Samotné nové review volání prošlo skutečným SDK function tool rozhraním.

Read-only replay runu 20261014-070113-32f0e632 potvrdil obě skutečné delegation
negace, recovery_probe=False, chybějící assertions a chybnou byte identity druhého
scriptu. Kontrolované původní soubory se nezměnily; historické verdikty nebyly
přepsány. Přenosná evidence: docs/validation/EVIDENCE_REVIEW_PROOF.json.
Log: Codex outputs/EVIDENCE_REVIEW_REGRESSIONS.log. Žádné placené API inference,
veřejný deposit ani produkční experiment; modely, limity a oprávnění nezměněny.
Vliv opravy na další skutečný výzkum ověří uživatelem spuštěný run-http.cmd.


## 0.6.14 — dokončení auditu a mechanism-specific prototype focus (2026-10-14)

Celá offline sada: 538 testů, 1 Windows symlink skip, prošla. Deset nových
kontrol ověřuje exact output paging, live SDK tool_choice READ→REVIEW→normal
po SDK resetu, token hard-stop před modelovým voláním, DEFER bez rejection,
aktuální focus/revision/scope, skutečné SDK focus arguments, ochranu známé
review fronty/posledního reportera a explicitní pending review counts.
Log: Codex outputs/REVIEW_FINISH_REGRESSIONS.log.

Skutečný Docker QA s network none zakódoval 28 865 původních manifest bytes do
XML metadata SVG. Decoder četl právě vytvořené SVG, obnovil původní bytes a
odmítl truncated XML. Jedna execution vytvořila specimen, decoded bytes a
report. Skutečné SDK s lokálním fake modelem následovalo sedm required artifact
reads, povinný review call a final response; review receipt i role completion
byly zaznamenány. Scope judgment je fixed host QA, nikoli placené nezávislé LLM
posouzení nebo nový preservation mechanism. Původní byte data nebyla použita
místo skutečného decoder output.

Read-only replay 084150 ukázal dva konkrétní chybějící rozsahy souboru
broken-recovery.json, potom povinné review volání. Host nevybral verdict;
22 kontrolovaných původních souborů a historické výsledky zůstaly beze změny.
Evidence: docs/validation/REVIEW_FINISH_PROOF.json. SDK interface kompatibilní
s openai-agents 0.23.1 / openai 3.24.0 / pydantic 2.13.5. Globální modely/budgety,
externí approval a resource grants zůstávají stejné. Žádné placené modelové API,
veřejný deposit nebo produkční agentní experiment při QA. Skutečnou výzkumnou
kvalitu levných modelů dál ověřuje uživatel novým run-http.cmd.


## 0.6.15 — funkční oprava kódu a RS export artefakt (2026-10-14)

Celá offline sada: 546 testů, 1 Windows symlink skip, prošla. Devět finálních cílených kontrol
ověřuje immutable failed source, vlastní čtení a nezávislost diagnosis, hold/reopen
bez paid rerun, změněný code nebo doloženou instalaci dependency + repair notes/check, DEFER bez rejection,
čistý repair context a skutečné SDK READ→DIAGNOSE. SDK po failed tool outcome
předá řízení před druhým modelovým požadavkem s úplnou známou usage/history.
Log: Codex outputs/PROTOTYPE_DEBUG_REGRESSIONS.log.

Skutečný Docker/PyPI průchod použil nefunkční script posledního user runu,
nezávislou diagnózu a opravu se skutečnou reedsolo 1.7.0 dependency. Celý EPUB
(1 294 314 bytes) se obnovil z osmi změněných bytes i 24 indexed erasures v
každém RS codewordu, s původním SHA256. Nadměrné poškození i malformed frame
byly odmítnuty. Změna dekodéru třídí erasure positions po blocích, aby nevzniklo
opakované globální skenování. Výsledek vznikl v jedné úspěšné execution po
jednom failed experimentu; úspěšný test receipt nevyžadoval další execution.
Modelové diagnosis/repair/scope judgments dodal místní fake provider; kód napsal
Codex. Neprokazuje to samostatnou schopnost cheap modelu implementovat algoritmus.
Původní stopped run zůstává beze změn.

Aktuální SDK schema/interface: openai-agents 0.23.1, openai 3.24.0,
pydantic 2.13.5. Žádné placené modelové API, public deposit, použití osobních
host accounts ani produkční agentní experiment. Artifact a požadavky jsou v
G:/metaweb-swarm-runs/manual-artifacts/rs-recovery-20261014-v0615. Přenosná evidence:
docs/validation/PROTOTYPE_DEBUG_PROOF.json. Scope je otestovaný RS payload
SUBCOMPONENT; žádný tisk/optika/unindexed-deletion recovery/custody claim.


## 0.6.16 — oprava po REVISE a omezený reporter (2026-10-15)

Počáteční celá sada: 558 kontrol, 518 prošlo, 1 Windows symlink skip. Dalších
39 kontrol private response vaultu/plan editů selhalo kvůli nedostupnému Windows
DPAPI v omezeném sandboxu, nikoli změně těchto modulů. Všech 39 poté prošlo
mimo sandbox. Finálních 52 cílených kontrol prošlo: těchto 39 a všech 13 nových
regresí (včetně dvou doplněných po prvním discovery). Logy jsou v Codex outputs
REVISION_REPORT_REGRESSIONS.log a REVISION_REPORT_FINAL.log.

Read-only replay skutečného runu 20261015-085555-e0c9aaeb: report tool payload
170 046 → 8 479 znaků; skutečný SDK dokončil report ve třech lokálních
modelových odpovědích. Dvě neproduktivní LOCAL_REVISION kola vytvořila
PROTOTYPE_REVISION_STALLED a další assignment byl IDEA-0002. Pět kontrolovaných
původních souborů běhu zůstalo hashově shodných.

Jedna skutečná networkless Docker execution ověřila úspěšnou opravu po
exit-zero/REVISE, čtení vyrobeného specimen, shodu obnovených 26 fixture bajtů a
odmítnutí změněného payloadu. SDK postup vyžádal read_revised_test → required
edit/plan → run_experiment → record_test. Nový receipt získal nezávislý
SUBCOMPONENT úsudek; nejde o nový discovery ani certifikaci celé preservation
vrstvy. Kód a modelové odpovědi/úsudky v QA dodal Codex, nikoli paid cheap model.

Žádné placené API, veřejný upload, host accounts ani experiment v produkčním
webovém stromu. Modely, configy/launchery, role/global budgets a approvals jsou
hashově shodné s předchozí instalací. SDK interface zůstává kompatibilní s
openai-agents 0.23.1/openai 3.24.0/pydantic 2.13.5.
Přenosná evidence: docs/validation/REVISION_REPORT_PROOF.json.


## 0.6.17 — actual payload, opravné odkazy a fakta před verdiktem (2026-10-20)

Celá offline sada: 569 kontrol, 1 Windows symlink skip, prošla. Finálních 24
cílených kontrol po zpřesnění typed facts a SDK dispatch prošlo. Logy: Codex
outputs/PAYLOAD_FACTS_REGRESSIONS.log a PAYLOAD_FACTS_FINAL_TARGETED.log.

Read-only replay reálného runu 20261020-061731-7b04b59a přes skutečný SDK
rozpoznal shodných 28 865 descriptor bytes ve frozen recovered output.
NO_RECOVERED_OUTPUT byl odmítnut jako REVIEW_RECOVERY_FACT_CONFLICT; následné
omezené SUBCOMPONENT hodnocení prošlo existujícím evidence kontraktem.
Žádný raw-content/full-mechanism či veřejný deposit claim nebyl udělen.
Original BagIt-like layout neprokazuje interoperabilitu s nezávislým validator.

Nový vstupní nástroj materializoval skutečný zachycený Metaweb EPUB o velikosti
1 294 314 bajtů a ověřil SHA256 b0e4617d9d3b77355c4b849d42e82497c0cd17080a015b70dd74288afdf712b1.
Hash research revision předaný jako TEST-ID byl odmítnut. Pět kontrolovaných
původních souborů běhu zůstalo hashově shodných. Opakované nekonzistentní
posouzení je technický INDEPENDENT_REVIEW_UNRESOLVED; neurčuje se tím chyba
kódu a hypotéza není REJECTED. Defaultní modely/role/global limity, approvals,
externí HTTP omezení a package policy jsou beze změn.

Replay odpovědi a úsudky dodal místní pevný model/Codex, nikoli placený API
agent. Ověřuje se framework a zachycené byte facts, ne autonomní výzkumná
kvalita cheap modelu. Během úprav žádné placené API, public upload ani experiment
v produkčním webovém stromu. SDK interface kompatibilní s openai-agents
0.23.1/openai 3.24.0/pydantic 2.13.5. Přenosná evidence:
docs/validation/PAYLOAD_FACTS_PROOF.json.

Dodatečná kontrola chrání i staré descriptor-only FULL receipts před novým
FULL_MECHANISM potvrzením. Legacy byte evidence se nemaže, vhodná metadata
operace nadále může být SUBCOMPONENT.
