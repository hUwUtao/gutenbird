const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');

function createWindow () {
  const win = new BrowserWindow({
    width: 1000,
    height: 800,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  win.loadFile('index.html');
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

ipcMain.handle('select-template', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [{ name: 'SVG Template', extensions: ['svg'] }]
  });
  if (canceled || filePaths.length === 0) return null;
  return filePaths[0];
});

ipcMain.handle('select-album', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    properties: ['openDirectory']
  });
  if (canceled || filePaths.length === 0) return null;
  return filePaths[0];
});

const outputDir = path.join(app.getPath('userData'), 'output');

ipcMain.on('run-generation', (event, args) => {
  const { album, template } = args;
  if (fs.existsSync(outputDir)) {
    fs.rmSync(outputDir, { recursive: true, force: true });
  }
  const script = path.join(__dirname, '..', 'cardmaker.py');
  const proc = spawn('python', ['-u', script, album, template, '--output-dir', outputDir]);

  proc.stdout.on('data', (data) => {
    event.sender.send('generation-progress', data.toString());
  });

  proc.stderr.on('data', (data) => {
    event.sender.send('generation-progress', data.toString());
  });

  proc.on('close', (code) => {
    event.sender.send('generation-complete', { code, output: outputDir });
  });
});

ipcMain.handle('save-final', async () => {
  const src = path.join(outputDir, 'final.pdf');
  const { filePath, canceled } = await dialog.showSaveDialog({
    defaultPath: 'final.pdf'
  });
  if (canceled || !filePath) return false;
  await fs.promises.copyFile(src, filePath);
  return true;
});
