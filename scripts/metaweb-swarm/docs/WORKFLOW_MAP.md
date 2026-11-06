# Živá mapa roje

V detailu libovolného běhu otevři kartu **Mapa roje**. Funguje i pro starší
běhy, pokud obsahují potřebné záznamy. Není potřeba nový API běh ani Docker.

Nahoře je schéma fází a počty uzlů v každé z nich. Jde o orientaci v systému,
nikoli přesné pořadí volání: agenti se střídají po omezených kolech a posudky
se mohou vracet k rozpracovaným nápadům. Experimenty a akce jsou volitelné.
Stejná fáze může obsahovat pracovníky i jejich výstupy; počet uzlů proto
není počtem modelových volání ani počtem dokončených úkolů.

Mapa při otevření vybere právě pracujícího agenta, jinak první nápad nebo
prvního agenta. Kliknutí na uzel zobrazí jeho přímé vazby, uložený stav,
shrnutí a podrobnosti. Z detailu lze přejít na činnost agenta, příslušný
nápad či námět nebo report. Pro vztahy celého běhu zvol **Celá síť**;
větší graf lze zúžit výběrem fáze nebo hledáním podle jména a ID.

Pozadí posuneš tažením. Přiblížení funguje tlačítky nebo Ctrl + kolečko;
**Zobrazit celé** přizpůsobí výřez. Uzly lze vybrat i klávesnicí nebo
rozbalovací nabídkou. Na úzké obrazovce se detail přesune pod graf.

Graf používá stávající obnovu GUI každé 2,5 sekundy. Zachovává vybraný uzel,
přiblížení, posunutí a rozečtený detail. Aktivní přidělení se zvýrazní pouze
tehdy, když skutečně běží proces a dotyčný agent má stav RUNNING.
Zastaralé RUNNING bez procesu se ukazuje jako přerušené.

## Co šipky skutečně znamenají

- Rodič → specialista: uložené `parent_id`, nikoli domnělé řízení celého týmu.
- Agent → námět/nápad: autorství nebo příspěvek z uložené provenance.
- Agent → cíl: aktuální či poslední zachycené přidělení úkolu, oddělené od posudku.
- Posuzovatel → námět/nápad/test: zaznamenaný posudek a jeho verdikt.
- Pracovník → námět: uložený pokus o rozpracování.
- Námět → IDEA: výslovně zaznamenaná návaznost, nikoli podobnost názvů.
- Agent/nápad → test, experiment, externí akce nebo schválení: uložená vazba.
- Zpracovatel/nápad → report: potvrzení zápisu závěru a výslovný seznam IDEA ID.

Šipky **nejsou přímými zprávami mezi modely**. Opakované posudky se slučují
pod jednu vazbu s počtem záznamů. Dvě zmínky téhož převodu HYP → IDEA
nevytvářejí dvě události. Existence reportu nedokládá dokončení všech rolí;
záznam testu sám nepotvrzuje funkčnost celého mechanismu.

## Implementace

`metaweb_swarm/workflow_graph.py` vytváří pouze čtecí projekci checkpointu,
nejvýše 600 uzlů; případné omezení je v mapě přiznané. Koncové body vazeb
musejí existovat v grafu. Do odpovědi nejdou historie modelů ani credentials.
GUI využívá autentizované `/api/run`, stávající redakci citlivých hodnot a
lokální `workflow.js` bez CDN či nové knihovny. Zobrazení nezapisuje do běhu,
nevolá model a nemění scheduler, CLI, schvalování ani rozpočty.
