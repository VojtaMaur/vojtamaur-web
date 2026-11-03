# Spuštění přes GUI nebo CMD (0.10.0)

Nejjednodušší lokální panel:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-gui.cmd
```

Samotný panel nevolá placené API ani Docker. Nabízí nový běh, modely a role,
limity, pokračování v uložených bězích, log/Swarm CMD, reporty a komentáře před
startem i na další bezpečné hranici běžící práce. [Úplný návod GUI](GUI.md).
Profily nových běhů nemění staré checkpointy; u resume lze explicitně rozšířit
rozpočty. Klíč z CMD se převezme, případně jej zadej jen pro GUI relaci.
Níže zůstávají dostupné původní CLI a historické podrobnosti.

## 0.9.4 — skutečně konečné uzavření

close-research nyní defaultně připraví report-only: zastaví další kritiku,
hosted search i dokumentové tool calls. Pokud ještě nejsou IDEA, nejprve
zachytí staré sketches bez placeného API. Následné resume má jediného reportéra
s nulovým seznamem tools a max_turns=1. Dostává kompaktní packet všech IDEA,
stávajících kritik a výslovných UNREVIEWED mezer; žádný chybějící posudek se
nepředstírá. Výslednou strukturovanou summary zaznamená host jako report receipt
v auditu, bez potřeby dalšího nástrojového volání. Není to potvrzení kandidátů.

Příprava report-only je idempotentní, zachová původní stavy/historie v auditu,
nepřidává rozpočet bez explicitních parametrů. Modely/ceny/credentials se nemění.
Stará vícekolová kritika je pouze přes --no-report-only; pro konečné uzavření
ji nepoužívej. Automatické znovuotevírání nedokončených kritik je report-only
fází zablokované. Reporter má přesně jedno další kolo; opakované modelové
volání nenavyšuje limit automaticky. Další chyby či limity se hlásí pravdivě.

Ověření: 27 SDK/report/closure regresí, včetně skutečného Agents SDK s fake
providerem: jeden modelový požadavek, žádný tool, dokončený report receipt,
nezměněný kandidát a žádné smyšlené kritiky. Kopie posledního checkpointu:
16 kandidátů, 9 kritik, packet cca 11800 znaků, konzervativní request rezerva
cca 26700 tokenů včetně 5000 systémových znaků a 4000 výstupu; zůstává 45915.
Nebylo potřeba další navýšení tokenů. Původní run při replayi nezměněn, API 0.

Příprava (bez placeného API):

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py close-research "CESTA_BEHU" --report-only --note "Konecna synteza bez dalsiho hledani"
```

Potom resume s --backend openai provede jednorázovou placenou syntézu. Historické
postupy vícekolového uzavírání níže nejsou doporučený finální postup.

## 0.9.3 — Explicitní uzavření běhu

`close-research` je operator-only příprava, nikoli placený modelový běh. Načte
z dosavadního auditu argumenty screen_carrier s konkrétním proposed_change,
uchová celé původní sketches v context/CLOSURE_SKETCHES.json a přes běžné
policy/admission kontroly a deterministický dedup zachytí neověřené kandidáty. Opakované formulace
stejného providera od téhož agenta odkazují na stejný kandidát; různí poskytovatelé
mohou být varianty téhož mechanismu a musí je posoudit kritik. UNKNOWN pricing,
žádný PASS nebo tvrzení o novosti/realizaci se negenerují. Záznamy bez konkrétního
proposed_change se automaticky nemění v nápad. Původní audit zůstává zachovaný.

Discovery/coordination role se zastaví, původní stavy jsou v closure auditu.
Historie modelových konverzací se archivují před resetem; dokumenty a tool
receipts zůstávají. Kritici dostanou omezenou round allowance podle počtu IDEA,
reportér dvě kola. Hosted search i vytváření nových kandidátů/specialistů jsou
v uzavírací fázi vypnuté. Kritici mohou dočíst nezbytné primární dokumenty;
reportér uzavírá stávající IDEA. Neznámé provider rezervace musí nejprve vyřešit
operátor, closure je nepřepisuje.

Příprava je idempotentní: opakování nepřidává stejné nápady ani stejné rozšíření
limitů. Rozšíření tokenů/času/kroků je explicitní, default nula. Ceny, credentials,
režim brainstormingu ani approvals se nemění. Automatická rezervace části
rozpočtu pro závěr budoucích nových běhů zatím není součástí tohoto příkazu.

Příklad pro existující silný run; přidává maximálně 2M tokenů, 30 minut a 30 kol:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py close-research "G:\metaweb-swarm-runs\20261103-092847-bc19693a" --note "Uzavrit dosavadni navrhy bez dalsi discovery" --extend-tokens 2000000 --extend-seconds 1800 --extend-steps 30
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\20261103-092847-bc19693a" --backend openai
```

První příkaz nevolá model, druhý pokračuje placenou kritikou a reportem.
Závěry mohou být REVISE/deferred; ukončení role není potvrzení mechanismu.

# Spuštění a modely (0.9.0)

Výchozí je výzkum a brainstorming. **Docker není potřeba.**
V CMD s nastaveným `OPENAI_API_KEY`:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run.cmd
```

Nový běh se uloží do `G:\metaweb-swarm-runs`; cestu vypíše při startu.
`run-research.cmd`, `run-supervised.cmd` a `run-http.cmd` jsou stejné výzkumné
aliasy. Používá se `config.research.json`, modely jsou nyní rozdělené podle tierů.

## Pokračování, pauza a kontrola

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "CESTA_BEHU" --backend openai
G:\metaweb-swarm-env\Scripts\python.exe swarm.py pause "CESTA_BEHU"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py status "CESTA_BEHU"
```

`resume` pokračuje v původním zachyceném profilu. Nemění staré Docker runy na
brainstorming. Pro nový režim založ nový běh. Explicitní rozšíření vyčerpaného
limitu role: přidej k resume `--extend-rounds 1`; runtime/token limity zůstávají.

## Modelové tiery

V `config.research.json`:

```json
"model_tiers": {
  "cheap": "gpt-6-luna",
  "strong": "gpt-6.1-terra",
  "flag": "gpt-6.1-sol"
}
```

| Tier | Role |
|---|---|
| `flag` | Orchestrator, Loophole Archivist, Hostile Reviewer, Synthesizer |
| `strong` | Anomaly Engineer, Format Mutant, Failure-Domain Hunter, Future Archaeologist, Evidence Auditor |
| `cheap` | Infrastructure Scout, Role Architect |

Emergentní role mají standardně `strong`. `role_model_tiers` umožňuje změnit
přiřazení konkrétní role. Hodnota `model` slouží jako fallback; tier má přednost.
Pro jednorázové přepsání všech tierů: `run.cmd --model NAZEV_API_MODELU`.
Změna configu platí pro nové runy, nikoli už uložené checkpointy. Levné testování zůstává dostupné: `run.cmd --config config.cheap.json`.

## Experimentální realizace

```cmd
run-experimental.cmd
```

Původní plný prototyp s `config.http.json`, Docker/PyPI a HTTP, externí zápisy
se schvalují. Samostatný sandbox: `run-sandbox.cmd`. Nepotřebuješ je pro
brainstorming. [Příprava Dockeru](DOCKER_SETUP.md). Další vývoj plné autonomie je
strategicky odložen, schopnosti zůstávají pro dobrovolné experimenty.

## Instalace, cesty a klíč

Stávající `G:\metaweb-swarm-env` lze použít beze změn. Nová instalace a nastavení
klíče jsou v [README](../README.md#instalace-a-nastavení). Launchery používají
`SWARM_PYTHON`, lokální `.venv`, existující prostředí na G: nebo `python` v PATH.
`SWARM_RUNS_ROOT` změní umístění runů. Všechny launchery jsou součástí projektu;
nepotřebují adresář chatu nebo dočasné `outputs`.

Host capture používá zvláštní operator-only cestu: deterministické slučování
a běžné policy/admission kontroly zůstávají, ale nevykonává placené sémantické
posouzení identity. Takto zachycené IDEA mají closure_provisional=true a jejich
počet není počet nových mechanismů. Různé aliasy stejné služby mohou zůstat
samostatnými provizorními variantami, které mají kritici výslovně označit. SDK
nemá přístup k parametru host_closure_capture a v closing fázi nemá submit_idea.
Ověření: 44 souvisejících testů a následná 28-case SDK/closure/profile sada
po doplnění operator-only capture. Offline fixture dokončila dva kritiky a
report bez nové discovery, bez API a bez mutací původního runu.
