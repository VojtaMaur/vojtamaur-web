import { promises as fs } from "node:fs";
import path from "node:path";

export const HISTORY_FILE = "BUILD_HASH_HISTORY.txt";
const BUILD_TYPES = new Set(["web", "usb", "arweave"]);

export function validateBuildType(buildType) {
  if (!BUILD_TYPES.has(buildType)) {
    throw new Error(`Invalid build type: ${buildType}. Expected web, usb, or arweave.`);
  }
}

export function validateHistory(text) {
  if (text === "") return [];
  if (!text.endsWith("\n")) {
    throw new Error(`${HISTORY_FILE} must end with a newline.`);
  }
  return text.replace(/\r?\n$/, "").split(/\r?\n/).map((line, index) => {
    const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z) \| (web|usb|arweave) \| SHA256 \| ([0-9a-f]{64})$/.exec(line);
    if (!match) throw new Error(`Invalid ${HISTORY_FILE} record on line ${index + 1}.`);
    const [, timestamp, buildType, buildHash] = match;
    const normalized = timestamp.length === 20 ? timestamp.replace("Z", ".000Z") : timestamp;
    if (!Number.isFinite(Date.parse(timestamp)) || new Date(timestamp).toISOString() !== normalized) {
      throw new Error(`Invalid UTC timestamp in ${HISTORY_FILE} on line ${index + 1}.`);
    }
    return { timestamp, buildType, buildHash };
  });
}

export async function readHistory(filePath) {
  const text = await fs.readFile(filePath, "utf8");
  validateHistory(text);
  return text;
}

// Call only after signature verification and successful metadata/status writes.
// The staging directory is already excluded from Git and the source archives.
export async function recordSignedBuild(projectRoot, { history, buildType, buildHash }) {
  validateHistory(history);
  validateBuildType(buildType);
  if (!/^[0-9a-f]{64}$/.test(buildHash)) throw new Error("Invalid signed build hash.");

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
      const next = current.startsWith(history) ? validateHistory(current.slice(history.length))[0] : null;
      if (next?.buildHash === buildHash && next.buildType === buildType) return false;
      throw new Error(`Canonical ${HISTORY_FILE} changed since this build. Rebuild before signing to preserve the chain.`);
    }

    const record = `${new Date().toISOString()} | ${buildType} | SHA256 | ${buildHash}\n`;
    await fs.writeFile(temporaryPath, current + record, "utf8");
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
