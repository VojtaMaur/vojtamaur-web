# Mechanismus, společný helper a nezávislé ověření — 0.8.0

## Proč poslední běh nebyl čtyřmi prototypy

Run 20261022-051417-8cb93cc5 zaznamenal čtyři SUBCOMPONENT posudky. Dvě Open Library
IDEA byly tentýž veřejný bibliografický pointer a jejich drivery měly totožné bytes.
Gist a Commons používaly prakticky stejný EPUB metadata extractor. Negativní případ
změnil checksum v kopii EPUB a potvrdil, že parser změnu přečetl. Neověřil odmítnutí
ani opravu poškozených dat. Extrakce fungovala; tvrzení o integritě a konkrétních
carriérech byla širší než evidence. Nevznikl žádný externí deposit.

## Co se změnilo

### Dedupe v jednom runu

Host sjednotí veřejný Open Library recovery pointer ve work/edition/subject record
slotech i při jiných mechanism_key/scope popiscích. Jde o jednu custody/payload/
recovery funkci. Zachovají se jednotlivé submissions a contributors pod prvním ID.
Plný EPUB/payload deposit a jiný nebo nejednoznačný provider se tím automaticky
neslučují. Semantický srovnávač také výslovně nerozlišuje pouhé názvy polí/scope.
Je to konzervativní naučená aliasová pravidla plus obecné srovnání; nejde o univerzální
rozpoznání všech parafrází. Historické runy a již vydaná ID se nepřepisují.

### Sdílená implementace

Před dalším finálním Docker capture host porovná driver a zachycené helpers s
aktuálními run-local receipts. Python používá AST: přejmenování souboru, komentáře
nebo formátování samy nevytvoří nový program. Konstanty i skutečné operace zůstávají
součástí podpisu. Totožná implementace z jiné IDEA dostane EXISTING_IMPLEMENTATION_REUSE
s odkazem na existující test. Nespustí se další finální capture jen pro jiné ID.
Závislost společného helperu v jinak novém driveru je přípustná.

Coder může doplnit skutečný primitive. Po třech nezměněných reuse submissions se
jen tento lokální pokus ponechá jako LIMIT_REACHED; další kandidáti mohou pokračovat.
Nápad není REJECTED a nevzniká nový tvrzený úspěch. Podpis není sémantická ekvivalence
libovolných odlišných programů: přepsanou variantu musí dále posoudit auditor.

### HELPER_ONLY

Auditor může uzavřít zachycený obecný extraktor jako HELPER_ONLY. Záznam a source
artifacts zůstávají ve shared_components s odkazy na testy/IDEA. Kandidát nedostane
prototype_component_tested ani PROTOTYPED. Není to potvrzení negativní integrity
ani externí služby. Samotný titul služby v JSON nepředstavuje její primitive.

Nový lokální kontrakt zahrnuje původního providera/mechanismus; tato vazba se při
výběru malé lokální operace neztrácí. Užitečný helper lze zachovat i když není
k dispozici smysluplná offline operace daného providera. Jeho chybějící ověření
zůstává v reportu; jiný konkrétní primitive lze řešit v nové revizi nebo dalším runu.

### Vlastní zkouška auditora

Profily config.http.json a config.research.json mají independent_review_probes=true.
Před FULL_MECHANISM/SUBCOMPONENT auditor musí spustit run_review_probe(test_id, code):
malý Python assertion program proti kopii zachyceného driveru/helpers, výstupů,
nezměněného vstupu a izolovaných .packages autora. Například přes runpy.run_path
může zavolat skutečný parser/validator a vyzkoušet nezávisle změněný vstup.

Nesmí při tom měnit kontrolovanou implementaci nebo originální vstup. Host porovná
jejich bytes po provedení. Probe běží v nové Workspace-created složce, v existujícím
Docker image, bez sítě, host účtů, API klíče nebo přístupu do produkčního stromu.
Zdědí jen sandbox dependencies, nikoli instalaci nebo credentials Windows hostitele.
Není potřeba stavět nový image. Coder dostává připomínku použít find/grep/Python,
protože rg v přibaleném image není.

Nejvýše 3 sondy na test, každá do 30 sekund a do zbývajícího aktivního runtime.
Kopie se rezervují před zápisem a jejich bytes společně s auditními blobs nesmějí
přesáhnout max_snapshot_bytes. Zůstává max_file_bytes. Neurčitý cleanup blokuje další
Docker příkazy; přerušené provedení se obnoví jako UNKNOWN. Zrušené čekání počká na
ukončení kontejneru. Příprava bez kontejneru ponechá účtovanou rezervaci a konkrétní
technickou chybu. Všechny stavy/code/output/hash jsou v prototype_review_probes a auditu.

Pro pozitivní coverage musí poslední vlastní sonda skončit exit=0, cleanup musí být
potvrzený, implementace nezměněná a program obsahovat assertion/failure větev.
Pouhé print('PASS') nebo assert True nestačí. Neúspěšná sonda nesmí být přepsaná na
úspěch důvodem posudku. REVISE a poctivý HELPER_ONLY nevyžadují úspěšnou sondu.

Tato struktura stále není univerzální sémantický oracle: triviální či špatně zvolený
assert může být nesmyslný. Auditor musí kontrolovat relevance a skutečné rejection/
recovery chování. Nové instrukce výslovně rozlišují parser readback od odmítnutí
poškození. Cílem je získat skutečné nezávislé provedení a poctivě omezený verdikt,
nikoli předstírat důkaz správnosti každého libovolného programu.

Základní config.json nechává nový přepínač false pro kompatibilitu starších/smoke
profilů; start přes config.http/research jej zapíná. Starý checkpoint si konfiguraci
sám nemění. Startup vypíše skutečně používaný auditní režim. Run report a report
packet oddělují shared helpers, reuse reference, skutečné review probes a mechanism
coverage. Chybějící rezerva pro další výzkum/report se nehlásí jako prototype blocker,
pokud žádná prototypová práce nečeká.

## Ověření

144 souvisejících regresí prošlo. Nové kontroly zahrnují aliasy a provenance,
neslučování cizího providera/payloadu, AST reuse, HELPER_ONLY bez coverage, odmítnutí
approval bez nezávislé sondy, oddělený workspace a originální input, neúspěšnou sondu,
změnu implementace, chybějící assertions, limity, rezervaci při selhání přípravy,
nejistý cleanup a skutečné SDK předání přes dvojici povolených nástrojů.

Nad skutečnými snapshoty posledního runu proběhlo přehrání v oddělené kopii:
Open Library varianty se našly jako jeden kandidát, totožný driver jako reuse a
nezávislý Docker assertion test prokázal, že decoder přijal upravený checksum.
Původní SUBCOMPONENT schválení nová gate odmítla INDEPENDENT_PROBE_FAILED.
Původní checkpoint beze změny, placená API volání 0. Neopravovali jsme ručně kód
agentů a nepřepsali historické posudky. Viz validation/MECHANISM_QUALITY_LIVE_PROOF.json.

Při návrhu ověření vycházíme z konkrétních tool traces a výsledků, nikoli pouze
napsané syntézy; viz také [official OpenAI agent evaluation guidance](https://developers.openai.com/api/docs/guides/agent-evals).

## Další skutečný výzkumný běh s levnými modely

Ze scripts/metaweb-swarm v CMD se stávajícím API klíčem a běžícím Docker Desktop:

```cmd
run-http.cmd
```

Je to nový izolovaný run se všemi rolemi a aktuálním kontextem/exporty. Není to
smoke ani pokračování starého checkpointu. Cheap/strong/flag zůstávají nastavené
na gpt-5.4-mini. Rozpočty, approval_required=true, zakázané osobní host accounts a
zákaz produkčních experimentů zůstávají. Externí mutace čekají na schválení podle
stávajícího profilu; auditní sonda nemá síť. Není nutné znovu instalovat knihovny
na hostu nebo měnit modely. Úspěch běhu se hodnotí podle konkrétního nového primitive,
nezávislé kontroly a případné skutečné deposit evidence, ne podle počtu IDEA.
