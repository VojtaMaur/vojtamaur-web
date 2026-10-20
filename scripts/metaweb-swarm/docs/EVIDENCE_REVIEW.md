# Skutečný výsledek testu a změna výzkumného směru (0.6.13)

Aktualizace 0.6.14: [REVIEW_FINISH](REVIEW_FINISH.md) předává konkrétní chybějící
read ranges a vynucuje SDK review volání po jejich dokončení, se zachováním
svobodného verdictu. Nové profily mají mechanism-specific prototype focus.

Nový běh v CMD se stávajícím API klíčem a běžícím Dockerem:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-http.cmd
```

Modelové tiery, globální limity a oprávnění zůstávají stejné. Image není třeba
rebuildovat. Instalace nespouští placený běh ani neupravuje staré runy.

## Prototyp versus vytištěné tvrzení

Běh `20261014-070113-32f0e632` vytvořil dva execution receipts. První report
obsahoval `recovery_probe=False`, druhý script neměl assertions a textovou
normalizací změnil původní bajty manifestu. Nezávislé SUBCOMPONENT verdikty
proto byly příliš velkorysé; ani jeden nedokládal funkční obnovu exportu.

Nové `review_prototype_test` má pro kladný FULL_MECHANISM i SUBCOMPONENT verdict
argumenty `positive_code` a `negative_code`: úplné skutečné případy z uloženého
Python scriptu. Host kontroluje přítomnost stejného executable AST, assertion
a operace s pozměněným/neplatným vstupem. Pouhé `print('negative_checks')`,
číselná tautologie nebo `body.startswith(first_chunk)` nejsou takovým testem.
Chybějící skutečné případy patří do REVISE, nikoli do dílčího úspěchu.

Auditor musí přečíst celý script a také výstupy přes `read_test_artifact`:
celý UTF-8 text do 64 KiB, u většího textu minimálně prvních 4096 znaků;
další části podle relevance. Binární čtení kontroluje hash, samo data nedekóduje.
Host detekuje konkrétní chybové positive-probe flags, například
`recovery_probe=False` nebo JSON `"round_trip": false`, a nedovolí kladné
posouzení takového testu. Nejde o obecný parser všech testovacích frameworků.

Pro FULL_MECHANISM je navíc nutný `recovered_path`: zachycený výstup obsahující
původní obnovené bajty. Host porovná délku a SHA256 s retained inputem. Použij
`read_bytes`/`write_bytes`; `read_text` může změnit CRLF na LF. Převod na jiný
formát není přesná kopie. Metadata-only test může mít užší scope, musí však
také obsahovat relevantní pozitivní a negativní případ.

Tři stejné nepodložené pokusy o kladné schválení uloží test jako REVISE,
s původním requested verdict a důvodem host kontroly. Hypotéza není REJECTED.
Opravený script potřebuje nový plán a skutečnou execution; identický script
po REVISE se znovu nespouští jako údajná oprava. Původní receipts zůstávají.

**Meze důkazu:** kontrola syntaxe nedokazuje, že testuje správnou věc nebo že
se citovaná větev provedla. Script může obsahovat nepoctivé či nedosažitelné
assertions. Význam, pokrytí a vazbu na mechanismus dál posuzuje nezávislý auditor.
Kontrola executable snippets je nyní pro Python ve výchozím image; jiné jazyky
potřebují rozšíření tohoto guardu. Staré uložené verdikty nejsou zpětně
certifikací nového `evidence_contract=2`.

## Delegování a známé směry

Delegation guard přijímá také přirozené výluky `not WACZ`, `non-WACZ` a
`Exclude WACZ and any recurring subscription dependency`. Kladné zadání,
výjimka typu `unless` a skutečné zakázané IDEA dál podléhají owner pravidlům.

Po odložení známé služby dostane discovery agent explicitní DISCOVERY_PIVOT:
jiný provider/mechanism family teď, dosud opakované směry a čistý pracovní
kontext s původní historií zachovanou v auditu. Pouhá poznámka „příště změním
směr“ tuto práci nedokončí. Host zohlední novou přijatou hypotézu nebo skutečně
přečtený jiný externí primární dokument. Materiální improvement zůstává možný
s konkrétní BASE evidencí. Jde o řízení výzkumné úlohy v původních role caps,
nikoli o zákaz HTTP přístupu nebo záruku originality příštího modelového nápadu.

Ověření a jeho praktické meze: [VALIDATION](../VALIDATION.md).
