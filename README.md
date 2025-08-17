# spawn lotta cards

## presiquites

- uv
- [GTKrt Windows](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases) or `libcairo`

## electron ui
An Electron-based interface lives in `electron-app/` and lets you run the card generator without the command line.

### usage
1. `cd electron-app`
2. `npm install`
3. `npm start`

The right panel lets you choose a template and an album folder, and these selections are remembered between launches. After clicking **Generate**, progress logs stream in real time. When generation completes, switch to the **Output** tab on the left to preview any page from the `svg/` directory, and use **Save final.pdf** to pick where to copy the merged PDF.

### build for windows
Ensure Python's build tools are installed first:

```
pip install pyinstaller cairosvg cairocffi
```

Then run `npm run build:win` inside `electron-app`. This script bundles the Python
generator (including the Cairo runtime) alongside the Electron files and places the
final package under `electron-app/dist/`.

If your SVG template includes a marker like `(slice=6)`, the generator will use that value to decide how many images make up a slice. Without this marker, each slice defaults to a single image.
