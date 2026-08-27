import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { deflateRawSync } from "node:zlib";

const ROOT = process.cwd();
const TARGET_DIR = path.resolve(process.argv[2] ?? "dist");
const OUTPUT_RELATIVE = "source/vojtamaur-web-source.zip";
const OUTPUT_PATH = path.join(TARGET_DIR, ...OUTPUT_RELATIVE.split("/"));
const CARRIER_SOURCE_RELATIVE = "public/images/kurt-godel-rat.jpg";
const CARRIER_OUTPUT_RELATIVE = "images/kurt-godel-rat.jpg";
const CARRIER_SOURCE_PATH = path.join(ROOT, ...CARRIER_SOURCE_RELATIVE.split("/"));
const CARRIER_OUTPUT_PATH = path.join(TARGET_DIR, ...CARRIER_OUTPUT_RELATIVE.split("/"));
const CARRIER_SOURCE_SHA256 = "c126fd28f83894b167c66ac2515c8d677c49d97acbc77f7212b15cbcace4d8a4";

// The clean carrier must be reconstructable without downloading the final
// polyglot, whose hash would depend on the ZIP that contains the manifest.
const BUNDLED_PUBLIC_FILES = new Set([
  CARRIER_SOURCE_RELATIVE,
]);

const ASSET_DIRS = [
  "public/images",
  "public/files",
];

const BUNDLED_PUBLIC_DIRS = [
  "public/demos",
];

const MIRROR_BASES = [
  "https://vojtamaur.cz",
  "https://vojtamaur.github.io/vojtamaur-web",
  "https://vojtamaur-web.pages.dev",
  "https://vojtamaur.netlify.app",
  "https://vojtamaur-web.vercel.app",
  "https://vojtamaur-977c1.web.app",
  "https://vojtamaur-977c1.firebaseapp.com",
  "https://vojtamaur-web-a22b59.gitlab.io",
  "https://vojta_maur.codeberg.page",
  "https://vojtamaur.neocities.org",
  "https://vojtamaur.vojtam.chatgpt.site",
  "https://vojtamaur.envs.net",
  "https://db6beycsnxhli2vxsahgn3ajpsi6qv5alttkr4d3sfwrj7uurqfq.ardrive.net/GHwSYFJtzrRqt5AOZuwJfJHoV6Bc5qjwe5FtFP6UjAs",
  "https://arweave.net/GHwSYFJtzrRqt5AOZuwJfJHoV6Bc5qjwe5FtFP6UjAs",
];

const EXCLUDED_ROOT_DIRS = new Set([
  ".astro",
  ".git",
  ".idea",
  ".source-bundle-staging",
  ".vscode",
  "dist",
  "dist-arweave",
  "dist-gemini",
  "exports",
  "node_modules",
  "source-bundle",
]);

const EXCLUDED_FILENAMES = new Set([
  ".DS_Store",
  "Thumbs.db",
]);

const EXCLUDED_FILE_PATTERNS = [
  /^\.env(?:\..*)?$/,
  /^npm-debug\.log.*$/,
  /^yarn-debug\.log.*$/,
  /^yarn-error\.log.*$/,
  /^pnpm-debug\.log.*$/,
  /^metadata-report.*\.json$/,
  /^vojtamaur-web-source.*\.zip$/,
];

const TEMPLATE_FILES = [
  {
    sources: [
      "source-bundle/download-assets.py",
      "download-assets.py",
    ],
    zipPaths: [
      "download-assets.py",
      "source-bundle/download-assets.py",
    ],
  },
  {
    sources: [
      "source-bundle/README_RECONSTRUCT.md",
      "README_RECONSTRUCT.md",
    ],
    zipPaths: [
      "README_RECONSTRUCT.md",
      "source-bundle/README_RECONSTRUCT.md",
    ],
  },
];

const ZIP_UTF8_FLAG = 0x0800;
const ZIP_FIXED_TIME = 0;
const ZIP_FIXED_DATE = (1 << 5) | 1; // 1980-01-01

function toPosix(filePath) {
  return filePath.split(path.sep).join("/");
}

const TARGET_RELATIVE_FROM_ROOT = toPosix(path.relative(ROOT, TARGET_DIR));
const TARGET_IS_INSIDE_ROOT = (
  TARGET_RELATIVE_FROM_ROOT !== "" &&
  TARGET_RELATIVE_FROM_ROOT !== "." &&
  !TARGET_RELATIVE_FROM_ROOT.startsWith("../") &&
  !path.isAbsolute(TARGET_RELATIVE_FROM_ROOT)
);

function normalizeRel(filePath) {
  return toPosix(path.relative(ROOT, filePath));
}

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function encodeWebPath(webPath) {
  return webPath
    .split("/")
    .map((segment, index) => index === 0 ? "" : encodeURIComponent(segment))
    .join("/");
}

function webPathForPublicFile(relativePath) {
  if (!relativePath.startsWith("public/")) {
    throw new Error(`Not a public file path: ${relativePath}`);
  }

  return `/${relativePath.slice("public/".length)}`;
}

function urlsForWebPath(webPath) {
  const encodedPath = encodeWebPath(webPath);

  return MIRROR_BASES.map((base) => {
    const cleanBase = base.replace(/\/+$/, "");
    return `${cleanBase}${encodedPath}`;
  });
}

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

function isExcludedByPattern(name) {
  return EXCLUDED_FILE_PATTERNS.some((pattern) => pattern.test(name));
}

function isAssetPath(relativePath) {
  return ASSET_DIRS.some((dir) => {
    return relativePath === dir || relativePath.startsWith(`${dir}/`);
  });
}

function shouldExclude(relativePath) {
  if (!relativePath || relativePath === ".") return true;

  if (
    TARGET_IS_INSIDE_ROOT &&
    (
      relativePath === TARGET_RELATIVE_FROM_ROOT ||
      relativePath.startsWith(`${TARGET_RELATIVE_FROM_ROOT}/`)
    )
  ) {
    return true;
  }

  const parts = relativePath.split("/");
  const first = parts[0];
  const name = parts.at(-1);

  if (EXCLUDED_ROOT_DIRS.has(first)) return true;
  if (EXCLUDED_FILENAMES.has(name)) return true;
  if (isExcludedByPattern(name)) return true;
  if (isAssetPath(relativePath)) return true;

  return false;
}

async function walk(dir, rootForRelative = ROOT) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  entries.sort((a, b) => a.name.localeCompare(b.name));

  const files = [];

  for (const entry of entries) {
    const absolutePath = path.join(dir, entry.name);
    const relativePath = toPosix(path.relative(rootForRelative, absolutePath));

    if (shouldExclude(relativePath)) {
      continue;
    }

    if (entry.isDirectory()) {
      files.push(...await walk(absolutePath, rootForRelative));
    } else if (entry.isFile()) {
      files.push({
        absolutePath,
        zipPath: relativePath,
      });
    }
  }

  return files;
}

async function walkExistingDir(relativeDir) {
  const absoluteDir = path.join(ROOT, ...relativeDir.split("/"));

  if (!await exists(absoluteDir)) {
    return [];
  }

  const entries = await fs.readdir(absoluteDir, { withFileTypes: true });
  entries.sort((a, b) => a.name.localeCompare(b.name));

  const files = [];

  async function visit(dir) {
    const children = await fs.readdir(dir, { withFileTypes: true });
    children.sort((a, b) => a.name.localeCompare(b.name));

    for (const child of children) {
      const absolutePath = path.join(dir, child.name);
      const relativePath = normalizeRel(absolutePath);
      const name = child.name;

      if (EXCLUDED_FILENAMES.has(name) || isExcludedByPattern(name)) {
        continue;
      }

      if (child.isDirectory()) {
        await visit(absolutePath);
      } else if (child.isFile()) {
        files.push({
          absolutePath,
          relativePath,
        });
      }
    }
  }

  await visit(absoluteDir);
  return files;
}

async function buildAssetManifest() {
  const files = [];

  for (const dir of ASSET_DIRS) {
    files.push(...await walkExistingDir(dir));
  }

  files.sort((a, b) => a.relativePath.localeCompare(b.relativePath));

  const manifestFiles = [];
  const shaLines = [];

  for (const file of files) {
    if (BUNDLED_PUBLIC_FILES.has(file.relativePath)) {
      continue;
    }

    const data = await fs.readFile(file.absolutePath);
    const hash = sha256(data);
    const stat = await fs.stat(file.absolutePath);
    const webPath = webPathForPublicFile(file.relativePath);

    manifestFiles.push({
      path: file.relativePath,
      web_path: webPath,
      size: stat.size,
      sha256: hash,
      urls: urlsForWebPath(webPath),
    });

    shaLines.push(`${hash}  ${file.relativePath}`);
  }

  const manifest = {
    version: 1,
    kind: "vojtamaur-source-bundle-assets",
    generatedBy: "scripts/generate-source-bundle.mjs",
    minimumPython: "3.9",
    assetDirectories: ASSET_DIRS,
    bundledPublicDirectories: BUNDLED_PUBLIC_DIRS,
    bundledPublicFiles: [...BUNDLED_PUBLIC_FILES].sort(),
    mirrors: MIRROR_BASES,
    files: manifestFiles,
  };

  return {
    manifestText: `${JSON.stringify(manifest, null, 2)}\n`,
    shaText: `${shaLines.join("\n")}${shaLines.length ? "\n" : ""}`,
    fileCount: manifestFiles.length,
    totalBytes: manifestFiles.reduce((sum, file) => sum + file.size, 0),
  };
}

async function collectZipEntries() {
  const entries = [];

  const sourceFiles = await walk(ROOT);
  sourceFiles.sort((a, b) => a.zipPath.localeCompare(b.zipPath));

  for (const file of sourceFiles) {
    entries.push({
      zipPath: file.zipPath,
      data: await fs.readFile(file.absolutePath),
    });
  }

  for (const relativePath of [...BUNDLED_PUBLIC_FILES].sort()) {
    const absolutePath = path.join(ROOT, ...relativePath.split("/"));

    if (!await exists(absolutePath)) {
      throw new Error(`Missing bundled public file: ${relativePath}`);
    }

    entries.push({
      zipPath: relativePath,
      data: await fs.readFile(absolutePath),
    });
  }

  for (const template of TEMPLATE_FILES) {
    let foundPath = null;

    for (const source of template.sources) {
      const absolutePath = path.join(ROOT, ...source.split("/"));

      if (await exists(absolutePath)) {
        foundPath = absolutePath;
        break;
      }
    }

    if (!foundPath) {
      throw new Error(`Missing source bundle template: ${template.sources.join(" or ")}`);
    }

    const data = await fs.readFile(foundPath);

    for (const zipPath of template.zipPaths) {
      if (!entries.some((entry) => entry.zipPath === zipPath)) {
        entries.push({
          zipPath,
          data,
        });
      }
    }
  }

  const assetManifest = await buildAssetManifest();

  entries.push({
    zipPath: "MEDIA_MANIFEST.json",
    data: Buffer.from(assetManifest.manifestText, "utf8"),
  });

  entries.push({
    zipPath: "MEDIA_SHA256SUMS.txt",
    data: Buffer.from(assetManifest.shaText, "utf8"),
  });

  entries.sort((a, b) => a.zipPath.localeCompare(b.zipPath));

  return {
    entries,
    assetManifest,
  };
}

const CRC_TABLE = new Uint32Array(256);
for (let n = 0; n < 256; n += 1) {
  let c = n;
  for (let k = 0; k < 8; k += 1) {
    c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
  }
  CRC_TABLE[n] = c >>> 0;
}

function crc32(buffer) {
  let crc = 0xffffffff;

  for (const byte of buffer) {
    crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }

  return (crc ^ 0xffffffff) >>> 0;
}

function u16(value) {
  const buffer = Buffer.alloc(2);
  buffer.writeUInt16LE(value);
  return buffer;
}

function u32(value) {
  if (value > 0xffffffff) {
    throw new Error("ZIP64 is not supported by this source bundle writer.");
  }

  const buffer = Buffer.alloc(4);
  buffer.writeUInt32LE(value >>> 0);
  return buffer;
}

async function writeZip(zipPath, entries, { prefix = Buffer.alloc(0) } = {}) {
  const archivePrefix = Buffer.isBuffer(prefix) ? prefix : Buffer.from(prefix);

  if (archivePrefix.length > 0xffffffff) {
    throw new Error("ZIP prefix is too large for non-ZIP64 offsets.");
  }

  await fs.mkdir(path.dirname(zipPath), { recursive: true });
  await fs.rm(zipPath, { force: true });

  const handle = await fs.open(zipPath, "w");
  const centralDirectory = [];
  // ZIP offsets are relative to the complete file, including an optional
  // self-extracting-style prefix. Strict readers therefore find local headers
  // even when the archive follows the JPEG EOI marker.
  let offset = archivePrefix.length;

  try {
    if (archivePrefix.length > 0) {
      await handle.write(archivePrefix);
    }

    for (const entry of entries) {
      const name = Buffer.from(entry.zipPath, "utf8");
      const uncompressed = Buffer.isBuffer(entry.data) ? entry.data : Buffer.from(entry.data);
      const compressed = deflateRawSync(uncompressed, { level: 9 });
      const method = 8;
      const crc = crc32(uncompressed);

      const localHeader = Buffer.concat([
        u32(0x04034b50),
        u16(20),
        u16(ZIP_UTF8_FLAG),
        u16(method),
        u16(ZIP_FIXED_TIME),
        u16(ZIP_FIXED_DATE),
        u32(crc),
        u32(compressed.length),
        u32(uncompressed.length),
        u16(name.length),
        u16(0),
        name,
      ]);

      await handle.write(localHeader);
      await handle.write(compressed);

      centralDirectory.push({
        name,
        crc,
        compressedSize: compressed.length,
        uncompressedSize: uncompressed.length,
        method,
        offset,
      });

      offset += localHeader.length + compressed.length;
    }

    const cdStart = offset;
    const cdParts = [];

    for (const entry of centralDirectory) {
      const header = Buffer.concat([
        u32(0x02014b50),
        u16(20),
        u16(20),
        u16(ZIP_UTF8_FLAG),
        u16(entry.method),
        u16(ZIP_FIXED_TIME),
        u16(ZIP_FIXED_DATE),
        u32(entry.crc),
        u32(entry.compressedSize),
        u32(entry.uncompressedSize),
        u16(entry.name.length),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(0),
        u32(entry.offset),
        entry.name,
      ]);

      cdParts.push(header);
      offset += header.length;
    }

    const cdBuffer = Buffer.concat(cdParts);
    await handle.write(cdBuffer);

    const eocd = Buffer.concat([
      u32(0x06054b50),
      u16(0),
      u16(0),
      u16(centralDirectory.length),
      u16(centralDirectory.length),
      u32(cdBuffer.length),
      u32(cdStart),
      u16(0),
    ]);

    await handle.write(eocd);
  } finally {
    await handle.close();
  }
}

async function readJpegCarrierBase() {
  const jpeg = await fs.readFile(CARRIER_SOURCE_PATH);

  if (jpeg.length < 4 || jpeg[0] !== 0xff || jpeg[1] !== 0xd8) {
    throw new Error(`${CARRIER_SOURCE_RELATIVE} is not a JPEG file.`);
  }

  if (jpeg.at(-2) !== 0xff || jpeg.at(-1) !== 0xd9) {
    throw new Error(
      `${CARRIER_SOURCE_RELATIVE} must be the clean JPEG base ending at EOI; ` +
      "do not replace it with a previously generated polyglot."
    );
  }

  const actualHash = sha256(jpeg);
  if (actualHash !== CARRIER_SOURCE_SHA256) {
    throw new Error(
      `${CARRIER_SOURCE_RELATIVE} changed (expected SHA-256 ${CARRIER_SOURCE_SHA256}, ` +
      `got ${actualHash}). Verify its six archival metadata copies before ` +
      "updating CARRIER_SOURCE_SHA256."
    );
  }

  return jpeg;
}

function isPathWithin(parentPath, candidatePath) {
  const relativePath = path.relative(path.resolve(parentPath), path.resolve(candidatePath));

  return (
    relativePath === "" ||
    (
      relativePath !== ".." &&
      !relativePath.startsWith(`..${path.sep}`) &&
      !path.isAbsolute(relativePath)
    )
  );
}

function validateTargetPaths() {
  if (path.relative(ROOT, TARGET_DIR) === "") {
    throw new Error("Build target must not be the project root.");
  }

  const publicDir = path.join(ROOT, "public");
  if (isPathWithin(publicDir, TARGET_DIR)) {
    throw new Error("Build target must not be public/ or one of its subdirectories.");
  }

  if (path.relative(CARRIER_SOURCE_PATH, CARRIER_OUTPUT_PATH) === "") {
    throw new Error("JPEG carrier output must not overwrite its clean public/ source.");
  }
}

async function main() {
  validateTargetPaths();

  if (!await exists(TARGET_DIR)) {
    throw new Error(`Build target does not exist: ${TARGET_DIR}`);
  }

  const { entries, assetManifest } = await collectZipEntries();
  const jpegCarrierBase = await readJpegCarrierBase();

  await writeZip(OUTPUT_PATH, entries);
  await writeZip(CARRIER_OUTPUT_PATH, entries, { prefix: jpegCarrierBase });

  const [zipStat, carrierStat] = await Promise.all([
    fs.stat(OUTPUT_PATH),
    fs.stat(CARRIER_OUTPUT_PATH),
  ]);

  console.log(`[source-bundle] ${OUTPUT_RELATIVE}`);
  console.log(`[source-bundle] ${entries.length} files in ZIP`);
  console.log(`[source-bundle] ${assetManifest.fileCount} external asset files`);
  console.log(`[source-bundle] ${assetManifest.totalBytes} external asset bytes`);
  console.log(`[source-bundle] ${zipStat.size} ZIP bytes`);
  console.log(
    `[source-bundle] ${CARRIER_OUTPUT_RELATIVE}: ` +
    `${jpegCarrierBase.length} JPEG bytes + ${carrierStat.size - jpegCarrierBase.length} ZIP bytes`
  );
}

main().catch((error) => {
  console.error("[source-bundle] Failed:", error);
  process.exit(1);
});
