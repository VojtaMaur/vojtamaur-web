# Náměty, předběžná kritika a závěr

Brainstorming může mít užitečný výstup i bez formální IDEA. Karta **Náměty**
obsahuje zachycené HYP návrhy, mechanismus, nejistoty, zdroje, autory a případnou
předběžnou kritiku. Nejde o human approval, ověření novosti ani ověření služby.
Počty námětů a formálních IDEA jsou oddělené v přehledu i seznamu běhů.

Výzkumníci dál používají `record_hypothesis`; konkrétní screeningové návrhy se
zachovávají také automaticky. Stejné mechanismy mohou mít varianty. Formální
`submit_idea`, deduplikace, stavy a důkazy realizace zůstávají zachované.

## Předání ke kritice

U OpenAI brainstormingového běhu host přiřazuje kritickým rolím přímo dávky po
nejvýše šesti námětech. Autor nehodnotí vlastní námět. Každá dávka dostane jeden
modelový požadavek bez nástrojů a webového hledání. Výstup musí obsahovat právě
přidělená HYP ID, konkrétní důvody, nejistoty a další validační krok. Neúplný nebo
neplatný výsledek se neoznačí za dokončené hodnocení.

Posudky jsou `PROMISING`, `NEEDS_EVIDENCE`, `UNSUITABLE`, `DUPLICATE` a vždy mají
scope `PRELIMINARY_CONCEPT_CRITIQUE`, verified=false. DUPLICATE musí odkázat na
jiné skutečné HYP ID. Nemění stav námětu na schválený, ověřený či realizovaný.
Podklady se při velkém objemu zkracují s označením; hodnocení je konceptuální,
nikoli plnohodnotný audit primárních zdrojů. Formální IDEA nadále používají
stávající samostatný audit. Limity mohou zanechat část námětů bez posudku.

## Syntéza

Při existujících námětech dostane reportér jedním souhrnem všechny HYP ID,
návrhy a předběžné posudky, spolu s formálními IDEA. Nemá nástroje a závěr
vrací v jediném požadavku. Host ho uloží do dosavadní report receipt.
Tím odpadá řetěz čtení indexů a jednotlivých detailů před napsáním závěru.
Globální tokenové/USD/časové limity a bezpečné účtování rezervací platí dál;
závěr se nemůže vytvořit, pokud se nevejde už ani jeho požadavek.

Výsledky brainstormingu, náměty a posudky jsou na začátku `SWARM_REPORT.md`;
technický audit zůstává za nimi. Při chybějícím modelovém závěru to report
výslovně říká a zachovává pracovní výstupy.

## Paměť

`RUN_MEMORY.json` obsahuje vedle `candidates` samostatné `hypotheses`, nejvýše
100 na běh a 200 v sestavené historické paměti. Každý má status UNREVIEWED,
record_kind PRELIMINARY_HYPOTHESIS, verified=false, referenci na původní běh
a zkrácené nejistoty. Neznamená to schválení, zamítnutí ani implementovanou
vrstvu. Lze je najít přes paměť GUI i `check_prior_work`; host je nepoužije
jako důvod automatického odmítnutí novosti. Mohou se dále rozpracovat.

Paměť je odvozený přehled. Starší zachycené `context/prior-runs.json` zůstávají
historickým snímkem; nový společný index lze znovu sestavit ze zastavených běhů.
Resume nemění modely, oprávnění ani rozpočty dřívějšího běhu.

Ověřeno bez placeného API: 32 námětů → dvě nezávislé kritiky → 64 posudků →
jednopožadavková syntéza, také přes celý plánovač; chybné pokrytí dávky se blokuje.
