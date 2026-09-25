import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { inflateRawSync } from "node:zlib";
import test from "node:test";
import { HISTORY_FILE, validateHistory } from "../scripts/build-hash-history.mjs";

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const gpg = process.env.GPG_BINARY || "gpg";
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const record = (type, hash) => `2026-01-01T00:00:00.000Z | ${type} | SHA256 | ${hash}\n`;

function run(command, args, { cwd, env = {}, success = true } = {}) {
  const result = spawnSync(command, args, {
    cwd, env: { ...process.env, ...env }, encoding: "utf8", windowsHide: true, timeout: 60000,
  });
  assert.ifError(result.error);
  if (success) assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  else assert.notEqual(result.status, 0, "Expected command to fail");
  return result;
}

// Read the central directory so this checks both the ordinary ZIP and JPEG/ZIP.
function archiveEntry(bytes, name) {
  const end = bytes.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  assert.ok(end >= 0, "ZIP end record");
  let cursor = bytes.readUInt32LE(end + 16);
  for (let index = 0; index < bytes.readUInt16LE(end + 10); index++) {
    assert.equal(bytes.readUInt32LE(cursor), 0x02014b50);
    const nameLength = bytes.readUInt16LE(cursor + 28);
    const entryName = bytes.subarray(cursor + 46, cursor + 46 + nameLength).toString();
    if (entryName === name) {
      const local = bytes.readUInt32LE(cursor + 42);
      assert.equal(bytes.readUInt32LE(local), 0x04034b50);
      const start = local + 30 + bytes.readUInt16LE(local + 26) + bytes.readUInt16LE(local + 28);
      return inflateRawSync(bytes.subarray(start, start + bytes.readUInt32LE(cursor + 20)));
    }
    cursor += 46 + nameLength + bytes.readUInt16LE(cursor + 30) + bytes.readUInt16LE(cursor + 32);
  }
  assert.fail(`Missing archive entry: ${name}`);
}

async function temporaryRoot(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "vm-history-"));
  t.after(async () => {
    const resolved = path.resolve(root);
    assert.ok(resolved.startsWith(path.resolve(os.tmpdir()) + path.sep));
    assert.ok(path.basename(resolved).startsWith("vm-history-"));
    await fs.rm(resolved, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  });
  return root;
}

async function fixture(parent, name, fingerprint = "A".repeat(40)) {
  const root = path.join(parent, name);
  for (const dir of ["scripts", "public/keys", "public/images", "source-bundle", "dist"]) {
    await fs.mkdir(path.join(root, dir), { recursive: true });
  }
  for (const script of ["build-hash-history.mjs", "generate-integrity.mjs", "generate-source-bundle.mjs", "sign-build.mjs", "usb-rewrite.mjs"]) {
    await fs.copyFile(path.join(repository, "scripts", script), path.join(root, "scripts", script));
  }
  await fs.copyFile(path.join(repository, "public/images/kurt-godel-rat.jpg"), path.join(root, "public/images/kurt-godel-rat.jpg"));
  await fs.writeFile(path.join(root, "public/keys/vojta-maur-openpgp-fingerprint.txt"), fingerprint);
  for (const name of ["download-assets.py", "README_RECONSTRUCT.md"]) {
    await fs.writeFile(path.join(root, "source-bundle", name), "source bundle fixture\n");
  }
  await fs.writeFile(path.join(root, HISTORY_FILE), "");
  return root;
}

async function build(root, buildType = "web") {
  const before = await fs.readFile(path.join(root, HISTORY_FILE), "utf8");
  await fs.writeFile(path.join(root, "dist/index.html"), `<a href="/${HISTORY_FILE}">${buildType}</a>`);
  run(process.execPath, ["scripts/generate-source-bundle.mjs"], { cwd: root });
  if (buildType === "usb") run(process.execPath, ["scripts/usb-rewrite.mjs"], { cwd: root });
  const args = ["scripts/generate-integrity.mjs", "dist"];
  if (buildType === "arweave") args.push("arweave");
  // Match the USB runners: BUILD_TARGET exists during integrity, not during signing.
  run(process.execPath, args, { cwd: root, env: { BUILD_TARGET: buildType === "usb" ? "usb" : "" } });
  assert.equal(await fs.readFile(path.join(root, HISTORY_FILE), "utf8"), before);
  assert.equal(await fs.readFile(path.join(root, "dist", HISTORY_FILE), "utf8"), before);
  const archives = ["source/vojtamaur-web-source.zip", "images/kurt-godel-rat.jpg"];
  for (const file of archives) {
    assert.equal(archiveEntry(await fs.readFile(path.join(root, "dist", file)), HISTORY_FILE).toString(), before);
  }
  const manifest = await fs.readFile(path.join(root, "dist/SHA256SUMS.txt"), "utf8");
  for (const line of manifest.trimEnd().split("\n")) {
    const [hash, relative] = line.split("  ");
    assert.equal(sha256(await fs.readFile(path.join(root, "dist", relative))), hash);
  }
  assert.ok(manifest.includes(`${sha256(before)}  ${HISTORY_FILE}\n`));
  const metadata = JSON.parse(await fs.readFile(path.join(root, "dist/integrity.json")));
  assert.equal(metadata.buildType, buildType);
  assert.equal(metadata.buildHistoryFile, HISTORY_FILE);
  assert.equal(metadata.buildHash, sha256(manifest));
  assert.ok(!metadata.excluded.includes(HISTORY_FILE));
  assert.equal(metadata.fileCount, manifest.trimEnd().split("\n").length);
  assert.equal(metadata.openPgp.present, false);
  assert.match(await fs.readFile(path.join(root, "dist/SIGNING_STATUS.txt"), "utf8"), /not OpenPGP signed/);
  await assert.rejects(fs.access(path.join(root, "dist/SHA256SUMS.txt.asc")));
  return { history: before, buildHash: metadata.buildHash, manifest };
}

test("history accepts UTC records and rejects malformed or ambiguous rows", () => {
  assert.deepEqual(validateHistory(""), []);
  const valid = record("web", "a".repeat(64));
  assert.equal(validateHistory(valid)[0].buildType, "web");
  assert.equal(validateHistory(valid.replaceAll("\n", "\r\n"))[0].buildHash, "a".repeat(64));
  assert.equal(validateHistory(valid.replace(".000Z", "Z")).length, 1);
  for (const invalid of [valid.trimEnd(), valid + "\n", valid.replace("01-01", "02-30"), valid.replace("web", "unknown"), valid.replace("SHA256", "MD5"), valid.replace("Z |", "+01:00 |"), "# header\n"]) {
    assert.throws(() => validateHistory(invalid));
  }
});

test("unsigned web and USB snapshots preserve source history and source archives", async (t) => {
  const parent = await temporaryRoot(t);
  const root = await fixture(parent, "unsigned");
  await fs.writeFile(path.join(root, HISTORY_FILE), record("web", "a".repeat(64)));
  await build(root, "web");
  await build(root, "usb");
  assert.match(await fs.readFile(path.join(root, "dist/index.html"), "utf8"), /href="\.\/BUILD_HASH_HISTORY.txt"/);
  await fs.writeFile(path.join(root, HISTORY_FILE), "invalid history\n");
  run(process.execPath, ["scripts/generate-source-bundle.mjs"], { cwd: root, success: false });
  assert.equal(await fs.readFile(path.join(root, HISTORY_FILE), "utf8"), "invalid history\n");
});

test("signed history commits only verified builds", async (t) => {
  if (spawnSync(gpg, ["--version"], { windowsHide: true }).status !== 0) {
    t.skip("GnuPG is unavailable; unsigned history tests still run.");
    return;
  }
  const parent = await temporaryRoot(t);
  const keyHome = path.join(parent, "gnupg");
  await fs.mkdir(keyHome, { mode: 0o700 });
  const env = { GNUPGHOME: keyHome, GPG_BINARY: gpg, BUILD_TARGET: "" };
  // No personal keyring, prompt, network operation, or production history is used.
  run(gpg, ["--batch", "--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key", "Build History Test <build-history@example.invalid>", "ed25519", "sign", "0"], { env });
  const listed = run(gpg, ["--batch", "--with-colons", "--list-secret-keys"], { env });
  const fingerprint = listed.stdout.split(/\r?\n/).find(line => line.startsWith("fpr:")).split(":")[9];
  t.after(() => {
    const gpgconf = path.isAbsolute(gpg) ? path.join(path.dirname(gpg), process.platform === "win32" ? "gpgconf.exe" : "gpgconf") : "gpgconf";
    spawnSync(gpgconf, ["--homedir", keyHome, "--kill", "gpg-agent"], { windowsHide: true });
  });

  // Fault injection at the external process boundary; successful paths use real GPG.
  const preload = path.join(parent, "gpg-fault.mjs");
  await fs.writeFile(preload, [
    'import childProcess from "node:child_process";',
    'import { syncBuiltinESMExports } from "node:module";',
    'const original = childProcess.spawnSync;',
    'childProcess.spawnSync = (command, args, options) => {',
    '  if (args.includes(process.env.TEST_GPG_FAIL)) return { status: 1 };',
    '  return original(command, args, options);',
    '};',
    'syncBuiltinESMExports();',
  ].join("\n"));
  function sign(root, { failure = null, success = true, extraEnv = {} } = {}) {
    return run(process.execPath, ["--import", pathToFileURL(preload).href, "scripts/sign-build.mjs"], {
      cwd: root, env: { ...env, TEST_GPG_FAIL: failure ?? "", ...extraEnv }, success,
    });
  }
  async function assertFailed(root, unchanged) {
    assert.equal(await fs.readFile(path.join(root, HISTORY_FILE), "utf8"), unchanged);
    await assert.rejects(fs.access(path.join(root, "dist/SHA256SUMS.txt.asc")));
    const metadata = JSON.parse(await fs.readFile(path.join(root, "dist/integrity.json")));
    assert.equal(metadata.openPgp.present, false);
    assert.ok(metadata.openPgp.error);
  }

  await t.test("web -> USB -> Arweave, inherited snapshots and idempotent re-signing", async () => {
    const root = await fixture(parent, "chain", fingerprint);
    let count = 0;
    for (const type of ["web", "usb", "arweave"]) {
      const built = await build(root, type);
      const zipBefore = await fs.readFile(path.join(root, "dist/source/vojtamaur-web-source.zip"));
      sign(root);
      const canonical = await fs.readFile(path.join(root, HISTORY_FILE), "utf8");
      const records = validateHistory(canonical);
      assert.equal(records.length, ++count);
      assert.equal(records.at(-1).buildHash, built.buildHash);
      assert.equal(records.at(-1).buildType, type);
      assert.equal(await fs.readFile(path.join(root, "dist", HISTORY_FILE), "utf8"), built.history);
      assert.equal(await fs.readFile(path.join(root, "dist/SHA256SUMS.txt"), "utf8"), built.manifest);
      assert.deepEqual(await fs.readFile(path.join(root, "dist/source/vojtamaur-web-source.zip")), zipBefore);
      run(gpg, ["--verify", "dist/SHA256SUMS.txt.asc", "dist/SHA256SUMS.txt"], { cwd: root, env });
      const metadata = JSON.parse(await fs.readFile(path.join(root, "dist/integrity.json")));
      assert.equal(metadata.openPgp.present, true);
      assert.equal(metadata.openPgp.fingerprint.replaceAll(" ", ""), fingerprint);
      assert.match(await fs.readFile(path.join(root, "dist/SIGNING_STATUS.txt"), "utf8"), /This build is OpenPGP signed/);
      assert.deepEqual((await fs.readdir(path.join(root, "dist"))).filter(name => name.endsWith(".asc")), ["SHA256SUMS.txt.asc"]);
      sign(root);
      assert.equal(await fs.readFile(path.join(root, HISTORY_FILE), "utf8"), canonical);
    }
  });

  for (const failure of ["--detach-sign", "--verify"]) {
    await t.test(`GPG failure at ${failure} leaves no history entry or signature`, async () => {
      const root = await fixture(parent, `failure-${failure}`, fingerprint);
      const built = await build(root, "usb");
      sign(root, { failure, success: false });
      await assertFailed(root, built.history);
      assert.match(await fs.readFile(path.join(root, "dist/SIGNING_STATUS.txt"), "utf8"), /not OpenPGP signed/);
    });
  }

  for (const failure of ["missing-key-home", "changed-history", "changed-build-hash", "missing-manifest-entry", "stale-canonical-history", "history-lock", "status-write"]) {
    await t.test(`${failure} cannot change canonical history`, async () => {
      const root = await fixture(parent, failure, fingerprint);
      const built = await build(root);
      let canonical = built.history;
      const extraEnv = {};
      if (failure === "missing-key-home") extraEnv.GNUPGHOME = "";
      if (failure === "changed-history") await fs.writeFile(path.join(root, "dist", HISTORY_FILE), record("web", "b".repeat(64)));
      if (failure === "changed-build-hash") await fs.writeFile(path.join(root, "dist/BUILD_SHA256.txt"), `${"0".repeat(64)}  SHA256SUMS.txt\n`);
      if (failure === "missing-manifest-entry") {
        const manifest = built.manifest.split("\n").filter(line => !line.endsWith(`  ${HISTORY_FILE}`)).join("\n");
        await fs.writeFile(path.join(root, "dist/SHA256SUMS.txt"), manifest);
        await fs.writeFile(path.join(root, "dist/BUILD_SHA256.txt"), `${sha256(manifest)}  SHA256SUMS.txt\n`);
      }
      if (failure === "stale-canonical-history") {
        canonical = record("usb", "b".repeat(64));
        await fs.writeFile(path.join(root, HISTORY_FILE), canonical);
      }
      if (failure === "history-lock") {
        await fs.mkdir(path.join(root, ".source-bundle-staging"));
        await fs.writeFile(path.join(root, ".source-bundle-staging/build-hash-history.lock"), "");
      }
      if (failure === "status-write") {
        await fs.unlink(path.join(root, "dist/SIGNING_STATUS.txt"));
        await fs.mkdir(path.join(root, "dist/SIGNING_STATUS.txt"));
      }
      sign(root, { success: false, extraEnv });
      await assertFailed(root, canonical);
    });
  }
});
