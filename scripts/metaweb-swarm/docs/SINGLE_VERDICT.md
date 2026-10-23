# Jeden verdikt a pokračování rozpracovaného běhu — 0.7.8

Run 20261022-051417-8cb93cc5 skončil po pěti kolech, 303 751 tokenech a přibližně
582 sekundách. Vznikl jeden capture, jehož negativní test jen porovnával řetězec
nul s původním hashem. Poškozený výstup nebyl poslán do validátoru. Auditor tuto
chybu správně našel a navrhl opravu, ale posílal REVISE + SATISFIED v duplicitním
local_contract_status. Host opravu nepřijal kvůli rozporu druhého pole.

## Oprava rozhraní

Živý SDK tool má jediný verdikt: FULL_MECHANISM / SUBCOMPONENT / REVISE.
local_contract_status už není ve schématu, instrukcích, nových review records ani
aktuálním report packetu. Starý argument přímého Python API se jen ignoruje kvůli
kompatibilitě; nic nerozhoduje a nepřepočítává historická hodnocení.

REVISE pro nový lokální kontrakt nadále potřebuje required_local_change a citaci
defect_code z hashově vázaného zdroje. Chybějící veřejný deposit sám není lokální
vada. Schválení SUBCOMPONENT/FULL dál vyžaduje skutečnou pozitivní i negativní
větev podle dosavadního evidence kontraktu. Vadný negativní test se neopravuje
automatickým schválením nebo odstraněním kontrol.

Při prvním dispatch po upgradu se starý coding/review kontext archivuje a obnoví
pro single-verdict-0.7.8. Captures, přečtené artefakty, checkpoint, rozpočty a audit
zůstávají. Platný REVISE se uloží a předá coderovi místo zastavení na duplicitě.
Třikrát opakovaná skutečně chybějící evidence pořád vede k technickému zablokování
posudku, nikoli fingovanému vědeckému zamítnutí.

Pokud kvůli BLOCKED auditorovi čeká posouzení a nelze nic dále přidělit, závěr
běhu uvádí BLOCKED / PROTOTYPE_REVIEW_BLOCKED. LIMIT_REACHED zůstává pro skutečně
nedostatečnou kapacitu. Nezvyšujeme žádný globální limit ani neposkytujeme účty.

## Ověření

11 kontrol lokálního kontraktu prošlo, včetně reálného SDK toolu s fake providerem:
nové schéma neobsahuje druhý verdikt, doložený REVISE se předá coderovi, starý
kontext se archivuje a restart nezmění globální rozpočty. 54 souvisejících regresí
a 11 queue testů prošlo. Nový queue test ověřuje BLOCKED bez dalšího dispatchu.

Přesné poslední odmítnuté API argumenty a skutečné hashově ověřené artefakty
byly přehrány v oddělené kopii. Nová logika přijala REVISE a předala požadavek
na skutečnou damaged-input kontrolu do test_revision coderu. Původní checkpoint
nezměněn; žádný kód agentů ani placené API nebyly spuštěny. Není tím opraven
ani potvrzen původní Open Library/EPUB prototyp.

## Pokračování tohoto běhu v CMD

Ve stejné konzoli s API klíčem, z adresáře scripts/metaweb-swarm:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py unblock "G:\metaweb-swarm-runs\20261022-051417-8cb93cc5" AGENT-006 --note "Opraveno rozhrani na jeden verdikt; dokoncit audit a predat konkretni opravu"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\20261022-051417-8cb93cc5" --backend openai
```

První příkaz jen zaznamená explicitní operátorovo obnovení auditora; druhý spustí
placené pokračování. Není třeba zakládat nový run ani přidávat tokeny/kola/čas.
Auditor má zbývající vlastní kola, coder čeká na jeho výsledek. Instalace tyto
příkazy sama nespouští a původní run neupravuje.
