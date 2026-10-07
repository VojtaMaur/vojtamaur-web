# Spuštění a modely

Všechny následující soubory patří projektu `scripts/metaweb-swarm/`. Žádný spouštěč
nepotřebuje adresář chatu ani dočasné `outputs/` z Codexu.

## Nový autonomous sandbox běh ve Windows CMD

Před obecným výzkumem v 0.3.3 spusť `run-smoke.cmd` ve stejné složce/CMD.
Oprava 0.3.4 řeší pip/chmod na disku G:; po jejím nainstalování spusť tentýž
příkaz znovu pro fresh run. [Audit prvního testu](RUN_REVIEW_20261007_093936.md).
Založí fresh run se dvěma rolemi pro cílené ověření balíčku, Dockeru a skutečné
obnovy exportu. [Postup a kritéria úspěchu](CANDIDATES_AND_SMOKE.md).

Docker Desktop musí běžet s Linux containers a musí existovat image
`metaweb-swarm-experiment:local`. Image se připravuje jednou podle
[DOCKER_SETUP.md](DOCKER_SETUP.md); spouštěč jej automaticky nestahuje ani nevytváří.

V CMD, kde je již nastavený skutečný `OPENAI_API_KEY`, zadej:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-sandbox.cmd
```

Každé spuštění založí **nový placený výzkumný běh**: ověří klíč/SDK/Docker bez
modelového volání, zachytí projekt, aktuální veřejný kontext a exporty, vypíše cestu
runu a spustí OpenAI backend. `autonomous`, `docker`, `sandbox-only`, approval
required. Agenti vybírají a testují v kopii; externí deposit konektory jsou vypnuté.
Změna `approval_required` sama nepovolí externí zápisy.

Výzkumný profil nyní povoluje `install_packages`: agenti mohou stáhnout
libovolné pojmenované PyPI knihovny bez whitelistu a jednotlivých approvals.
Instalace mají oddělený online build bez webu/exports a offline instalaci do
soukromé kopie. Experimentální síť zůstává vypnutá; image nemusíš kvůli
knihovnám přestavovat. Podrobnosti: [PACKAGES.md](PACKAGES.md).

Pro samotný supervised výzkum bez spuštění experimentů:

```cmd
run-supervised.cmd
```

Pro supervised výzkum s možností později schválit Docker realizaci:

```cmd
run-supervised.cmd --experiments docker
```

Výchozí interpreter: `.venv\Scripts\python.exe` vedle spouštěče, jinak existující
`G:\metaweb-swarm-env\Scripts\python.exe`, jinak `python` z PATH. Běhy se ukládají
do `metaweb-swarm-runs` vedle kořene projektu; u zdejší instalace tedy
`G:\metaweb-swarm-runs`. Obě cesty můžeš změnit:

```cmd
set "SWARM_PYTHON=D:\tools\swarm-env\Scripts\python.exe"
set "SWARM_RUNS_ROOT=D:\swarm-runs"
run-sandbox.cmd
```

API klíč nepatří do launcheru ani configu. Již nastavená proměnná prostředí
zůstává použitá; spouštěč jej nečte do souboru, nevypisuje ani nepředává Dockeru.

Nový profil má `prior_work_policy=continue`: paměť generací je informativní.
Deduplikace posuzuje jen aktuální run. Kontrola ARCHIVE.txt je samostatná.
Po opravách 0.3.3 spusť nový run; resume zachovává původní profil a starou historii.

Bez CMD spouštěče (také na jiných systémech):

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py start --project G:\vojtamaur-web --runs-root G:\metaweb-swarm-runs --config config.research.json --backend openai --mode autonomous --experiments docker --external-scope sandbox-only --approval required --fetch-live
```

`start --backend demo` je offline fixture. `--fetch-live` je veřejné čtení webu;
vynech jej pro zcela offline spuštění (`--no-fetch-live` přepíše volbu spouštěče).
`init` nadále pouze připraví run, `run` jej
spustí. Stavový kód 3 po doběhnutí znamená `LIMIT_REACHED`; report a checkpoint
jsou uložené. V CMD musí být jednotlivé příkazy na samostatných řádcích.

## Levný test a tři předefinovatelné tiery

V `config.research.json` jsou zatím **všechny tiery `gpt-5.4-mini`**:

```json
"model_tiers": {
  "cheap": "gpt-5.4-mini",
  "strong": "gpt-5.4-mini",
  "flag": "gpt-5.4-mini"
}
```

Pro pozdější přechod stačí přepsat názvy API modelů ve zvoleném tieru. Tyto názvy
jsou interní kategorie frameworku, nikoli aliasy OpenAI. Každý model musí být
dostupný tvému API projektu a podporovat potřebné nástroje/structured outputs.
SDK předává konkrétní model jednotlivému agentovi.

| Tier | Výchozí role | Důvod |
|---|---|---|
| `flag` | Orchestrator, **Loophole Archivist**, Hostile Reviewer, Synthesizer | Směr roje, nečekané cesty, kritické rozhodnutí, závěr |
| `strong` | Anomaly Engineer, Format Mutant, Failure-Domain Hunter, Future Archaeologist, Evidence Auditor, Prototyper | Náročné návrhy, ověřování, implementace |
| `cheap` | Infrastructure Scout, Role Architect | Vyhledávání a úzce vymezené organizační návrhy |

Profil aktuálně nespouští všechny dostupné seed role. Uvedená tabulka platí i pro
později přidané seed role. Emergentní specialisté dostávají operátorem nastavený
`emergent_model_tier`, výchozí `strong`; agent si tier ani model nepřidělí sám.

Jednotlivou roli lze předefinovat v témže configu, například:

```json
"role_model_tiers": {
  "Anomaly Engineer": "flag",
  "Evidence Auditor": "cheap"
},
"emergent_model_tier": "cheap"
```

Přiřazení se zachytí při init/spawn do checkpointu, manifestu a reportu. Úprava
profilu mění **nové běhy**; `resume` pokračuje s uloženými modely a configem.
Staré configy bez tierů používají globální `model` pro každou roli.

`--model` je pohodlné přepsání **všech tří tierů** pro jediný nový run:

```cmd
run-sandbox.cmd --model gpt-5.4-mini
```

Pro vlastní profil bez zásahu do společného configu:

```cmd
copy config.research.json config.my-run.json
run-sandbox.cmd --config config.my-run.json
```

## USD limity při více modelech

Tokeny, runtime, request reservations a počet externích akcí zůstávají společné
pro celý roj. `cheap/strong/flag` nezvyšují žádný limit. Výzkumný profil má dál
40 kol, 3 000 000 tokenů a 3 600 sekund. Jeho lokální USD limit zatím není
nastavený; provider spend limit je samostatná věc.

Při nastavení `estimated_budget_usd` potřebuje **každý nakonfigurovaný model**
vlastní operátorské cenové stropy. Např. struktura `model_prices` má pro konkrétní
API název tři čísla:

```text
model_prices[API_MODEL_NAME] = {
  input_price_per_million: aktuální horní sazba vstupních tokenů,
  output_price_per_million: aktuální horní sazba výstupních tokenů,
  web_search_price_per_call: aktuální horní cena search volání
}
```

Nejde o automaticky získaný ceník. Vyplň aktuální konzervativní sazby a cenu
search vstupu; cached discounts se neodečítají. Legacy globální ceny platí pouze
pro legacy `model`. Dražší tier je nepřebírá. Při `--model` na jiný model se
legacy ceny vyčistí; aktivní USD limit vyžaduje nové explicitní sazby.
Spotřeba se zaznamenává po modelech a rezervace uchovává ceny použité při volání.

Web search mají discovery/review role. Koordinace, lokální prototypování a
syntéza pracují s již získanými podklady; nemají hosted search ani jeho tokenovou
rezervaci. Chybějící externí ověření musí předat výzkumné roli. To pomáhá dokončit
syntézu bez navyšování budgetu; úplně spotřebovaný tokenový/časový limit ji přesto
může zastavit. Deterministický report vzniká i bez úspěšného LLM reportéra.

## Čitelná konzole

Na začátku: run, režim/oprávnění, skutečné modely po tierech, role a limity.
Průběžně: role/tier a číslo kola, nové IDEA nebo změna jejich názvu/stavu,
nový specialista, zahájení/výsledek pip instalace, Docker pokusu a test receipt. Identické
IDEA aktualizace se znovu nevypisují. Souborové čtení a dlouhé tool odpovědi
patří do auditu. Konzole nedokládá věcnou správnost nápadu.

Krátká kontrola nastavení bez placeného API:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py doctor --backend openai --config config.research.json --docker-check --format text
```

Bez `--format text` zůstává kompletní JSON, nově včetně přiřazených modelů.

## Pause, resume a výsledky

Ulož skutečnou cestu vypsanou spouštěčem:

```cmd
set "LIVE_RUN=G:\metaweb-swarm-runs\SKUTECNE_ID_BEHU"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py pause "%LIVE_RUN%"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py status "%LIVE_RUN%"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "%LIVE_RUN%" --backend openai
G:\metaweb-swarm-env\Scripts\python.exe swarm.py verify "%LIVE_RUN%"
```

Pause z druhého CMD se projeví po aktuálním ohraničeném kole. Resume nezaloží
další run a samo nezvýší rozpočty. Pro rozšíření použij explicitní `--extend-*`
parametry dle [README](../README.md), až po kontrole skutečné příčiny zastavení.

Čti `SWARM_REPORT.md`, `TIMELINE.md`, `ideas.jsonl`, `manifest.json` a Docker
receipts v auditu. Kontroluj soubory a test assertions, ne pouze `returncode=0`.
**PROTOTYPED není důkaz standardní kompatibility ani externího uložení.**
