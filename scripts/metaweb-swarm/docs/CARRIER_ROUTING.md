# Kontrola služby a změna směru (0.5.2)

Další krok je skutečný výzkumný běh, bez opakování již úspěšných Docker/HTTP smoke testů. Z CMD ve složce frameworku:

~~~cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-deposit-trial.cmd
~~~

Vznikne **nový run** se zachyceným projektem, kontextem a vybraným EPUB. API klíč musí být v tomto CMD už nastaven. Modelové tiery, rozpočet, credential grants a approval se touto aktualizací nemění. Příkaz a dokumentace jsou přímo v projektu; soubory z prostředí Codexu nepotřebuješ.

## Pracovní postup

1. Discovery agent vyhledá konkrétní službu externím web search.
2. screen_carrier(provider, service_url) provede rychlou lokální kontrolu původního zachyceného korpusu, bez HTTP a bez dalšího modelu.
3. U použitelného směru přečte skutečné API a podmínky přes read_document, sestaví kvalifikaci, předá existující IDEA auditorovi.
4. U nezměněné již používané nebo zakázané služby přejde ke **jiné službě v témže kole**. Uložené zadání zabrání další hluboké četbě přes read_document, dokud agent nevybere nový směr nebo výslovně nepředloží skutečné zlepšení.
5. Auditor, realizátor a reporter mají dál vlastní oddělené úkoly. Upload vyžaduje splněné podmínky a při approval_required=true rozhodnutí člověka o konkrétním požadavku.

Nejde o provider connector: služby si agent stále sám hledá, protokoly čte z dokumentace a požadavky skládá obecným HTTP nástrojem.

## Význam výsledků screen_carrier

| Stav | Co doloženo / další krok |
| --- | --- |
| EXISTING_LAYER | Pojmenovaný záznam v sekci existujících vrstev ARCHIVE.txt **a** následující URL; přesné jméno/alias nebo host nasazené kopie. Zachycený registr, nikoli aktuální dostupnost služby. Změnit směr. |
| BASELINE_MENTION_REVIEW | Jen textové shody. Samy nedokazují používání; prověřit jejich kontext, pak dokumentaci. |
| NO_MATCH_FOUND | Žádná doslovná shoda. **Nedokazuje novost.** Přečíst dokumentaci a doložit rozdíl. |
| IMPROVEMENT_REVIEW | Známá služba, ale výslovně popsané odlišné použití a ověření. Lze zkoumat, stále nutný nezávislý audit. |
| POLICY_FORBIDDEN / OWNER_REJECTED | Existující oprávnění / vlastníkovo zamítnutí směr vylučují. Vybrat jinou službu. |
| SWITCH_CARRIER_REQUIRED | Agent se vrací ke stejnému kvalifikací odmítnutému směru bez skutečného zlepšení. Vybrat jiný. |

Samotná zmínka v článku či v návrhové sekci ARCHIVE není nasazení. Cloudflare Pages neznamená automaticky Cloudflare R2. Návrh OSF není automaticky již používaná registrace. Srovnávají se přesné aliasy; žádné obecné slučování všech produktů stejné firmy.

Pro skutečné zlepšení vyplnit všechny tři: baseline_behavior, proposed_change, validation_plan; změna se musí lišit od dosavadního chování. Toto je přijetí směru k výzkumu, **ne certifikace novosti** ani přeskočení auditora.

## Přesměrovaná dokumentace

GET s 301/302/303/307/308 vrátí DOCUMENT_REDIRECT_REQUIRES_GET a syntakticky validovaný veřejný redirect_url, pokud ho lze bezpečně uvést. Agent musí sám zavolat read_document na tento cíl. Nic se automaticky nenásleduje, cookies/credentials se nepředávají a samotný redirect není doklad přečteného dokumentu.

Nový požadavek znovu projde DNS/pinning, ověřeným TLS, oprávněními a rozpočtem chráněného transportu. Chybný certifikát se neobchází. Neplatný/private/insecure cíl, URL s credentials/sensitive query nebo smyčka vrátí DOCUMENT_REDIRECT_TARGET_UNAVAILABLE, bez následování.

## Konfigurace a checkpointy

carrier_screening je boolean. Výchozí obecný výzkum: false; aktuální config.deposit-trial.json: true. Platí pro role DISCOVERY, nikoli pro nezávislého auditora či realizátora. Jde o explicitní pracovní směrování, oddělené od approval_required; není další human approval.

Výsledek screen i požadavek na změnu směru jsou uloženy v checkpointu a event logu. SWARM_REPORT.md obsahuje přehled i podklady; manifest.json úplné SCREEN receipts, původní dokument/hash/řádky/URL a aktuální zadání agentů. Konzole vypisuje jen Carrier: ... -> switch a Docs redirect: ....

Změna profilu nepřepíše kontext starého checkpointu. Proto pro tento upgrade spusť **nový run**, místo prodlužování posledního. Žádná IDEA ani dobrý neprovedený nápad se touto kontrolou nepřeklasifikuje na REJECTED. Oprávnění, credentials a rozpočtové stropy mají dál samostatnou autoritu.

## Ověření při vývoji

Regrese používají skutečný chráněný lokální HTTP transport a nainstalovaný Agents SDK s kontrolovaným modelem. Prověřují přesměrování bez autofollow, privátní/credential-bearing redirect, skutečný GET po explicitním pokračování, registr proti pouhé zmínce, oddělené produkty, zlepšení, uloženou změnu směru/resume, opt-out, ostatní role a auditní report.

Původní run 20261008-123103-808f0f46 byl také zkontrolován offline bez změny jeho souborů: ArDrive → EXISTING_LAYER, další četba → SWITCH_CARRIER_REQUIRED; původní 301 dává konkrétní https://ardrive.io/. Tento důkaz potvrzuje opravenou mechaniku; úspěšný nový objev musí teprve doložit skutečný výzkumný run.
