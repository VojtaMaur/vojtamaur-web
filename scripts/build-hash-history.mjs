import { promises as fs } from "node:fs";
import path from "node:path";

export const HISTORY_FILE = "BUILD_HASH_HISTORY.txt";
const BUILD_TYPES = new Set(["web", "usb", "arweave", "gemini"]);
export const HISTORY_HEADER = [
  "RECORDED_AT_UTC".padEnd(24), "TYPE".padEnd(7), "ALGO".padEnd(6),
  "BUILD_SHA256".padEnd(64), "PRIMARY_KEY_FINGERPRINT",
].join(" | ");

export function formatHistoryRecord({ timestamp, buildType, buildHash, fingerprint }) {
  const columns = [timestamp.padEnd(24), buildType.padEnd(7), "SHA256".padEnd(6), buildHash];
  if (fingerprint) columns.push(fingerprint);
  return columns.join(" | ") + "\n";
}

export function validateBuildType(buildType) {
  if (!BUILD_TYPES.has(buildType)) {
    throw new Error(`Invalid build type: ${buildType}. Expected web, usb, arweave, or gemini.`);
  }
}

export function validateHistory(text) {
  if (text === "") return [];
  if (!text.endsWith("\n")) {
    throw new Error(`${HISTORY_FILE} must end with a newline.`);
  }
  const lines = text.replace(/\r?\n$/, "").split(/\r?\n/);
  if (lines[0] === HISTORY_HEADER) lines.shift();
  return lines.map((line, index) => {
    const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z) * \| (web|usb|arweave|gemini) * \| SHA256 * \| ([0-9a-f]{64})(?: \| ([0-9A-F]{40}|[0-9A-F]{64}))?$/.exec(line);
    if (!match) throw new Error(`Invalid ${HISTORY_FILE} record on line ${index + 1}.`);
    const [, timestamp, buildType, buildHash, fingerprint = null] = match;
    const normalized = timestamp.length === 20 ? timestamp.replace("Z", ".000Z") : timestamp;
    if (!Number.isFinite(Date.parse(timestamp)) || new Date(timestamp).toISOString() !== normalized) {
      throw new Error(`Invalid UTC timestamp in ${HISTORY_FILE} on line ${index + 1}.`);
    }
    return { timestamp, buildType, buildHash, fingerprint };
  });
}

export async function readHistory(filePath) {
  const text = await fs.readFile(filePath, "utf8");
  validateHistory(text);
  return text;
}

// Call only after signature verification and successful metadata/status writes.
// The staging directory is already excluded from Git and the source archives.
export async function recordSignedBuild(projectRoot, build) {
  return recordSignedBuilds(projectRoot, [build]);
}

// A batch shares one previous-history snapshot and commits all records together.
export async function recordSignedBuilds(projectRoot, builds) {
  if (!builds.length) throw new Error("No signed builds to record.");
  const { history } = builds[0];
  validateHistory(history);
  const identities = new Set();
  for (const { history: snapshot, buildType, buildHash, fingerprint } of builds) {
    if (snapshot !== history) throw new Error("Signed builds must share the same history snapshot.");
    validateBuildType(buildType);
    if (!/^[0-9a-f]{64}$/.test(buildHash)) throw new Error("Invalid signed build hash.");
    if (!/^(?:[0-9A-F]{40}|[0-9A-F]{64})$/.test(fingerprint ?? "")) {
      throw new Error("Missing or invalid verified signing-key fingerprint.");
    }
    const identity = `${buildType}:${buildHash}`;
    if (identities.has(identity)) throw new Error("Duplicate build in signing batch.");
    identities.add(identity);
  }

  const historyPath = path.join(projectRoot, HISTORY_FILE);
  const stagingDir = path.join(projectRoot, ".source-bundle-staging");
  await fs.mkdir(stagingDir, { recursive: true });
  const lockPath = path.join(stagingDir, "build-hash-history.lock");
  const temporaryPath = path.join(stagingDir, "build-hash-history.next");
  let lock;
  try {
    lock = await fs.open(lockPath, "wx");
  } catch (error) {
    if (error.code === "EEXIST") {
      throw new Error(`History update is locked: ${lockPath}. Wait for the other signer; remove a stale lock only after it has stopped.`);
    }
    throw error;
  }

  try {
    const current = await readHistory(historyPath);
    if (current !== history) {
      // Re-signing an already recorded build must not duplicate its entry.
      const recorded = current.startsWith(history) ? validateHistory(current.slice(history.length)) : [];
      if (recorded.length === builds.length && recorded.every((entry, index) => {
        const build = builds[index];
        return entry.buildHash === build.buildHash && entry.buildType === build.buildType
          && entry.fingerprint === build.fingerprint;
      })) return false;
      throw new Error(`Canonical ${HISTORY_FILE} changed since this build. Rebuild before signing to preserve the chain.`);
    }

    const timestamp = new Date().toISOString();
    const record = builds.map((build) => formatHistoryRecord({ ...build, timestamp })).join("");
    // Existing snapshots are immutable. Only a brand-new history gets a header here;
    // migrating an existing source history is an explicit, separate operation.
    await fs.writeFile(temporaryPath, (current || HISTORY_HEADER + "\n") + record, "utf8");
    // Check again before the atomic replacement, including edits outside this script.
    if (await fs.readFile(historyPath, "utf8") !== current) {
      throw new Error(`Canonical ${HISTORY_FILE} changed during the history update.`);
    }
    await fs.rename(temporaryPath, historyPath);
    return true;
  } finally {
    // Cleanup failure must not turn an already committed record into a failed build.
    await lock.close().catch((error) => console.warn(`[history] ${error.message}`));
    for (const filePath of [temporaryPath, lockPath]) {
      await fs.rm(filePath, { force: true }).catch((error) => console.warn(`[history] ${error.message}`));
    }
  }
}
