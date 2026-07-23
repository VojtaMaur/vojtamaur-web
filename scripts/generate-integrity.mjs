import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

const targetArg = process.argv[2] ?? "dist";
const TARGET_DIR = path.resolve(targetArg);
const SCOPE = path.basename(TARGET_DIR);

const MANIFEST_FILE = "SHA256SUMS.txt";
const OLD_MANIFEST_FILE = "SHA256SUMS";
const BUILD_HASH_FILE = "BUILD_SHA256.txt";
const JSON_FILE = "integrity.json";
const SIGNATURE_FILE = "SHA256SUMS.txt.asc";
const SIGNING_STATUS_FILE = "SIGNING_STATUS.txt";

const EXCLUDED = new Set([
  MANIFEST_FILE,
  OLD_MANIFEST_FILE,
  BUILD_HASH_FILE,
  JSON_FILE,
  SIGNATURE_FILE,
  SIGNING_STATUS_FILE,
  ".DS_Store",
  "Thumbs.db"
]);

const UNSIGNED_STATUS = `OPENPGP BUILD SIGNATURE STATUS

This build is not OpenPGP signed.

SHA256SUMS.txt.asc is created only for builds explicitly signed locally
by the author. The private signing key is never provided to third-party
CI or deployment services.

This file is informational. A build is signed only when
SHA256SUMS.txt.asc is present and its signature verifies successfully.
`;

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function toWebPath(filePath) {
  return filePath.split(path.sep).join("/");
}

async function walk(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  entries.sort((a, b) => a.name.localeCompare(b.name));

  const files = [];

  for (const entry of entries) {
    const absolutePath = path.join(dir, entry.name);
    const relativePath = toWebPath(path.relative(TARGET_DIR, absolutePath));

    if (EXCLUDED.has(relativePath) || EXCLUDED.has(entry.name)) {
      continue;
    }

    if (entry.isDirectory()) {
      files.push(...await walk(absolutePath));
    } else if (entry.isFile()) {
      files.push({
        absolutePath,
        relativePath
      });
    }
  }

  return files;
}

async function removeOldIntegrityFiles() {
  await Promise.all([
    fs.rm(path.join(TARGET_DIR, MANIFEST_FILE), { force: true }),
    fs.rm(path.join(TARGET_DIR, OLD_MANIFEST_FILE), { force: true }),
    fs.rm(path.join(TARGET_DIR, BUILD_HASH_FILE), { force: true }),
    fs.rm(path.join(TARGET_DIR, JSON_FILE), { force: true }),
    fs.rm(path.join(TARGET_DIR, SIGNATURE_FILE), { force: true }),
    fs.rm(path.join(TARGET_DIR, SIGNING_STATUS_FILE), { force: true })
  ]);
}

async function main() {
  await fs.access(TARGET_DIR);

  await removeOldIntegrityFiles();

  const files = await walk(TARGET_DIR);
  files.sort((a, b) => a.relativePath.localeCompare(b.relativePath));

  const lines = [];

  for (const file of files) {
    const data = await fs.readFile(file.absolutePath);
    lines.push(`${sha256(data)}  ${file.relativePath}`);
  }

  const manifestText = lines.join("\n") + "\n";
  const manifestHash = sha256(Buffer.from(manifestText, "utf8"));

  await fs.writeFile(
    path.join(TARGET_DIR, MANIFEST_FILE),
    manifestText,
    "utf8"
  );

  await fs.writeFile(
    path.join(TARGET_DIR, BUILD_HASH_FILE),
    `${manifestHash}  ${MANIFEST_FILE}\n`,
    "utf8"
  );

  await fs.writeFile(
    path.join(TARGET_DIR, JSON_FILE),
    JSON.stringify({
      algorithm: "sha256",
      scope: SCOPE,
      root: targetArg,
      manifest: MANIFEST_FILE,
      buildHashFile: BUILD_HASH_FILE,
      buildHash: manifestHash,
      fileCount: files.length,
      excluded: [...EXCLUDED],
      openPgp: {
        signedFile: MANIFEST_FILE,
        signatureFile: SIGNATURE_FILE,
        statusFile: SIGNING_STATUS_FILE,
        present: false,
        note: "Informational metadata. Verify the detached signature directly."
      },
      generatedAt: new Date().toISOString(),
      note: "Global build hash is the SHA-256 hash of the sorted per-file checksum manifest."
    }, null, 2) + "\n",
    "utf8"
  );

  await fs.writeFile(
    path.join(TARGET_DIR, SIGNING_STATUS_FILE),
    UNSIGNED_STATUS,
    "utf8"
  );

  console.log(`[integrity] target=${targetArg}`);
  console.log(`[integrity] ${files.length} files`);
  console.log(`[integrity] ${MANIFEST_FILE}`);
  console.log(`[integrity] ${BUILD_HASH_FILE}: ${manifestHash}`);
  console.log(`[integrity] ${JSON_FILE}`);
  console.log(`[integrity] ${SIGNING_STATUS_FILE}: unsigned`);
}

main().catch((error) => {
  console.error("[integrity] Failed:", error);
  process.exit(1);
});
