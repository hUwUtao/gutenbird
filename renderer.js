const { ipcRenderer } = require('electron');
const path = require('path');
const fs = require('fs');
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
const prevPageBtn = document.getElementById('prevPage');
const nextPageBtn = document.getElementById('nextPage');
const pageIndicators = document.getElementById('pageIndicators');
const pageStatus = document.getElementById('pageStatus');
const outputLoading = document.getElementById('outputLoading');
const parityInput = document.getElementById('parityInput');
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
let outputPages = [];
let currentPageIndex = 0;
let outputPreloadToken = 0;

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


function setLoadingOverlay(active, total = null) {
  if (!outputLoading) return;
  outputLoading.classList.toggle('hidden', !active);
  const label = outputLoading.querySelector('span');
  if (label) {
    if (!active) {
      label.textContent = 'Loading pages…';
    } else if (typeof total === 'number' && Number.isFinite(total)) {
      const plural = total === 1 ? '' : 's';
      label.textContent = `Loading ${total} page${plural}…`;
    } else {
      label.textContent = 'Loading pages…';
    }
  }
}

function resetOutputPreview(statusMessage = 'No pages loaded') {
  outputPages = [];
  currentPageIndex = 0;
  if (outputPreview) {
    outputPreview.removeAttribute('src');
  }
  if (pageIndicators) {
    pageIndicators.innerHTML = '';
  }
  if (pageStatus) {
    pageStatus.textContent = statusMessage;
  }
  if (prevPageBtn) {
    prevPageBtn.disabled = true;
  }
  if (nextPageBtn) {
    nextPageBtn.disabled = true;
  }
  setLoadingOverlay(false);
}

function updateNavigationState() {
  const total = outputPages.length;
  const hasPages = total > 0;
  if (prevPageBtn) {
    prevPageBtn.disabled = !hasPages || currentPageIndex === 0;
  }
  if (nextPageBtn) {
    nextPageBtn.disabled = !hasPages || currentPageIndex >= total - 1;
  }
}

function updateIndicatorActiveState() {
  if (!pageIndicators) return;
  const buttons = pageIndicators.querySelectorAll('button');
  buttons.forEach((btn, idx) => {
    btn.classList.toggle('active', idx === currentPageIndex);
    btn.setAttribute('aria-pressed', idx === currentPageIndex ? 'true' : 'false');
  });
}

function renderIndicators(total) {
  if (!pageIndicators) return;
  pageIndicators.innerHTML = '';
  if (!total) return;
  const fragment = document.createDocumentFragment();
  for (let idx = 0; idx < total; idx += 1) {
    const dot = document.createElement('button');
    dot.type = 'button';
    dot.dataset.pageIndex = String(idx);
    dot.title = `Go to page ${idx + 1}`;
    dot.setAttribute('aria-label', `Go to page ${idx + 1}`);
    dot.setAttribute('aria-pressed', idx === currentPageIndex ? 'true' : 'false');
    if (idx === currentPageIndex) {
      dot.classList.add('active');
    }
    fragment.appendChild(dot);
  }
  pageIndicators.appendChild(fragment);
}

function goToPage(index) {
  if (!outputPages.length) return;
  const safeIndex = Math.min(Math.max(0, index), outputPages.length - 1);
  currentPageIndex = safeIndex;
  const page = outputPages[safeIndex];
  if (outputPreview) {
    outputPreview.src = page.url;
  }
  if (pageStatus) {
    pageStatus.textContent = `Page ${safeIndex + 1} of ${outputPages.length}`;
  }
  updateIndicatorActiveState();
  updateNavigationState();
}

function buildSvgPathList(baseDir, metadata) {
  if (!baseDir) return [];
  if (Array.isArray(metadata?.pages_detail) && metadata.pages_detail.length) {
    return metadata.pages_detail
      .map(page => page?.svg)
      .filter(Boolean);
  }
  const svgDir = metadata?.svg_dir || path.join(baseDir, 'svg');
  const pageCount = typeof metadata?.page_count === 'number' ? metadata.page_count : 0;
  if (pageCount > 0) {
    return Array.from({ length: pageCount }, (_, idx) =>
      path.join(svgDir, `page_${String(idx + 1).padStart(3, '0')}.svg`)
    );
  }
  try {
    const entries = fs.readdirSync(svgDir, { withFileTypes: true });
    return entries
      .filter(entry => entry.isFile() && entry.name.toLowerCase().endsWith('.svg'))
      .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
      .map(entry => path.join(svgDir, entry.name));
  } catch (_) {
    return [];
  }
}

function preloadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const cleanup = () => {
      img.onload = null;
      img.onerror = null;
    };
    img.onload = () => {
      cleanup();
      resolve(img);
    };
    img.onerror = () => {
      cleanup();
      reject(new Error(`Failed to load ${src}`));
    };
    img.src = src;
    if (img.complete) {
      cleanup();
      resolve(img);
    }
  });
}

async function preloadOutputPages(svgPaths) {
  const loaders = svgPaths.map((filePath, index) => {
    const fileUrl = pathToFileURL(filePath).href;
    return preloadImage(fileUrl).then(() => ({
      index,
      filePath,
      url: fileUrl,
    }));
  });
  return Promise.all(loaders);
}

async function prepareOutputPreview(baseDir, metadata) {
  const token = ++outputPreloadToken;
  const svgPaths = buildSvgPathList(baseDir, metadata);
  if (!svgPaths.length) {
    resetOutputPreview('No pages produced');
    return;
  }
  resetOutputPreview('Loading output pages…');
  setLoadingOverlay(true, svgPaths.length);
  try {
    const pages = await preloadOutputPages(svgPaths);
    if (token !== outputPreloadToken) return;
    outputPages = pages;
    currentPageIndex = 0;
    renderIndicators(pages.length);
    goToPage(0);
  } catch (err) {
    console.error('Failed to preload output pages', err);
    if (token === outputPreloadToken) {
      resetOutputPreview('Failed to load output preview');
      alert('Unable to load output previews. Check the console for details.');
    }
  } finally {
    if (token === outputPreloadToken) {
      setLoadingOverlay(false);
    }
  }
}

function clearProgress() {
  if (!progress) return;
  progress.textContent = '';
}

function appendProgressChunk(chunk) {
  if (!chunk || !progress) return;
  const normalized = chunk.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  progress.append(document.createTextNode(normalized));
  progress.scrollTop = progress.scrollHeight;
}

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

generateBtn.addEventListener('click', () => {
  if (!templatePath || !albumPath) {
    alert('Please choose a template and an albums folder.');
    return;
  }
  const parityValue = Math.max(1, parseInt(parityInput.value, 10) || 1);
  clearProgress();
  saveBtn.disabled = true;
  generateBtn.disabled = true;
  outputDir = null;
  generationMetadata = null;
  outputPreloadToken += 1;
  resetOutputPreview('Preparing generation…');
  ipcRenderer.send('run-generation', {
    album: albumPath,
    template: templatePath,
    parity: parityValue,
    outputDir: customOutputDir || null,
  });
});

saveBtn.addEventListener('click', async () => {
  if (!outputDir) return;
  await ipcRenderer.invoke('save-final', outputDir);
});

ipcRenderer.on('generation-progress', (_event, data) => {
  const chunk = typeof data === 'string' ? data : data?.toString?.() ?? String(data);
  appendProgressChunk(chunk);
});

ipcRenderer.on('generation-complete', (_event, payload) => {
  const { code, output, metadata, error } = payload;
  generateBtn.disabled = false;
  if (code === 0) {
    outputDir = output;
    saveBtn.disabled = false;
    generationMetadata = metadata || null;
    prepareOutputPreview(outputDir, generationMetadata);
  } else {
    saveBtn.disabled = true;
    outputDir = null;
    generationMetadata = metadata || null;
    resetOutputPreview('Generation failed');
    const errorMessage = error || 'Generation failed. See output for details.';
    alert(errorMessage);
  }
});

if (prevPageBtn) {
  prevPageBtn.addEventListener('click', () => {
    goToPage(currentPageIndex - 1);
  });
}

if (nextPageBtn) {
  nextPageBtn.addEventListener('click', () => {
    goToPage(currentPageIndex + 1);
  });
}

if (pageIndicators) {
  pageIndicators.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const pageIndex = Number.parseInt(target.dataset.pageIndex ?? '', 10);
    if (Number.isNaN(pageIndex)) return;
    goToPage(pageIndex);
  });
}

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
