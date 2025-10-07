#!/usr/bin/env bun

import { $ } from "bun";
import { join, dirname } from "path";

const root = import.meta.dir;
const stagingDir = join(root, "build", "electron-app");
const distDir = join(root, "dist");
const lockFile = join(root, "bun.lock");
const pyBuildDir = join(root, "build", "py", "cardmaker");
const assetsDir = join(root, "assets");
const iconDir = join(assetsDir, "icon");

// Parse command line arguments
const packageArgs = process.argv.slice(2);
let platform = process.platform;
let arch = process.arch === "arm64" ? "arm64" : "x64";
const forwarded = [];

for (const arg of packageArgs) {
  if (!arg.startsWith("--") && platform === process.platform) {
    platform = arg;
    continue;
  }
  if (
    !arg.startsWith("--") &&
    arch === (process.arch === "arm64" ? "arm64" : "x64")
  ) {
    arch = arg;
    continue;
  }
  forwarded.push(arg);
}

// Validate prerequisites
// Check if main entry point exists in dist
const mainEntry = join(distDir, "main", "index.js");
try {
  await Bun.file(mainEntry).text();
} catch {
  console.error(`Missing main entry point: ${mainEntry}`);
  console.error("Run `bun run build` before packaging.");
  process.exit(1);
}

// Check if cardmaker binary exists
const cardmakerBinary = join(pyBuildDir, "cardmaker");
try {
  await Bun.file(cardmakerBinary).text();
} catch {
  console.error(`Missing cardmaker binary: ${cardmakerBinary}`);
  console.error("Run `bun run build:py` first.");
  process.exit(1);
}

// Clean staging directory
await $`rm -rf ${stagingDir}`.quiet();
await $`mkdir -p ${stagingDir}`.quiet();

// Copy required files and directories
const copyEntries = ["dist", "assets", "fonts"];

// Copy required directories using Bun's file system API
for (const entry of copyEntries) {
  const src = join(root, entry);
  const dest = join(stagingDir, entry);

  try {
    // Check if directory exists by trying to read it
    await Bun.$`ls ${src}`.quiet();
    // Use Bun's built-in recursive copy
    await Bun.$`cp -r ${src} ${dest}`.quiet();
  } catch {
    console.warn(`Warning: ${src} does not exist, skipping`);
  }
}

// Copy lockfile if it exists
try {
  await Bun.file(lockFile).text();
  await Bun.$`cp ${lockFile} ${stagingDir}`.quiet();
} catch {
  // Lockfile doesn't exist, skip
}

// Create package.json for staging
const rootPkg = JSON.parse(await Bun.file(join(root, "package.json")).text());
const appPkg = {
  name: rootPkg.name,
  productName: rootPkg.productName || "Gutenbird Studio",
  version: rootPkg.version,
  main: rootPkg.main || "dist/main/index.js",
  type: rootPkg.type,
  dependencies: rootPkg.dependencies || {},
};

await Bun.write(
  join(stagingDir, "package.json"),
  JSON.stringify(appPkg, null, 2),
);

// Install production dependencies
try {
  await Bun.$`bun install`.cwd(stagingDir);
} catch (err) {
  console.error("Failed to install production dependencies for packaged app.");
  process.exit(1);
}

// Prepare electron-packager arguments
const outDir = join(root, "release");
await Bun.$`mkdir -p ${outDir}`.quiet();

const appName = appPkg.productName || appPkg.name || "Gutenbird Studio";
const packagerArgs = [
  "bunx",
  "electron-packager",
  ".",
  JSON.stringify(appName),
  `--platform=${platform}`,
  `--arch=${arch}`,
  `--out=${outDir}`,
  "--overwrite",
  "--asar",
  `--extra-resource=${pyBuildDir}`,
];

// Add platform-specific icon arguments
try {
  await Bun.$`ls ${iconDir}`.quiet();
  switch (platform) {
    case "win32":
      const winIcon = join(iconDir, "app.ico");
      try {
        await Bun.file(winIcon).text();
        packagerArgs.push(`--icon=${winIcon}`);
        console.log(`Using Windows icon: ${winIcon}`);
      } catch {
        // Icon file doesn't exist
      }
      break;

    case "darwin":
      const macIcon = join(iconDir, "app.icns");
      try {
        await Bun.file(macIcon).text();
        packagerArgs.push(`--icon=${macIcon}`);
        console.log(`Using macOS icon: ${macIcon}`);
      } catch {
        // Icon file doesn't exist
      }
      break;

    case "linux":
      const linuxIcon = join(iconDir, "app.png");
      try {
        await Bun.file(linuxIcon).text();
        packagerArgs.push(`--icon=${linuxIcon}`);
        console.log(`Using Linux icon: ${linuxIcon}`);
      } catch {
        // Icon file doesn't exist
      }
      break;
  }
} catch {
  // Icon directory doesn't exist
}

// Add forwarded arguments
packagerArgs.push(...forwarded);

// Run electron-packager
try {
  console.log(
    "Running electron-packager with arguments:",
    packagerArgs.join(" "),
  );
  await Bun.$`${packagerArgs}`.cwd(stagingDir).env({
    ...process.env,
    NODE_ENV: "production",
  });
  console.log("Packaging completed successfully!");
} catch (err) {
  console.error("electron-packager failed.");
  process.exit(1);
}
