# 0.8.1 — skutečná operace a stabilní zadání prototypu

Oprava vychází z runu `20261022-080541-385bea51`. Jeho „podcast RSS“
implementace vytvořila JSON a textový hash, žádný RSS feed. Poslední nezávislá
sonda hledala řetězce ve zdrojáku místo zkoušení chování. Přidání evidence přes
SAME mezitím měnilo otisk zadání a spouštělo další kódování stejné věci.

## Co se změnilo

- **SAME přidává příspěvek ke stejnému zadání.** Host zachová jeho implementační
  revizi, titul a popis operace; alternativní znění, zdroje a autor zůstanou
  v `submissions`, `contributors` a evidence. Přidané zdroje mohou otevřít nový
  výzkumný audit, nikoli automaticky nové kódování. Explicitní změna existujícího
  IDEA ID v mechanismu, scope, validačním plánu, navrhované změně nebo platebních
  podmínkách změní zadání a zneplatní aktuální coverage. Hostové pole
  `implementation_revision` agent nepřiděluje.
- **Review vybírá řádky, nekopíruje text.** `read_test_artifact` vrací u zachycené
  implementace také `source_lines`. `positive_refs` / `negative_refs` obsahují
  1..8 rozsahů `{path, start_line, end_line}`; čísla jsou od 1 a oba konce patří
  do rozsahu. Framework ověří hash i vlastní přečtení každého celého rozsahu a
  uloží skutečné citace. Lze vybrat několik nesouvislých bloků. Prázdné pole je
  přípustné tam, kde daný typ evidence není potřeba. Přímé starší Python volání
  s citacemi zůstává kompatibilní, živé SDK je již nevyžaduje.
- **RSS má nativní minimum.** Pokud kandidát výslovně tvrdí RSS, coder předem
  dostane `format_contract`: skutečné RSS 2.0 XML, jeden item, titul původního
  exportu, GUID s jeho SHA256 a veřejný ukazatel na Metaweb. Má implementovat
  `read_pointer(path)`, přečíst uložený feed a odmítnout poškozené XML či chybějící
  GUID. Host nezávisle parsuje výstup standardním XML parserem a porovná očekávaná
  pole; JSON s jiným názvem neprojde. Chyba vrací feedback přímo do stejného
  coding workeru před vytvořením test receipt. Kontrola se opakuje při schválení
  historického zachyceného testu. Modelový kód se na hostu neimportuje.
- **Čtení zdrojáku není behaviorální sonda.** Syntax guard odmítá sondu, jejíž
  assertions pouze hledají text či jeho odvozeniny v implementačním souboru.
  Provedení author scriptu před takovým hledáním nestačí. Auditor může v rámci
  stávajícího limitu opravit vlastní chybnou sondu; její selhání samo neprokazuje
  chybu implementace.
- **Aktuální coverage určuje poslední test a jeho poslední audit.** Novější
  neuzavřený test, REVISE, HELPER_ONLY nebo změněné zadání zruší staré příznaky
  `prototype_tested` / `prototype_component_tested`. Starší úspěšné audity zůstanou
  v historii. Přepočet probíhá po zachycení, auditu, merge, resume a pro report.

## Praktické meze

RSS pravidlo je minimum pro jednu skutečně inzerovanou reprezentaci, nikoli
connector k nějaké službě ani obecný rozhodovač správnosti všech mechanismů.
Neprokazuje podcast playback, veřejné hostování, nezávislou úschovu ani obnovu
EPUB z pointeru. Ostatní reprezentace nadále vyžadují vlastní konkrétní operaci,
nezávislou sondu a posouzení auditora. Syntax guard také není sémantický důkaz.

Soukromé workspace, Docker bez sítě, rozpočty, modely i schvalování externích
zápisů se touto opravou nemění. Limity velkých exportů se nezvyšují; ZIP celého
buildu je legitimní budoucí vstup, pro který se musí vhodně nastavit velikostní
rozpočet. Staré běhy a jejich checkpointy oprava při instalaci neupravuje.

## Ověření a další běh

Offline replay skutečného posledního runu odmítl jeho JSON jako RSS, odmítl
source-only sondu, vyřešil nesouvislé řádky a odstranil zastaralý příznak v kopii.
Samostatná lidsky napsaná RSS reference nad skutečným zachyceným EPUB prošla
v Dockeru: vytvoření feedu, nezávislé přečtení a odmítnutí chybějícího title,
GUID, link i neplatného XML. To ověřuje implementaci frameworku, nikoli budoucí
autonomní výkon modelu. Původní checkpoint zůstal stejný; API volání a externí
zápisy: 0. Podrobnosti jsou v `validation/OPERATION_EVIDENCE_LIVE_PROOF.json`.

Pro další **nový výzkumný běh s levnými modely**, v CMD s nastaveným klíčem a
spuštěným Dockerem:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-http.cmd
```

Není nutné před ním opakovat smoke testy. Příkaz spustí placený run podle
`config.http.json`; všechny tiery zůstávají `gpt-5.4-mini`. Starý RSS run má
historii nevhodných lokálních smluv, proto je pro další výzkum vhodnější nový run.
Pro explicitní resume se obnoví modelový review kontext podle nového protokolu,
nezmění se však automaticky limity, příčiny blokování ani původní smlouvy.
