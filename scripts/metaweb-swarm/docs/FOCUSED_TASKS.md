# Vlastní zadání a čtení internetové dokumentace

Od verze 0.5.0 dostává cílený deposit běh krátký společný cíl, vlastní úkol role a konkrétní aktuální checkpoint. Už nepřehrává celý návod pro všechny role, CORE a historii minulých generací. CURRENT_STATE, závazná zamítnutí vlastníka, skutečné exporty a aktuální kvalifikace/approval zůstávají v kontextu. Baseline se kontroluje přes původní BASE podklady až pro konkrétní externí nález. Historická paměť není v tomto režimu dostupná jako agentní vyhledávací nástroj; aktuální dedupe zůstává.

## Spuštění skutečného výzkumu

Z CMD ve složce projektu a s již nastaveným OPENAI_API_KEY:

```cmd
run-deposit-trial.cmd
```

Jde o nový běh výzkumu pro skutečný připravený EPUB, ne smoke test. Zachovává cheap modely, $5 lokální odhadový strop, 20 kol, 1.5M tokenů, 40 minut aktivní práce, jednu privilegovanou akci a lidské schválení konkrétního uploadu. Žádná garance nového nálezu nebo uploadu; konkrétní setup lead je platný výsledek.

Pro změnu cíle bez přepisování profilu:

```cmd
run-deposit-trial.cmd --task "Find an independent FREE preservation carrier for the retained EPUB; verify exact bytes."
run-deposit-trial.cmd --task-file moje-zadani.txt
```

Vyber jen jeden způsob zadání. Soubor je UTF-8, cíl maximálně 12 000 znaků / soubor maximálně 48 000 bytes. `init` i `start` podporují stejné přepínače. Úkol se zachytí do konfigurace/checkpointu běhu; resume pokračuje se stejným zadáním. Nový úkol neuděluje credentials, oprávnění, větší payload nebo dodatečný rozpočet. V deposit profilu dál platí úkoly role pro kvalifikaci → nezávislý audit → exact-byte upload; pro jiné pracovní flow změň `role_assignments` ve vlastním profilu.

## Konfigurace role

`task_style: "focused"` zapíná stručné kontexty a nástroje podle typu práce. `role_assignments` je mapa jména seed role → její konkrétní úkol. Role dědí tento úkol při inicializaci; živý checkpoint se změnou souboru profilu nepřepisuje. Výchozí obecný roj má `task_style: "research"` a původní širší workflow. Obecný roj neztrácí kreativní role nebo emergence.

- Objevitel: externí search, read_document, baseline pro konkrétní službu, metadata exportů/grantů, kvalifikace a přijetí IDEA. Neprochází lokální adresáře/předchozí generace, nenahrává a nehodnotí sám sebe.
- Auditor: vlastní čtení konkrétních dokumentů, baseline a critique existující IDEA. Nezakládá další nápady a nerealizuje upload.
- Realizátor: příprava payload/request artefaktu, HTTP upload/download/verify; Docker/PyPI nástroje jen při zapnuté capability. Nemusí vytvářet umělý encoder pro hotový export.
- Reporter: čtení aktuálních artefaktů a note; žádný další průzkum nebo implementace.

Úzké pracovní zadání nemění hard permissions a approval mechanismus. Konfigurace dostupných nástrojů role není provider connector. Objevitel si stále sám hledá neznámé služby; obecný HTTP executor sám skládá požadavky podle skutečné dokumentace.

## read_document

`read_document(url, purpose, offset=0, limit=12000)` provede existujícím chráněným HTTP transportem GET a vrátí text přímo modelu. HTML se převede na text bez script/style/head/svg/template; vrátí nejvýše 80 HTTP(S) odkazů, bez automatického následování. Text/JSON/XML zůstává čitelný UTF-8. Výstup má URL, HTTP request ID, původní soubor, SHA256, rozsah znaku, next_offset a označení reprezentace. Nepodporuje JS-rendering, PDF konverzi, jiné textové encodings ani automatické přesměrování; původní odpověď je dál auditní artefakt. Lokální reader má strop 2 MB.

Další stránka téhož nezměněného úspěšného GET se bere z vlastního workspace bez nového HTTP volání. Auditor nemůže použít objevitelův read receipt; dokument si musí vyžádat sám. Změněný response artifact se nepovažuje za původní dokument. Truncated/error/binary/empty odpověď nevytvoří tvrzení o přečteném textu. Receipt osvědčuje předaný excerpt, **ne** pochopení podmínek nebo přečtení celého dokumentu. Auditor odpovídá za nalezení relevantních částí a své posouzení.

V konzoli se objeví krátké `Docs: URL | chars ...` včetně cache, takže poznáš skutečnou externí práci. Plné podklady jsou v auditu; claim z web search/snippetu sám nestačí pro nezávislý PASS.

## Ověření při vývoji

Ověřeno bez placené inference: reálný chráněný GET na lokální fixture, extrakce HTML, paging/cache/hash, nezávislé čtení auditora a kvalifikace, checkpoint, skutečná dispatch přes nainstalovaný Agents SDK s kontrolovaným modelem a zachycení vlastního task-file. Nový profil ještě nemá doložený placený výzkumný výsledek. Následující uživatelské spuštění je další skutečný výzkum; opakování úspěšných smoke testů není potřeba.


## Aktualizace 0.5.1

check_deposit_target nyní přijímá pojmenovaná typovaná pole přímo, bez plan_json. Neznámou upload URL/auth uváděj jako prázdnou/UNKNOWN; unresolved QUAL zůstává dohledatelné s konkrétním dalším krokem. [Aktuální kvalifikační contract](DEPOSIT_QUALIFICATION.md). Reporter čte cizí podklady přes read_audit_artifact(request_id); mezi workspace nekopíruj domnělé cesty. [Sdílený audit](SHARED_AUDIT.md). Forbidden hosty/subdomény jsou uvedeny v runtime task policy; osobní ani dedicated accounts je neodemykají.


## Aktualizace 0.5.2

V deposit-trial discovery nejprve zavolá screen_carrier pro konkrétního poskytovatele, pak čte dokumentaci. Známý nezměněný směr se změní; pouhá zmínka není důvod k zamítnutí. Host ukládá aktivní směr a switch_required do checkpointu. read_document umí vrátit bezpečný redirect_url pro explicitní následující GET. [Pracovní postup a nastavení](CARRIER_ROUTING.md).
