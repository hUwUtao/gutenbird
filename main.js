const { app, BrowserWindow, dialog, ipcMain, Menu } = require('electron');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');

function createWindow() {
  const win = new BrowserWindow({
    width: 1000,
    height: 800,
    backgroundColor: '#14161c',
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
  });

  win.loadFile('index.html');
}

function resolveCardmakerExecutable() {
  const exeName = process.platform === 'win32' ? 'cardmaker.exe' : 'cardmaker';
  const candidates = [];

  if (process.env.CARDMAKER_BIN) {
    candidates.push({ type: 'binary', path: process.env.CARDMAKER_BIN });
  }

  if (app.isPackaged) {
    candidates.push({ type: 'binary', path: path.join(process.resourcesPath, 'cardmaker', exeName) });
  } else {
    candidates.push({ type: 'binary', path: path.join(__dirname, 'build', 'py', 'cardmaker', exeName) });
    candidates.push({ type: 'binary', path: path.join(__dirname, exeName) });
  }

  for (const candidate of candidates) {
    try {
      if (candidate.path && fs.existsSync(candidate.path)) {
        return candidate;
      }
    } catch (_) {
      // ignore
    }
  }

  return { type: 'script', path: path.join(__dirname, 'cardmaker.py') };
}

function findPythonCommand() {
  const preferred = [
    process.env.CARDMAKER_PYTHON,
    process.platform === 'win32' ? 'py' : null,
    'python3',
    'python',
  ].filter(Boolean);

  for (const cmd of preferred) {
    try {
      const check = spawnSync(cmd, ['--version'], { stdio: 'pipe' });
      if (!check.error && check.status === 0) {
        return cmd;
      }
    } catch (_) {
      // continue searching
    }
  }
  return null;
}

function prepareOutputDirectory(baseDir, isCustom) {
  if (!isCustom) {
    if (fs.existsSync(baseDir)) {
      fs.rmSync(baseDir, { recursive: true, force: true });
    }
  } else {
    const targets = [
      path.join(baseDir, 'svg'),
      path.join(baseDir, 'pdf'),
      path.join(baseDir, '.imgcache'),
      path.join(baseDir, 'final.pdf'),
      path.join(baseDir, 'metadata.json'),
    ];
    for (const target of targets) {
      try {
        if (fs.existsSync(target)) {
          fs.rmSync(target, { recursive: true, force: true });
        }
      } catch (_) {
        // ignore
      }
    }
  }
  fs.mkdirSync(baseDir, { recursive: true });
}

function readMetadata(metadataPath) {
  try {
    if (fs.existsSync(metadataPath)) {
      const raw = fs.readFileSync(metadataPath, 'utf-8');
      return JSON.parse(raw);
    }
  } catch (err) {
    console.error('Failed to read metadata:', err);
  }
  return null;
}

function checkCardmakerVersion() {
  const resolved = resolveCardmakerExecutable();
  if (resolved.type !== 'binary') {
    return;
  }
  try {
    const result = spawnSync(resolved.path, ['--version'], { stdio: 'pipe' });
    if (result.status === 0) {
      console.log(result.stdout.toString().trim());
    } else if (result.stderr?.toString()) {
      console.warn(result.stderr.toString());
    }
  } catch (err) {
    console.warn('Failed to query cardmaker version:', err.message);
  }
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  checkCardmakerVersion();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

ipcMain.handle('select-template', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [{ name: 'SVG Template', extensions: ['svg'] }],
  });
  if (canceled || filePaths.length === 0) return null;
  return filePaths[0];
});

ipcMain.handle('select-album', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    properties: ['openDirectory'],
  });
  if (canceled || filePaths.length === 0) return null;
  return filePaths[0];
});

ipcMain.handle('select-output', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    properties: ['openDirectory', 'createDirectory'],
  });
  if (canceled || filePaths.length === 0) return null;
  return filePaths[0];
});

const defaultOutputDir = path.join(app.getPath('userData'), 'output');

ipcMain.on('run-generation', (event, args) => {
  const {
    album,
    template,
    parity = 1,
    lockCells = false,
    outputDir: requestedOutput,
  } = args;

  const targetOutputDir = requestedOutput ? path.resolve(requestedOutput) : defaultOutputDir;
  const isCustomOutput = Boolean(requestedOutput);

  if (!album || !template) {
    event.sender.send('generation-complete', {
      code: -1,
      output: targetOutputDir,
      error: 'Album folder and template file are required to start generation.',
    });
    return;
  }

  try {
    prepareOutputDirectory(targetOutputDir, isCustomOutput);
  } catch (err) {
    event.sender.send('generation-complete', {
      code: -1,
      output: targetOutputDir,
      error: `Failed to prepare output directory: ${err.message}`,
    });
    return;
  }

  const metadataPath = path.join(targetOutputDir, 'metadata.json');
  try {
    if (fs.existsSync(metadataPath)) {
      fs.rmSync(metadataPath, { force: true });
    }
  } catch (err) {
    event.sender.send('generation-complete', {
      code: -1,
      output: targetOutputDir,
      error: `Failed to reset metadata: ${err.message}`,
    });
    return;
  }

  const cliArgs = [
    album,
    template,
    '--output-dir',
    targetOutputDir,
    '--parity',
    String(parity),
    '--metadata-json',
    metadataPath,
  ];
  if (lockCells) {
    cliArgs.push('--lock-cells');
  }

  const resolved = resolveCardmakerExecutable();
  let proc;

  if (resolved.type === 'binary') {
    proc = spawn(resolved.path, cliArgs, { stdio: 'pipe' });
  } else {
    const pythonCmd = findPythonCommand();
    if (!pythonCmd) {
      event.sender.send('generation-complete', {
        code: -1,
        output: targetOutputDir,
        error: 'No Python interpreter found to run cardmaker.py',
      });
      return;
    }
    const scriptArgs = pythonCmd === 'py' ? ['-3', '-u', resolved.path, ...cliArgs] : ['-u', resolved.path, ...cliArgs];
    proc = spawn(pythonCmd, scriptArgs, { stdio: 'pipe' });
  }

  proc.stdout.on('data', (data) => {
    event.sender.send('generation-progress', data.toString());
  });

  proc.stderr.on('data', (data) => {
    event.sender.send('generation-progress', data.toString());
  });

  proc.on('error', (err) => {
    event.sender.send('generation-complete', {
      code: -1,
      output: targetOutputDir,
      error: err.message,
    });
  });

  proc.on('close', (code) => {
    const metadata = readMetadata(metadataPath);
    event.sender.send('generation-complete', {
      code,
      output: targetOutputDir,
      metadata,
      error: metadata?.error,
    });
  });
});

ipcMain.handle('save-final', async (_event, outputPath) => {
  const baseDir = outputPath ? path.resolve(outputPath) : defaultOutputDir;
  const src = path.join(baseDir, 'final.pdf');
  if (!fs.existsSync(src)) {
    await dialog.showMessageBox({
      type: 'warning',
      message: 'final.pdf was not found in the output directory.',
    });
    return false;
  }
  const { filePath, canceled } = await dialog.showSaveDialog({
    defaultPath: 'final.pdf',
  });
  if (canceled || !filePath) return false;
  await fs.promises.copyFile(src, filePath);
  return true;
});
