"""Read-only corpus retrieval. A literal mention is evidence of a mention, not use."""
import hashlib
import re
from pathlib import Path
from .context import _is_link, redact_text

ALIASES = {
    "software heritage": ["Software Heritage", "softwareheritage.org", "SWHID"],
    "softwareheritage": ["Software Heritage", "softwareheritage.org", "SWHID"],
    "zenodo": ["Zenodo", "zenodo.org"],
    "osf": ["OSF", "osf.io", "Open Science Framework"],
    "open science framework": ["OSF", "osf.io", "Open Science Framework"],
    "qr": ["QR", "QR code"],
    "cbor": ["CBOR"],
    "perma.cc": ["Perma.cc"],
    "wacz": ["WACZ", "Webrecorder"],
    "warcz": ["WACZ", "Webrecorder"],
    "webrecorder": ["WACZ", "Webrecorder"],
    "bagit": ["BagIt"],
    "oais": ["OAIS", "Submission Information Package"],
    "fountain": ["fountain", "rateless", "RaptorQ", "erasure coding"],
    "rateless": ["fountain", "rateless", "RaptorQ", "erasure coding"],
    "at protocol": ["AT Protocol", "atproto", "Bluesky"],
    "atproto": ["AT Protocol", "atproto", "Bluesky"],
    "ipfs": ["IPFS"],
    "sia": ["Sia", "renterd", "hostd"],
}


def owner_rejection(data, rules):
    # Candidate fields only: quoted unrelated state does not reject a candidate.
    value = " ".join(str(data.get(k, "")) for k in ("title", "provider", "mechanism"))
    for rule in rules:
        if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", value, re.I) for alias in rule["aliases"]):
            return rule
    return None


def mechanism_identity(data):
    provider = str(data.get("provider", "")).casefold()
    canonical = provider.strip()
    for name, terms in (("zenodo", ["zenodo"]), ("osf", ["osf", "open science framework"]),
                        ("software heritage", ["software heritage", "softwareheritage"]),
                        ("at protocol", ["at protocol", "atproto"]), ("ipfs", ["ipfs"]), ("sia", ["sia"])):
        if any(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", provider) for t in terms):
            canonical = name
            break
    kind = data.get("mechanism_kind", "OTHER")
    if kind == "OTHER":
        kind = {"zenodo": "REPOSITORY_SNAPSHOT", "osf": "REGISTRATION", "software heritage": "SOURCE_ARCHIVE", "at protocol": "DISTRIBUTION", "ipfs": "DISTRIBUTION", "sia": "REPOSITORY_SNAPSHOT"}.get(canonical, "OTHER")
    if kind == "OTHER" or not canonical:
        return None
    delta = str(data.get("novelty_delta", "")).strip().casefold() if data.get("novelty_class") == "IMPROVEMENT" else ""
    return canonical, kind, delta


def candidate_terms(data):
    value = " ".join(str(data.get(k, "")) for k in ("provider", "title", "mechanism")).casefold()
    terms = []
    for key, aliases in ALIASES.items():
        if re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", value):
            terms.extend(aliases)
    provider = str(data.get("provider", "")).strip()
    if 2 <= len(provider) <= 100:
        terms.append(provider)
    return list(dict.fromkeys(terms))[:8]


class BaselineCorpus:
    def __init__(self, run_dir):
        self.root = Path(run_dir).resolve()
        paths = list((self.root / "snapshot" / "src" / "content" / "posts").glob("*.mdx"))
        paths += list((self.root / "snapshot" / "src" / "content" / "posts").glob("*.md"))
        paths += list((self.root / "snapshot" / "src" / "pages").glob("*.mdx"))
        paths += [self.root / "snapshot" / "public" / name for name in ("ARCHIVE.txt", "PRESERVATION_INSTRUCTIONS.txt")]
        paths += [p for p in (self.root / "context").glob("*")
                  if p.name in ("CURRENT_STATE.md", "local-metaweb-article.mdx", "local-documentation.mdx", "local-ARCHIVE.txt", "live-3.txt")]
        self.documents, self.hits = [], {}
        warnings = []
        for path in sorted(set(paths), key=lambda p: (0 if "ARCHIVE" in p.name or p.name == "live-3.txt" else 1 if p.name == "CURRENT_STATE.md" else 2, str(p))):
            if not path.exists():
                continue
            if any(_is_link(p) for p in (path, *path.parents)) or not path.is_file():
                raise ValueError("Baseline corpus refuses linked sources")
            if path.stat().st_size > 16 * 1024 * 1024:
                warnings.append(str(path.relative_to(self.root)) + ": exceeds 16 MiB; not indexed")
                continue
            data = path.read_bytes()
            self.documents.append({"path": path.relative_to(self.root).as_posix(),
                                   "sha256": hashlib.sha256(data).hexdigest(),
                                   "lines": redact_text(data.decode("utf-8-sig", errors="replace")).splitlines()})
        self.coverage = {"documents": len(self.documents),
                         "archive_captured": any("ARCHIVE" in d["path"] or d["path"] == "context/live-3.txt" for d in self.documents),
                         "scope": "ARCHIVE.txt first, then curated state, original MDX posts/pages and captured documentation; excludes translations and generated/repeated payloads.",
                         "warnings": warnings,
                         "absence_meaning": "No literal match in this captured corpus; not proof of novelty or absence everywhere."}
        self.coverage["corpus_sha256"] = hashlib.sha256("".join(d["path"] + d["sha256"] for d in self.documents).encode()).hexdigest()

    def search(self, terms, limit=12):
        if not isinstance(terms, list) or not 1 <= len(terms) <= 8 or any(not isinstance(t, str) or not 2 <= len(t.strip()) <= 100 for t in terms):
            raise ValueError("Provide 1..8 literal baseline terms, each 2..100 characters")
        patterns = [(term, re.compile(r"(?<!\w)" + re.escape(term.strip()) + r"(?!\w)", re.I)) for term in terms]
        results, total = [], 0
        for doc in self.documents:
            for line_number, line in enumerate(doc["lines"], 1):
                found = next(((term, pattern.search(line)) for term, pattern in patterns if pattern.search(line)), None)
                if not found:
                    continue
                total += 1
                term, match = found
                start = max(0, match.start() - 120)
                excerpt = line[start:start + 500]
                identity = doc["path"] + doc["sha256"] + str(line_number) + excerpt
                hit = {"id": "BASE-" + hashlib.sha256(identity.encode()).hexdigest()[:20],
                       "path": doc["path"], "line": line_number, "excerpt": excerpt,
                       "workspace_path": doc["path"].replace("snapshot/", "source/vojtamaur-web/", 1) if doc["path"].startswith("snapshot/") else doc["path"],
                       "document_sha256": doc["sha256"], "matched_term": term}
                self.hits[hit["id"]] = hit
                if len(results) < limit:
                    results.append(hit)
        return {"terms": terms, "matches": results, "total_matches": total, "coverage": self.coverage,
                "interpretation": "Matches prove text mentions only. Inspect excerpts to distinguish implemented, proposed, rejected and unrelated uses. No matches do not prove novelty."}
