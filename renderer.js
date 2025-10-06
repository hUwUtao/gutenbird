const { ipcRenderer } = require('electron');
const path = require('path');
const { pathToFileURL } = require('url');

const templateBtn = document.getElementById('chooseTemplate');
const albumBtn = document.getElementById('chooseAlbum');
const outputBtn = document.getElementById('chooseOutput');
const clearOutputBtn = document.getElementById('clearOutput');
const generateBtn = document.getElementById('generate');
const saveBtn = document.getElementById('saveFinal');

const templatePreview = document.getElementById('templatePreview');
const outputPreview = document.getElementById('outputPreview');
const progress = document.getElementById('progress');
const pageNumberInput = document.getElementById('pageNumber');
const pageNumberDisplay = document.getElementById('pageNumberDisplay');
const loadPageBtn = document.getElementById('loadPage');
const parityInput = document.getElementById('parityInput');
const lockCellsToggle = document.getElementById('lockCellsToggle');
const templatePathLabel = document.getElementById('templatePath');
const albumPathLabel = document.getElementById('albumPath');
const outputPathLabel = document.getElementById('outputPath');

const tabs = document.querySelectorAll('.tab');
const panes = document.querySelectorAll('.pane');

let templatePath = localStorage.getItem('templatePath') || '';
let albumPath = localStorage.getItem('albumPath') || '';
let customOutputDir = localStorage.getItem('outputDir') || '';
let outputDir = null;
let generationMetadata = null;

function totalPages() {
  if (!generationMetadata) return 0;
  if (typeof generationMetadata.page_count === 'number') {
    return generationMetadata.page_count;
  }
  if (Array.isArray(generationMetadata.pages_detail)) {
    return generationMetadata.pages_detail.length;
  }
  return 0;
}

function updatePathLabel(label, value, emptyMessage) {
  if (value) {
    label.textContent = value;
    label.classList.remove('empty');
  } else {
    label.textContent = emptyMessage;
    label.classList.add('empty');
  }
}

if (templatePath) {
  updatePathLabel(templatePathLabel, templatePath, 'No template selected');
  templatePreview.src = `file://${templatePath}`;
}

if (albumPath) {
  updatePathLabel(albumPathLabel, albumPath, 'No folder selected');
}

if (customOutputDir) {
  updatePathLabel(outputPathLabel, customOutputDir, 'Using app data folder');
}

let parity = parseInt(localStorage.getItem('parity') || '1', 10);
if (!Number.isInteger(parity) || parity < 1) parity = 1;
parityInput.value = parity;

const lockPref = localStorage.getItem('lockCells');
const lockCells = lockPref === 'true';
lockCellsToggle.checked = lockCells;

function loadOutputPage(page) {
  if (!outputDir) return;
  const maxPages = totalPages();
  const safePage = Math.min(Math.max(1, page), Math.max(1, maxPages || 1));
  const svgPath = path.join(outputDir, 'svg', `page_${String(safePage).padStart(3, '0')}.svg`);
  outputPreview.src = pathToFileURL(svgPath).href;
  pageNumberInput.value = safePage;
  const metaTotal = totalPages();
  pageNumberDisplay.textContent = metaTotal > 0 ? `${safePage} / ${metaTotal}` : String(safePage);
}

loadPageBtn.addEventListener('click', () => {
  const p = Math.max(1, parseInt(pageNumberInput.value, 10) || 1);
  loadOutputPage(p);
});

templateBtn.addEventListener('click', async () => {
  templatePath = await ipcRenderer.invoke('select-template');
  if (!templatePath) {
    templatePath = '';
    updatePathLabel(templatePathLabel, '', 'No template selected');
    templatePreview.src = '';
    localStorage.removeItem('templatePath');
    return;
  }
  updatePathLabel(templatePathLabel, templatePath, 'No template selected');
  templatePreview.src = `file://${templatePath}`;
  localStorage.setItem('templatePath', templatePath);
});

albumBtn.addEventListener('click', async () => {
  albumPath = await ipcRenderer.invoke('select-album');
  if (!albumPath) {
    albumPath = '';
    updatePathLabel(albumPathLabel, '', 'No folder selected');
    localStorage.removeItem('albumPath');
    return;
  }
  updatePathLabel(albumPathLabel, albumPath, 'No folder selected');
  localStorage.setItem('albumPath', albumPath);
});

outputBtn.addEventListener('click', async () => {
  const dir = await ipcRenderer.invoke('select-output');
  if (!dir) return;
  customOutputDir = dir;
  updatePathLabel(outputPathLabel, customOutputDir, 'Using app data folder');
  localStorage.setItem('outputDir', customOutputDir);
});

clearOutputBtn.addEventListener('click', () => {
  customOutputDir = '';
  updatePathLabel(outputPathLabel, '', 'Using app data folder');
  localStorage.removeItem('outputDir');
});

parityInput.addEventListener('change', () => {
  const value = Math.max(1, parseInt(parityInput.value, 10) || 1);
  parityInput.value = value;
  localStorage.setItem('parity', String(value));
});

lockCellsToggle.addEventListener('change', () => {
  localStorage.setItem('lockCells', lockCellsToggle.checked ? 'true' : 'false');
});

generateBtn.addEventListener('click', () => {
  if (!templatePath || !albumPath) {
    alert('Please choose a template and an albums folder.');
    return;
  }
  const parityValue = Math.max(1, parseInt(parityInput.value, 10) || 1);
  const lockValue = lockCellsToggle.checked;
  progress.textContent = '';
  saveBtn.disabled = true;
  generateBtn.disabled = true;
  outputDir = null;
  generationMetadata = null;
  pageNumberDisplay.textContent = '1';
  pageNumberInput.max = 1;
  pageNumberInput.value = 1;
  pageNumberInput.disabled = true;
  loadPageBtn.disabled = true;
  ipcRenderer.send('run-generation', {
    album: albumPath,
    template: templatePath,
    parity: parityValue,
    lockCells: lockValue,
    outputDir: customOutputDir || null,
  });
});

saveBtn.addEventListener('click', async () => {
  if (!outputDir) return;
  await ipcRenderer.invoke('save-final', outputDir);
});

ipcRenderer.on('generation-progress', (_event, data) => {
  progress.textContent += data;
  progress.scrollTop = progress.scrollHeight;
});

ipcRenderer.on('generation-complete', (_event, payload) => {
  const { code, output, metadata, error } = payload;
  generateBtn.disabled = false;
  if (code === 0) {
    outputDir = output;
    saveBtn.disabled = false;
    generationMetadata = metadata || null;
    const pages = totalPages();
    pageNumberInput.max = Math.max(pages, 1);
    pageNumberInput.disabled = pages === 0;
    loadPageBtn.disabled = pages === 0;
    if (pages > 0) {
      loadOutputPage(1);
    }
  } else {
    pageNumberInput.disabled = true;
    loadPageBtn.disabled = true;
    const errorMessage = error || 'Generation failed. See output for details.';
    alert(errorMessage);
  }
});

for (const tab of tabs) {
  tab.addEventListener('click', () => {
    if (tab.classList.contains('active')) return;
    tabs.forEach(t => t.classList.remove('active'));
    panes.forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    const pane = document.getElementById(tab.dataset.target);
    if (pane) {
      pane.classList.add('active');
    }
  });
}
