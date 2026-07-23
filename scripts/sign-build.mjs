import { spawnSync } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { fileURLToPath } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const scriptDir = path.dirname(scriptPath);
const projectRoot = path.resolve(scriptDir, "..");

const targetArg = process.argv[2] ?? "dist";
const targetDir = path.resolve(projectRoot, targetArg);

const MANIFEST_FILE = "SHA256SUMS.txt";
const SIGNATURE_FILE = "SHA256SUMS.txt.asc";
const SIGNING_STATUS_FILE = "SIGNING_STATUS.txt";
const JSON_FILE = "integrity.json";

const manifestPath = path.join(targetDir, MANIFEST_FILE);
const signaturePath = path.join(targetDir, SIGNATURE_FILE);
const signingStatusPath = path.join(targetDir, SIGNING_STATUS_FILE);
const integrityJsonPath = path.join(targetDir, JSON_FILE);
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

  if (!/^[0-9A-F]{40}$/.test(normalized)) {
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

async function updateIntegrityMetadata({
  present,
  fingerprint = null,
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
      error,
      note: "Informational metadata. Verify the detached signature directly."
    };

    await fs.writeFile(
      integrityJsonPath,
      JSON.stringify(current, null, 2) + "\n",
      "utf8"
    );
  } catch (metadataError) {
    console.warn(
      `[signing] Could not update ${JSON_FILE}: ${metadataError.message}`
    );
  }
}

async function writeSignedStatus(fingerprint) {
  const text = `OPENPGP BUILD SIGNATURE STATUS

This build is OpenPGP signed by the author.

Signed manifest: ${MANIFEST_FILE}
Detached signature: ${SIGNATURE_FILE}
Signing key fingerprint:
${formatFingerprint(fingerprint)}

This file is informational. Verify the detached signature directly.
`;

  await fs.writeFile(signingStatusPath, text, "utf8");
}

async function writeFailedStatus(error) {
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

async function main() {
  await fs.access(targetDir);
  await fs.access(manifestPath);

  const fingerprint = await readFingerprint();

  await fs.rm(signaturePath, { force: true });

  console.log(`[signing] target=${targetArg}`);
  console.log(`[signing] key=${formatFingerprint(fingerprint)}`);

  const gnuPgHome = await resolveGnuPgHome(fingerprint);
  console.log(`[signing] GNUPGHOME=${gnuPgHome}`);

  run(gpgBinary, [
    "--yes",
    "--armor",
    "--detach-sign",
    "--local-user",
    fingerprint,
    "--output",
    signaturePath,
    manifestPath
  ]);

  run(gpgBinary, [
    "--verify",
    signaturePath,
    manifestPath
  ]);

  await writeSignedStatus(fingerprint);
  await updateIntegrityMetadata({
    present: true,
    fingerprint: formatFingerprint(fingerprint)
  });

  console.log(`[signing] ${SIGNATURE_FILE}: verified`);
}

main().catch(async (error) => {
  await fs.rm(signaturePath, { force: true }).catch(() => {});

  await writeFailedStatus(error).catch((statusError) => {
    console.error(
      `[signing] Could not write fallback status: ${statusError.message}`
    );
  });

  await updateIntegrityMetadata({
    present: false,
    error: String(error?.message ?? error)
  });

  console.error(`[signing] Failed: ${error.message}`);
  process.exit(1);
});
