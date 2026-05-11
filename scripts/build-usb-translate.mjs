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

let status = run("astro", ["build"], {
  BUILD_TARGET: "usb",
  EN_TRANSLATE: "missing",
});

if (status === 0) {
  status = run("node", ["scripts/en-postprocess.mjs"], {
    BUILD_TARGET: "usb",
    EN_TRANSLATE: "missing",
  });
}

// Tohle se spustí VŽDYCKY, i když DeepL/postprocess failne.
const rewriteStatus = run("node", ["scripts/usb-rewrite.mjs"], {
  BUILD_TARGET: "usb",
});

if (status !== 0) {
  process.exit(status);
}

process.exit(rewriteStatus);