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

let status = 0;

status = run("astro", ["build"], {
  BUILD_TARGET: "usb",
  EN_STRICT: "1",
});

if (status === 0) {
  status = run("node", ["scripts/en-postprocess.mjs"], {
    BUILD_TARGET: "usb",
    EN_STRICT: "1",
  });
}

const rewriteStatus = run("node", ["scripts/usb-rewrite.mjs"], {
  BUILD_TARGET: "usb",
});

if (status !== 0) {
  process.exit(status);
}

process.exit(rewriteStatus);