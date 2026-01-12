# Raster Edit Plugin (QGIS)

A QGIS plugin for **interactive raster editing** aimed at practical cleanup tasks such as:
- removing unwanted objects (mask to NoData),
- correcting local defects,
- repairing gaps using interpolation.

The workflow is designed to be lightweight and reproducible by operating on an **editable copy** of the raster.

---

## Key features

- **Create editable copy** of the active raster (writes `*_edited` next to the original file)
- **Suppress zone**: set a user-drawn area to **NoData**
- **Interpolate zone**: fill **NoData** pixels inside the selected area
- **Interpolate (all)**: interpolate all pixels inside the selected area (stronger repair)
- **Undo / Redo** for block-based edits
- Interactive tools on the map canvas (polygon/area selection)

---

## Requirements

- QGIS (3.x)
- Python packages in the QGIS Python environment:
  - `numpy`
  - `scipy` (used for `scipy.interpolate.griddata`)

> Note: `scipy` is not always available in default QGIS installations.  
> If interpolation tools fail, install SciPy in the QGIS Python environment.

---

## Installation

### Install from ZIP (recommended for users)

1. Download the plugin ZIP from GitHub Releases.
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**
3. Select the ZIP and install.
4. Restart QGIS if required.

### Development install

Copy (or symlink) the plugin folder into your QGIS profile plugins directory:

- Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
- macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
- Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`

Restart QGIS.

---

## Typical workflow

1. Load a raster and set it as the active layer.
2. Use **Create Editable Copy** (recommended).
3. Draw an area on the map canvas:
   - Suppress unwanted objects → **Suppress Zone**
   - Repair gaps/defects → **Interpolate Zone** (choose method: nearest/linear/cubic)
4. Use **Undo/Redo** to iterate safely.

---

## Limitations / Notes

- Editing currently targets **band 1**.
- Large selections can be slow (masking/interpolation cost grows with area).
- Some raster sources may not support writing back reliably; the editable copy workflow is recommended.

---

## License

MIT License (see `LICENSE`).
