"""Shared observable coding/audit requirements, independent of provider/format."""
REQUIREMENTS={
    'source':'Use bytes from the retained export. Whole-payload claims recover its exact bytes; fragment/metadata claims identify the actual source-derived content and narrower scope. Hardcoded toy strings are fixtures, not a Metaweb prototype.',
    'native_format':'Produce a genuine artifact of the claimed format and open it with a separate established reader when available. A JPEG needs decodable pixels; marker-like bytes alone are not an image.',
    'consumer':'Recover from saved artifacts with an independent reader. Carrier recovery must not depend on the author script, original export, in-memory expected payload or an undeclared sidecar manifest. Put bootstrap metadata inside the artifact.',
    'negative':'Change/truncate/remove actual encoded data and assert consumer rejection or successful repair. Compare recovered content with independent expected data; hash inequality alone is not a decoder test.',
    'scope':'An extractor/shared helper is HELPER_ONLY. A real local operation can be SUBCOMPONENT; public custody, metadata survival through re-encoding and long-term retention remain separate untested claims.'}
