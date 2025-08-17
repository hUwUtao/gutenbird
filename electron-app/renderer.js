const { ipcRenderer } = require('electron');
const path = require('path');

const templateBtn = document.getElementById('chooseTemplate');
const albumBtn = document.getElementById('chooseAlbum');
const outputBtn = document.getElementById('chooseOutput');
const generateBtn = document.getElementById('generate');
const openOutputBtn = document.getElementById('openOutput');
const templatePreview = document.getElementById('templatePreview');
const generatedPreview = document.getElementById('generatedPreview');
const progress = document.getElementById('progress');

let templatePath, albumPath, outputPath;

templateBtn.addEventListener('click', async () => {
  templatePath = await ipcRenderer.invoke('select-template');
  document.getElementById('templatePath').innerText = templatePath || '';
  if (templatePath) {
    templatePreview.src = `file://${templatePath}`;
  }
});

albumBtn.addEventListener('click', async () => {
  albumPath = await ipcRenderer.invoke('select-album');
  document.getElementById('albumPath').innerText = albumPath || '';
});

outputBtn.addEventListener('click', async () => {
  outputPath = await ipcRenderer.invoke('select-output');
  document.getElementById('outputPath').innerText = outputPath || '';
});

generateBtn.addEventListener('click', () => {
  if (!templatePath || !albumPath || !outputPath) {
    alert('Please choose template, album and output folder');
    return;
  }
  progress.textContent = '';
  ipcRenderer.send('run-generation', { album: albumPath, template: templatePath, output: outputPath });
});

ipcRenderer.on('generation-progress', (_event, data) => {
  progress.textContent += data;
  progress.scrollTop = progress.scrollHeight;
});

ipcRenderer.on('generation-complete', (_event, { code, output }) => {
  if (code === 0) {
    const svgPath = path.join(output, 'svg', 'page_001.svg');
    generatedPreview.src = `file://${svgPath}`;
    openOutputBtn.style.display = 'inline-block';
    openOutputBtn.onclick = () => ipcRenderer.invoke('open-path', output);
  } else {
    alert('Generation failed. See output for details.');
  }
});
