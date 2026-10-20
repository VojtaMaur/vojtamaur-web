# Opravy prototypů bez ručního párování ID — 0.6.18

Nový běh v CMD z této složky: `run-http.cmd`.

Běh `20261020-080422-5528d06b` předal skutečný EPUB, ale dva skripty
selhaly. Model opakovaně vložil EXPERIMENT-ID do `revision_test_id`, pak
vymazal oba odkazy a nedokázal opravu zaregistrovat. První skript navíc
ověřoval EPUB místo svého deklarovaného fediverse mechanismu.

## Současný postup

1. `prepare_prototype_input` kopíruje skutečný veřejný export do workspace.
2. Model napíše skript se skutečnou operací daného mechanismu a negativním
   testem. `record_prototype_plan` zmrazí kontrakt a kód. V jeho schématu
   nejsou žádná opravná ID. Při opravě stačí změnit kód a dodat
   `repair_notes` / `repair_check`; framework dohledá vlastní aktuální
   selhaný experiment nebo skutečný REVISE test. Poznámky se nezahazují.
3. Stávající Evidence Auditor dostane `PROTOTYPE_PLAN`, přečte přesný
   zmrazený skript a zvolí READY nebo REVISE. Kontroluje konkrétní operaci,
   pozitivní/negativní případ a rozsah. Generický ZIP test není test
   ActivityPub profilu. READY není vědecký certifikát ani externí approval.
4. `execute_prototype(argv)` spustí současný plán v Dockeru a při úspěchu
   samo uloží záznam s přesně zachycenými artefakty. Není nutný další modelový
   požadavek na `record_test` ani opakované spuštění pro registraci.
5. Nonzero exit se předá nezávislé diagnóze. Model opraví příčinu a předloží
   nový plán. Exit-zero receipt dál vyžaduje nezávislé posouzení skutečných
   testů. Teprve FULL_MECHANISM může certifikovat celý lokální mechanismus;
   SUBCOMPONENT zůstává dílčí výsledek.

Čekající prototyper se bez placeného pollingu uvolní auditorovi. Auditor má
prioritu před další implementací. Dvě LOCAL kola bez změněného skriptu,
skutečného spuštění nebo nového testu ukončí technickou smyčku a ponechají
kandidáta pro další práci. Model může stále napsat chybný kód; framework
takový výsledek nepovýší na úspěch.

## Audit, limity a pokračování

Plány a review jsou v `prototype_plan_submissions` checkpointu, jejich
skripty mají hash a neměnné auditní kopie. Reporter vidí počty READY/REVISE/
PENDING a může načíst jednotlivé původní záznamy. Konzole vypíše stručný
výsledek kontroly relevance. Externí approval, Docker izolace, credentials,
modely a globální rozpočty se touto změnou nemění. Výzkum bez
`require_prototype_focus` a samostatné smoke profily zachovávají oddělené
`run_experiment` / `record_test`.

Při explicitním resume se stará LOCAL modelová historie jednou archivuje,
aby nepřenášela původní schéma s opravnými ID. Staré výsledky se nepřepisují.
Dosud nezkontrolovaný starý plán musí před novým spuštěním projít kontrolou.
Opakování úspěšného `execute_prototype` se stejným plánem/argv znovu použije
původní zachycený receipt; změněné soubory nemůže certifikovat. Nejasné
přerušené spuštění se nepovažuje za úspěch ani automaticky neopakuje.

## Skutečné lokální ověření

Soubor `validation/PROTOTYPE_WORKFLOW_DOCKER.json` dokládá dva skutečné
networkless Docker běhy s kopií 1 294 314bajtového Metaweb EPUBu a již
zachycených veřejných knihoven. První reprodukuje původní `epub.ITEM_DOCUMENT`
chybu. Druhý s opraveným kódem vytvoří VTT, načte ho zpět, dekóduje vložený
textový fragment a odmítne neplatný cue. Opravný odkaz i test receipt vzniknou
automaticky a opakovaná registrace nevyvolá další Docker běh.
Přesný opravený skript je v `validation/PROTOTYPE_WORKFLOW_SOURCE.txt`;
jeho SHA256 odpovídá execution receiptu, takže audit nezávisí na adresáři chatu.

Jde o skutečné spuštění opravy napsané během vývoje. Rozhodnutí testovacího
auditora a diagnóza jsou skriptované, žádné placené API volání neproběhlo.
Výsledek ověřuje pouze lokální transport omezeného textového fragmentu;
neprokazuje úplné uchování EPUBu, standardní konformitu WebVTT ani veřejný
deposit. Původní run a produkční web se při ověření nezměnily.

Model-facing tools mají malé konkrétní rozhraní; syntaktická validita sama
nezaručuje správné propojení aplikace. Použitý podklad:
[OpenAI Docs — Function calling](https://developers.openai.com/api/docs/guides/function-calling).
