# Programovací pracovník 0.7.2

Předchozí postup rozmělňoval práci do plánovacích formulářů, preflight review a
krátkých kol. Před každou opravou lokálního kódu se tak řešilo další předání.
Nový pracovník dostane jeden aktuální úkol a souvisle píše, spouští a opravuje kód.
Nezávislé posouzení přijde nad skutečně zachycenými výsledky.

Používáme existující `Runner` a `Shell`/`exec_command` z OpenAI Agents SDK 0.23.1.
Malý transportní adaptér směruje každý shell příkaz do dosavadního izolovaného
Docker executoru. Není to samostatný Codex CLI proces, implementace celého
`SandboxAgent`, ani nový vlastní shell protokol. MCP tento pracovní cyklus samo
neřeší; případné další nástroje lze připojit později.

## První spuštění

Docker Desktop musí běžet v Linux režimu a musí existovat image podle
[DOCKER_SETUP.md](DOCKER_SETUP.md). API klíč nastav v témže CMD viditelným příkazem
`set "OPENAI_API_KEY=tvuj_skutecny_klic"`. Závislosti pro nové prostředí:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
G:\metaweb-swarm-env\Scripts\python.exe -m pip install -e ".[openai]"
run-prototype.cmd
```

V aktuálním Vojtově prostředí jsou závislosti doplněné. Stačí poslední příkaz.
Spouštěč je uložený v projektu; nepotřebuje žádnou složku chatu.
Vytvoří **nový placený běh** podle `config.prototype.json`: gpt-5.4-mini ve všech
tierech, 800 000 tokenů, 20 minut aktivního času, 12 plánovacích kol.
Modelové volání zůstává rezervované a účtované hostem; SDK pracovník nemá web
search nástroj, a proto za něj nerezervuje search tokeny.

Úkol je záměrně přesný: zachycený skutečný export → CBOR bootstrap metadata →
Base64 textový přepis → skutečné dekódování obou uložených podob → ověření údajů
proti zdrojovému exportu. Správný CBOR s chybným hashem i neplatný text musí
dekodér odmítnout. Specifikace je v manifestu/checkpointu pod
`coding_acceptance_contract`; nejde o nový preservation objev ani kódování celého EPUB.

Vedle agentova testu host s vlastní knihovnou `cbor2` dekóduje skutečné artefakty.
Další Docker běh spustí vytvořený dekodér nad správnými i hostem vytvořenými
chybnými vzorky. `Worker acceptance: PASS` znamená splnění tohoto konkrétního
kontraktu. Následný nezávislý auditor posoudí lokální rozsah; očekáváme
`SUBCOMPONENT`, nikoli falešné potvrzení archivace celého webu.

## Souvislý vývoj a pokračování

Pracovník má `exec_command` a podle profilu `install_packages`. Může provést až
`coding_max_turns` modelových tahů v jednom plánovacím kole (zde 24). Neúspěšný
příkaz vrací skutečnou chybu; nevyvolává povinné předání auditorovi.
`max_coding_commands_per_agent` omezuje celkový počet příkazů (zde 64).
Každý příkaz má čerstvý kontejner; soubory a `.packages` ve workspace přetrvají.
PTY ani dlouho běžící služby tento adaptér neposkytuje. Delší příkaz může používat
`yield_time_ms` až do konfigurovaného `experiment_timeout_seconds`.

Při `READY` host uloží plán z jediného strukturovaného výsledku, znovu jednou spustí
finální test, zachytí generované výstupy i pomocné zdrojové soubory a automaticky
vytvoří test receipt. Změněný helper kód nebo chybějící výstup se necertifikuje.
Zpětné vazby se týkají aktuálního úkolu; nejsou potřeba ručně vyplněná opravná ID.

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py pause "CESTA_BEHU"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "CESTA_BEHU" --backend openai
```

Použij skutečnou cestu vypsanou při startu. Pause se kontroluje před dalšími
modelovými voláními a příkazy; běžící Docker příkaz se nejdřív dokončí/uklidí.
Vyčerpání krátkého SDK kola uchová historii i soubory pro další kolo. Tokenový,
časový a případný USD limit zůstávají společné a tvrdé. Zvětšuj je pouze podle
konkrétního důvodu, nikoli automaticky při každém `LIMIT_REACHED`.

## Výzkumné profily a staré běhy

Nové `run-http.cmd` a `run-sandbox.cmd` používají `coding_backend: "sdk_shell"`
pro LOCAL úkoly. Výzkum, přidělování rolí, dedupe a externí HTTP realizátor zůstávají.
Jejich globální modely, rozpočty a externí granty tato změna nezvyšuje.
Před opakováním celého roje nejprve ověř pracovníka přes `run-prototype.cmd`.

Staré checkpointy bez `coding_backend` mají nadále `legacy`. Resume je tiše
nepřevádí a nepřepisuje předchozí výsledky. Cílený deposit trial zůstává původním
HTTP postupem; tato změna řeší programování, nikoli samovolné přidělení účtů.

## Bezpečnost a audit

- Docker příkazy mají pouze soukromý workspace, síť `none`, omezené prostředky,
  read-only kořen a nemají připojený host filesystem ani Docker socket.
- OpenAI klíč a host osobní účty zůstávají mimo kontejner. Žádný host shell fallback.
  PyPI download/build zůstává oddělený od projektu a exportů.
- Supervised výběr realizace, sandbox-only/external a HTTP approval jsou oddělené
  politiky. Lokální coding pracovník neposkytuje HTTP upload ani přístup k host účtům.
- Každý vývojový příkaz má `coding_commands` receipt. `coding_validations` obsahuje
  výsledky specifického acceptance kontraktu. Plné údaje jsou v manifestu a auditu;
  report odděluje vývojové příkazy, finální experimenty, testy a verdict auditora.
- Nevyřešené odstranění kontejneru blokuje další příkazy i finální capture.
  Záznam `RUNNING` po pádu není automaticky považován za úspěch ani bezmyšlenkovitě opakován.

## Co je ověřeno bez placeného modelu

`tests/test_coding_worker.py` používá skutečný SDK Runner s lokálním scripted modelem.
Volitelný `tools/prove_coding_worker.py` navíc provede skutečný PyPI/Docker cyklus
nad explicitně předaným veřejným EPUB v nové kopii, včetně chyby, opravy a nezávislé
kontroly dekodéru. Kód, modelové odpovědi a verdict review v této zkoušce jsou
skriptované; není to doklad schopnosti živého modelu ani nového objevu.
Živou implementační schopnost ověří `run-prototype.cmd` s tvým API klíčem.

Uložený [výsledek skutečného průchodu](validation/CODING_WORKER_PROOF.json)
má `COMPLETED`, vývojové exit kódy `[1, 0]`, jednu finální test receipt a PASS
nezávislého kontraktu. [Zachycený dekodér](validation/CODING_WORKER_CODEC.txt),
[test](validation/CODING_WORKER_TEST_SCRIPT.txt) a
[textový přepis CBOR](validation/CODING_WORKER_MIRROR.txt) jsou přesné auditované
bajty scripted fixture. Prošla [regresní sada a finální cílené kontroly](validation/CODING_WORKER_TESTS.txt).

## Oprava 0.7.1: jednoznačné jméno vstupu

Live run `20261020-124142-61ef3319` vytvořil funkční dekodér, ale poslední kontrola
odmítla pole `export`: pracovní kopie měla hash přidaný přímo do jména, zatímco
kontrola očekávala původní basename. Hash, velikost a verze dekodéru odpovídaly.
Šlo o nejednoznačný kontrakt frameworku, nikoli o důkaz nefunkčního dekodéru.

Nové kopie jsou v `inputs/<hash>/<původní-jméno>`; již materializované vstupy při
resume zůstávají na své cestě. Kontrakt předává konkrétní `expected_fields` ze
stejné host funkce, kterou používá nezávislá kontrola. Neúspěch vrací jména
neshodných polí a očekávané/skutečné hodnoty. SDK pracovník také dostává aktuální
návod místo směsi starých preflight pokynů.

[Oddělený replay](validation/CODING_NAME_BINDING_PROOF.json) použil dekodér z live
runu beze změn a upravil pouze cestu vstupu v jeho testu. Finální capture i
nezávislé dekódování a negativní testy prošly. Původní run tím nezískal zpětný
PASS ani certifikaci; jeho audit zůstal nezměněný. Žádné placené modelové volání.
[25 cílených kontrol prošlo](validation/CODING_NAME_BINDING_TESTS.txt).

Pro dokončení téhož běhu po instalaci opravy:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\20261020-124142-61ef3319" --backend openai --extend-rounds 1
```

To přidá jedno plánovací kolo rolím; tokenový a časový limit zůstane stejný.
Agent obdrží explicitní hodnoty a může upravit zbývající názvovou nejasnost ve
svém existujícím kódu/testu. `run-prototype.cmd` nadále zakládá nový běh.

## 0.7.2: host feedback uvnitř stejného pracovního cyklu

Při resume původního live běhu model znovu pouze spustil vlastní test a odevzdal
READY. Host zjistil stejnou chybu jména až po skončení SDK konverzace; staré READY
výroky navíc zůstávaly v historii. Přesné zadání z 0.7.1 samo nestačilo.

Host nyní po neúspěšném odevzdání předá `HOST_VALIDATION_FEEDBACK` přímo zpět do
SDK cyklu: konkrétní skutečné/očekávané hodnoty a platný kontrakt. Pracovník může
opravit soubory a odevzdat je znovu ve stejném plánovacím kole. Všechny pokusy
sdílejí původní `coding_max_turns`, deadline, tokeny a USD budget. Další SDK start
tyto limity neresetuje. Při jejich vyčerpání se uloží historie včetně host chyby.

Staré strukturované výroky READY se z aktivního replaye odstraní; přesné původní
odpovědi zůstávají v auditu. První LOCAL dispatch po upgradu archivuje dosavadní
modelovou historii a načte aktuální úkol. Soubory, účetnictví a receipts zůstávají.

[Skutečný SDK/Docker replay](validation/CODING_FEEDBACK_PROOF.json) začal přesným
kódem z live runu s původní chybnou metadatovou hodnotou. Host jej odmítl, skriptovaný
model dostal feedback a provedl dvě úpravy normalizace jména v dekodéru/testu.
Další host kontrola prošla v jediném backend kroku: 3 modelové požadavky, 1 platná
test receipt, žádné přidané plánovací kolo ani API náklady. Odpovědi modelu a oprava
v tomto důkazu jsou fixture; není to test schopnosti živého modelu.
[40 cílených regresí prošlo](validation/CODING_FEEDBACK_TESTS.txt).

Původní run po druhém FAIL zůstal beze změn. Pro další placené pokračování po
instalaci 0.7.2 lze použít tentýž výše uvedený příkaz s `--extend-rounds 1`;
zpětná vazba už se zpracovává uvnitř tohoto kola.
