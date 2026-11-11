import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { HISTORY_FILE, readHistory, validateBuildType, recordSignedBuilds } from "./build-hash-history.mjs";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { fileURLToPath } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const scriptDir = path.dirname(scriptPath);
const projectRoot = path.resolve(scriptDir, "..");

const targetArgs = process.argv.slice(2);
if (!targetArgs.length) targetArgs.push("dist");
const targets = targetArgs.map((targetArg) => {
  const targetDir = path.resolve(projectRoot, targetArg);
  return {
    targetArg, targetDir,
    manifestPath: path.join(targetDir, "SHA256SUMS.txt"),
    signaturePath: path.join(targetDir, "SHA256SUMS.txt.asc"),
    signingStatusPath: path.join(targetDir, "SIGNING_STATUS.txt"),
    integrityJsonPath: path.join(targetDir, "integrity.json"),
  };
});
const attemptedTargets = [];

const MANIFEST_FILE = "SHA256SUMS.txt";
const SIGNATURE_FILE = "SHA256SUMS.txt.asc";
const SIGNING_STATUS_FILE = "SIGNING_STATUS.txt";
const JSON_FILE = "integrity.json";
const BUILD_HASH_FILE = "BUILD_SHA256.txt";

const fingerprintPath = path.join(
  projectRoot,
  "public",
  "keys",
  "vojta-maur-openpgp-fingerprint.txt"
);

const gpgBinary = process.env.GPG_BINARY || "gpg";

function run(command, args, env = process.env) {
  const result = spawnSync(command, args, {
    cwd: projectRoot,
    env,
    stdio: "inherit",
    windowsHide: false
  });

  if (result.error) {
    throw result.error;
  }

  if (result.status !== 0) {
    throw new Error(`${command} exited with status ${result.status}`);
  }
}

function inspectSecretKey(fingerprint, env) {
  const result = spawnSync(
    gpgBinary,
    ["--batch", "--with-colons", "--list-secret-keys", fingerprint],
    {
      cwd: projectRoot,
      env,
      encoding: "utf8",
      windowsHide: false
    }
  );

  if (result.error) {
    throw result.error;
  }

  return {
    found: result.status === 0 && /^sec:/m.test(result.stdout ?? ""),
    detail: String(result.stderr ?? "").replace(/\s+/g, " ").trim()
  };
}

async function readFingerprint() {
  const raw = await fs.readFile(fingerprintPath, "utf8");
  const normalized = raw.replace(/\s+/g, "").toUpperCase();

  if (!/^(?:[0-9A-F]{40}|[0-9A-F]{64})$/.test(normalized)) {
    throw new Error(
      `Invalid OpenPGP fingerprint in ${path.relative(projectRoot, fingerprintPath)}`
    );
  }

  return normalized;
}

function formatFingerprint(fingerprint) {
  return fingerprint.match(/.{1,4}/g)?.join(" ") ?? fingerprint;
}

function expandEnvironmentVariables(value) {
  return value.replace(/%([^%]+)%/g, (match, name) => {
    return process.env[name] ?? process.env[name.toUpperCase()] ?? match;
  });
}

function normalizeEnteredPath(value) {
  let cleaned = value.trim();

  if (
    cleaned.length >= 2 &&
    ((cleaned.startsWith('"') && cleaned.endsWith('"')) ||
      (cleaned.startsWith("'") && cleaned.endsWith("'")))
  ) {
    cleaned = cleaned.slice(1, -1).trim();
  }

  cleaned = expandEnvironmentVariables(cleaned);

  if (cleaned === "~") {
    cleaned = os.homedir();
  } else if (cleaned.startsWith("~/") || cleaned.startsWith("~\\")) {
    cleaned = path.join(os.homedir(), cleaned.slice(2));
  }

  return path.resolve(projectRoot, cleaned);
}

async function validateGnuPgHome(directory) {
  const info = await fs.stat(directory);

  if (!info.isDirectory()) {
    throw new Error(`Not a directory: ${directory}`);
  }
}

async function resolveGnuPgHome(fingerprint) {
  const configured = process.env.GNUPGHOME?.trim();

  if (configured) {
    const resolved = normalizeEnteredPath(configured);
    await validateGnuPgHome(resolved);

    const keyCheck = inspectSecretKey(fingerprint, {
      ...process.env,
      GNUPGHOME: resolved
    });

    if (!keyCheck.found) {
      const detail = keyCheck.detail ? ` ${keyCheck.detail}` : "";
      throw new Error(
        `The signing key was not found in GNUPGHOME=${resolved}.${detail}`
      );
    }

    process.env.GNUPGHOME = resolved;
    return resolved;
  }

  if (!input.isTTY || !output.isTTY) {
    throw new Error(
      "GNUPGHOME is not set and interactive input is unavailable. " +
      "Set GNUPGHOME to the directory containing the private key before running the signed build."
    );
  }

  console.log("[signing] GNUPGHOME is not set.");
  console.log("[signing] The private-key location will not be guessed automatically.");

  const terminal = createInterface({ input, output });

  try {
    while (true) {
      const answer = await terminal.question(
        "Enter the path to your GnuPG home directory (blank cancels): "
      );

      if (!answer.trim()) {
        throw new Error("Signing cancelled: no GnuPG home directory was provided.");
      }

      const resolved = normalizeEnteredPath(answer);

      try {
        await validateGnuPgHome(resolved);

        const keyCheck = inspectSecretKey(fingerprint, {
          ...process.env,
          GNUPGHOME: resolved
        });

        if (!keyCheck.found) {
          console.error(
            `[signing] The requested secret key was not found in: ${resolved}`
          );
          if (keyCheck.detail) {
            console.error(`[signing] ${keyCheck.detail}`);
          }
          continue;
        }

        process.env.GNUPGHOME = resolved;
        return resolved;
      } catch (error) {
        console.error(`[signing] ${error.message}`);
      }
    }
  } finally {
    terminal.close();
  }
}

async function inspectBuildHistory({ manifestPath, targetDir, integrityJsonPath }) {
  const manifest = await fs.readFile(manifestPath);
  const buildHash = createHash("sha256").update(manifest).digest("hex");
  const declaredHash = await fs.readFile(path.join(targetDir, BUILD_HASH_FILE), "utf8");
  if (declaredHash.trim() !== buildHash + "  " + MANIFEST_FILE) {
    throw new Error(BUILD_HASH_FILE + " does not match " + MANIFEST_FILE + ".");
  }

  const history = await readHistory(path.join(targetDir, HISTORY_FILE));
  const historyHash = createHash("sha256").update(history, "utf8").digest("hex");
  const historyEntries = manifest.toString("utf8").split(/\r?\n/)
    .filter((line) => line.endsWith("  " + HISTORY_FILE));
  if (historyEntries.length !== 1 || historyEntries[0] !== historyHash + "  " + HISTORY_FILE) {
    throw new Error(MANIFEST_FILE + " does not cover the exact " + HISTORY_FILE + " snapshot.");
  }

  const metadata = JSON.parse(await fs.readFile(integrityJsonPath, "utf8"));
  validateBuildType(metadata.buildType);
  if (metadata.buildHash !== buildHash || metadata.buildHistoryFile !== HISTORY_FILE) {
    throw new Error(JSON_FILE + " does not match the build history or manifest.");
  }
  return { history, buildHash, buildType: metadata.buildType };
}

async function updateIntegrityMetadata({ integrityJsonPath }, {
  present,
  fingerprint = null,
  signingFingerprint = null,
  error = null
}) {
  try {
    const current = JSON.parse(await fs.readFile(integrityJsonPath, "utf8"));

    current.openPgp = {
      ...(current.openPgp ?? {}),
      signedFile: MANIFEST_FILE,
      signatureFile: SIGNATURE_FILE,
      statusFile: SIGNING_STATUS_FILE,
      present,
      fingerprint,
      signingFingerprint,
      error,
      note: "Informational metadata. Verify the detached signature directly."
    };

    await fs.writeFile(
      integrityJsonPath,
      JSON.stringify(current, null, 2) + "\n",
      "utf8"
    );
  } catch (metadataError) {
    if (present) throw metadataError;
    console.warn(
      `[signing] Could not update ${JSON_FILE}: ${metadataError.message}`
    );
  }
}

async function writeSignedStatus({ signingStatusPath }, fingerprint, signingFingerprint) {
  const text = `OPENPGP BUILD SIGNATURE STATUS

This build is OpenPGP signed by the author.

Signed manifest: ${MANIFEST_FILE}
Detached signature: ${SIGNATURE_FILE}
Previous signed builds: ${HISTORY_FILE} (covered by the signed manifest)
Primary-key fingerprint:
${formatFingerprint(fingerprint)}
Actual signing-key fingerprint:
${formatFingerprint(signingFingerprint)}

This file is informational. Verify the detached signature directly.
`;

  await fs.writeFile(signingStatusPath, text, "utf8");
}

async function writeFailedStatus({ signingStatusPath }, error) {
  const message = String(error?.message ?? error).replace(/\s+/g, " ").trim();
  const text = `OPENPGP BUILD SIGNATURE STATUS

This build is not OpenPGP signed.

A local signing attempt failed, so ${SIGNATURE_FILE} was not created.
The SHA-256 integrity files remain available, but they do not authenticate
the author of this build.

Reason: ${message}

This file is informational. A build is signed only when
${SIGNATURE_FILE} is present and its signature verifies successfully.
`;

  await fs.writeFile(signingStatusPath, text, "utf8");
}

// VALIDSIG reports the actual signer plus (for a signing subkey) its primary key.
// History identifies the primary key; metadata also retains the exact signing subkey.
export function parseVerifiedFingerprint(status, expectedFingerprint) {
  const signatures = status.split(/\r?\n/).filter((line) => line.startsWith("[GNUPG:] VALIDSIG "));
  if (signatures.length !== 1) throw new Error("Expected exactly one valid OpenPGP signature.");
  const fields = signatures[0].slice("[GNUPG:] ".length).trim().split(/\s+/);
  const signingFingerprint = fields[1];
  const fingerprint = fields[10] ?? signingFingerprint;
  const valid = /^(?:[0-9A-F]{40}|[0-9A-F]{64})$/;
  if (!valid.test(signingFingerprint) || !valid.test(fingerprint) || fingerprint !== expectedFingerprint) {
    throw new Error("Verified signature does not belong to the expected primary key.");
  }
  return { fingerprint, signingFingerprint };
}

function verifySignature(target, expectedFingerprint) {
  const result = spawnSync(gpgBinary, [
    "--batch", "--status-fd", "1", "--verify", target.signaturePath, target.manifestPath,
  ], { cwd: projectRoot, env: process.env, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"], windowsHide: true });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`OpenPGP verification failed for ${target.targetArg}.`);
  return parseVerifiedFingerprint(result.stdout, expectedFingerprint);
}

async function main() {
  const fingerprint = await readFingerprint();
  const paths = new Set();
  const builds = [];
  for (const target of targets) {
    const realPath = await fs.realpath(target.targetDir);
    const identity = process.platform === "win32" ? realPath.toLowerCase() : realPath;
    if (paths.has(identity)) throw new Error("Duplicate signing target.");
    paths.add(identity);
    builds.push(await inspectBuildHistory(target));
  }
  if (builds.some((build) => build.history !== builds[0].history)) {
    throw new Error("Signing targets have different history snapshots; rebuild them together.");
  }

  console.log(`[signing] key=${formatFingerprint(fingerprint)}`);
  const gnuPgHome = await resolveGnuPgHome(fingerprint);
  console.log(`[signing] GNUPGHOME=${gnuPgHome}`);

  // Any subsequent failure invalidates the entire attempted batch.
  attemptedTargets.push(...targets);
  for (const target of targets) await fs.rm(target.signaturePath, { force: true });
  for (const [index, target] of targets.entries()) {
    console.log(`[signing] target=${target.targetArg}`);
    run(gpgBinary, [
      "--yes", "--armor", "--detach-sign", "--local-user", fingerprint,
      "--output", target.signaturePath, target.manifestPath,
    ]);
    Object.assign(builds[index], verifySignature(target, fingerprint));
  }

  // Recheck every manifest after all signing, before committing either history record.
  for (const [index, target] of targets.entries()) {
    const verifiedBuild = await inspectBuildHistory(target);
    const build = builds[index];
    if (verifiedBuild.buildHash !== build.buildHash || verifiedBuild.buildType !== build.buildType
      || verifiedBuild.history !== build.history) {
      throw new Error("Build changed during signing; rebuild before signing again.");
    }
    await writeSignedStatus(target, build.fingerprint, build.signingFingerprint);
    await updateIntegrityMetadata(target, {
      present: true,
      fingerprint: formatFingerprint(build.fingerprint),
      signingFingerprint: formatFingerprint(build.signingFingerprint),
    });
  }

  // One atomic history commit for the entire batch, after every signature verifies.
  const appended = await recordSignedBuilds(projectRoot, builds);
  console.log("[signing] " + HISTORY_FILE + ": " + (appended ? `${builds.length} build(s) recorded in source` : "already recorded"));
  for (const target of targets) console.log(`[signing] ${target.targetArg}/${SIGNATURE_FILE}: verified`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === scriptPath) {
  main().catch(async (error) => {
    for (const target of attemptedTargets) {
      await fs.rm(target.signaturePath, { force: true }).catch(() => {});
      await writeFailedStatus(target, error).catch((statusError) => {
        console.error(`[signing] Could not write fallback status: ${statusError.message}`);
      });
      await updateIntegrityMetadata(target, { present: false, error: String(error?.message ?? error) });
    }
    console.error(`[signing] Failed: ${error.message}`);
    process.exitCode = 1;
  });
}
