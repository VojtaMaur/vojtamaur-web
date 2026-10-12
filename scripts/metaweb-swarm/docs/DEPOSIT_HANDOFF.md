# 0.5.4 — kandidát čekající na setup, resume a upload flow

## Spuštění pokračování

Oprava je přímo ve frameworku. Pro již rozpracovaný NudgeHost pokračuj stejným runem:

~~~cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\20261012-092352-fd4b9ba8" --backend openai --extend-rounds 2
~~~

Přidá dvě kola k limitům rolí, nikoli tokeny/USD/runtime nebo oprávnění. Podklady NudgeHost zůstávají. Aktuální granty jsou prázdné; žádný účet se nevytváří a žádný klíč se nepřebírá z hostitelských účtů. Nečekej hotový upload: cílem pokračování je dokončit explicitní plán, nezávisle prověřit kandidáta a uložit konkrétní setup/capability překážky. Nový run lze dál založit run-deposit-trial.cmd.

## Přijetí kandidáta není přijetí realizace

Kvalifikace vrací admission_kind:
- READY_FOR_AUDIT: strukturální předpoklady realizace splněny; stále nutný nezávislý audit a případný approval.
- BLOCKED_LEAD: smysluplný konkrétní plán může zůstat jako kandidát, ale chybí credential, resource limit nebo explicitní/supported flow.
- NOT_ADMITTED: například forbidden target, nedoložený endpoint/auth, chybějící export, zdroje nebo baseline srovnání.

admissible=true znamená, že může vzniknout IDEA, nikoli že se může nahrávat. execution_ready je oddělené pole. ACCOUNT_SETUP_REQUIRED není REJECTED a nemusí čekat na založení účtu, aby byl nápad uložen.

Na scheduler checkpointu host doplní zapomenutý kandidátský záznam z přijaté QUAL. Je označen host_retained_deposit_draft: zdroje jsou pouze evidované URL, cena UNKNOWN, novost a tvrzení neověřené, žádné umělé skóre či preservation receipt. Samotný draft nesmí získat PASS s neověřenou cenou. Auditor jej může nezávisle doplnit nebo dát REVISE/REJECT podle skutečných podkladů.

Pozdější submit_idea se stejnou QUAL upraví stejné IDEA ID a zachová provenance. Přehodnocení stejného host draftu při jiné QUAL/credential používá stejné ID; stará QUAL nesmí přepsat novější plán zpět. Nejasná deduplikace vůči jiným kandidátům je DEFERRED a zůstává v auditu; host ji nepřeskočí.

## Obnovení návazných rolí

Při resume i mezi koly se znovu vyhodnotí:
- NO_ADMITTED_DISCOVERY_CANDIDATE: auditor se obnoví, když existuje kandidát.
- NO_INDEPENDENTLY_APPROVED_DEPOSIT_PLAN: realizátor se obnoví až po PASS vázaném na aktuální READY kvalifikaci.
- dokončený auditor: nový kvalifikovaný plán může vyžadovat nové posouzení.
- dokončený reporter: nová evidence vyžaduje aktualizaci, pokud zbývá přidělené kolo.

Neobnovuje se HUMAN_APPROVAL_REQUIRED, UNKNOWN outcome/budget, technická blokace, zamítnutí ani překročený limit rolí. Report se neobnovuje pořád nad stejnou evidencí. Žádné kolo/budget se automaticky nepřidává.

## Záznam celého protokolu

check_deposit_target přijímá pojmenované pole operation_steps, nikoli JSON string. Každý krok má method, purpose, sends_export a uses_credential.

Příklad obecného tříkrokového protokolu:

~~~json
[
  {"method":"POST","purpose":"Reserve upload slot","sends_export":false,"uses_credential":true},
  {"method":"PUT","purpose":"Send retained export to returned URL","sends_export":true,"uses_credential":false},
  {"method":"POST","purpose":"Finalize upload and get public link","sends_export":false,"uses_credential":true}
]
~~~

Host spočítá všechny mutace a autentizované GET/HEAD/OPTIONS. Agentovo required_external_actions=1 nemůže snížit odvozené tři akce. Překročení max_external_actions se uchová jako RESOURCE_LIMIT, bez změny skutečného limitu. Bez popsaného flow vrátí UPLOAD_FLOW_REQUIRED, když je require_explicit_upload_flow=true; tento boolean je zapnutý v deposit-trial profilu. Legacy obecné profily zachovávají jedno-requestový contract.

**Záznam protokolu není nový executor.** Kvalifikovaný executor nyní podporuje jeden payload-bearing HTTP request. Více kroků dostane MULTI_STEP_EXECUTION_UNAVAILABLE a zůstane BLOCKED lead, i kdyby operátor později povolil více akcí. Obecný HTTP transport tím neztrácí GET/upload/download schopnosti; přesně vázané, nezávisle auditované provedení dynamického deposit protokolu je další implementační práce. Nikdy se neobchází qualification/approval přes prázdné IDEA ID.

## Vývoj a ověření

Lokální regrese pokrývají zapomenuté submit, zachování ID/provenance, nové/stará QUAL bez rollbacku, skutečný scheduler resume audit → report bez předčasné realizace, technické a approval blokace, autentizované reads, podhodnocený počet kroků, chybějící/invalidní flow a skutečnou dispatch nového typu přes nainstalovaný Agents SDK s kontrolovaným modelem. Bez placené inference nebo veřejného depositu.


Ověření této verze: 371 testů OK, jeden Windows symlink test přeskočen. Rozpracovaný run byl před opravou zálohován; bez API/HTTP vznikla IDEA-0001 jako neověřený BLOCKED NudgeHost draft, auditor a reporter přešli do PENDING, realizátor zůstal BLOCKED. Doplnění celého upload flow je nyní explicitní požadavek pokračování. Všechny modely, token/USD/runtime limity, credential grants, approval i limit externích akcí zůstaly zachovány. Audit: docs/validation/DEPOSIT_HANDOFF_REAL_RUN_RECOVERY.json.
