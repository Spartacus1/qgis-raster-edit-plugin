# Raster Edit Plugin

[![QGIS](https://img.shields.io/badge/QGIS-3.10%2B-93b023?logo=qgis&logoColor=white)](https://qgis.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1-orange.svg)](https://github.com/Spartacus1/qgis-raster-edit-plugin/releases)

A QGIS plugin for **interactive raster editing**, enabling direct pixel-level modifications for cleanup and repair tasks. The plugin provides tools for masking unwanted features, filling gaps, and correcting local defects through interpolation.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Tools Reference](#tools-reference)
- [Usage](#usage)
- [Interpolation Methods](#interpolation-methods)
- [Output](#output)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [License](#license)
- [Author](#author)

---

## Overview

**Raster Edit Plugin** addresses common raster cleanup scenarios encountered in remote sensing, terrain analysis, and image processing workflows:

- Removing unwanted objects or artifacts (buildings, vehicles, noise)
- Filling gaps and NoData holes
- Correcting local defects or sensor errors
- Smoothing anomalous regions

The plugin operates on an **editable copy** of the original raster, ensuring non-destructive editing with full undo/redo support.

---

## Features

- Non-destructive workflow with automatic editable copy creation
- Interactive polygon drawing on map canvas
- Three editing tools:
  - **Suppress Zone** — mask areas to NoData
  - **Interpolate Zone** — fill NoData pixels using surrounding values
  - **Interpolate All** — replace all pixels in selected area (stronger repair)
- Three interpolation methods: linear, cubic, nearest
- Full **Undo/Redo** support for all edit operations
- Dedicated toolbar with visual feedback
- Preserves original raster data type and NoData value
- Support for multiple raster formats (GeoTIFF, etc.)

---

## Requirements

### Software

- **QGIS 3.10 or higher**

### Python Dependencies

The following packages must be available in the QGIS Python environment:

| Package | Purpose |
|---------|---------|
| `numpy` | Array operations and data type handling |
| `scipy` | Interpolation algorithms (`scipy.interpolate.griddata`) |

### Installing SciPy

SciPy may not be available in default QGIS installations. If interpolation tools fail:

**Windows (OSGeo4W Shell):**
```bash
python -m pip install scipy
```

**Linux:**
```bash
pip3 install --user scipy
```

**macOS:**
```bash
/Applications/QGIS.app/Contents/MacOS/bin/pip3 install scipy
```

---

## Installation

### From ZIP (Recommended)

1. Download the latest release ZIP from [Releases](https://github.com/Spartacus1/qgis-raster-edit-plugin/releases)
2. Open QGIS and navigate to **Plugins > Manage and Install Plugins**
3. Select **Install from ZIP**
4. Browse to the downloaded file and click **Install Plugin**
5. Restart QGIS if required

### Development Installation

Clone the repository directly into your QGIS plugins folder:

```bash
# Linux
cd ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
git clone https://github.com/Spartacus1/qgis-raster-edit-plugin.git

# macOS
cd ~/Library/Application\ Support/QGIS/QGIS3/profiles/default/python/plugins/
git clone https://github.com/Spartacus1/qgis-raster-edit-plugin.git

# Windows (PowerShell)
cd $env:APPDATA\QGIS\QGIS3\profiles\default\python\plugins\
git clone https://github.com/Spartacus1/qgis-raster-edit-plugin.git
```

Restart QGIS and enable the plugin in **Plugins > Manage and Install Plugins**.

---

## Tools Reference

### Toolbar Overview

The plugin adds a dedicated toolbar with the following tools:

| Icon | Tool | Description |
|------|------|-------------|
| Create Editable Copy | Creates a duplicate `*_edited` file for safe editing |
| Suppress Zone | Draw polygon to set pixels to NoData |
| Interpolate Zone | Draw polygon to interpolate NoData pixels only |
| Interpolate All | Draw polygon to interpolate all pixels in area |
| Method selector | Choose interpolation method (linear/cubic/nearest) |
| Undo | Revert last edit operation |
| Redo | Restore last undone operation |
| Activate Edit | Enable editing mode for selected layer |
| Deactivate Edit | Disable editing mode and clear undo history |

### Tool Details

#### Create Editable Copy

Creates a duplicate of the active raster with `_edited` suffix in the same directory. This ensures the original file remains untouched. The editable copy is automatically loaded and set as the active layer.

**Example:** `terrain.tif` becomes `terrain_edited.tif`

#### Suppress Zone

Converts all pixels within a user-drawn polygon to the raster's NoData value. Use this to:
- Remove unwanted objects (buildings, vehicles, vegetation)
- Mask out erroneous data regions
- Create holes for later interpolation

#### Interpolate Zone

Fills only the **NoData pixels** within the drawn polygon using values from surrounding valid pixels. Existing valid data inside the polygon is preserved. Use this to:
- Fill small gaps and holes
- Repair isolated NoData pixels
- Complete missing data areas

#### Interpolate All

Replaces **all pixels** within the drawn polygon (both valid and NoData) using interpolation from pixels outside the polygon boundary. Use this for:
- Smoothing anomalous regions
- Removing artifacts while preserving surface continuity
- Stronger repair when Interpolate Zone is insufficient

---

## Usage

### Quick Start

1. Load a raster layer in QGIS
2. Select the raster in the Layers panel
3. Click **Activate Edit** in the Raster Edit toolbar
4. Click **Create Editable Copy** (if not already an `*_edited` layer)
5. Select a tool (Suppress, Interpolate Zone, or Interpolate All)
6. Draw a polygon on the map:
   - **Left-click** to add vertices
   - **Right-click** to complete the polygon
   - **ESC** to cancel drawing
7. Use **Undo/Redo** as needed
8. Click **Deactivate Edit** when finished

### Step-by-Step Workflow

#### Removing an Unwanted Object

1. Activate editing on your raster
2. Create an editable copy
3. Select **Suppress Zone**
4. Draw a polygon around the object to remove
5. The area is converted to NoData
6. Select **Interpolate Zone**
7. Draw a slightly larger polygon around the same area
8. NoData pixels are filled with interpolated values

#### Repairing a Defective Region

1. Activate editing on your raster
2. Create an editable copy
3. Select interpolation method (e.g., "cubic" for smooth surfaces)
4. Select **Interpolate All**
5. Draw a polygon around the defective region
6. All pixels inside are replaced with interpolated values

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| **ESC** | Cancel current drawing operation |
| **Left-click** | Add vertex to polygon |
| **Right-click** | Complete polygon and execute tool |

---

## Interpolation Methods

The plugin offers three interpolation methods via `scipy.interpolate.griddata`:

| Method | Description | Best For |
|--------|-------------|----------|
| **linear** | Triangulated linear interpolation | General use, balanced results |
| **cubic** | Cubic spline interpolation | Smooth surfaces (terrain, gradients) |
| **nearest** | Nearest-neighbor assignment | Categorical data, sharp boundaries |

### Method Selection Guidelines

- **Linear** (default): Good all-purpose choice, handles most scenarios well
- **Cubic**: Produces smoother results but may overshoot near edges; best for continuous data like DEMs
- **Nearest**: Preserves original values at boundaries; use for classified rasters or when smoothing is undesirable

---

## Output

### Modified Raster

The plugin modifies the editable copy in place. No new files are created during editing operations. Changes are written directly to the `*_edited` raster file.

| Aspect | Behavior |
|--------|----------|
| File location | Same directory as original |
| File name | `<original_name>_edited.<ext>` |
| Data type | Preserved from original |
| NoData value | Preserved from original |
| CRS | Preserved from original |
| Extent | Preserved from original |

### Supported Data Types

The plugin supports all common raster data types:

- Byte (8-bit unsigned)
- UInt16 (16-bit unsigned)
- Int16 (16-bit signed)
- UInt32 (32-bit unsigned)
- Int32 (32-bit signed)
- Float32 (32-bit floating point)
- Float64 (64-bit floating point)

---

## Troubleshooting

### Common Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| Interpolation fails | SciPy not installed | Install scipy in QGIS Python environment |
| "Please select a raster layer" | Wrong layer type selected | Select a raster layer, not vector |
| Edit tools disabled | Layer not in edit mode | Click **Activate Edit** first |
| No visible changes | Layer not repainted | Trigger refresh or toggle layer visibility |
| Slow interpolation | Large polygon area | Use smaller polygons or nearest method |
| Undo not working | Edit mode deactivated | Undo history is cleared when edit mode is deactivated |

### Checking Dependencies

Open the QGIS Python Console (**Plugins > Python Console**) and run:

```python
import numpy
import scipy
from scipy.interpolate import griddata
print("All dependencies OK")
```

### Plugin Not Appearing

1. Verify the plugin folder is in the correct location
2. Check that all files are present (`__init__.py`, `main.py`, `rasteredition.py`, etc.)
3. Restart QGIS
4. Enable the plugin in **Plugins > Manage and Install Plugins > Installed**

---

## Limitations

- **Single band editing**: Currently operates on **band 1** only
- **Performance**: Large polygon selections can be slow due to pixel-by-pixel masking and interpolation
- **Memory**: Very large edit areas may consume significant memory
- **Format support**: Some raster formats may not support in-place writing; GeoTIFF is recommended
- **Undo persistence**: Undo/Redo history is cleared when edit mode is deactivated or QGIS is closed

---

## Roadmap

- Multi-band support
- Batch processing for multiple regions
- Additional interpolation methods (kriging, IDW)
- Performance optimization for large areas
- Persistent undo history

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-feature`)
3. Commit your changes (`git commit -am 'Add new feature'`)
4. Push to the branch (`git push origin feature/new-feature`)
5. Open a Pull Request

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

## Author

**Renato Henriques**  
University of Minho, Portugal  
rhenriques@dct.uminho.pt

---

## Citation

If you use this plugin in your research, please cite:

```bibtex
@software{henriques2025rasteredit,
  author = {Henriques, Renato},
  title = {Raster Edit Plugin: Interactive Raster Editing for QGIS},
  year = {2025},
  url = {https://github.com/Spartacus1/qgis-raster-edit-plugin}
}
```

---

## Acknowledgments

- University of Minho, Department of Earth Sciences; Institute of Earth Sciences
