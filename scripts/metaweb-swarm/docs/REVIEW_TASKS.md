# Konkrétní zadání nezávislého auditu (0.6.8)

## Problém a změna

Běh 20261013-084733-7be96a07 měl jen dva LEADy, žádnou IDEA ani upload plán. Auditor nepřečetl Open Library zdroje, místo toho zkusil jinou Internet Archive URL (404) a hodnocení prázdného IDEA ID. Změna je ve směrování práce, nikoli v tom, aby host automaticky udělil kladný verdict.

Host před SDK kolem přidělí Evidence Auditorovi jeden konkrétní review packet: LEAD/IDEA ID, revizi, primární dokumenty a jejich source receipts. Samotný screen bez dokumentů auditora nespouští. Přidělení je zaznamenané v audit chain a checkpointu.

## LEAD → vlastní čtení → posouzení

`get_review_task` vrací aktuální stav:

- READ_DOCUMENTS: přesné `missing_documents` URL, offset a limit pro relevantní rozsahy, které discovery skutečně četl. Vlastní čtení se stránkuje a pokrytí přežije restart. Jiný agent/source path ani samotný URL nejsou nezávislé čtení.
- TRIAGE: vlastní required ranges byly přečteny; agent volá `record_lead_review` se skutečným LEAD ID a vlastními source URLs. Výsledek je NEEDS_EVIDENCE / SETUP_REQUIRED / NOT_SUITABLE / QUALIFY, nikoli PASS nebo povolení k uploadu. NOT_SUITABLE stále vyžaduje literal negative quote; nepodložené tvrzení zůstane NEEDS_EVIDENCE.
- DONE: aktuální posouzení je zaznamenané. Role může skončit COMPLETED i při nedokumentovaném uploadu nebo chybějícím setupu. Následný výzkum/kvalifikace jsou handoff, nikoli povinné nekonečné pokračování auditora.
- DOCUMENT_BLOCKED: HTTP/TLS/parser/empty source neposkytl čtení. Role je technicky BLOCKED, LEAD se automaticky nezamítá. Stejný blocker se automaticky neotevře; změněná revize nebo explicitní lidské unblock umožní nový omezený pokus.
- STALE: zadání mezitím změnilo revizi nebo se změnilo na přijatou IDEA; další SDK kolo přidělí aktuální packet.

LEAD packet poskytuje jen `get_review_task`, `read_document`, `record_lead_review`, `note`. Web search je pro přidělený audit vypnutý; primární vlastní GET zůstává dostupný. SDK URL enum obsahuje konkrétní dokumenty tohoto packetu, host kontroluje tutéž scope i při přímém tool volání. Auditor proto nehledá jiný provider a nevolá critique na neexistující IDEA.

Ve stejném bounded SDK kole lze přečíst několik dokumentů a následně zaznamenat triage. Host ověřuje vlastní čtení i když tool schema vzniklo ještě v READ_DOCUMENTS stavu. Redirects se automaticky nenásledují; bezpečný transportem pozorovaný redirect target se přidá k packetu. SDK enum se obnoví v dalším kole.

U skutečné přijaté IDEA packetu zůstává hodnocení kvalifikace a kritiky dostupné, včetně původních pre-deployment evidence/setup pravidel. Paket sám nevytváří kandidáta, verdikt, účet, grant ani souhlas.

## Konfigurace a bezpečnost

Platí pro focused Evidence Auditor + require_deposit_qualification. Obecné výzkumné role pokračují normálně. Modely, USD/token/runtime/call/action limity, credentials a approval policy se tím nenavyšují. Síť dál obsluhuje původní host HTTP/TLS/URL policy. Produkční/repository write zákaz a immutable export pravidla zůstávají.

Source text i modelové závěry jsou tvrzení. Úspěšné nezávislé GET a coverage receipts dokládají čtení, nikoli správnost interpretace nebo to, že se služby skutečně povedlo využít.

## Dokončení auditu posledního běhu v CMD

Ze `G:\vojtamaur-web\scripts\metaweb-swarm` zadej odděleně:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py unblock "G:\metaweb-swarm-runs\20261013-084733-7be96a07" AGENT-002 --note "Opraveny review packet: dokoncit vlastni cteni a posouzeni Open Library"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\20261013-084733-7be96a07" --backend openai
```

Unblock poskytne auditorovi jedno další bounded role kolo; globálních 20 kol, tokeny, USD a runtime se nemění. V posledním běhu bylo spotřebováno 8 globálních kol, ale všechna 3 původní auditora. Příkazy pokračují ve stávajícím běhu. Nezaručují objev ani deposit; předmětem je nyní dokončení skutečného posouzení uloženého LEADu. Nový izolovaný běh: `run-deposit-trial.cmd`.

Ověření: lokální HTTP zdroje, own coverage, blokace cizí URL před sendem, technické 404 bez rejection, checkpoint, skutečný Agents SDK s FakeProviderem a kopie původního běhu. Bez placených modelů a veřejných uploadů. Oficiální strict schema dokumentace: https://developers.openai.com/api/docs/guides/function-calling .
