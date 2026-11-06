**0.12.0 — sjednocené pracovní soubory:** [umístění, přesun a nové cesty](RUNTIME_FILES.md).

# Lokální GUI Metaweb Swarm (0.13.0)

**Výchozí nastavení** v levém panelu ukládá zadání, role a limity pro příští běhy
v GUI i CMD. **Průběh práce** ukazuje nástroje, hledání a čtené podklady; pracovní
hypotézy jsou samostatně na kartě **Nápady**. [Uložené profily a aktivity](DEFAULTS_AND_ACTIVITY.md),
[šířka výzkumu a tokenové rezervace](BRAINSTORM_PRODUCTIVITY.md).

## Úprava zadání, týmu a živý náhled

Při založení běhu je **Celé zadání tohoto běhu** předvyplněné cílem profilu.
Můžeš ho celé přepsat. Volitelný doplňující komentář se připíše až za tento text.
Změna výzkumného cíle nemění oprávnění, approval ani limity.

U výchozích rolí rozbal **Upravit zadání role**. Interní názvy rolí zůstávají,
protože podle nich framework směruje audit, koordinaci a reportování; upravuje
se jejich mise, tier a počet kol. Tlačítko **Přidat agenta** přidává vlastní
pojmenované výzkumné specialisty s misí, tierem a limitem kol. Jejich názvy musejí
být unikátní. Počítají se do max. agentů i globálních limitů a ukládají se do
konfigurace/checkpointu. Vlastní specialisté začínají ve výzkumné fázi.

Výchozí Orchestrátor má nově dvě kola v brainstormingových profilech. Může
skončit dříve; plánování pořadí agentů stále řídí program, nikoli nepřetržité
volání orchestrátora. Zvětšení jeho limitu neprodlužuje automaticky celý běh.

**Živý náhled** ukazuje stream veřejného textu modelu (i neúplného JSON), nejvýše
posledních 12000 znaků. Aktualizace se auditují nejvýše přibližně jednou za
sekundu, max. 60 průběžných záznamů na odpověď plus dokončení. Skryté uvažování
se nepřenáší. Při práci s nástroji může být text prázdný; průběh je v aktivitách
a konzoli. Zapíná se pro nové GUI běhy (`live_output_preview`); staré běhy se
zpětně nepřepínají a demo žádný skutečný modelový stream nevytváří.

Nastavení cest i klíče mají jediné tlačítko **Nastavení / API klíč** vpravo nahoře.
Původní postranní tlačítko bylo odstraněno. CLI zůstává kompatibilní.

Ověřeny GUI/backend/brainstorming regrese, vlastní role, nahrazení zadání,
veřejný stream přes skutečný Agents SDK s lokálním modelem bez sítě a zrušení
streamu. Nebyl spuštěn placený modelový běh. Streaming vychází z
[oficiální dokumentace OpenAI](https://developers.openai.com/api/docs/guides/streaming-responses).

GUI je ovládací panel nad existujícím Python CLI. Nejde o další agentní runtime:
stejné profily, checkpointy, limity a audit zůstávají rozhodující. Původní CMD
spouštěče a všechny dosavadní příkazy fungují dál.

## Spuštění

Ve stávající instalaci:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-gui.cmd
```

Spustí lokální server a otevře běžný prohlížeč. Samotné otevření panelu nevolá
placené API, nevyžaduje klíč a nespouští Docker. Stačí stávající Python 3.11+
a běhové závislosti swarmu. HTML/CSS/JavaScript jsou součástí projektu; není
potřeba Node, npm, frontend build ani další UI knihovna.

Přímo přes CLI, případně bez automatického otevření prohlížeče:

```cmd
G:\vojtamaur-metaweb-swarm-files\env\Scripts\python.exe swarm.py gui --project G:\vojtamaur-web --runs-root G:\vojtamaur-metaweb-swarm-files\runs --no-browser
```

Pak otevři úplnou adresu vypsanou v terminálu včetně jejího fragmentu `#token=…`.
Port se standardně přidělí automaticky; lze zvolit `--port 8765`. Panel naslouchá
pouze na `127.0.0.1`, nepovoluje vzdálený přístup a nemá se publikovat na web.
Launcher respektuje `SWARM_PYTHON` a `SWARM_RUNS_ROOT` stejně jako ostatní CMD.

## Nový běh a konfigurace

V levém panelu zvol **Nový běh**. Profil určuje dostupné schopnosti:

| Profil | Význam |
|---|---|
| Brainstorming | Výchozí výzkum, kritika a report; bez Dockeru, instalací a externích zápisů |
| Brainstorming · levné modely | Stejné výzkumné schopnosti, tiery používají `gpt-5.4-mini` |
| Plný běh · experimentální prototyp | Dosavadní `config.http.json`: Docker, PyPI a obecné HTTP, externí zápisy se schválením |

Formulář zobrazuje oprávnění zvoleného profilu a dovoluje nastavit modely
`cheap/strong/flag`, výchozí role, tier a počet kol jednotlivých rolí, celkové
tokeny, aktivní čas, kola, maximum agentů, tahy v kole a maximum výstupních tokenů.
Nulový výběr rolí je odmítnut; nevytvoří nechtěně celý tým. USD limit se zobrazuje
z profilu. Zůstatek účtu se nečte; vykázaná cena je odhad, nikoli faktura.
Změny modelů mohou změnit cenu i při stejném tokenovém rozpočtu.

Nastavení se uloží jako samostatný runtime profil do `.gui/profiles` pod složkou
běhů, mimo produkční projekt. Zdrojové profily se formulářem nepřepisují.
Změny platí pro **nový běh**, nikoli zpětně pro již vytvořené checkpointy.

Ve formuláři lze zvolit OpenAI backend (placený výzkum) nebo jasně označené
**offline demo** bez modelových volání. Demo ověřuje infrastrukturu, nepředstavuje
skutečný objev. Zachycení aktuálního veřejného kontextu webu je samostatná volba;
pro čistě offline demo je vypni. Plný experimentální profil potřebuje připravený
a běžící Docker; jeho přepnutí samo nezpřístupní osobní hostitelské účty.

## Komentář před startem a během práce

Pole **Vaše zadání pro swarm** před startem doplní původní cíl profilu o tvůj
komentář, například „Hledejte jen digitální možnosti, ne fyzické nosiče.“
Základní preservation mise a oprávnění zůstávají. Celé výsledné zadání musí
vyhovět existujícímu limitu 12000 znaků; delší kombinace se odmítne.

U otevřeného běhu použij **Pokyn pro další krok** (nejvýše 1800 znaků). Komentář
se nejdříve uloží jako `QUEUED` do `operator-inbox`; GUI nesoutěží s runnerem
o zápis do SQLite. Runner ho převezme na bezpečné hranici mezi omezenými batchi
nebo při resume a zapíše `APPLIED` s auditem. Právě běžící modelové volání nebo
experiment se nepřerušuje a dosavadní závěry se automaticky nepřepisují.

Agenti dostávají **poslední tři aplikované komentáře**. Novější protichůdné
výzkumné preference mají přednost, starší záznamy dál zůstávají v auditu.
Komentář nemění oprávnění, credentials, approval, hard limity ani vybraný režim.
U dokončeného běhu samotný komentář nezakládá nový výzkum ani negarantuje nové
modelové kolo; pro jiné nové zadání je vhodný nový běh.

Stejná cesta existuje i v původním CLI:

```cmd
G:\vojtamaur-metaweb-swarm-files\env\Scripts\python.exe swarm.py comment "CESTA_BEHU" --text "Pouze digitalni moznosti ulozeni, bez fyzickych nosicu."
```

## Přehled práce a výsledků

Seznam běhů čte skutečné uložené stavy. Detail zobrazuje tokeny a limity, aktivní
čas, odhad ceny, role/modely, aktuální přidělení, poslední aktivitu, nápady, report,
parametry a schválení. Záznamy nápadů a report jsou výsledky výzkumu, nikoli
potvrzení implementace. Rozpracovaný směr a ověřený mechanismus se nerozlišují
jen barvou: dál platí původní stavové a auditní podmínky frameworku.

GUI nečte do karet celé historické konverzace nebo syrové odpovědi s credentials.
Souhrny čte přes read-only SQLite a konzolový výstup zobrazuje s redakcí tajných
hodnot. Běhy spuštěné mimo GUI se po aktualizaci také zobrazí. Pro konzoli je
sledovaný jeden GUI podproces; aktivita samostatného CMD se ukazuje přes stav
a audit běhu, nikoli kopírováním obsahu cizího okna terminálu.

## Pokračování, pauza, report a schválení

**Pokračovat** použije modely, schopnosti a profil z uloženého checkpointu.
Dialog dovoluje explicitně přidat tokeny, aktivní sekundy, kroky a kola.
Nezmění jej právě otevřený formulář nového běhu. Nevyčerpané peníze nenahrazují
vyčerpaný jiný limit.

**Pozastavit** vytváří stávající `PAUSE.flag`; aktuální omezená práce může doběhnout.
GUI rozeznává skutečného writera podle OS locku. Pouhý starý stav `RUNNING` po
pádu nenechá tlačítko Pokračovat navždy zablokované; autoritativní ochranu jednoho
writera dále vynucuje CLI `run_lock`.

**Připravit závěrečný report** připraví `close-research --report-only` bez placeného modelu.
Zastaví další rešerši i kritiku a ponechá zachované podklady pro jednorázový report.
Teprve následné **Pokračovat** provede placenou syntézu s nulovým seznamem tools.
Nevyřešené či neposouzené návrhy zůstávají přiznané; report není jejich ověření.
Limity se při tomto tlačítku samy nezvyšují.

V přehledu schválení lze zaznamenat rozhodnutí i poznámku. Pokud run ještě drží
writer lock, nejprve jej pozastav. Rozhodnutí ani příprava uzavření samy automaticky
nespouštějí placený resume nebo experiment. Původní technické a approval podmínky
externích akcí zůstávají.

## Swarm CMD a skutečný CMD

Spodní **Swarm CMD** zobrazuje výstup GUI podprocesů a přijímá stejné `swarm.py`
příkazy jako běžné CLI. Je to konzole swarmu, **ne obecný systémový shell**.
Argumenty se předávají jako seznam s `shell=False`; nevykonává se libovolné
PowerShell/bash/CMD vyhodnocování. Zkrácené základní launchery fungují jako aliasy;
pro parametry použij formulář nebo úplný `swarm.py` příkaz. Příkazy v této konzoli
musí pracovat s projektem a kořenem běhů nastavenými v GUI. Běží jeden GUI příkaz
najednou; pauzu a komentář lze poslat i během práce.

**Otevřít CMD** ve Windows otevře skutečné samostatné CMD ve složce swarmu.
Tam funguje původní CLI i další běžné terminálové příkazy. Proces dostane aktuální
API klíč z prostředí GUI, pokud je nastavený. Další podproces v samostatném CMD
není automaticky spravován GUI a svůj běh musíš ovládat jeho CLI/pauzou.

## API klíč, lokální relace a ukončení

Vpravo nahoře klikni na **Vložit API klíč** (po zadání **API klíč uložen · změnit**).
Vlož OpenAI API klíč a ponech zaškrtnuté **Zapamatovat API klíč i po zavření GUI**.
Příště jej GUI načte automaticky, takže platí pro další běhy i restarty. Lze jej
zobrazit při vkládání, nahradit nebo tlačítkem **Zapomenout uložený klíč** odstranit.
Bez zapamatování zůstává jen v paměti aktuálního GUI. Prázdné pole zachová aktuální
hodnotu. Změny se provádějí po dokončení nebo pozastavení aktivní GUI úlohy.

Soubor `G:\vojtamaur-metaweb-swarm-files\gui-settings.json` obsahuje klíč jako prostý text
(obecně `gui-settings.json` pod `SWARM_FILES_ROOT`). Je mimo projekt i běhy,
takže se nedostane do git commitu, snapshotu ani reportů. GUI jej neposílá zpět do
prohlížeče a předává jej podprocesu prostředím. Pokud uložený klíč není, převezme
`OPENAI_API_KEY` z CMD. Expiraci určuje poskytovatel klíče; prošlý klíč nahraď novým.

Lokální API vyžaduje náhodný token a správný Host/Origin. Není podporován CORS ani
obecné čtení lokálních souborů přes HTTP. Adresu s tokenem nesdílej; pro novou
GUI relaci vznikne nový token. Není to ochrana před malwarem spuštěným pod stejným
uživatelem. Osobní forge credentials nejsou přidělovány agentům.

Zavření browser tabu běžící úlohu nezastaví. Ukončení serveru přes Ctrl+C požádá
aktivní GUI běh o pauzu, nikoli o násilné zabití. Pokud se run teprve inicializuje,
požadavek se použije po získání jeho ID. Omezený aktuální batch může doběhnout.
Stav a checkpoint zůstávají pro další CLI/GUI resume.

## Ověření

Sada `tests.test_gui`, `tests.test_gui_review`, `tests.test_operator_comments`:
**33 testů prošlo**, jeden z celkem 34 testů byl vynechán kvůli Windows symlink
oprávnění. Ověřeny lokální HTTP auth hranice, profily, read-only stav, subprocess
argv/redakce, writer lock a zotavení, fronta komentářů, crash dedup a prompt guidance.
Python syntaxe a shoda verze `0.10.0` s pyproject byly ověřeny. Tyto kontroly
nepředstavují placený modelový výzkum. V prohlížeči byl navíc dokončen nový offline
demo běh, předání komentáře a resume se stejným demo backendem, načtení reportu
a spuštění `doctor` z integrované konzole. Vše na samostatném testovacím projektu;
žádné placené modelové volání ani externí upload.

## Paměť minulých běhů (0.11.1)

Tlačítko **Paměť běhů / RUN_MEMORY.json** vlevo otevře sdílený index z nastavené
složky běhů. Ukazuje shrnutí běhů a rozbalitelné kandidáty (mechanismus, stav,
překážku a další krok), nabízí hledání, otevření původního běhu a původní JSON
ke zkopírování. **Obnovit** znovu načte soubor; nic neregeneruje ani nezapisuje.
Zdroj lze přepnout na `context/prior-runs.json` právě vybraného běhu: to je paměť,
kterou dostal zachycenou pro svůj výzkum, nikoli dnešní sdílený index. Zdrojová
cesta a čas změny jsou vidět. Chybějící paměť se hlásí výslovně.
Index je omezený a odvozený; historické tvrzení není realizovaná baseline.
Úplná historie a důkazy zůstávají v původních bězích. Pohled je pouze pro čtení,
bez placených volání. Endpoint povoluje jen tyto dvě pevné cesty, odmítá propojené
soubory a načítá nejvýše 4 MiB; zobrazení prochází stejnou redakcí jako ostatní GUI.

## Mapa roje

Karta **Mapa roje** ukazuje fáze workflow a živé vztahy mezi agenty, náměty,
nápady a záznamy výsledků. Návod a přesný význam šipek: [WORKFLOW_MAP.md](WORKFLOW_MAP.md).
