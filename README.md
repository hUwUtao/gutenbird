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

The UI allows you to pick a template and an albums folder, shows generation progress, previews the template and first generated page, and opens the output directory when finished.

If your SVG template includes a marker like `(slice=6)`, the generator will use that value to decide how many images make up a slice. Without this marker, each slice defaults to a single image.
