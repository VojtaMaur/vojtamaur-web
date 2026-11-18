# Správce exportů Vojtamaur.cz

Spusť **export-manager.bat v kořeni projektu** dvojklikem. Aplikace potřebuje Python 3.10 nebo novější s Tkinterem. Původní **export-all.bat je beze změny**.

## Vybrat a spustit

Kategorie **Sestavení webu** sdružuje Online web, Offline web (USB), Arweave, Gemini / Gopher a kompaktní ZIPy pro USB / web. Zdrojový ZIP k rekonstrukci je v kategorii **Data**.

1. **Zaškrtni exporty vlevo a klikni na Spustit vybrané.** Nemusíš je jednotlivě otevírat ani přidávat do sestavy. Výběr zůstává zachovaný při hledání a obnovení seznamu.
2. Kliknutí na název otevře nastavení. Parametry se pamatují zvlášť pro každý export. **Sekce se vybírají zaškrtnutím a lze jich zvolit více.** Prázdná běžná pole ponechávají výchozí nastavení skriptu. Méně časté volby jsou pod Další parametry.
3. Pro aktuální data zapni společnou volbu **Před exporty obnovit web**. Na kartě **Příprava webu** vyber postup. Výchozí **build:web:translate:signed** doplní chybějící překlady a podepíše web i Gemini. Lze zvolit i variantu bez překladu či podpisu.
4. Zadej zde dočasné přístupy podle následující části. Běžný výběr sdílí jedno nové sestavení. USB je při spuštění zaškrtnutých exportů poslední, protože nahrazuje dist/ offline verzí.
5. **Dokumentace tohoto exportu** otevře rovnou odpovídající kapitolu přes # v adrese. **Spustit tento export** spustí jen právě otevřený detail.

Samostatná položka **Online web** vytvoří klasický web do dist/ podle postupu zvoleného v Přípravě webu. Běží i bez společné volby obnovy. Pro obyčejný build bez nových překladů a podpisu zvol build:web; pro překlad a podpis build:web:translate:signed. Při hromadném výběru běží Online web před ostatními exporty a příprava se neopakuje. Web se automaticky nenahrává na hosting. Online a USB verze sdílejí dist/: při výběru obou USB běží poslední a nahradí obsah offline verzí.

Volitelná karta **Sestava** slouží pro opakované varianty jednoho exportu, vlastní pořadí a uložení dávky do JSON. Při chybě se další kroky nespustí. Opětovné spuštění provede celou zvolenou dávku znovu. Spodní tlačítka zůstávají viditelná při zmenšení okna; nastavení se posouvá samostatně.

## Dočasný DeepL klíč a GNUPGHOME

Na kartě **Příprava webu** vyplň DEEPL_AUTH_KEY a vyber složku GNUPGHOME. Klíč je při psaní skrytý. Oba údaje zůstávají pouze v paměti otevřeného manageru a předávají se spuštěným procesům přes prostředí. V logu se skrývají. **Neukládají se do nastavení, sestav, .env, spouštěčů ani repozitáře.** Zavřením okna nebo tlačítkem Zapomenout dočasné údaje je manager zapomene. Již běžící proces si do svého ukončení ponechává údaje, se kterými byl spuštěn.

Při spuštění z prostředí, kde už tyto proměnné jsou, je manager převezme pro aktuální otevření. Systémové proměnné nepřepisuje. Při chybějících údajích tě před spuštěním postupu s překladem nebo podpisem přepne na příslušnou kartu. Skutečný klíč ani soukromé PGP soubory nejsou součástí manageru.

## Samostatné ALL_POSTS.txt a ALL_POSTS.json

Jsou dvě jasně oddělené položky. Každá uloží přesnou kopii odpovídajícího souboru ze současného dist/ do nového časově označeného souboru v exports/. Chceš-li nový obsah, zapni předem obnovu webu. **Samotné uložení archivní kopie nemění dist/ ani jeho podpis.** Položka **TXT s filtry** navíc umožňuje výběr sekcí, jazyka, data a kompaktní podobu; nejde o přesnou kopii základního TXT.

## JPG/PNG z PDF

U obrazových galerií je ve výchozím stavu zapnuté **Nejdřív vytvořit nové PDF**. Manager vytvoří úplné společné české a anglické PDF webu nebo PDF Metawebu a teprve potom začne převod. Oba kroky sdílejí přesný čas edice, takže se nepoužije starší PDF.

Pro konkrétní existující PDF tuto volbu vypni a nastav --pdf, případně --source-manifest. Bez nového PDF a bez vlastního zdroje se použije běžný výběr nejnovější edice původního exportéru. --verify pouze ověří existující galerii; nevytváří nový web ani PDF.

## Nové exporty

Po otevření a po **F5 / Obnovit seznam** se načítají scripts/export-*.py, export-*.mjs, export-*.js, filter-all-posts.py a příkazy export:* z package.json. Není potřeba doplňovat každý export ručně. Samostatné přepočty indexů a graf odkazů jsou z nabídky vynechané. Úplné buildy jsou dostupné jako Online web a Offline web (USB); jejich variantu zvol na kartě Příprava webu.

Parametry se čtou ze zdrojů bez spouštění exportérů. U nestandardních či dynamických voleb lze použít pole **Vlastní argumenty**. Cesty s mezerami piš do dvojitých uvozovek; jednoduché uvozovky ve Windows neseskupují argumenty.

## Průběh a omezení

- Karta **Průběh** zobrazuje výstup kroku a návratový kód. Celé logy jsou v exports/export-manager/logs/.
- Běžné zapamatované volby jsou v exports/export-manager/settings.json; přístupové údaje v tomto souboru nejsou.
- **Zastavit** ukončí vlastní export i jeho podprocesy. Rozpracované soubory mohou zůstat neúplné.
- Příkaz python scripts/export-manager.py --check vypíše seznam bez otevření okna a bez spouštění exportů.
- Samotné exporty dál potřebují své původní knihovny, Chromium, Ghostscript či Poppler podle dokumentace. Manager je automaticky neinstaluje.
- USB používá odpovídající zvolený postup sestavení a nahrazuje dist/. Před následným PDF/EPUB/Gemini je třeba standardní web. Arweave jen připravuje místní soubory a nic nepublikuje.
- Opakovaná samostatná regenerace Gemini nebo zdrojového balíčku může změnit soubory podepsaného buildu. Při novém společném sestavení se jejich nezměněné výchozí regenerátory zbytečně neopakují. Vlastní cíle a parametry se provedou podle zadání.
- SSTV vytváří PNG. Převod na WAV je samostatný postup z dokumentace. Rosetta má offline výchozí operaci prepare; run a submit využívají nastavené placené API.

## Soubory

Hlavní **export-manager.bat patří do kořene projektu**. Ve scripts/ ponech export-manager.py, export_manager_core.py, export_manager_help.py, export_manager_tasks.py a tento návod. Starší scripts/export-manager.bat je kompatibilní odkaz na hlavní spouštěč.

Dokumentace: https://vojtamaur.cz/documentation/
Kontrolní přehled: https://vojtamaur.cz/metawebovy-clanek/
