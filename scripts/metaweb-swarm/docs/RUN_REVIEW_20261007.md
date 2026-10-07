# Revize prvního autonomous Docker běhu

Run: `G:\metaweb-swarm-runs\20261007-052011-7c9a9a90`, verze 0.2.0,
`gpt-5.4-mini`, autonomous / sandbox-only / Docker.

Revize čte SQLite checkpoint v read-only režimu, audit, zdrojové prototypy a
receipts. Původní checkpoint, kandidáti ani report nebyly přepsány. Toto jsou
závěry revize, nikoli nové agentní objevy.

## Verdikt

**Fungující ohraničený framework, ne úspěšně dokončený preservation výzkum.**
Roj skutečně vytvořil soubory a spouštěl kód v Dockeru. Zůstal v sandbox-only,
nevytvořil externí deposit a zachoval audit při vyčerpání rezervací. Výzkumná
kvalita a shoda prototypů se zamýšlenými mechanismy však nejsou doložené.

- 10 agentů, 27 kol, 108 modelových requestů, 16 hosted search volání.
- 1 551 197 input + 26 268 output = **1 577 465 tokenů**.
- Přibližně 34 min 49 s aktivního času. Lokální USD cena není nastavená;
  checkpoint nedokládá skutečnou fakturu.
- Hash chain všech **1 102 auditních událostí** ověřen. Žádná neuzavřená budget
  reservation a `unknown_steps=0`.
- 7 IDEA ID, přibližně **5 mechanismů** po identifikaci dvou duplicitních párů.
- 2 Docker experimenty: jeden exit 0, druhý exit 1. Jeden test receipt, žádný
  externí deposit. Všech 10 agentů skončilo `LIMIT_REACHED`.

## Co skutečně vytvořili

| IDEA | Výsledek revize |
|---|---|
| 0001 ORCID recovery pointer | Rozpracovaná hypotéza veřejného odkazu na archivovaný build. Žádný deposit ani test obnovy. |
| 0002 + 0003 CC REL / RDFa license plaque | Jeden mechanismus pod dvěma ID. Existuje lokální HTML specimen; nebyl spuštěn funkční test. |
| 0004 self-described CBOR bootstrap | Spuštěný toy round-trip, **nikoli CBOR implementace**. |
| 0005 Wikidata statement pointer | Rozpracovaný odkazový mechanismus, bez depositu a doložené obnovy. |
| 0006 + 0007 QR + XMP card | Jeden mechanismus pod dvěma ID. Skript neproběhl kvůli chybějící PIL. |

Přínos je hlavně zjištění chyb ve flow a několik hypotéz o discoverability/
recovery pointers. Z tohoto běhu nelze doložit novou nezávislou kopii webového
buildu. Odkaz či nový formát sám další custody vrstvu nevytvoří.

### „CBOR“

`agents/AGENT-008/workspace/prototype/cbor_recovery_bundle.py` výslovně označuje
formát jako pseudo-CBOR. `encode()` vrací `b'CBORREC1'` následované JSON UTF-8;
`decode()` používá `json.loads`. Assertion ověřuje pouze round-trip vlastního
formátu. Payload obsahuje `example.invalid` a vymyšlený hash. Není to důkaz
RFC 8949 kompatibility, nezávislého decoderu, reálného exportu ani uchování webu.
Test receipt neměl přiřazené artefakty či exporty, takže nevázal testované bajty
na výsledný kandidát.

### QR / XMP

`agents/AGENT-008/workspace/prototype/qr_xmp_card.py` importuje `PIL` a `qrcode`,
které stdlib image neposkytuje. Experiment skončil
`ModuleNotFoundError: No module named 'PIL'`; nebyla vytvořena karta. Ani při
doplnění knihoven tento skript zatím nevkládá XMP: vykresluje QR pro placeholder
URL a text části hash. Digitální metadata nelze zaměňovat za informace uchované
na vytištěné kartě; výsledný návrh potřebuje jasný decoder a test.

## Proč skončila syntéza

Z globálních 2 000 000 tokenů zůstalo 422 535. Přesto se další request reportéra
nevešel: systém rezervoval až 3 × 128 000 tokenů pro web search, k tomu prompt,
schema, tool odpovědi a maximum output. Reportér už dostal jednu odpověď
(23 168 tokenů), ale nedokončil typed závěr. Deterministický report se zapsal.

Jde o rezervaci horního limitu před požadavkem, ne účtovaných 384 000 search
tokenů. Účet proto může mít kredit, zatímco lokální kapacita na request nestačí.
Ochrana rezervace se nevypíná; role bez potřeby discovery search jej nově nemají.

Orchestrator a Role Architect po svém jediném kole narazili na SDK 6-turn bound.
Nástrojové výsledky zůstaly v auditu, ale nevznikl typed závěr. Jasnější assignment
a odebrání redundantního search mají snížit zbytečné kroky. Kvalitu ukončování
musí potvrdit další levný živý běh; offline test ji věcně nesimuluje.

## Deduplikace

QR dvojice má shodný fingerprint a scope, ale různé agentem vytvořené
`mechanism_key`. Původní fallback odmítal přesnou textovou shodu, jakmile měla
obě podání odlišný explicitní klíč. Nově se neznámé rodiny se shodným přesným
claimem/scope sloučí i při rozdílném klíči. Známé různé mechanismy/scope se
neslučují; nejde o obecné fuzzy matching.

CC REL dvojice mění i prose/scope: `cc-rel-recovery-pointer / license-plaque`
vs `cc-rel-license-plaque / rdfa-plaque`. Host pravidlo nově rozpoznává tyto
konkrétní aliasy jednoho RDFa recovery plaque. Jiné scope zůstávají samostatné.
Contributors a jednotlivá podání se zachovají. Staré publikované IDEA ID z tohoto
běhu nebyly zpětně sloučené; pravidla platí při dalších podáních.

## Změny po revizi a další acceptance

- Modelové tiery per role, konzole s modely/IDEA/Docker událostmi a spouštěče
  přímo v projektu; všechny tiery stále mini, stejné globální limity.
- Koordinace/syntéza/lokální prototypování bez hosted search a jeho rezervace.
- Test receipt musí obsahovat konkrétní artefakt nebo materializovaný export;
  exit zero bez testovaných bajtů už nestačí. Požadavky na standards fidelity,
  skutečná data, dependency check a independent decoder jsou v promptu.
- V reportu jsou vypsané pokusy i test receipts; status souboru není certifikace
  formátu ani proof of preservation.

Příští levný sandbox run má doložit: konkrétní mechanismus na reálném exportu/
excerptu, existující artefakty svázané s testem, smysluplné assertions, žádné
uvedené duplicitní páry a dokončenou syntézu nebo jasný důvod jejího limitu.
Prompt nemůže automaticky dokázat pravdivost kódu či tvrzení malého modelu.
Externí uložení zůstává samostatný pozdější acceptance.
