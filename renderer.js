const { ipcRenderer } = require('electron');
const path = require('path');
const { pathToFileURL } = require('url');

const templateBtn = document.getElementById('chooseTemplate');
const albumBtn = document.getElementById('chooseAlbum');
const generateBtn = document.getElementById('generate');
const saveBtn = document.getElementById('saveFinal');

const templatePreview = document.getElementById('templatePreview');
const outputPreview = document.getElementById('outputPreview');
const progress = document.getElementById('progress');
const pageNumberInput = document.getElementById('pageNumber');
const loadPageBtn = document.getElementById('loadPage');

const tabs = document.querySelectorAll('.tab');
const panes = document.querySelectorAll('.pane');

let templatePath = localStorage.getItem('templatePath') || '';
let albumPath = localStorage.getItem('albumPath') || '';
let outputDir = null;

if (templatePath) {
  document.getElementById('templatePath').innerText = templatePath;
  templatePreview.src = `file://${templatePath}`;
}

if (albumPath) {
  document.getElementById('albumPath').innerText = albumPath;
}

templateBtn.addEventListener('click', async () => {
  templatePath = await ipcRenderer.invoke('select-template');
  document.getElementById('templatePath').innerText = templatePath || '';
  if (templatePath) {
    templatePreview.src = `file://${templatePath}`;
    localStorage.setItem('templatePath', templatePath);
  }
});

albumBtn.addEventListener('click', async () => {
  albumPath = await ipcRenderer.invoke('select-album');
  document.getElementById('albumPath').innerText = albumPath || '';
  if (albumPath) {
    localStorage.setItem('albumPath', albumPath);
  }
});

function loadOutputPage(page) {
  if (!outputDir) return;
  const svgPath = path.join(outputDir, 'svg', `page_${String(page).padStart(3, '0')}.svg`);
  outputPreview.src = pathToFileURL(svgPath).href;
  pageNumberInput.value = page;
}

loadPageBtn.addEventListener('click', () => {
  const p = parseInt(pageNumberInput.value, 10) || 1;
  loadOutputPage(p);
});

generateBtn.addEventListener('click', () => {
  if (!templatePath || !albumPath) {
    alert('Please choose template and album');
    return;
  }
  progress.textContent = '';
  saveBtn.disabled = true;
  ipcRenderer.send('run-generation', { album: albumPath, template: templatePath });
});

saveBtn.addEventListener('click', async () => {
  if (outputDir) {
    await ipcRenderer.invoke('save-final', outputDir);
  }
});

ipcRenderer.on('generation-progress', (_event, data) => {
  progress.textContent += data;
  progress.scrollTop = progress.scrollHeight;
});

ipcRenderer.on('generation-complete', (_event, { code, output }) => {
  if (code === 0) {
    outputDir = output;
    saveBtn.disabled = false;
    loadOutputPage(1);
  } else {
    alert('Generation failed. See output for details.');
  }
});

// tab switching
for (const tab of tabs) {
  tab.addEventListener('click', () => {
    tabs.forEach(t => t.classList.remove('active'));
    panes.forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    const pane = document.getElementById(tab.dataset.target);
    pane.classList.add('active');
  });
}
