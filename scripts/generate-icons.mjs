import fs from 'fs';
import path from 'path';
import { fileURLToPath, pathToFileURL } from 'url';
import sharp from 'sharp';
import png2icons from 'png2icons';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');

const SOURCE_SVG = path.resolve(projectRoot, 'assets/icon/chick.svg');
const OUTPUT_BASE = path.resolve(projectRoot, 'assets/icon/app');

async function ensureDirExists(dir) {
  await fs.promises.mkdir(dir, { recursive: true });
}

export async function generateIcons() {
  if (!fs.existsSync(SOURCE_SVG)) {
    throw new Error(`Icon source not found at ${SOURCE_SVG}`);
  }

  await ensureDirExists(path.dirname(OUTPUT_BASE));

  const pngBuffer = await sharp(SOURCE_SVG)
    .resize(1024, 1024, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png({ compressionLevel: 9 })
    .toBuffer();

  const pngPath = `${OUTPUT_BASE}.png`;
  await sharp(pngBuffer)
    .resize(512, 512)
    .png({ compressionLevel: 9 })
    .toFile(pngPath);

  const ico = png2icons.createICO(pngBuffer, png2icons.BICUBIC, false, 0, false);
  if (!ico) {
    throw new Error('ICO conversion failed');
  }
  fs.writeFileSync(`${OUTPUT_BASE}.ico`, ico);

  const icns = png2icons.createICNS(pngBuffer, png2icons.BICUBIC, false);
  if (!icns) {
    throw new Error('ICNS conversion failed');
  }
  fs.writeFileSync(`${OUTPUT_BASE}.icns`, icns);

  return {
    source: SOURCE_SVG,
    outputs: [pngPath, `${OUTPUT_BASE}.ico`, `${OUTPUT_BASE}.icns`]
  };
}

const entryUrl = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : null;

if (entryUrl && import.meta.url === entryUrl) {
  generateIcons()
    .then(({ outputs }) => {
      console.log('Generated icons:', outputs.map((file) => path.relative(projectRoot, file)).join(', '));
    })
    .catch((error) => {
      console.error('Failed to generate icons:', error);
      process.exitCode = 1;
    });
}
