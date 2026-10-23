# Aktuální report a běžný výzkum — 0.7.3

První live coding test prošel host acceptance i nezávislým SUBCOMPONENT auditem.
Původní závěrečný LIMIT_REACHED zůstal na reporterovi: jeho historie a conclusion
pocházely z doby před úspěšným testem. Výsledek implementace tím nebyl zneplatněn.

Reporter má nyní vlastní CURRENT_RUN_REPORT assignment svázaný s revizí podkladů.
Při změně výsledků archivuje starou konverzaci stejně jako jiné role. Nový bounded
packet dostane přímo v promptu, včetně aktuálních counts, testů, scope verdictů,
acceptance výsledků a příznaku otestované dílčí součásti. Může rovnou zapsat report
receipt; get_research_task slouží i k případnému obnovení packetu. Nezkoumá znovu
baseline, nepíše kód a neopakuje experimenty.

Revize sleduje také Docker development příkazy, acceptance kontroly, balíčky,
prototype reviews, external actions a approvals. Vlastní aktivita reportera,
souhrn, modelová historie a plynutí času revizi nemění, takže se report sám
nezneplatňuje. Historický receipt zůstává v auditu. Neaktuální modelová syntéza se
v hlavním reportu označí místo vydávání za současný závěr.

## Nový běžný běh

V CMD se skutečným OPENAI_API_KEY a běžícím Dockerem:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-http.cmd
```

To založí nový placený výzkumný běh celého seed roje podle config.http.json.
Všechny modelové tiery zůstávají gpt-5.4-mini. Agenti hledají vlastní kandidáty;
programování probíhá v soukromých Docker workspaces. HTTP je dostupné, externí
zápisy dál vyžadují schválení; host osobní účty nejsou přiděleny.
Globální nastavení zůstalo 40 kol, 3 000 000 tokenů a 3600 sekund aktivního času.
Žádný další CBOR/PyPI/HTTP smoke před tímto během není potřeba.

Pokračování existujícího běhu vyžaduje jeho vypsanou cestu:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "CESTA_BEHU" --backend openai
```

Instalace opravy původní run nepřepisuje, nerozšiřuje jeho limity ani jej nespouští.

## Ověření

66 cílených kontrol prošlo: archivace report kontextu, nové revize evidence,
nezneplatňování vlastní činností, current prompt, dokončení role skutečným SDK se
skriptovaným modelem, označení staré syntézy, dosavadní packet/předání/core chování.
Neproběhlo placené modelové volání ani nový výzkumný run.

[Read-only replay původního live stavu](validation/REPORTER_REFRESH_PROOF.json)
vrací 1 úspěšnou acceptance, 1 recorded test a 1 SUBCOMPONENT review. Starý závěr
v novém promptu není. Prompt má 3529 znaků při limitu 20000. Původní checkpoint
zůstal beze změn. [Výsledky kontrol](validation/REPORTER_REFRESH_TESTS.txt).
