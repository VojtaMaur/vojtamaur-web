# Odevzdání testu a ukončení neproduktivní smyčky — 0.7.6

Poslední run 20261021-092549-cd328641 vytvořil čtyři hypotézy, ale žádný finální
capture/test. Spotřeboval 34 kol, 2 097 974 tokenů a 64 vývojových příkazů.
Host odmítal shellový testovací driver, agent opakovaně přepisoval soubory místo
opravy argv. V auditu je 28 validation feedback událostí. Po vyčerpání příkazů
následovaly zbytečné pokusy o další lokální úkoly. Žádný upload neproběhl.

## Jednoznačné odevzdání

SDK coding task obsahuje submission_contract s konkrétními příklady script_path
a argv. Finální test může být uložený Python i shellový driver:

```json
{"script_path":"prototype/test.py","argv":["python","prototype/test.py"]}
{"script_path":"prototype/test.sh","argv":["sh","prototype/test.sh"]}
```

Prázdné argv u podporovaného typu host doplní odpovídajícím interpretem. Přímý
shell driver musí být .sh soubor svázaný s plánem/hashem; shell -c a Python -c
substituce zůstávají odmítnuté. Driver se spouští ve stejném privátním Dockeru,
bez sítě, host příkazů nebo účtů. Jeho zdroj i helpery se ukládají k receipt.
Povolení shell driveru nepřiděluje nový approval ani přístup do produkce.

Diagnostic nyní zachovává next_action, expected_argv a submitted_argv také
v dalším modelovém kole. Chyba způsobu spuštění má vést k opravě argv nebo
driveru, nikoli k přepisování algoritmu. Python nemůže spouštět .sh soubor.

## Ukončení chybných pokusů

Třetí host odmítnutí se stejným reason pro stejnou IDEA/revizi zastaví coding
worker s BLOCKED / CODING_SUBMISSION_STALLED. Počítadlo přežívá checkpoint i
další kola; kosmetická změna skriptu jej neresetuje. Skutečné finální spuštění
znamená posun za chybu odevzdání a počítadlo resetuje. Běžné runtime chyby kódu
se do tohoto počítadla nezahrnují. Nová věcná revize úkolu nebo explicitní human
unblock s poznámkou umožní další opravný pokus; evidence se nemaže.

Po dosažení max_coding_commands_per_agent se role zastaví jako LIMIT_REACHED,
nikoli jen tool odpovědí s exit=126, kterou by model mohl donekonečna opakovat.
Host kontroluje kapacitu před dispatch, před modelovým požadavkem i před
samotným Docker příkazem. Ani po posledním povoleném příkazu se neplatí další
modelový požadavek; soubory a výstup zůstávají zachovány. To může vyžadovat
výslovné rozšíření limitu pro pozdější dokončení — limity se samy nezvyšují.
Samotný unblock nemění vyčerpaný příkazový rozpočet.

## Ověření

Osm nových offline testů: přímý shell capture, odmítnutí inline substituce,
konkrétní expected_argv v SDK feedbacku, oprava argv v témže kvantu, zastavení
třetího odmítnutí, persistence mezi koly, nula provider volání po limitu,
zastavení před dalším requestem po posledním příkazu a runtime mismatch.
64 souvisejících regresí prošlo. Testy používají fake provider/executor.

Navíc byl původní run.sh, helper a skutečný EPUB zkopírován do samostatného
Workspace a spuštěn skutečným DockerExecutorem jako sh work/run.sh. Exit=0,
cleanup OK, vznikly tři deklarované výstupy; hash původního checkpointu stejný.
Žádné API náklady. Tento test potvrzuje spuštění driveru, nikoli RSS publikaci,
obnovu přes feed či audio kódování: starý helper jen čte metadata/text z EPUB.

Nový běžný běh: run-http.cmd z projektu, s Dockerem a OPENAI_API_KEY ve stejném
CMD. Modely gpt-5.4-mini, rozpočty a externí approval se nemění. Není nutné
opakovat smoke. Původní run ani jeho zablokované IDEA tato instalace nemění.
