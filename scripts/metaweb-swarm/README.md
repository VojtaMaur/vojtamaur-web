# Metaweb agent swarm

Výzkumný a realizační framework pro Metaweb Vojty Maura. Agenti hledají, ověřují a kritizují preservation mechanisms, navrhují specialisty a mohou vytvářet a testovat prototypy. Každý má soukromou kopii projektu. Produkční `G:\vojtamaur-web` se při běhu pouze čte; změny zdroje se vracejí jako reviewable patche a artefakty.

Prioritou je uchování **připravených buildů a exportů** webu bez potřeby git push nebo změny produkčního kódu. ZIP, EPUB, PDF a další veřejné podklady z `exports/` jsou samostatný vstup. Hlavním výstupem je `SWARM_REPORT.md`, časová osa, kandidáti, evidence, spotřeba a skutečné deposit receipts.

Tato dokumentace patří frameworku; do veřejné dokumentace vojtamaur.cz se zatím nepřidává. Průběžný stav: [PROJECT_PROGRESS.md](docs/PROJECT_PROGRESS.md). Podrobnosti režimů: [EXECUTION_MODES.md](docs/EXECUTION_MODES.md). Docker: [DOCKER_SETUP.md](docs/DOCKER_SETUP.md).

**Začni zde: [Spuštění v CMD, modelové tiery a resume](docs/START_HERE.md).**
Před dalším výzkumem spusť `run-smoke.cmd`: cílený cheap-model test PyPI → Docker →
funkční obnova exportu. [Deduplikace a význam PROTOTYPED](docs/CANDIDATES_AND_SMOKE.md).
Přímo v projektu jsou `run-sandbox.cmd` a `run-supervised.cmd`; nepotřebují soubory
z Codexu. `run-sandbox.cmd` ověří prerequisites, založí nový autonomous Docker run
a spustí placený výzkum, s externími deposity vypnutými. Zachovává nastavený API
klíč. Všechny modelové tiery zatím používají `gpt-5.4-mini`.

## Tři nezávislá nastavení

| Nastavení | Výchozí hodnota | Co řídí |
|---|---|---|
| `run_mode` | `supervised` | Kdo vybírá kandidáta k realizaci |
| `external_scope` | `sandbox-only` | Povolení konkrétních externích deposit connectorů |
| `approval_required` | `true` | Lidské schválení povoleného depositu |

**Supervised:** výzkum je autonomní, kandidátovy experimenty a deposit čekají na `select … --decision implement`. Výzkum může normálně skončit reportem. Dobrý nerealizovaný kandidát zůstává `NOT_SELECTED`/`DEFERRED`, nikoli `REJECTED`. Agenti mohou v soukromé kopii psát poznámky a návrhy souborů; zápis sám není provedený experiment.

**Autonomous:** roj sám vybírá, prototypuje a testuje v povoleném sandboxu. S `external_scope=external` může použít deklarovaný connector. Při `approval_required=false` jeho `deposit_file` nemá druhou lidskou approval gate. Dál platí rozpočty, přidělené credentials/resources, kritika, provedený test a kontrola přesných bajtů. To jsou technické podmínky a evidence, nikoli další schvalování.

`sandbox-only` omezuje externí **zápisy**, nikoli hosted web search či veřejné čtení kontextu. `experiments=disabled|docker` samostatně určuje spuštění kódu. Bez dostupného Dockeru není host execution fallback.

## Instalace a offline start

Python 3.11+, samostatný virtualenv a adresář běhů mimo produkční projekt. Windows CMD: každý řádek zadej samostatně.

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
py -3.11 -m venv G:\metaweb-swarm-env
G:\metaweb-swarm-env\Scripts\python.exe swarm.py doctor --backend demo
G:\metaweb-swarm-env\Scripts\python.exe swarm.py init --project G:\vojtamaur-web --runs-root G:\metaweb-swarm-runs --mode supervised --experiments disabled
```

`init` vypíše jediný řádek s absolutní cestou. Vlož **skutečně vypsanou cestu**, nikoli placeholder:

```cmd
set "LIVE_RUN=SEM_VLOZ_SKUTECNOU_CESTU_Z_INIT"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py run "%LIVE_RUN%" --backend demo
G:\metaweb-swarm-env\Scripts\python.exe swarm.py verify "%LIVE_RUN%"
```

Demo je deterministický offline fixture za 0 USD, ne skutečný výzkum ani ověření služeb. Demo a živý backend zakládej odděleně. V PowerShellu lze stdout zachytit do `$liveRun = & $swarmPython swarm.py init …`; nejprve ověř úspěšný exit. CMD `for /f` není nutný: ruční cesta a samostatné `set` předcházejí slepeným příkazům.

## Živý běh s levným modelem

```cmd
G:\metaweb-swarm-env\Scripts\python.exe -m pip install -r requirements-openai.txt
G:\metaweb-swarm-env\Scripts\python.exe swarm.py doctor --backend openai
```

SDK a závislosti jsou připnuté v requirements. `doctor` ověřuje instalované rozhraní a přítomnost `OPENAI_API_KEY`, execution policy a budget nastavení; nevolá placené API a neověřuje účet. Klíč nastav v prostředí běžícího CMD, například `set "OPENAI_API_KEY=SKUTECNY_KLIC"`; nedávej ho do configu či zdroje. Backend jej nepředává experimentům ani deposit connectorům.

`config.research.json` zachovává `gpt-5.4-mini` ve všech tierech a devět seed rolí. Má 40 kol, 12 SDK tahů/kolo, 3 miliony tokenů a hodinu aktivního času; Prototyper má 6 kol. `init/start --model NAZEV_API_MODELU` přepíše všechny tiery jen pro nový run. Samostatné názvy `model_tiers.cheap/strong/flag` a přiřazení `role_model_tiers` jsou popsány v [START_HERE.md](docs/START_HERE.md). Vyber dostupný API model s Responses, hosted search, function tools a structured outputs; pro USD limit musí být cenové stropy definovány pro každý model.

Supervised výzkum bez spuštění prototypů:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py init --project G:\vojtamaur-web --runs-root G:\metaweb-swarm-runs --config config.research.json --mode supervised --external-scope sandbox-only --approval required --experiments disabled --fetch-live
```

Po init samostatně nastav cestu a explicitně spusť placený run:

```cmd
set "LIVE_RUN=SEM_VLOZ_SKUTECNOU_CESTU_Z_INIT"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py run "%LIVE_RUN%" --backend openai
```

Autonomous sandbox pokus zakládej až při dostupném Dockeru a připraveném image:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py init --project G:\vojtamaur-web --runs-root G:\metaweb-swarm-runs --config config.research.json --mode autonomous --external-scope sandbox-only --approval required --experiments docker --fetch-live
```

Samotný init nezahájí modelové volání; `run`/`resume --backend openai` může spotřebovávat kredit. Instalační skript může přepsat profil, proto pro změnu modelu používej CLI nebo vlastní config kopii. Nové request parametry a jejich fakturaci musí potvrdit levný placený acceptance test.

Pokud má supervised run později v témže checkpointu realizovat vybraný nápad, založ jej už s `--experiments docker`. Supervised volba stále blokuje samotné provedení až do select. Init s disabled je čistý výzkumný run; select sám tuto zachycenou capability nezapne.

## Supervised rozhodnutí

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py status "%LIVE_RUN%"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py select "%LIVE_RUN%" IDEA-0001 --decision implement --note "Vybrano k sandbox prototypu."
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "%LIVE_RUN%" --backend openai
```

Použij skutečné IDEA ID. `select` nemění vědecké hodnocení ani globální rozpočty; připraví Prototypera. `--decision defer` realizaci odloží. Docker musí být povolen v zachyceném configu runu, jinak se experiment nevykoná.

Ukončení výzkumu bez realizace:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py finish-research "%LIVE_RUN%" --note "Vyzkum uzaviram; kandidaty ponechat pro pozdejsi rozhodnuti."
```

Příkaz je pro supervised běhy. Zachová nápady, otevřené směry, limity i neprovedené akce; nevytvoří falešnou implementaci nebo zamítnutí dobrého nápadu. Pozdější pokračování vyžaduje explicitní operátorské rozhodnutí.

## Externí executory a approvals

První executory jsou `local_directory` a `http_put`. Agent volí pouze resource ID z configu; nepřidělí si endpoint, credentials nebo hostitelský shell. Jiný connector je skutečná chybějící schopnost, ne skryté schvalování. Automatické platby, založení účtů, git push a provider-specific archivní API tento základ zatím neimplementuje.

Do **kopie výzkumného configu**, která zachovává model a rozpočty, přidej například:

```json
{
  "run_mode": "autonomous",
  "external_scope": "external",
  "approval_required": false,
  "experiments": "docker",
  "max_external_actions": 2,
  "max_external_bytes": 134217728,
  "external_resources": [
    {
      "id": "local-deposit",
      "kind": "local_directory",
      "directory": "G:\\metaweb-swarm-deposits",
      "max_bytes": 134217728,
      "cost_usd": 0
    }
  ]
}
```

Tento výřez sám nenastavuje model. Cíl nesmí překrývat produkci ani run/workspace; jiný existující obsah se nepřepisuje. Lokální deposit testuje flow, nikoli novou geografickou archivní vrstvu. Nový run může načíst vlastní config a stejné policy lze přepsat přes `--mode autonomous --external-scope external --approval disabled`.

HTTP PUT resource deklaruje pevné HTTPS `endpoint`, `max_bytes`, případně `credential_env` a `authorization_scheme` (`Bearer`/`Basic`). Dedicated credential zůstává v hostitelském connectoru. URL nesmí mít credentials/query/fragment; redirects se odmítají. `allow_loopback_http=true` je výjimka jen pro explicitní lokální fixture. Endpoint musí podporovat PUT a následný GET stejného objektu; není to hotový S3 SigV4 klient ani obecné webové ovládání.

Deposit vyžaduje způsobilého kandidáta, `record_critique` s PASS a `record_test` navázaný na skutečný úspěšný Docker experiment. Odesílané bajty musejí odpovídat artefaktu/exportu v test receipt. Před akcí se uloží rezervace; potom connector provede deposit a nezávislý SHA256 read-back. `host_verified` receipt opravňuje k dokončené realizaci/`DEPOSIT_VERIFIED`. Nejasná přerušená akce zůstává UNKNOWN a neopakuje se naslepo.

Při `approval_required=true`:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py approvals "%LIVE_RUN%"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py decide "%LIVE_RUN%" APPROVAL-0001 --decision approve --note "Souhlasim s presnymi bajty a cilem pozadavku."
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "%LIVE_RUN%" --backend openai
```

`decide` samo nic neodešle; schválený deposit se může vykonat při resume. Generické/staré approval intents bez executoru zůstávají popsanými ručními kroky. Při `approval_required=false` podporovaný deposit vykoná akci bez approval intentu. Chybějící resource, credentials, test či limit se dál vykazují podle skutečného důvodu.

## Rozpočty a rezervace

| Oblast | Pole |
|---|---|
| Model/souběh | `model`, `max_concurrent_agents`, `max_agents` |
| Delegace/plánování | `max_descendants`, `max_depth`, `max_agent_rounds`, `role_round_limits`, `max_steps` |
| Modelové požadavky | `max_turns`, `max_output_tokens`, `max_total_tokens`, `step_timeout_seconds` |
| Aktivní čas | `max_active_seconds`, `experiment_timeout_seconds` |
| Cena | `estimated_budget_usd`, `input_price_per_million`, `output_price_per_million`, `web_search_price_per_call` |
| Hosted search | `max_web_search_calls_per_request`, `max_web_search_context_tokens_per_call` |
| Externí akce | `external_resources`, `max_external_actions`, `max_external_bytes`, resource `max_bytes` |
| Vstupy | `max_file_bytes`, `max_snapshot_bytes`, `include_exports`, `max_export_file_bytes`, `max_export_total_bytes` |
| Kontext | `prompt_chars`, `history_chars` |

Config je při init zachycený a agent jej nemění. Neznámé klíče se odmítají. Dolarový limit vyžaduje všechny tři operátorské **cenové stropy**; neznámá cena není nula, cache slevy se při rezervaci neodečítají. Default `estimated_budget_usd=null` není dolarový limit.

Před každým provider requestem host trvale rezervuje konzervativní tokenový a případně USD strop: prompt, historii, skutečná tool/response schémata, maximální odpověď a interní search allowance. Rezervovaný souběh snižuje dostupný příděl. Po známé odpovědi se vyúčtuje skutečná usage; neznámá rezerva se neuvolní. Nejde pouze o kontrolu mezi dávkami.

Base config povoluje **1 hosted search call/request**, výzkumný profil explicitně **3** a 2 miliony tokenů. `max_web_search_context_tokens_per_call=128000` je konzervativní allowance, nikoli běžná spotřeba; počet search calls se posílá přes SDK `extra_args.max_tool_calls`. Request může čekat kvůli velké rezervaci i při nízkém dosavadním účtu. Report odlišuje rezervovaný strop a skutečnou usage. Allowance nesnižuj podle ceny jednoho minulého runu bez zdůvodněného boundu pro vybraný model/tool.

Lokální enforcement není záruka konečné faktury: závisí na správných cenových stropech, boundech, přijetí request parametrů a úplné usage. Překročení rezervovaného boundu se zaznamená a zastaví další request. Současné placené API přijetí nových parametrů se musí ještě ověřit živě. Automatické API retry jsou vypnuté.

Po neznámém požadavku použij **ověřenou** spotřebu:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py reconcile-budget "%LIVE_RUN%" AGENT-001:1 --input-tokens 1200 --output-tokens 300 --web-search-calls 1 --note "Overeno podle konkretniho provider requestu."
```

Čísla jsou pouze syntaxe; ID a rezervaci přečti ze status. Nedávej nulu, když výsledek neznáš. Reconciliation je operátorská, zachová audit a sama nepokračuje; po vyřešení blockeru použij unblock a resume. Jde o neznámé účtování, ne dodatečné permission gate.

Závislost archivního kandidáta na měsíčních/ročních platbách je zakázaná. `requires_ongoing_payments=true` variantu zamítne; null je neposouzeno. One-time kandidát je přípustný, první deposit executory však podporují pouze nulový action cost. Platební executor je budoucí samostatná schopnost, ne skrytě povinné schválení už podporované akce.

## Pause/resume a stavy

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py pause "%LIVE_RUN%"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py status "%LIVE_RUN%"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "%LIVE_RUN%" --backend openai
```

Pause lze zadat v druhém CMD; probíhající omezená práce korektně doběhne. Docker nesmí dál měnit kopii, kterou runner exportuje či obnovuje. Ctrl+C uloží checkpoint, pokud je možné korektní ukončení. Jeden run má jediného writera. Po pádu jsou nejasné modelové rezervace/externí akce neznámé, nikoli úspěšné. Lidská pauza se do aktivního runtime nepočítá; po tvrdém pádu se nepřesný čas konzervativně započítá s důvodem.

Explicitní rozšíření spotřebu nenuluje:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "%LIVE_RUN%" --backend openai --extend-steps 12 --extend-tokens 100000 --extend-seconds 900 --extend-rounds 1
G:\metaweb-swarm-env\Scripts\python.exe swarm.py report "%LIVE_RUN%"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py verify "%LIVE_RUN%"
```

Extend-rounds zvyšuje i explicitní role limits, nikoli USD strop. `unblock … --note` zaznamená vyřešení konkrétní překážky a omezené pokračování; samo nedokazuje úspěch depositu.

| Stav | Význam |
|---|---|
| BLOCKED | Chybí podklad, capability, credentials nebo konkrétní podmínka |
| REJECTED | Posouzená a zamítnutá varianta s důvodem |
| COMPLETED | Dokončený úkol/výzkum; realizaci dokládají zvláštní receipts |
| LIMIT_REACHED | Vyčerpaný příděl, otevřená práce zachována |
| PAUSED | Operátorská pauza nebo připravený run |

## Role, baseline a duplicity

Plný roster má 12 rolí, `seed_roles` vybírá podmnožinu; prázdný seznam znamená plný roster. Výzkumný profil obsahuje Anomaly Engineera a ostřejší Loophole zadání hledat, jak web v nějaké podobě dostat do „škvír internetu“, s konkrétní evidencí a povolenými prostředky. Emergentní role uvádí misi, důvod a přínos, ale nemění oprávnění ani rozpočet.

Scheduler střídá role stejné fáze po kolech a chrání alespoň jeden krok pro čekající pozdější role. Absolutní tokenový/cenový/časový limit jej může zastavit, report vznikne i pak. SDK MaxTurnsExceeded zachová tool výsledky a pokračuje v dalším omezeném kole, pokud zbývá příděl; HTTP chyby nejsou automatické opakování. Handoff_leads předává budoucí práci, unexplored_leads zachovává vlastní nedokončený úkol.

`check_baseline` hledá celý zachycený ARCHIVE.txt, potom curated state, dokumentaci a původní zdroje. Vrací řádky, dokument hash a BASE receipts; nepřidává live ALL_POSTS download. Nepodložené „už v baseline“ nesmí zamítnout OSF. Shoda slov není doklad realizace a absence shody není důkaz novosti. Hypotézy a paměť minulých běhů nejsou implementovaná baseline.

Deduplikace používá rodinu mechanismu a stabilní scope, nikoli název IDEA či dlouhé novelty prose. `mechanism_key` a `mechanism_scope` jsou názvy do 160 znaků, ne URL/cesty. Host normalizuje známé aliasy, například AWS/S3 Object Lock a ORCID recovery pointer. Governance/compliance, replikační varianta či embedded payload proti pointeru mohou zůstat odlišné. Explicitní key neznámé rodiny je vodítko k přesné shodě, ne sémantický důkaz.

Sloučený kandidát má jedno ID a zachovává submissions, contributors, claimed/host-normalized hodnoty, zdroje, revize a status/payment conflicts. Host ověřuje evidence a artefakty před merge; konflikt nevyléčí hlasování ani vyšší slovní hodnocení. Historické IDEA IDs se nepřepisují; různé runy neslučují ledgery. Nejednoznačné parafráze se potichu fuzzy-merge nedělají.

Externí URL pozorované v search je provenance, ne potvrzení pravdivosti. Critique je agentův úsudek. Record_test dokládá skutečně úspěšný Docker příkaz a zachycené bajty, ne správnost všech assertions. PROTOTYPED není deposit a exit zero samo nedokazuje obnovu webu. Emergentní DISCOVERY role mají stejné external coverage pravidlo jako seed výzkumníci.

Trvale odmítnuté směry uprav v `context/REJECTED_IDEAS.json` (`id`, konkrétní `aliases`, `reason`, `scope`). WACZ/WARCZ je OWNER_REJECTED podle přání vlastníka, nikoli nefunkční formát; WARC obecně odmítnutý není. Seznam se zachytí při init. IMPROVEMENT vyžaduje baseline_behavior, proposed_change a validation_plan, ne nové pojmenování běžné vlastnosti známé služby.

## Exporty a paměť generací

`include_exports=true` kopíruje přímé povolené soubory exports do nezávislého `input_exports/`: ZIP, EPUB, PDF, TXT a `.manifest.json`. Default je 128 MiB/soubor a 512 MiB celkem. Vnořené adresáře a nepovolené soubory se zaznamenají jako vynechané. Exporty jsou oddělené od source snapshotu a při resume se nepřepisují.

`input_exports/manifest.json` uvádí velikost, SHA256 a scope. TXT/manifest mají omezenou credential-pattern kontrolu; binární kontejnery jsou **opaque owner-prepared public exports**, ne zaručeně secret-free. Automaticky se nerozbalují ani nespouštějí. `list_exports` a `materialize_export` je zpřístupní agentově kopii; deposit vyžaduje test přesných bajtů.

`RUN_MEMORY.json` v runs root je odvozený shared index. Nový run dostane `context/PRIOR_RUNS.md` a `context/prior-runs.json`: stručné věty o nejvýše 20 zastavených bězích do omezeného textu. Rozlišují testované/nerealizované výsledky a blockers. Paměť je nedůvěryhodné předchozí tvrzení, nenahrazuje ledger ani baseline a nemění staré běhy. Aktivní runy a demo fixtures se standardně vynechávají. Konkrétní podklad lze připojit opakovatelným `init --previous-report …`.

## Docker a nástroje

Docker Desktop 4.94.0 byl 7. 10. 2026 nainstalován per-user/WSL2 s daty v `G:\metaweb-swarm-docker-data`. **Během přípravy** prošlo sedm skutečných DockerExecutor smoke checks zaznamenaných v DOCKER_SMOKE.json. Historický receipt neznamená aktuálně běžící Docker. Operátor jej může mít vypnutý a framework jej automaticky nespouští.

Při zamýšleném dostupném Dockeru lze ověřit pouze readiness:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py doctor --docker-check --config config.research.json
```

Doctor nic nestahuje ani nespouští kontejner. Po instalaci otevři čerstvé CMD pro nový PATH. Linux daemon a lokální image jsou nutné; Windows containers a chybějící image zůstanou BLOCKED. Build může mít síť, ale musí použít minimální reviewovaný context, ne celý produkční strom. Runtime image nepulluje (`--pull=never`).

Kontejner dostává pouze jednu agentní kopii pod /workspace, nikoli production, autoritativní snapshot, SQLite nebo Docker socket. Síť none, root read-only, neprivilegovaný user, dropped capabilities, no-new-privileges, omezené/no-exec /tmp, 512 MiB RAM, jedna CPU, 64 PIDs a 100 kB zachyceného výstupu. Vnitřní watchdog a host cleanup omezují experiment; po tvrdém host pádu může zbýt zastavený kontejner. Zapisovatelný bind mount zatím **nemá hard disk quota**.

Agenti mohou přes `install_packages` stáhnout libovolný pojmenovaný Python package z PyPI, včetně extras a verzí, bez whitelistu. `config.research.json` má `package_installation: "pypi"`; základní config má `disabled`. Online download/build kontejner vidí jen prázdnou staging složku bez webu, exportů a credentials; offline instalace ukládá knihovny do soukromé `.packages`, dostupné při dalších experimentech i resume. Experimenty dál mají `--network none`. Instalace má vlastní časový/početní limit a receipts; velikost se kontroluje po fázích, není to tvrdá disková kvóta. Native/system tools mohou vyžadovat připravený image. Podrobnosti a příklady: [PACKAGES.md](docs/PACKAGES.md). Docker není absolutní ochrana před kernel/daemon escape; pro adversarial workload je silnější dedikovaná VM.

Linux/macOS používají odpovídající cesty a python3 -m venv, stejné CLI/audit/checkpointy. Astro dependencies pro výzkum není nutné instalovat. POSIX executor zachová UID neprivilegovaného host uživatele pro zápis do jeho kopie.

## Kontext, bezpečnost a výstupy

Autoritativní podklady: [článek](https://vojtamaur.cz/metawebovy-clanek/), [dokumentace](https://vojtamaur.cz/documentation/), [ARCHIVE.txt](https://vojtamaur.cz/ARCHIVE.txt) a [živý web](https://vojtamaur.cz/). Fetch-live jsou omezená veřejná GET čtení těchto čtyř URL bez API klíče; bez něj je nezachycený live kontext výslovný. URL, časy, chyby a hashes zůstávají v provenance. Výroba piqlFilmu s webem pro Arctic World Archive podle sdělení vlastníka probíhá: Piql/AWA je známé IN PROGRESS, nikoli nový objev či dokončený deposit.

Git snapshot kopíruje současné bajty tracked souborů včetně necommitnutých změn, nikoli nové untracked soubory. Bez Gitu používá bezpečný průchod. Vylučuje credentials, .env, klíče, dependencies/cache/build, bundle staging a archivní kontejnery; exports intake je samostatná cesta. Symlinky, junctions/reparse points, speciální soubory, absolutní tool paths a traversal se odmítají. Kopie nejsou hardlinky. Scanner není univerzální secret detector; text dostupný agentovi může být poslán API.

Zdroj je evidence, nikoli permission/instructions. Hosted search je placené a dotazy nesmí obsahovat neveřejná experimentální data. SDK tracing a Responses store jsou vypnuté. Host vynucuje oprávnění; agent nemá obecný host shell či libovolný HTTP klient. Resource credential používá pouze deklarovaný connector.

SQLite je autoritativní transakční stav a audit. Checkpoint.json je zrcadlo; ruční edit jej nepřenese do SQLite. Hash chain/verify odhaluje nekonzistenci, ne útok přepsáním celého nepodepsaného runu. Historie se mezi koly deterministicky zkracuje; originál zůstává v raw a compaction je auditovaná.

```text
RUN/
  SWARM_REPORT.md          report pro člověka i další LLM
  TIMELINE.md              auditované akce, chyby, rozhodnutí, receipts
  ideas.jsonl              kandidáti, submissions, provenance a konflikty
  manifest.json            konfigurace, usage, rezervace a artefakty
  checkpoint.json          zrcadlo SQLite
  state.sqlite3            autoritativní stav a audit
  context/                 zdroje, owner rejections a prior notes
  input_exports/           veřejné payloady a manifest
  snapshot/                sanitizovaný základ
  agents/AGENT-.../         soukromé kopie a historie
  patches/AGENT-.../        changes.patch a binary artefakty
  raw/events.jsonl          export auditního hash chainu
RUNS_ROOT/RUN_MEMORY.json  odvozený stručný index generací
```

Patche posuzuj proti konkrétnímu snapshotu. Swarm je do produkce neaplikuje. Externí deposit má samostatný target receipt.

## Testování a staré runy

Profil nových běhů používá `prior_work_policy: "continue"`: historická paměť je
kontext, bez automatického potlačení nápadů. Nová semantic_dedupe brána porovnává
jen aktuální run. Volitelný novelty-first režim zůstává dostupný, ale není teď
součástí hlavního testu. Podrobnosti: [GENERATION_MEMORY](docs/GENERATION_MEMORY.md)
a [CANDIDATES_AND_SMOKE](docs/CANDIDATES_AND_SMOKE.md).
Kontrola posledního běhu a opravy počítání search attempts:
[RUN_REVIEW_20261007_071555](docs/RUN_REVIEW_20261007_071555.md).

```cmd
G:\metaweb-swarm-env\Scripts\python.exe -m unittest discover -s tests -v
```

Offline testy ověřují workspace/policy, dedup/provenance, režimy, exports, memory, rezervace, checkpointy, audit a mock SDK/connector workflows. Živý Docker smoke je samostatná evidence; mock executor/demo jej nenahradí. Local/HTTP fixture ověřuje konkrétní bajty a read-back, nikoli dlouhodobou dostupnost veřejné služby. Počet prošlých testů čti z konkrétního test logu; dokumentace jej nefixuje.

Staré běhy zachovávají snapshots, role missions, IDEA IDs, config a audit. Chybějící nová policy pole se interpretují konzervativně jako supervised, sandbox-only, approval required. Nové režimy/zadání zkoušej v čistém novém runu. Placené acceptance testy nového API flow jsou oddělené od offline kontrol a od již provedených historických živých pokusů.
