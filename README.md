# spawn lotta cards

## presiquites

- uv
- [GTKrt Windows](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases) or `libcairo`
- bun
- Python 3.12

## electron ui
An Electron-based interface lives in this repository and lets you run the card generator without the command line.

### usage
1. `bun install`
2. `bun run start`

The right panel lets you choose a template and an album folder, and these selections are remembered between launches. After clicking **Generate**, progress logs stream in real time. When generation completes, switch to the **Output** tab on the left to preview any page from the `svg/` directory, and use **Save final.pdf** to pick where to copy the merged PDF. If your SVG template includes a marker like `(slice=6)`, the generator will use that value to decide how many images make up a slice. Without this marker, the generator fills all slices with the provided images.

### building packages
All Python requirements—including **PyInstaller**—are tracked in `pyproject.toml`. After cloning the repo, run:

```
uv sync
```

This installs the dependencies into a local environment so `uv run` can launch them.

#### linux

```
bun install
bun run build:linux
```

This produces a distributable under `dist/` with the bundled `cardmaker` executable.

#### windows
On a Windows host, run:

```
bun install
bun run build:win
```

The output appears in `dist/` and includes the bundled `cardmaker.exe`. PyInstaller pulls in the required `pywin32-ctypes` runtime automatically.
