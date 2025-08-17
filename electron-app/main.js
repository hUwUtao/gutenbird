const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

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

ipcMain.handle('select-output', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    properties: ['openDirectory', 'createDirectory']
  });
  if (canceled || filePaths.length === 0) return null;
  return filePaths[0];
});

ipcMain.on('run-generation', (event, args) => {
  const { album, template, output } = args;
  const script = path.join(__dirname, '..', 'cardmaker.py');
  const proc = spawn('python', ['-u', script, album, template, '--output-dir', output]);

  proc.stdout.on('data', (data) => {
    event.sender.send('generation-progress', data.toString());
  });

  proc.stderr.on('data', (data) => {
    event.sender.send('generation-progress', data.toString());
  });

  proc.on('close', (code) => {
    event.sender.send('generation-complete', { code, output });
  });
});

ipcMain.handle('open-path', async (_event, targetPath) => {
  await shell.openPath(targetPath);
});
