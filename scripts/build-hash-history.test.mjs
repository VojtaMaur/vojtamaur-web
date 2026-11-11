import test from "node:test";
import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { validateHistory, recordSignedBuild, recordSignedBuilds, HISTORY_FILE, HISTORY_HEADER, formatHistoryRecord } from "../scripts/build-hash-history.mjs";
import { generateIntegrity } from "../scripts/generate-integrity.mjs";
import { parseVerifiedFingerprint } from "../scripts/sign-build.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const fingerprint = "A".repeat(40);
const legacy = `2026-01-01T00:00:00.000Z | web | SHA256 | ${"1".repeat(64)}\n`;
const hash = (data) => createHash("sha256").update(data).digest("hex");
const build = (buildType, buildHash, history = legacy) => ({ history, buildType, buildHash, fingerprint });
async function temporary(t) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "vm-"));
  t.after(async () => {
    const home = path.join(dir, "g");
    try {
      await fs.access(home);
      spawnSync("gpgconf", ["--homedir", home, "--kill", "gpg-agent"], { windowsHide: true });
    } catch {}
    await fs.rm(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  });
  return dir;
}

test("legacy histories remain readable; new rows validate full fingerprints and Gemini type", () => {
  assert.equal(validateHistory(legacy)[0].fingerprint, null);
  assert.equal(validateHistory(legacy + `2026-01-02T00:00:00Z | gemini | SHA256 | ${"2".repeat(64)} | ${fingerprint}\n`)[1].fingerprint, fingerprint);
  assert.throws(() => validateHistory(legacy.trimEnd()), /newline/);
  assert.throws(() => validateHistory(legacy.replace("2026-01-01", "2026-02-30")), /timestamp/);
  assert.throws(() => validateHistory(legacy.trimEnd() + " | ABCD\n"), /Invalid/);
});

test("labelled history keeps every separator aligned across types and timestamp formats", () => {
  const records = ["web", "usb", "arweave", "gemini"].map((buildType, index) => ({
    timestamp: index % 2 ? "2026-01-01T00:00:00Z" : "2026-01-01T00:00:00.000Z",
    buildType, buildHash: String(index + 1).repeat(64), fingerprint,
  }));
  const text = HISTORY_HEADER + "\n" + records.map(formatHistoryRecord).join("");
  assert.deepEqual(validateHistory(text), records);
  const positions = line => [...line.matchAll(/\|/g)].map(match => match.index);
  const lines = text.trimEnd().split("\n");
  for (const line of lines) assert.deepEqual(positions(line), positions(HISTORY_HEADER));
  assert.deepEqual(validateHistory(HISTORY_HEADER + "\n"), []);
  assert.throws(() => validateHistory(text + HISTORY_HEADER + "\n"), /Invalid/);
});

test("new histories get one header and subsequent appends preserve it", async (t) => {
  const dir = await temporary(t);
  const historyPath = path.join(dir, HISTORY_FILE);
  await fs.writeFile(historyPath, "");
  const first = build("web", "2".repeat(64), "");
  assert.equal(await recordSignedBuild(dir, first), true);
  let history = await fs.readFile(historyPath, "utf8");
  assert.ok(history.startsWith(HISTORY_HEADER + "\n"));
  assert.equal(validateHistory(history).length, 1);
  assert.equal(await recordSignedBuild(dir, first), false);
  await recordSignedBuild(dir, build("gemini", "3".repeat(64), history));
  const updated = await fs.readFile(historyPath, "utf8");
  assert.ok(updated.startsWith(history));
  assert.equal(updated.split(HISTORY_HEADER).length - 1, 1);
  assert.equal(validateHistory(updated).length, 2);
});

test("batch appends both builds atomically, keeps their snapshot, and is idempotent", async (t) => {
  const dir = await temporary(t);
  const historyPath = path.join(dir, HISTORY_FILE);
  await fs.writeFile(historyPath, legacy);
  const builds = [build("web", "2".repeat(64)), build("gemini", "3".repeat(64))];
  assert.equal(await recordSignedBuilds(dir, builds), true);
  const result = await fs.readFile(historyPath, "utf8");
  assert.ok(result.startsWith(legacy));
  const rows = validateHistory(result);
  assert.deepEqual(rows.slice(1).map((row) => row.buildType), ["web", "gemini"]);
  assert.equal(rows[1].timestamp, rows[2].timestamp);
  assert.ok(rows.slice(1).every((row) => row.fingerprint === fingerprint));
  assert.equal(await recordSignedBuilds(dir, builds), false);
  assert.equal(await fs.readFile(historyPath, "utf8"), result);
  await assert.rejects(recordSignedBuild(dir, build("web", "4".repeat(64))), /changed since/);
  assert.equal(await fs.readFile(historyPath, "utf8"), result);
});

test("conflicts, mixed snapshots, missing fingerprints and lock contention do not change history", async (t) => {
  const dir = await temporary(t);
  const historyPath = path.join(dir, HISTORY_FILE);
  await fs.writeFile(historyPath, legacy);
  await assert.rejects(recordSignedBuilds(dir, [build("web", "2".repeat(64)), build("gemini", "3".repeat(64), "")]), /same history/);
  await assert.rejects(recordSignedBuild(dir, { ...build("web", "2".repeat(64)), fingerprint: null }), /fingerprint/);
  await assert.rejects(recordSignedBuilds(dir, [build("web", "2".repeat(64)), build("web", "2".repeat(64))]), /Duplicate/);
  const lockDir = path.join(dir, ".source-bundle-staging");
  await fs.mkdir(lockDir);
  await fs.writeFile(path.join(lockDir, "build-hash-history.lock"), "");
  await assert.rejects(recordSignedBuild(dir, build("gemini", "2".repeat(64))), /locked/);
  assert.equal(await fs.readFile(historyPath, "utf8"), legacy);
});

test("single-output web, USB, Arweave and Gemini records retain their build types", async (t) => {
  const dir = await temporary(t);
  let history = legacy;
  await fs.writeFile(path.join(dir, HISTORY_FILE), history);
  for (const [index, type] of ["web", "usb", "arweave", "gemini"].entries()) {
    await recordSignedBuild(dir, build(type, String(index + 2).repeat(64), history));
    history = await fs.readFile(path.join(dir, HISTORY_FILE), "utf8");
    assert.equal(validateHistory(history).at(-1).buildType, type);
    assert.equal(validateHistory(history).at(-1).fingerprint, fingerprint);
  }
});

test("verified primary key and actual signing subkey come from VALIDSIG", () => {
  const subkey = "B".repeat(40);
  const status = `[GNUPG:] VALIDSIG ${subkey} 2026-01-01 1767225600 0 4 0 22 8 00 ${fingerprint}\n`;
  assert.deepEqual(parseVerifiedFingerprint(status, fingerprint), { fingerprint, signingFingerprint: subkey });
  assert.throws(() => parseVerifiedFingerprint(status, "C".repeat(40)), /expected primary key/);
  assert.throws(() => parseVerifiedFingerprint("[GNUPG:] GOODSIG 123 Example\n", fingerprint), /exactly one/);
  assert.throws(() => parseVerifiedFingerprint(status + status, fingerprint), /exactly one/);
});

test("Gemini integrity covers its own Gemtext and Gopher maps and removes an inherited signature", async (t) => {
  const dir = await temporary(t);
  await fs.writeFile(path.join(dir, HISTORY_FILE), legacy);
  await fs.writeFile(path.join(dir, "index.gmi"), "# Capsule\n");
  await fs.writeFile(path.join(dir, "gophermap"), "iCapsule\tfake\t(NULL)\t0\n");
  await fs.writeFile(path.join(dir, "SHA256SUMS.txt.asc"), "old web signature");
  await generateIntegrity(dir, "gemini");
  const manifest = await fs.readFile(path.join(dir, "SHA256SUMS.txt"), "utf8");
  for (const name of [HISTORY_FILE, "index.gmi", "gophermap"]) {
    assert.ok(manifest.includes(`${hash(await fs.readFile(path.join(dir, name)))}  ${name}\n`));
  }
  assert.equal((await fs.readFile(path.join(dir, "BUILD_SHA256.txt"), "utf8")).trim(), hash(manifest) + "  SHA256SUMS.txt");
  const metadata = JSON.parse(await fs.readFile(path.join(dir, "integrity.json"), "utf8"));
  assert.equal(metadata.buildType, "gemini");
  assert.equal(metadata.openPgp.present, false);
  await assert.rejects(fs.access(path.join(dir, "SHA256SUMS.txt.asc")));
});

test("capsule generator creates independent integrity with custom paths and preserves the source snapshot", async (t) => {
  const dir = await temporary(t);
  const web = path.join(dir, "web");
  const capsule = path.join(dir, "custom-gemini");
  const content = path.join(dir, "posts");
  await fs.mkdir(path.join(web, "en"), { recursive: true });
  await fs.mkdir(path.join(web, "keys"));
  await fs.mkdir(content);
  for (const name of ["index.html", "en/index.html"]) {
    await fs.writeFile(path.join(web, name), '<html><body><header><div class="site-header__motto">Test</div></header><main>Example</main></body></html>');
  }
  await fs.writeFile(path.join(web, HISTORY_FILE), legacy);
  await fs.writeFile(path.join(web, "keys", "example.asc"), "public test material");
  await fs.writeFile(path.join(web, "SHA256SUMS.txt.asc"), "web-only signature");
  await fs.writeFile(path.join(web, "SHA256SUMS.txt"), "web-only manifest");
  const args = [path.join(root, "scripts", "generate-gemini-capsule.mjs"), "--dist", web, "--output", capsule, "--content", content];
  let result = spawnSync(process.execPath, args, { cwd: dir, encoding: "utf8", windowsHide: true });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  const manifest = await fs.readFile(path.join(capsule, "SHA256SUMS.txt"), "utf8");
  assert.notEqual(manifest, "web-only manifest");
  for (const line of manifest.trimEnd().split("\n")) {
    const [, digest, name] = /^([0-9a-f]{64})  (.+)$/.exec(line);
    assert.equal(hash(await fs.readFile(path.join(capsule, name))), digest, name);
  }
  assert.match(manifest, /  index\.gmi\n/);
  assert.match(manifest, /  gophermap\n/);
  assert.match(manifest, /  keys\/example\.asc\n/);
  assert.equal(await fs.readFile(path.join(capsule, HISTORY_FILE), "utf8"), legacy);
  assert.equal(JSON.parse(await fs.readFile(path.join(capsule, "integrity.json"), "utf8")).buildType, "gemini");
  await assert.rejects(fs.access(path.join(capsule, "SHA256SUMS.txt.asc")));
  await fs.writeFile(path.join(capsule, "SHA256SUMS.txt.asc"), "stale signature");
  result = spawnSync(process.execPath, args, { cwd: dir, encoding: "utf8", windowsHide: true });
  assert.equal(result.status, 0, result.stderr);
  await assert.rejects(fs.access(path.join(capsule, "SHA256SUMS.txt.asc")));
  await fs.rm(path.join(web, HISTORY_FILE));
  result = spawnSync(process.execPath, args, { cwd: dir, encoding: "utf8", windowsHide: true });
  assert.notEqual(result.status, 0);
  assert.equal(await fs.readFile(path.join(capsule, HISTORY_FILE), "utf8"), legacy);
});

test("Czech and English integrity links stay inside the capsule for Gemini and Gopher", async (t) => {
  const dir = await temporary(t);
  const web = path.join(dir, "web");
  const capsule = path.join(dir, "link-test-gemini");
  const content = path.join(dir, "posts");
  const assets = ["SHA256SUMS.txt", "SHA256SUMS.txt.asc", "BUILD_SHA256.txt", HISTORY_FILE,
    "integrity.json", "SIGNING_STATUS.txt", "keys/vojta-maur-openpgp.asc", "ALL_POSTS.txt", "ARCHIVE.txt"];
  await fs.mkdir(path.join(web, "keys"), { recursive: true });
  await fs.mkdir(content);
  await fs.writeFile(path.join(content, "example.mdx"), "---\nslug: example\ntitle: Example\nsection: volna-tvorba\n---\n");
  await fs.writeFile(path.join(web, HISTORY_FILE), legacy);
  for (const file of ["ALL_POSTS.txt", "ARCHIVE.txt", "keys/vojta-maur-openpgp.asc"]) {
    await fs.writeFile(path.join(web, file), "Test asset\n");
  }
  const article = '<html><body><main><article><h1>Example</h1>'
    + assets.map(file => `<p><a href="/${file}">${file}</a></p><p><a href="https://vojtamaur.cz/${file}?download=1#identity">Absolute ${file}</a></p>`).join("")
    + '<p><a href="https://other.example/SIGNING_STATUS.txt">External status</a></p>'
    + '<p><a href="/files/guide.pdf">External media</a></p>'
    + '<p><a href="/NOT_IN_CAPSULE.txt">Unknown file</a></p>'
    + '</article></main></body></html>';
  for (const lang of ["cs", "en"]) {
    const directory = path.join(web, ...(lang === "en" ? ["en", "example"] : ["example"]));
    await fs.mkdir(directory, { recursive: true });
    await fs.writeFile(path.join(directory, "index.html"), article);
  }
  const result = spawnSync(process.execPath, [path.join(root, "scripts", "generate-gemini-capsule.mjs"),
    "--dist", web, "--output", capsule, "--content", content], { cwd: dir, encoding: "utf8", windowsHide: true });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  for (const [articlePath, prefix] of [["personal-work/example.gmi", "../"], ["cs/volna-tvorba/example.gmi", "../../"]]) {
    const gemtext = await fs.readFile(path.join(capsule, articlePath), "utf8");
    const links = [...gemtext.matchAll(/^=> (\S+)/gm)].map(match => match[1]);
    for (const file of assets) {
      assert.ok(links.includes(prefix + file), `${articlePath}: ${file} must be local`);
      assert.ok(links.includes(prefix + file + "?download=1#identity"), `${articlePath}: absolute same-site link must be local`);
      assert.ok(!links.some(link => link.startsWith("https://vojtamaur.cz/" + file)));
      for (const base of ["gemini://envs.net/~vojtamaur/", "gopher://envs.net/0/~vojtamaur/"]) {
        assert.equal(new URL(prefix + file, base + articlePath).href, base + file);
      }
      if (file !== "SHA256SUMS.txt.asc") await fs.access(path.join(capsule, file));
    }
    assert.ok(links.includes("https://other.example/SIGNING_STATUS.txt"));
    assert.ok(links.includes("https://vojtamaur.cz/files/guide.pdf"));
    assert.ok(links.includes("https://vojtamaur.cz/NOT_IN_CAPSULE.txt"));
  }
});

const gpg = process.env.GPG_BINARY || "gpg";
const hasGpg = spawnSync(gpg, ["--version"], { windowsHide: true }).status === 0;

test("real OpenPGP: signs both outputs, records verified fingerprints, and rolls back on a second-signature failure", { skip: !hasGpg, timeout: 120000 }, async (t) => {
  const dir = await temporary(t);
  const gnupgHome = path.join(dir, "g");
  await fs.mkdir(gnupgHome);
  const env = { ...process.env, GNUPGHOME: gnupgHome, GPG_BINARY: gpg };
  const run = (args) => spawnSync(gpg, ["--homedir", gnupgHome, ...args], { env, encoding: "utf8", windowsHide: true });
  let result = run(["--batch", "--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key", "Build signing test <test@example.invalid>", "ed25519", "cert", "0"]);
  assert.equal(result.status, 0, result.stderr);
  const primary = run(["--with-colons", "--list-secret-keys"]).stdout.split(/\r?\n/).find((line) => line.startsWith("fpr:")).split(":")[9];
  result = run(["--batch", "--pinentry-mode", "loopback", "--passphrase", "", "--quick-add-key", primary, "ed25519", "sign", "0"]);
  assert.equal(result.status, 0, result.stderr);
  const snapshot = HISTORY_HEADER + "\n" + formatHistoryRecord({ ...validateHistory(legacy)[0], fingerprint: primary });
  await fs.mkdir(path.join(dir, "public", "keys"), { recursive: true });
  await fs.writeFile(path.join(dir, "public", "keys", "vojta-maur-openpgp-fingerprint.txt"), primary);
  await fs.writeFile(path.join(dir, HISTORY_FILE), snapshot);
  await fs.mkdir(path.join(dir, "scripts"));
  for (const file of ["sign-build.mjs", "build-hash-history.mjs"]) {
    await fs.copyFile(path.join(root, "scripts", file), path.join(dir, "scripts", file));
  }
  for (const name of ["dist", "dist-gemini"]) {
    const output = path.join(dir, name);
    await fs.mkdir(output);
    await fs.writeFile(path.join(output, HISTORY_FILE), snapshot);
    await fs.writeFile(path.join(output, "index.txt"), name);
    await generateIntegrity(output, name === "dist" ? "web" : "gemini");
  }
  const sign = (customEnv = {}) => spawnSync(process.execPath, [path.join(dir, "scripts", "sign-build.mjs"), "dist", "dist-gemini"], {
    cwd: dir, env: { ...env, ...customEnv }, encoding: "utf8", windowsHide: true,
  });
  result = sign();
  assert.equal(result.status, 0, result.stdout + result.stderr);
  const recordedHistory = await fs.readFile(path.join(dir, HISTORY_FILE), "utf8");
  const rows = validateHistory(recordedHistory);
  assert.deepEqual(rows.slice(1).map((row) => row.buildType), ["web", "gemini"]);
  assert.ok(rows.slice(1).every((row) => row.fingerprint === primary));
  for (const name of ["dist", "dist-gemini"]) {
    const output = path.join(dir, name);
    result = run(["--batch", "--verify", path.join(output, "SHA256SUMS.txt.asc"), path.join(output, "SHA256SUMS.txt")]);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(await fs.readFile(path.join(output, HISTORY_FILE), "utf8"), snapshot);
    const metadata = JSON.parse(await fs.readFile(path.join(output, "integrity.json"), "utf8"));
    assert.equal(metadata.openPgp.fingerprint.replace(/\s/g, ""), primary);
    assert.notEqual(metadata.openPgp.signingFingerprint.replace(/\s/g, ""), primary);
  }
  result = sign();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(await fs.readFile(path.join(dir, HISTORY_FILE), "utf8"), recordedHistory);

  // New outputs share the latest history; a failure on the second target must
  // remove both attempted signatures and leave both new records uncommitted.
  for (const name of ["dist", "dist-gemini"]) {
    const output = path.join(dir, name);
    await fs.writeFile(path.join(output, HISTORY_FILE), recordedHistory);
    await generateIntegrity(output, name === "dist" ? "web" : "gemini");
  }
  const preload = path.join(dir, "fail-second.cjs");
  await fs.writeFile(preload, `const cp = require('node:child_process');\nconst original = cp.spawnSync;\ncp.spawnSync = function(command,args,options) { if (args?.includes('--detach-sign') && args.some(a => a.includes('dist-gemini'))) return {status:7}; return original(command,args,options); };\nrequire('node:module').syncBuiltinESMExports();\n`);
  result = sign({ NODE_OPTIONS: `--require="${preload.split(path.sep).join("/")}"` });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /exited with status 7/, result.stdout + result.stderr);
  assert.equal(await fs.readFile(path.join(dir, HISTORY_FILE), "utf8"), recordedHistory);
  for (const name of ["dist", "dist-gemini"]) {
    await assert.rejects(fs.access(path.join(dir, name, "SHA256SUMS.txt.asc")));
    const metadata = JSON.parse(await fs.readFile(path.join(dir, name, "integrity.json"), "utf8"));
    assert.equal(metadata.openPgp.present, false);
  }

  // Another signer advances history after both signatures verify. Preserve its
  // record and reject this stale batch without leaving misleading signatures.
  const externalRecord = `2026-01-02T00:00:00.000Z | usb | SHA256 | ${"D".toLowerCase().repeat(64)} | ${primary}\n`;
  await fs.writeFile(preload, `const cp = require('node:child_process');\nconst fs = require('node:fs');\nconst original = cp.spawnSync;\ncp.spawnSync = function(command,args,options) { const r = original(command,args,options); if (args?.includes('--verify') && args.some(a => a.includes('dist-gemini'))) fs.appendFileSync(${JSON.stringify(path.join(dir, HISTORY_FILE))}, ${JSON.stringify(externalRecord)}); return r; };\nrequire('node:module').syncBuiltinESMExports();\n`);
  result = sign({ NODE_OPTIONS: `--require="${preload.split(path.sep).join("/")}"` });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /changed since/, result.stdout + result.stderr);
  assert.equal(await fs.readFile(path.join(dir, HISTORY_FILE), "utf8"), recordedHistory + externalRecord);
  for (const name of ["dist", "dist-gemini"]) {
    await assert.rejects(fs.access(path.join(dir, name, "SHA256SUMS.txt.asc")));
  }
});
