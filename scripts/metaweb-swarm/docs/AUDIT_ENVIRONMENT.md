# 0.8.3 — chyba sondy není chyba prototypu

Oprava vychází z runu `20261022-105239-d403be02`. Jeho tři auditorské sondy
skončily na importu dřív, než ověřily zamýšlené chování: RSS modul ležel
v `prototype/`, v output-only JPEG prostředí záměrně nebyl autorův modul a nebylo
tam ani Pillow. Auditor pak žádal coderovi opravy kvůli vlastnímu prostředí.

## Prostředí a diagnostika

- **AUTHOR_ENVIRONMENT** zachovává soubory a cesty zachyceného kódu. Pevný hostový
  launcher přidává adresáře driveru a zachycených helperů do Python importů,
  například `prototype/`. Není třeba kopírovat moduly do kořene nebo opravovat
  správný prototyp, aby na něj auditor dosáhl.
- **SPECIMENS_ONLY** nadále nevidí autorův kód, originál, nezvolený manifest ani
  autorovy balíčky. Statický import zachyceného autorova modulu je odmítnut ještě
  před Dockerem s konkrétní instrukcí napsat vlastní reader nebo zvolit author
  režim. Chybná syntaxe sondy má obdobnou lokální diagnostiku. Statická kontrola
  není úplný analyzátor Pythonu: dynamické importy řeší runtime launcher.
- Auditor má při přiděleném otevřeném PROTOTYPE_TEST dostupné **install_packages**.
  Balíčky instaluje do svého vlastního workspace přes dosavadní izolovaný
  PyPI build/install postup. Jeho knihovny se do sondy kopírují samostatně jako
  `.review-packages` s evidovaným ID auditora. Čistý režim nekopíruje autorovy
  `.packages`. Typický případ: import `PIL` vyžaduje PyPI balíček `Pillow`.
- Instalace auditora je výzkumná závislost, takže nečeká na supervised výběr
  realizace. Vyžaduje však přidělený audit, Docker a povolené PyPI; platí stejné
  počty instalací, runtime, bajtové kvóty a síťový model. Žádná platba, osobní
  credential ani veřejný zápis se tím nepovoluje.
- Launcher uvnitř networkless Dockeru rozlišuje **PASSED**, **SETUP_ERROR**,
  **ASSERTION_FAILED** a **RUNTIME_ERROR**. Chybějící diagnostika je označena jako
  INDETERMINATE při neúspěšném transportu; původní exit/cleanup informace zůstávají.
  ImportError/ModuleNotFoundError je dependency/setup problém, nikoli automatický
  důkaz implementační chyby. Ani neúspěšná assertion sama neprokazuje správnost
  očekávání auditora. Výsledek launcheru je diagnostika, nikoli vědecký verdict.
- Dokud je evidována chyba přípravy sondy, review neukládá REVISE ani HELPER_ONLY
  odvozené z neprovedeného testu. Dispatch zpřístupní opravu sondy a povolenou
  instalaci závislosti; coder nedostává falešný repair. Staré import tracebacky
  jsou zohledněny bez přepisování původních receipts.
- Třetí stejná nezvládnutá setup chyba zablokuje **audit**, ponechá test bez
  verdiktu a nevytvoří implementační selhání. Změna problému je nový setup pokus;
  původní limity tří provedených sond/test, času, tokenů, kvót a cleanup zůstávají.
  Bytecode zápisy jsou v launcheru vypnuté, aby Python importem neměnil chráněné
  kopie knihoven. Nedokončený cleanup stále zastavuje další práci.

## Rozsah posouzení

Zmrazená **operation + positive_assertion + negative_assertion** je primární cíl
auditu; discovery titul dává kontext. Nativní serializer/parser source-derived
RSS pointeru může být užitečný SUBCOMPONENT. Není automaticky HELPER_ONLY jen
proto, že jde o metadata. Naopak obecný extractor přejmenovaný podle služby
zůstává helper. Pokud kontrakt vyžaduje chybějící GUID odmítnout, auditor nesmí
bez důvodu posunout cíl na obnovu celého EPUB nebo veřejnou úschovu.

První RSS test měl i skutečnou chybu: broad `except Exception` polykal vlastní
AssertionError. Tato oprava neznamená schválení takového testu. Pozdější zachycený
RSS měl skutečný XML výstup a opravenu negativní cestu; jeho původní nezávislá
sonda v opravovaném author prostředí prošla beze změny svého kódu.

Scope stále posuzuje model. Instrukce, izolace a syntaktické kontroly neumějí
garantovat, že další levný model nevymyslí nesprávný požadavek nebo triviální
sondu. Oprava konkrétně odstraňuje importní chyby a chybné předání setup problému
coderovi; nepřidává automatické schvalování mechanismů.

## Ověření na skutečném posledním runu

V soukromé kopii byl přehrán přesně původní RSS probe kód: PASSED. Host přijal
ručně odůvodněný lokální SUBCOMPONENT verdict v této kopii. Původní JPEG sonda
importující autora byla odmítnuta před Dockerem a nečerpala execution slot.
Nepodložené REVISE bylo odmítnuto bez změny coderova úkolu. Auditorovi se přes
skutečný PackageInstaller nainstalovalo Pillow; vlastní nezávislá čtečka ověřila
platný JPEG 1×1, zachycená metadata a odmítnutí změněného digestu i truncation.
V čistém runtime nebyl autorův modul ani originál; závislosti měly REVIEWER původ.

**JPEG stále obsahuje jen metadata a privátní `inputs/...` pointer, nikoli celý
EPUB nebo ověřený veřejný recovery cíl.** Tento výsledek se nesmí prezentovat jako
hotová záloha. Původní run ani verdict nebyly změněny. Nejde o nový autonomní run:
je to ruční offline replay s 0 placenými API voláními a 0 externími akcemi.
Proof: `validation/AUDIT_ENVIRONMENT_LIVE_PROOF.json`.

Modely, rozpočty a schvalování externích akcí se nemění. Pro další pokračování
tohoto již blokovaného runu je potřeba explicitní unblock auditora a dostupné
role-round allowance; instalátor tyto stavy ani limity sám nepřepisuje. Při resume
se obnoví starý modelový kontext podle nového review protokolu a aktuálních faktů.
