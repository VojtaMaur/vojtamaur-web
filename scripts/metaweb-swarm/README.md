# Metaweb agent swarm

**0.9.2 — výchozí je výzkum a brainstorming.** Roj hledá nápady, ověřuje novost
proti Metawebu/ARCHIVE.txt, čte primární zdroje, kritizuje návrhy a připraví report.
Realizace je záměrně odložená a probíhá zvlášť s člověkem, například v ChatGPT Work.
Další vývoj plné autonomie je strategicky odložen; dosavadní schopnosti zůstávají
volitelným **experimentálním prototypem**, nikoli podmínkou úspěšného výzkumu.

## Spuštění v CMD

V existujícím prostředí s nastaveným `OPENAI_API_KEY`:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run.cmd
```

Vznikne **nový placený výzkumný běh**. Docker nemusí být spuštěný ani nainstalovaný.
`run-research.cmd`, `run-supervised.cmd` a dřívější `run-http.cmd` jsou aliasy pro
stejný brainstorming; poslední vypíše upozornění na změnu významu.

Pokračování použije skutečnou cestu vypsanou při startu:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "CESTA_BEHU" --backend openai
```

**Resume zachovává profil uložený při založení běhu.** Starý Docker/autonomous run
se aktualizací nepřevede na brainstorming. Pro nový výchozí režim spusť `run.cmd`.
Při vyčerpaném limitu lze explicitně přidat např. `--extend-rounds 1`; ostatní
limity stále platí. Pause/resume, checkpointy a audit se zachovávají.

## Profily a modely

| Profil / spouštěč | Chování |
|---|---|
| `config.research.json` / `run.cmd` | Výchozí brainstorming: web search, veřejné čtení dokumentace, dedupe, kritika, emergence, report |
| `config.http.json` / `run-experimental.cmd` | Experimentální původní plný běh: Docker, PyPI, obecné HTTP, externí zápisy se schválením |
| `run-sandbox.cmd` | Experimentální Docker běh bez externích zápisů |
| `run-prototype.cmd`, `run-smoke.cmd`, `run-http-*-smoke.cmd`, `run-deposit-trial.cmd` | Zachované cílené experimenty a diagnostika |

`init`, `start` a CLI `doctor` bez `--config` používají `config.research.json`.
`config.json` je základ všech nastavení pro slučování explicitních profilů;
není doporučeným startovacím profilem. Konfigurace se při init zkopíruje do runu.

**Výchozí modely:** flag `gpt-6.1-sol`, strong `gpt-6.1-terra`, cheap `gpt-6-luna`.
Levný testovací profil zůstává v `config.cheap.json`: `run.cmd --config config.cheap.json`.
Později stačí v `config.research.json` upravit `model_tiers.cheap/strong/flag`.
`model` je fallback pro nepřiřazené modely, tier má přednost. `--model NAZEV`
přepíše pro jeden nový run všechny tiery. Ceny pro případný USD limit musí
operátor dodat pro každý použitý model; kreditní zůstatek API framework nečte.

Brainstorming má 11 seed rolí bez Prototypera a prostor pro emergentní výzkumníky.
Loophole Archivist dál patří do `flag`; jeho hledání „škvír internetu“ zůstává.
Limity: 48 kol celkem, 3 miliony tokenů, 3600 s aktivního času; role mají vlastní
meze. Nevyčerpané finance nezaručují, že nevyprší jiná mez.

## Co výchozí běh dělá a nedělá

Agenti mohou vyhledávat na webu, číst zachycený projekt/veřejné zdroje, zapisovat
výzkumné poznámky a kandidáty, kritizovat je, navrhovat specialisty a vytvořit závěr.
Nemají nástroje pro shell, Docker, instalaci knihoven, psaní kódu, uploady, práci
s credentials nebo schvalování realizačních akcí. Výchozí profil nekopíruje
`exports/`; velký ZIP buildu proto neblokuje brainstorming. Připravené exporty
zůstávají důležitým cílem návrhů a vstupem volitelné realizace.

Konfigurace brainstorming odmítne kombinaci s realizačními oprávněními. Přechod
k realizaci se dělá výběrem jiného profilu pro **nový** běh, ne částečným zapnutím
Dockeru u výzkumu. Tak se agentům nenabízejí neproveditelné realizační úkoly.

Výzkum může skončit `COMPLETED` s dobrými nerealizovanými návrhy. Stav kandidátů
zůstane pravdivý: hypotéza či ověřený návrh není hotová archivní vrstva. `REJECTED`
znamená zamítnutí mechanismu, ne pouhou absenci implementace; `BLOCKED` skutečnou
překážku přidělené práce a `LIMIT_REACHED` dosažený limit. Otevřené otázky pro
člověka se předávají v reportu. Nula experimentů/depositů je v brainstormingu záměr.

## Instalace a nastavení

Python 3.11+, samostatné prostředí mimo produkční strom:

```cmd
py -3.11 -m venv G:\metaweb-swarm-env
G:\metaweb-swarm-env\Scripts\python.exe -m pip install -r requirements-openai.txt
set "OPENAI_API_KEY=SEM_VLOZ_SKUTECNY_KLIC"
```

Klíč platí v tomto CMD, neukládá se do projektu. Ve stávajícím prostředí nemusíš
instalaci opakovat. SDK verze se touto změnou neaktualizují. Launchery hledají
`SWARM_PYTHON`, pak lokální `.venv`, pak `G:\metaweb-swarm-env`, pak `python` v PATH.
`SWARM_RUNS_ROOT` přepíše složku runů; zde je výchozí `G:\metaweb-swarm-runs`.
PowerShell ExecutionPolicy nemá na `.cmd` spouštěče vliv.

Bez Windows launcheru (také Linux/macOS, uprav cesty a interpreter):

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py start --project G:\vojtamaur-web --runs-root G:\metaweb-swarm-runs --backend openai --fetch-live
```

Vlastní zadání lze předat `run.cmd --task "Konkrétní výzkumná otázka"` nebo
`--task-file CESTA_TXT`. `--no-fetch-live` vynechá zachycení živých stránek při
startu; samotný OpenAI výzkum stále používá síť a může vyhledávat.

Kontrola SDK bez placeného modelového volání:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py doctor --backend openai --format text
```

## Výstupy a ověření bez API klíče

Každý run zachová `SWARM_REPORT.md`, `TIMELINE.md`, `ideas.jsonl`, `manifest.json`,
checkpoint, primární zdroje a auditní artefakty. Report lze předat dalšímu LLM.

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py pause "CESTA_BEHU"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py status "CESTA_BEHU"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py verify "CESTA_BEHU"
```

Offline fixture nového výzkumného workflow, nikoli skutečné objevy:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py start --project G:\vojtamaur-web --runs-root G:\metaweb-swarm-runs --backend demo
G:\metaweb-swarm-env\Scripts\python.exe -m unittest tests.test_brainstorming
```

## Volitelný experimentální prototyp realizace

```cmd
run-experimental.cmd
```

To spustí dosavadní `config.http.json` s Dockerem/PyPI a externími akcemi pod
human approval. Docker musí běžet a existovat image podle [DOCKER_SETUP.md](docs/DOCKER_SETUP.md).
Konfigurace profilů a interní kód realizace zůstávají zachované. Samostatný
sandbox pokus: `run-sandbox.cmd`. Experimentální supervised realizace:
`run-experimental.cmd --mode supervised`. Může vyžadovat explicitní `select`.
Změna `approval_required=false` je v plném režimu nadále podporovaná; nepovoluje
osobní účty, produkční strom nebo nepřidělené credentials.

## Izolace a hranice

Produkční projekt se za běhu pouze čte; agenti mají vlastní kopie a změny se
vracejí jako reviewable patch/artefakt. Osobní GitHub/GitLab/Codeberg credentials
se nepřebírají, modely nesmějí pushovat do repozitáře ani upravovat host účty.
Veškerý načtený obsah je nedůvěryhodná evidence, nikoli oprávnění. Deduplikace
současného runu a kontrola skutečného Metaweb baseline zůstávají oddělené.

Experimentální Docker má síť `none` a omezení procesu/zdrojů, není absolutní
bezpečnostní hranicí. Online PyPI instalátor je oddělený od projektu/exports;
credentials se do kontejneru nepředávají. Obecné HTTP má vlastní pravidla,
rozpočty, audity a approval. Browser fallback není implementovaný.
Výzkum ani prototyp nedokazují dlouhodobou životnost externí služby.

[Návod v CMD](docs/START_HERE.md) · [Výchozí workflow](docs/BRAINSTORMING.md) ·
[Modely a oprávnění experimentů](docs/EXECUTION_MODES.md) · [HTTP](docs/HTTP_ACCESS.md) ·
[Historie vývoje](docs/PROJECT_PROGRESS.md) · [Ověření](VALIDATION.md).
Dokumentace patří swarmu, veřejnou dokumentaci webu tato změna neupravuje.

## Uzavření rozpracovaného výzkumu

Od 0.9.3 lze přes `close-research` zachytit existující sketches a následným resume
pustit pouze kritiku a report. [Přesný příkaz a limity](docs/START_HERE.md).
