# Sdílené auditní podklady mezi rolemi

Od 0.5.1 se úspěšné úplné veřejné GET odpovědi uchovávají také hostem pod run/audit/http/HTTP-….bin. Jde o bytes po sanitizaci HTTP transportem, se SHA256 odpovídajícím původní response receipt. Žádné ukládání agentních experimentů do produkce. Agentní write_file se do této složky nedostane; Docker vidí pouze vlastní workspace.

read_audit_artifact(request_id, offset=0, limit=8000) čte konkrétní zaznamenaný HTTP záznam, ne libovolnou cestu. Vrátí owner_agent_id, původní URL, hash, reprezentaci textu, excerpt a next_offset. Nespouští HTTP a nemění cizí workspace. Neznámé IDs, neúspěšné/truncated odpovědi, autentizované/privilegované požadavky, změněné bytes a traversal se odmítají. Text reader má 2 MB limit; binary/PDF není automaticky dekódované. Autorita výsledku je omezená na zaznamenané byte/excerpt evidence, ne pochopení nebo nezávislé ověření.

response_path z checkpointu patří uvedenému owner_agent_id. Reporter ho nemá předávat do svého read_file: jeho private workspace tuto cestu nemusí mít. Sdílený nástroj předchází falešnému tvrzení o chybějících souborech. U starších běhů bez shared capture čte pouze původní registrovaný owner workspace soubor a ověří hash; nic znovu nestahuje ani nevytváří nový workspace. Legacy fallback nefunguje, pokud skutečný původní soubor chybí nebo byl změněn.

Auditor smí sdílený text použít k orientaci, ale pro PASS si musí API/terms nezávisle načíst svým read_document. Shared read nepřidá external_sources ani vlastní http_document_reads. Sdílení nepřenáší permissions, approval nebo credentials mezi rolemi.

Selhání pomocného sdíleného capture nezmění známý HTTP výsledek na UNKNOWN; zachová se původní receipt a možnost hash-checked legacy čtení. U neurčitého síťového výsledku se naopak žádný success nevymýšlí.

Bez placené inference ověřeno přes nainstalovaný SDK a skutečný lokální HTTP: named qualification, unresolved fields, cross-role reads, hash/tamper/traversal/private-request odmítnutí, checkpoint a zachování nezávislého audit gate. Navíc původní čtyři úspěšné GET artefakty běhu 20261008-113459-2fb32e3b přečetl nový reader v režimu bez zápisu do tohoto runu: původní report nesprávně hledal u reportera, nikoli u vlastníka.
