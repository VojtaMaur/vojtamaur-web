# Od námětu ke konkrétní IDEA

Brainstorming pokračuje po konceptuální kritice omezeným rozpracováním vybraných
námětů. Samotné PROMISING se nepřeznačuje na IDEA ani na ověřený mechanismus.

## Výběr a rozpočet

Host čeká na první širší kritiku: nejvýše prvních 12 námětů od každé aktivní
kritické role, případně na dokončení dostupné kritiky. Potom vybere nejvýše tři
náměty s nezávislým PROMISING, přednostně s více takovými posudky. Výslovné
DUPLICATE vazby se seskupují; z každé skupiny postupuje jeden námět. Je to
omezený shortlist z dosavadních posudků, nikoli zaručený globální žebříček všech
pozdějších námětů nebo důkaz historické novosti.

Vznikne jeden **Candidate Developer** v tieru strong. Počítá se do max_agents.
Na každý námět má výchozí limit dvě kola. Používá stávající celkový tokenový,
časový, finanční i kolový rozpočet; nic se potichu nezvyšuje. Plánovač chrání
zbývající kola pro rozpracování a konečný report. Pokud tým nebo rozpočet nemá
místo, důvod se uloží a slibné náměty zůstanou zachované.

Při existujících HYP si každý nesyntetizační modelový požadavek drží také
konzervativní prostor pro závěr: min(96 000 tokenů, osmina celkového limitu).
Je součástí rezervace a po skutečné odpovědi se uvolní; nepřičítá se k účtované
spotřebě. Syntéza tuto přirážku nemá. Při tlaku na zbývající tokeny či kola
plánovač přesune pozornost z dalšího průzkumu ke kritice a rozpracování.

V editoru nového běhu i výchozího profilu lze nastavit **Vybrat nejvýše námětů**
(0–5; nula funkci vypíná) a **Kola na jeden námět** (1–4). Konfigurační klíče
jsou `brainstorm_development_candidates` a `brainstorm_development_rounds`.
Bez těchto klíčů ve starém checkpointu platí 3 a 2. Resume vždy respektuje jeho
dosavadní celkové limity; vyčerpaný běh neobdrží nový rozpočet aktualizací.

## Co pracovník dělá

Má web search, read_document, check_baseline, check_prior_work a jediný nástroj
pro ukončení úkolu: finish_development. Nemá zápis do projektu, Docker, upload,
správu účtů ani externí zápisy. Ke konci bounded round host směruje model na
uložení výsledku místo dalšího hledání. Historie se mezi vybranými náměty oddělí.

- **CANDIDATE:** konkrétní služba, mechanismus, porovnání s baseline, cesta
  rekonstrukce a tvrzení s primárními URL, které tento pracovník skutečně četl
  přes read_document. Host nedovolí samotný nalezený odkaz vydávat za přečtený
  podklad. Výklad zdrojů zůstává úsudkem modelu, nikoli hostem ověřeným faktem.
- **DEFERRED:** chybějící nebo neprůkazné podklady; konkrétní důvod se zachová.
- **REJECTED:** věcně zdůvodněná nevhodnost dané varianty. Chybějící realizace
  sama není důvod zamítnutí. Měsíční/roční nebo jiné opakované platby jsou dál
  vyloučené; neznámá cena může zůstat UNKNOWN se zapsanou nejistotou.
- **LIMIT_REACHED:** po vyčerpání přidělených kol bez platného výsledku host
  zachová stav a pokračuje dalším námětem, pokud se vejde do globálních limitů.

Vytvoření IDEA prochází dosavadním admission a run-local dedupe, včetně
porovnání levným modelem při nejednoznačné identitě. Pracovní IDEA má stav
INVESTIGATING a nemá důkaz realizace ani ověřené novosti. Odkazuje na původní
HYP a zachovává autory. Formální kritika IDEA pokračuje v dostupných limitech
kritiků; vyčerpané kapacity zůstávají v reportu výslovně nedokončené.

## Co uvidí člověk

Karta Náměty ukazuje shortlist, výsledky rozpracování, důvody odložení a odkazy
na vzniklá IDEA ID. Průběh práce hlásí přidělení a dokončení. Výsledky jsou i v
SWARM_REPORT.md, manifest.json, auditních událostech a v odvozené paměti běhů.
Reportér dostává skutečné výsledky rozpracování, ne pouze úvodní posudky.

Ověření bez placeného API: skutečný Agents SDK s lokálním modelem vytvořil
z námětu zdrojovanou IDEA přes normální host admission, zachoval vazbu a ukončil
úkol bez dalšího modelového požadavku. Otestovány jsou také poctivé odložení,
chybějící čtení zdroje, slučování výslovných duplicit, plný tým a uzavření reportu.

## Oprava 0.14.1

Jedno skutečné kolo zvyšuje čítač právě jednou. CONTINUE uloží checkpoint pro
další přidělené kolo, například při přesměrování dokumentace. Dřívější HYP
není implementovaný baseline; rozpracování může doplnit jeho chybějící podklady
bez předstírání nové myšlenky proti vlastnímu námětu. Kontrola reportu přijímá
také přesná HYP ID výslovně uvedená v závěru (včetně odložených/zamítnutých),
i když je model zapomněl připojit do pomocného seznamu. Skutečně vynechaná ID
stále brání přijetí závěru. Historie oprav neplní pracovní prompty.
