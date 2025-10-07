const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const root = __dirname;
const stagingDir = path.join(root, 'build', 'electron-app');
const distDir = path.join(root, 'dist');
const lockFile = path.join(root, 'bun.lock');
const pyBuildDir = path.join(root, 'build', 'py', 'cardmaker');

if (!fs.existsSync(distDir)) {
  console.error('Missing dist output. Run `bun run build` before packaging.');
  process.exit(1);
}

const packageArgs = process.argv.slice(2);
let platform = process.platform;
let arch = process.arch === 'arm64' ? 'arm64' : 'x64';
const forwarded = [];

for (const arg of packageArgs) {
  if (!arg.startsWith('--') && platform === process.platform) {
    platform = arg;
    continue;
  }
  if (!arg.startsWith('--') && arch === (process.arch === 'arm64' ? 'arm64' : 'x64')) {
    arch = arg;
    continue;
  }
  forwarded.push(arg);
}

if (!fs.existsSync(pyBuildDir)) {
  console.error('Missing built cardmaker binary. Run `bun run build:py` first.');
  process.exit(1);
}

fs.rmSync(stagingDir, { recursive: true, force: true });
fs.mkdirSync(stagingDir, { recursive: true });

const copyEntries = ['dist', 'assets', 'fonts'];

const copyRecursive = (src, dest) => {
  if (!fs.existsSync(src)) {
    return;
  }
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true });
    for (const entry of fs.readdirSync(src)) {
      copyRecursive(path.join(src, entry), path.join(dest, entry));
    }
    return;
  }
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
};

for (const entry of copyEntries) {
  copyRecursive(path.join(root, entry), path.join(stagingDir, entry));
}

if (fs.existsSync(lockFile)) {
  copyRecursive(lockFile, path.join(stagingDir, 'bun.lock'));
}

const rootPkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf-8'));
const appPkg = {
  name: rootPkg.name,
  productName: rootPkg.productName || 'Gutenbird Studio',
  version: rootPkg.version,
  main: rootPkg.main || 'dist/main/index.js',
  type: rootPkg.type,
  dependencies: rootPkg.dependencies || {},
};

fs.writeFileSync(path.join(stagingDir, 'package.json'), JSON.stringify(appPkg, null, 2));

try {
  execSync('bun install --production', {
    cwd: stagingDir,
    stdio: 'inherit',
  });
} catch (err) {
  console.error('Failed to install production dependencies for packaged app.');
  process.exit(err.status ?? 1);
}

const outDir = path.join(root, 'release');
fs.mkdirSync(outDir, { recursive: true });

const appName = appPkg.productName || appPkg.name || 'Gutenbird Studio';
const packagerArgs = [
  'bunx',
  'electron-packager',
  '.',
  JSON.stringify(appName),
  `--platform=${platform}`,
  `--arch=${arch}`,
  `--out="${outDir}"`,
  '--overwrite',
  '--asar',
  `--extra-resource="${pyBuildDir}"`,
  ...forwarded,
];

try {
  execSync(packagerArgs.join(' '), {
    cwd: stagingDir,
    stdio: 'inherit',
    env: {
      ...process.env,
      NODE_ENV: 'production',
    },
  });
} catch (err) {
  console.error('electron-packager failed.');
  process.exit(err.status ?? 1);
}
