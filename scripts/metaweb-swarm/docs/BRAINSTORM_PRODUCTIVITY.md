# Šířka brainstormingu a konec rozpočtu

## Co ukázal běh 20261104-052705-eac193b7

Běh spotřeboval 2 970 949 ze 3 000 000 tokenů ve 194 požadavcích.
Z toho 2 949 730 byly vstupy a 21 219 výstupy. Hlavní spotřebou byl opakovaný
kontext a definice nástrojů. Jeden požadavek `submit_idea` vytvořil jedinou IDEA;
25 volání `screen_carrier` přitom obsahovalo pracovní návrh. Nejde o důkaz 25
různých nových mechanismů: některé se překrývají nebo mohou být nevhodné.

Po 13 odmítnutích kvůli nedostatečné rezervaci následovala přibližně minutová
příprava patchů. Skenování stromu po těchto kolech přidalo asi 13,5 minuty.
Brainstorming nyní tento krok vynechává. Historické patch záznamy nemaže.

## Včasné zachycení pracovních směrů

Výzkumné role dostávají pokyn nejprve uložit 2–3 věcně různé hypotézy, pokud
mají smysluplné návrhy. Není to vynucená kvóta; nemají vyrábět výplň.
Nový nástroj `record_hypothesis` ukládá stručný mechanismus, nejistoty a zdroje.
Konkrétní návrhy ze `screen_carrier` se zachovávají také automaticky.

Hypotézy mají ID `HYP-…`, autory a stav `UNREVIEWED`. Jsou v GUI u nápadů,
ve `SWARM_REPORT.md`, `manifest.json` a v podkladech reportéra. Nezvyšují počet
formálních IDEA ani neobcházejí kontrolu novosti, deduplikaci či nezávislou kritiku.
Stejné znění zachovává příspěvky autorů; podobné formulace hypotéz mohou stále
tvořit varianty. Teprve podložený návrh má projít stávajícím `submit_idea`.

Výchozí nové výzkumné profily mají 6 SDK tahů v jednom kole místo 12. Tato
hodnota je vidět a lze ji změnit v editoru; neexistuje další skrytý strop pro
průzkumníky. Již založené běhy ani vlastní uložené hodnoty se nepřepisují.
Globální tokenový, časový a finanční rozpočet se touto změnou nezvyšuje.

## Když nezbývá místo na celý požadavek

Host před vytvořením pracovního adresáře ověří minimální nutnou rezervaci.
Přesná kontrola dál probíhá před každým skutečným API požadavkem včetně
historie, schémat, maximálního výstupu a rezervy pro hosted search.
Odmítnutí si zapamatuje pro konkrétní úkol a kontext. Stejný neproveditelný
požadavek se znovu nespouští a nezabírá další kolo. Změna úkolu nebo dostatečné
navýšení rozpočtu umožní pokračování. Menší úloha bez hledání, například syntéza,
může pokračovat, pokud se sama vejde. Po vyčerpání dostupné práce běh skončí
`LIMIT_REACHED`; kandidáti se tím nezamítají.

Neznámý výsledek skutečně odeslaného požadavku dál vyžaduje vyrovnání rezervace.
Předběžné odmítnutí nikdy nevytváří fiktivní API spotřebu ani neodblokovává
nevyřešené požadavky. Krátký Windows zámek checkpointu řeší omezené opakování
atomického přejmenování; trvalou chybu host dál oznámí.

## Ověření změn

Ověřeno bez placeného API: skutečný Agents SDK s lokálním náhradním modelem,
uložení několika hypotéz, zachování návrhů i při existující IDEA, sestavení
reportu, zamítnutí požadavku před přípravou adresáře, pokračování menší syntézy,
pause/cancel s neznámou rezervací a Windows dočasný zámek souboru.
Přínos pro rozmanitost a cenu skutečné modelové rešerše musí potvrdit další běh.
