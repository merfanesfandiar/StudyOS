/**
 * Copy the build's hashed assets into the standalone tree.
 *
 * `next.config.ts` sets `output: "standalone"` so the image can ship a slim
 * runtime, and Next then warns that `next start` is unsupported for that build.
 * It happens to work, which is worse: local runs and the deployed container end
 * up on two different code paths, and a bug that reproduces in only one of them
 * gets found in the wrong place.
 *
 * The standalone server serves HTML and the server runtime from
 * `.next/standalone`, but hashed assets sit in `.next/static` beside it, and the
 * image copies them in by hand. This does the same copy so `npm run start` and
 * the container's `CMD` run the same server against the same tree.
 *
 * Wired as `prestart`, so it is a no-op when the assets are already in place and
 * restarting the server does not re-copy a directory tree.
 */

import { cp, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const standalone = path.join(appRoot, ".next", "standalone");
const entry = path.join(standalone, "server.js");

async function exists(target) {
  try {
    await stat(target);
    return true;
  } catch {
    return false;
  }
}

if (!(await exists(entry))) {
  console.error(
    `No standalone build at ${entry}.\nRun \`npm run build\` first -- this script does not build.`,
  );
  process.exit(1);
}

for (const [from, to] of [
  [path.join(appRoot, ".next", "static"), path.join(standalone, ".next", "static")],
  [path.join(appRoot, "public"), path.join(standalone, "public")],
]) {
  if (!(await exists(from))) continue;
  await cp(from, to, { recursive: true, force: true });
}
