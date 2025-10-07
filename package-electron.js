#!/usr/bin/env node
/* eslint-disable no-console */

import { promises as fs } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { spawn } from "child_process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const root = __dirname;
const stagingDir = path.join(root, "build", "electron-app");
const distDir = path.join(root, "dist");
const lockFile = path.join(root, "bun.lock"); // kept as-is
const pyBuildDir = path.join(root, "build", "py", "cardmaker");
const assetsDir = path.join(root, "assets");
const iconDir = path.join(assetsDir, "icon");

// args
const packageArgs = process.argv.slice(2);
let platform = process.platform;
let arch = process.arch === "arm64" ? "arm64" : "x64";
const forwarded = [];

for (const arg of packageArgs) {
  if (!arg.startsWith("--") && platform === process.platform) {
    platform = arg;
    continue;
  }
  if (!arg.startsWith("--") && arch === (process.arch === "arm64" ? "arm64" : "x64")) {
    arch = arg;
    continue;
  }
  forwarded.push(arg);
}

async function exists(p) {
  try { await fs.access(p); return true; } catch { return false; }
}

async function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: "inherit", shell: process.platform === "win32", ...opts });
    child.on("close", (code) => code === 0 ? resolve() : reject(new Error(`${cmd} ${args.join(" ")} exited ${code}`)));
  });
}

// prereq: main entry
const mainEntry = path.join(distDir, "main", "index.js");
if (!(await exists(mainEntry))) {
  console.error(`Missing main entry point: ${mainEntry}`);
  console.error("Run `npm run build` before packaging.");
  process.exit(1);
}

// prereq: cardmaker binary
// const cardmakerBinary = path.join(pyBuildDir, "cardmaker");
// if (!(await exists(cardmakerBinary))) {
//   console.error(`Missing cardmaker binary: ${cardmakerBinary}`);
//   console.error("Run `npm run build:py` first.");
//   process.exit(1);
// }

// clean staging
await fs.rm(stagingDir, { recursive: true, force: true });
await fs.mkdir(stagingDir, { recursive: true });

// copy dirs
const copyEntries = ["dist", "assets", "fonts"];
for (const entry of copyEntries) {
  const src = path.join(root, entry);
  const dest = path.join(stagingDir, entry);
  if (await exists(src)) {
    await fs.cp(src, dest, { recursive: true, force: true });
  } else {
    console.warn(`Warning: ${src} does not exist, skipping`);
  }
}

// copy lockfile if present
if (await exists(lockFile)) {
  await fs.cp(lockFile, path.join(stagingDir, path.basename(lockFile)));
}

// staging package.json
const rootPkg = JSON.parse(await fs.readFile(path.join(root, "package.json"), "utf8"));
const appPkg = {
  name: rootPkg.name,
  productName: rootPkg.productName || "Gutenbird Studio",
  version: rootPkg.version,
  main: rootPkg.main || "dist/main/index.js",
  type: rootPkg.type,
  dependencies: rootPkg.dependencies || {},
};
await fs.writeFile(path.join(stagingDir, "package.json"), JSON.stringify(appPkg, null, 2));

// install production deps in staging
try {
  // prefer npm ci if lockfile exists, else npm install --omit=dev
  const hasPkgLock = await exists(path.join(root, "package-lock.json"));
  if (hasPkgLock) {
    await run("npm", ["ci", "--omit=dev"], { cwd: stagingDir });
  } else {
    await run("bun", ["install", "--omit=dev"], { cwd: stagingDir });
  }
} catch {
  console.error("Failed to install production dependencies for packaged app.");
  process.exit(1);
}

// prepare electron-packager args
const outDir = path.join(root, "release");
await fs.mkdir(outDir, { recursive: true });

const appName = appPkg.productName || appPkg.name || "Gutenbird Studio";
const packagerArgs = [
  ".", appName,
  `--platform=${platform}`,
  `--arch=${arch}`,
  `--out=${outDir}`,
  "--overwrite",
  "--asar",
  `--extra-resource=${pyBuildDir}`,
];

// platform icons
if (await exists(iconDir)) {
  if (platform === "win32") {
    const winIcon = path.join(iconDir, "app.ico");
    if (await exists(winIcon)) {
      packagerArgs.push(`--icon=${winIcon}`);
      console.log(`Using Windows icon: ${winIcon}`);
    }
  } else if (platform === "darwin") {
    const macIcon = path.join(iconDir, "app.icns");
    if (await exists(macIcon)) {
      packagerArgs.push(`--icon=${macIcon}`);
      console.log(`Using macOS icon: ${macIcon}`);
    }
  } else if (platform === "linux") {
    const linuxIcon = path.join(iconDir, "app.png");
    if (await exists(linuxIcon)) {
      packagerArgs.push(`--icon=${linuxIcon}`);
      console.log(`Using Linux icon: ${linuxIcon}`);
    }
  }
}

// forwarded args
packagerArgs.push(...forwarded);

// run electron-packager via npx
try {
  console.log("Running electron-packager with arguments:", ["npx", "electron-packager", ...packagerArgs].join(" "));
  await run("bunx", ["electron-packager", ...packagerArgs], {
    cwd: stagingDir,
    env: { ...process.env, NODE_ENV: "production" },
  });
  console.log("Packaging completed successfully!");
} catch (err) {
  console.error("electron-packager failed.");
  process.exit(1);
}
