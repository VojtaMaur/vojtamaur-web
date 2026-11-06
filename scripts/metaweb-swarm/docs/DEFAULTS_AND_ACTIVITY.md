# Uložené profily a sledování práce

Vedle vestavěných profilů lze ukládat další pojmenované varianty, přejmenovávat je
a mazat; postup je v [NAMED_PROFILES.md](NAMED_PROFILES.md).

V GUI lze upravit výchozí nastavení každého ze tří profilů: brainstorming,
brainstorming s levnými modely a experimentální plný běh. Uložení profilu
nezakládá běh a nevolá placené API.

## Co se ukládá

Ukládá se hlavní zadání, vybrané seed role, jejich upravené mise, přiřazení
modelových tierů, modely v tierech, počty kol, vlastní startovní agenti a
zobrazené rozpočty. Nastavení přežije zavření GUI i restart počítače.

Výchozí soubory projektu se nemění. Uživatelské nastavení leží vedle běhů
v provozní složce swarmu, standardně:

```text
G:\vojtamaur-metaweb-swarm-files\defaults\research.json
G:\vojtamaur-metaweb-swarm-files\defaults\cheap.json
G:\vojtamaur-metaweb-swarm-files\defaults\experimental.json
```

Pokud je nastavené `SWARM_FILES_ROOT`, použije se jeho podsložka `defaults`.
Složka musí být mimo produkční projekt. Propojené soubory a junction/symlink
v této cestě jsou odmítnuty. Zápis je atomický; poškozené nebo neplatné
nastavení se nepoužije potichu.

Volba obnovy profilu odstraní pouze jeho uživatelské změny a načte původní
profil dodaný s projektem. Ostatní profily a starší běhy zůstanou zachovány.

## GUI a CMD používají stejné nastavení

Nový běh v GUI vychází z uloženého profilu. Případné změny ve formuláři pro
jeden nový běh samy o sobě výchozí profil nepřepisují. Komentář pro konkrétní
běh se připojí k jeho zadání; do výchozího profilu se automaticky neukládá.

Příkazy `swarm.py init` a `swarm.py start` také načítají uložená nastavení,
pokud používají původní projektový `config.research.json`, `config.cheap.json`
nebo `config.http.json`. Platí to i pro výchozí profil při vynechání
`--config`. Výslovné argumenty jako `--task` a `--model` mají přednost pro
daný nový běh. Vlastní konfigurační soubor na jiné cestě se načte samostatně.

`resume` používá nastavení uložené v checkpointu konkrétního běhu. Pozdější
úpravy výchozího profilu nemění jeho role, modely ani oprávnění. Rozpočet
staršího běhu lze rozšířit existujícími volbami pokračování.

Editor výchozího profilu nepřidává externí přístupy, credentials, Docker,
instalaci balíčků ani nevypíná approval. Tyto schopnosti nadále vycházejí ze
zvoleného původního profilu. Změna mise neuděluje další technická oprávnění.

## Co je vidět během běhu

Panel průběhu nyní zobrazuje konkrétní pozorované události: začátek a konec
kola, čekání na model, webové dotazy, názvy nástrojů, bezpečné části jejich
zadání, čtené soubory a dokumentaci, krátké výňatky veřejných odpovědí a
poznámky agentů. Detail může obsahovat účel dotazu, cestu, název služby či
ID nápadu. Seznam zachovává posledních 80 smysluplných událostí. U každého
agenta je navíc dostupná jeho poslední činnost, i když mezitím ostatní agenti
vyprodukovali mnoho událostí.

SDK checkpointy a historie modelů se do tohoto přehledu nevkládají a
nevytlačují užitečné události. Veřejný rozepsaný výstup modelu má vlastní
náhled. Agent, který zatím pouze používá nástroje, nemusí mít žádný
rozepsaný text; v tu chvíli jeho práci ukazuje přehled nástrojů a dokumentů.
Zobrazená čekající operace se může aktualizovat až s další skutečnou událostí.

Přehled neobsahuje skryté uvažování, celé historie, síťové hlavičky, cookies,
HTTP těla ani hodnoty credentials. U URL se nezobrazují přihlašovací údaje,
query parametry ani fragmenty. Textové výňatky jsou omezené a redigované.
Události a výsledky přečtené z internetu zůstávají nedůvěryhodným obsahem;
zobrazení události samo o sobě nepotvrzuje správnost tvrzení agenta.

Brzké pracovní hypotézy jsou zobrazeny odděleně od formálních IDEA. Stav
`UNREVIEWED` výslovně znamená neprověřený návrh, nikoli hotovou archivaci,
úspěšný prototyp nebo ověřený nový mechanismus.

