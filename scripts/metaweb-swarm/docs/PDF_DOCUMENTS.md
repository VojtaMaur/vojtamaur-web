# PDF dokumentace — 0.6.3

`read_document` umí kromě HTML, JSON a textu také PDF s textovou vrstvou.
Není potřeba nový tool, Docker ani browser. Existující `offset` / `limit` stránkují
celý odvozený text; nástroj vrací čísla skutečně zahrnutých PDF stran a `next_offset`.
Hlavička `[PDF page N]` usnadňuje orientaci, sama není důkazem přečteného textu.

## Instalace

`pypdf==6.20.1` je deklarováno v základních dependencies i requirements pro OpenAI.
V tomto pracovním prostředí již bylo nainstalováno. Na jiném počítači:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe -m pip install -r requirements-openai.txt
```

PDF dependency se během agentního běhu neinstaluje automaticky do hosta. Chybějící
knihovna vrátí `PDF_DEPENDENCY_MISSING`; po instalaci lze znovu použít původní GET.

## Původ a audit

- Původní binární HTTP odpověď zůstává nezměněná. `sha256` nadále identifikuje
  zdrojové bajty, nikoli text získaný parserem.
- `audit/pdf/HTTP-….json` obsahuje odvozené texty stran. Host zaznamená SHA256
  tohoto artefaktu, parser/verzi, zdrojový hash a počet stran.
- Receipt zaznamená zahrnuté strany, rozsah znaků, hash výřezu a hash celého
  odvozeného textu. Tato metadata se připojí i k rozpracovanému LEAD.
- Upravená textová cache se nepoužije; znovu se vytvoří z hashově ověřeného PDF.
  Nezměněný vlastní GET a odvozená cache se používají i po resume.
- `read_audit_artifact` umí stejný PDF výřez bez nového síťového požadavku.
  Sdílené čtení nepředstírá vlastní nezávislý GET auditora. Pro vlastní posouzení
  auditor používá `read_document` a jeho vlastní source receipt.
- Doslovné negativní podklady v PDF lze použít pro existující review kontrakt;
  host kontroluje nezměněný zdroj a odvozený text. Existence citace sama
  nepotvrzuje správnost úsudku ani poskytovatelovy tvrzení.
- Text před zpřístupněním projde existující redakcí credential hodnot/patternů;
  původní veřejný binární zdroj a odvozený redigovaný text mají odlišné hashe.

## Omezení

Jde o pevný hostem spravovaný parser, nikoli obecný sandbox pro agentní kód.
Samostatný proces dostává pouze PDF bajty přes stdin; ne děděné API credentials,
proxy konfiguraci ani agentní PYTHONPATH. Python běží s `-I`. PDF skripty,
odkazy a vložené programy se nespouštějí ani nenásledují.

Tvrdé limity parseru: 8 MB zdroje, 500 stran, 1 milion extrahovaných znaků,
20 sekund a 512 MiB procesní paměti. Windows používá process memory Job Object,
POSIX `RLIMIT_AS`. Stávající HTTP a run limity zůstávají účinné nezávisle.
Ochrana procesu nemění uživatelská filesystem oprávnění hosta.

Šifrovaný dokument vrátí PDF_ENCRYPTED, poškozený PDF_PARSE_FAILED a dokument
bez extrahovatelného textu PDF_NO_TEXT_OCR_REQUIRED. OCR zatím není zahrnuto.
Překročení limitu/timeout má vlastní důvod. Žádná z těchto odpovědí nevytváří
document-read receipt ani neznamená, že služba zakazuje EPUB.

Tabulky a pořadí sloupců mohou při extrakci ztratit vzhled; textový výřez není
zárukou správné interpretace API. Podrobnosti omezení uvádí
[dokumentace pypdf](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).

## OpenDrive a další pokračování

Bez síťového/placeného volání byl ověřen již stažený zdroj z runu
`20261013-043825-09e42a24`: 109 stran, první výřez zahrnuje strany 1–6.
V izolované kopii prošlo read_document → uložený PDF receipt → LEAD → obnovení
závislosti auditora; shared read nevyrobil nezávislý receipt. Původní run nebyl
upraven. Důkaz: [PDF_DOCUMENT_PROOF.json](validation/PDF_DOCUMENT_PROOF.json).

Pro pokračování původního runu v CMD z projektové složky:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\20261013-043825-09e42a24" --backend openai --extend-rounds 2
```

Tento příkaz spouští modelové pokračování s původním rozpočtem, oprávněními a
approval pravidly; přidává pouze povolená kola rolí. Prompt nově výslovně říká,
že dříve nečitelné PDF lze zkusit znovu na stejné URL z cache. Úspěšná extrakce
neprokazuje vhodnost OpenDrive, free tier, upload nebo podporu EPUB; to je další
práce discovery a auditora. Nový run ani opakovaný HTTP smoke nejsou nutné.
