const fs = require('fs');
const path = require('path');
const {execSync} = require('child_process');

const platform = process.argv[2] || process.platform;
const root = __dirname;
const buildDir = path.join(root, 'build', 'electron');

// Clean and recreate build directory
fs.rmSync(buildDir, { recursive: true, force: true });
fs.mkdirSync(buildDir, { recursive: true });

const copyIfExists = (p) => {
  const src = path.join(root, p);
  if (fs.existsSync(src)) {
    const dest = path.join(buildDir, p);
    fs.cpSync(src, dest, { recursive: true });
  }
};

// Copy essential Electron files
['package.json', 'index.html', 'main.js', 'renderer.js', 'bun.lock', 'fonts'].forEach(copyIfExists);

// Copy the bundled Python executable
const binary = platform === 'win32' ? 'cardmaker.exe' : 'cardmaker';
copyIfExists(binary);

// Install dependencies in the scoped directory
execSync('bun install', { cwd: buildDir, stdio: 'inherit' });

// Package the app using the scoped directory
const extraResource = binary;
const outDir = path.join(root, 'dist');
execSync(
  `npx electron-packager . gutenbird-studio --platform=${platform} --arch=x64 --out=${outDir} --overwrite --extra-resource ${extraResource}`,
  { cwd: buildDir, stdio: 'inherit' }
);
