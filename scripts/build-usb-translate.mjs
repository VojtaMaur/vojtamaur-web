import { spawnSync } from "node:child_process";

function run(command, args, env = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    shell: true,
    env: {
      ...process.env,
      ...env,
    },
  });

  return result.status ?? 1;
}

const usbEnv = {
  BUILD_TARGET: "usb",
  EN_TRANSLATE: "missing",
};

let status = run("astro", ["build"], usbEnv);

if (status === 0) {
  status = run("node", ["scripts/en-postprocess.mjs"], usbEnv);
}

if (status === 0) {
  status = run("npm", ["run", "generate:all-posts"], usbEnv);
}

if (status === 0) {
  status = run("npm", ["run", "generate:source-bundle"], usbEnv);
}

// Tohle se spustí VŽDYCKY, i když DeepL/postprocess failne.
// Když build prošel, source bundle už existuje a /source/... se přepíše správně pro file:// USB režim.
const rewriteStatus = run("node", ["scripts/usb-rewrite.mjs"], {
  BUILD_TARGET: "usb",
});

if (status !== 0) {
  process.exit(status);
}

if (rewriteStatus !== 0) {
  process.exit(rewriteStatus);
}

process.exit(run("npm", ["run", "generate:integrity"], {
  BUILD_TARGET: "usb",
}));
