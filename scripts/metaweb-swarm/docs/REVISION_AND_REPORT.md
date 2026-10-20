# Opravy po REVISE a stručný reporter (0.6.16)

## Spuštění ve Windows CMD

Ve složce `G:\vojtamaur-web\scripts\metaweb-swarm`, s nastaveným
`OPENAI_API_KEY` a spuštěným Docker Desktopem:

```cmd
run-http.cmd
```

To vytvoří nový izolovaný výzkumný běh. Modely, globální limity, konfigurace
externích oprávnění a schvalování se touto aktualizací nemění. Docker image
není třeba přestavovat. Instalace aktualizace sama výzkum ani API nespouští.

Pro pokračování existujícího běhu použij jeho skutečnou cestu:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\ID_BEHU" --backend openai
```

Resume samo nezvýší vyčerpané limity kol/tokenů/času. Aktualizace nepřepisuje
historické výsledky ani neresetuje původní účtování. Pro další výzkum po dnešním
vyčerpaném běhu je vhodný nový `run-http.cmd`.

## Dva rozdílné opravné postupy

- **Nonzero exit:** `read_failed_experiment` a nezávislá diagnóza pádu kódu
  z 0.6.15 zůstávají v platnosti.
- **Exit zero + nezávislé REVISE:** nový úkol `LOCAL_REVISION` dostane přesný
  posudek, původní plán a neměnný zdroj skutečně vykonaného testu. Stará
  konverzace se archivuje, aby deklarace „už jsem hotov“ nepřebila nový úkol.

Prototyper musí pomocí `read_revised_test` přečíst celý původní zdroj,
opravit implementaci a aktualizovat `record_prototype_plan` s
`revision_test_id`, `repair_notes` a `repair_check`. Nové deklarace cíle,
přejmenování souboru či poznámka o starém receipt nenahradí změněné bajty kódu.
Host směruje práci na implementační nástroje, nový běh a následně `record_test`.
Po úspěšném provedení se nevynucuje další Docker běh jen kvůli evidenci.
Nový test opět potřebuje nezávislý posudek; oprava sama nezíská PROTOTYPED.

Pokud chybí reálný vzorek, dokumentace, přístup či potřebná schopnost,
`record_research_blocker` uchová konkrétní překážku a dovolí pokračovat dalším
kandidátem. Dvě dokončená kola bez změny zdroje nebo nového testu vytvoří
`PROTOTYPE_REVISION_STALLED` pro daný lokální úkol. Hypotéza není REJECTED.
Změna kandidáta či nové řešení zaznamenané operátorem umožní nové posouzení;
limity běhu a role nadále platí. Hash změněného kódu měří postup práce, nikoli
jeho vědeckou správnost — tu znovu posuzuje auditor.

## Reporter a úplné důkazy

`get_research_task` v roli SYNTHESIS vrací omezený přehled aktuálních kandidátů,
stavů, hodnocení testů, místních odkladů a přesných počtů skutečných akcí.
Neobsahuje opakované původní submissions/revisions ani HTTP hlavičky.
Výchozí HTTP profil omezuje tento přehled na 10 000 znaků; u větších inventářů
výslovně označí vynechané souhrny. Seznam ID zůstává úplný, případně je dostupný
stránkovaným indexem. Nulový počet ověřených uložení je platný závěr reportu.

`read_report_detail(section, record_id, offset, limit)` umožňuje dočíst jeden
původní záznam po nejvýše 8 000 znacích. Prázdné ID vrací stránkovaný index.
Úplné checkpointy, přílohy a audit zůstávají zachované; tato projekce mění
pouze velikost podkladů modelu. Lokální úkoly rovněž neopakují historická
submissions/revisions ve svých podkladech. Úplné záznamy jsou v auditu a
`context/SWARM_STATE.json`.

## Co bylo ověřeno

Na kopii běhu `20261015-085555-e0c9aaeb` reporter dokončil závěr bez navýšení
limitů. Prototyper po dvou neproduktivních kolech odložil Commons a dostal
IDEA-0002. Původní soubory běhu zůstaly hashově shodné.

Samostatný průchod přes skutečný SDK a Docker ověřil cestu čtení posudku →
změna kódu → plán s vazbou na REVISE → jeden nový běh → nový test → nezávislé
SUBCOMPONENT posouzení. Skript skutečně četl vyrobený soubor, obnovil původní
bajty a odmítl poškozený payload. Jde o integrační fixture, nikoli nový
preservation mechanism nebo veřejné uložení. Modelové odpovědi a kód v tomto
ověření dodal Codex; neprokazuje to samostatnou výzkumnou kvalitu cheap modelu.

Přenosné výsledky: `docs/validation/REVISION_REPORT_PROOF.json`.
Žádné placené API ani veřejné externí zápisy při vývoji.

Návrh krátkého modelového kontextu navazuje na
[OpenAI Docs: správa kontextu SDK](https://developers.openai.com/cookbook/examples/agents_sdk/session_memory).
Implementace používá lokální účtování a rozhraní instalovaného SDK 0.23.1,
bez změny modelů nebo závislostí.
