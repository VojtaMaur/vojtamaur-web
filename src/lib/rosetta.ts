import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { rosettaCopy } from "./rosetta-copy";

const root = process.cwd();
const directory = path.join(root, "public", "rosetta");
const rtl = new Set(["ar", "fa", "he", "ps", "sd", "ur"]);

export type RosettaLanguage = {
  code: string;
  name: string;
  notice: string;
  open: string;
  languages: string;
  translationDate: string;
  translatedAt?: string;
  date?: string;
  filename: string;
  href: string;
  dir: "ltr" | "rtl";
};

type Manifest = {
  updatedAt?: string;
  source: { generatedAt: string; sha256: string };
  totalCzechArticles: number;
  languages: Array<{
    code: string;
    filename: string;
    status: string;
    exportedArticles: number;
    sha256: string;
  }>;
};

// The JSON is optional repository-only input. It is never imported as a module
// or copied to public/. TXT headers remain sufficient for a standalone edition.
async function readManifest(): Promise<Manifest | undefined> {
  let text: string;
  try {
    text = await fs.readFile(path.join(root, "rosetta.json"), "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw error;
  }
  const { manifest } = JSON.parse(text.replace(/^\uFEFF/, ""));
  if (!manifest?.source?.generatedAt || !Array.isArray(manifest.languages)) {
    throw new Error("rosetta.json has no valid export manifest.");
  }
  return manifest;
}

export async function getRosettaLanguages(): Promise<RosettaLanguage[]> {
  const manifest = await readManifest();
  // updatedAt is set after TXT serialization, unlike the source-content date
  // or manifest.generatedAt (which records initial preparation, before translation).
  const translatedAt = manifest?.updatedAt;
  if (translatedAt && !Number.isFinite(Date.parse(translatedAt))) {
    throw new Error("Invalid Rosetta TXT export date in rosetta.json.");
  }
  const files = (await fs.readdir(directory, { withFileTypes: true }))
    .filter((entry) => entry.isFile() && /^ALL_POSTS__lang-[a-z]{2,3}(?:-[A-Za-z]+)?\.txt$/.test(entry.name))
    .map((entry) => entry.name)
    .sort();
  const languages: RosettaLanguage[] = [];

  for (const filename of files) {
    const code = filename.slice("ALL_POSTS__lang-".length, -4);
    if (code === "en" || code === "cs") continue;
    const copy = rosettaCopy[code];
    if (!copy) throw new Error(`Missing localized Rosetta notice for ${code}.`);

    const bytes = await fs.readFile(path.join(directory, filename));
    const header = bytes.subarray(0, 4096).toString("utf8").replace(/^\uFEFF/, "");
    const target = /^Target language: (\S+)/m.exec(header)?.[1];
    const generatedAt = /^Source generated: (.+)$/m.exec(header)?.[1].trim();
    const sourceSha = /^Source SHA-256: (\S+)/m.exec(header)?.[1];
    const articles = /^Articles: (\d+) of (\d+) Czech versions/m.exec(header);
    if (target !== code || !generatedAt || !Number.isFinite(Date.parse(generatedAt)) ||
        !articles || Number(articles[1]) === 0 || articles[1] !== articles[2]) {
      throw new Error(`Incomplete or invalid Rosetta TXT header: ${filename}`);
    }

    const record = manifest?.languages.find((language) => language.code === code);
    if (manifest && (!record || record.status !== "complete" || record.filename !== filename ||
        record.exportedArticles !== Number(articles[1]) ||
        manifest.totalCzechArticles !== Number(articles[2]) ||
        manifest.source.generatedAt !== generatedAt || manifest.source.sha256 !== sourceSha ||
        record.sha256 !== createHash("sha256").update(bytes).digest("hex"))) {
      throw new Error(`Rosetta TXT does not match rosetta.json: ${filename}`);
    }

    languages.push({
      ...copy,
      code,
      translatedAt,
      date: translatedAt?.slice(0, 10),
      filename,
      href: `/rosetta/${filename}`,
      dir: rtl.has(code) ? "rtl" : "ltr",
    });
  }
  return languages;
}
