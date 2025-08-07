# MKE Tools

A comprehensive Houdini package providing utility tools and HDAs for VFX pipeline management and workflow optimization.

![MKE Tools Logo](config/icons/mke_logo.svg)

## Table of Contents
- [Overview](#overview)
- [Installation](#installation)
- [Tools](#tools)
  - [Python Scripts](#python-scripts)
  - [HDAs (Houdini Digital Assets)](#hdas-houdini-digital-assets)
  - [Shelf Tools](#shelf-tools)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Contributing](#contributing)

## Overview

MKE Tools is a production-ready package designed to streamline VFX workflows in SideFX Houdini. It includes project setup automation, texture conversion utilities, version control helpers, and specialized LOP (Lighting/USD) nodes for modern USD-based pipelines.

## Installation

1. **Download/Clone** the MKE_Tools package to your Houdini packages directory:
   ```
   $HOUDINI_USER_PREF_DIR/packages/MKE_Tools
   ```

2. **Package Configuration**: The package automatically configures the following environment variables:
   - `MKETOOLS_DIR`: Points to the package directory
   - `HOUDINI_TOOLBAR_PATH`: Adds the toolbar directory
   - `HOUDINI_PATH`: Adds config/icons directory
   - `PYTHONPATH`: Adds scripts directory

3. **Restart Houdini** to load the tools.

## Tools

### Python Scripts

#### 🏗️ Project Setup (`projectSetup.py`)
**Purpose**: Automated project structure creation with industry-standard folder hierarchy.

**Features**:
- Interactive GUI for project configuration
- Customizable folder structure with presets for:
  - ASSET, CHARACTER, ENVIRONMENT, FX, RND projects
- Automatic environment variable setup (`$JOB`, `$HIP`, `$CACHE`)
- Initial .hip file creation with version naming
- Configurable cache directory location

**Typical Folder Structure Created**:
```
ProjectName/
├── 3D/
│   ├── CACHES/
│   └── SCENES/
├── USD/
├── PIPELINE/
├── REFERENCES/
├── _DAILIES/
├── IN/
│   ├── ASSETS/
│   ├── PROPS/
│   ├── CHARACTERS/
│   ├── ENVIRONMENT/
│   ├── CAMERAS/
│   └── TEXTURES/
└── OUT/
    └── [PROJECT_TYPE]/
```

#### 💾 Save Up (`saveUp.py`)
**Purpose**: Intelligent version increment for Houdini scene files.

**Features**:
- Automatic version number detection (e.g., `_v0001`, `_v0002`)
- Increments version and saves new file
- Handles unsaved scenes gracefully
- Maintains file naming conventions

#### 🎨 RAT Converter (`ratConverter.py`)
**Purpose**: Batch conversion of texture files to Houdini's RAT format for optimized rendering.

**Features**:
- Multi-threaded processing for fast conversion
- Recursive subdirectory scanning
- Progress tracking and cancellation support
- Automatic thread count optimization
- Support for common texture formats

#### 🔗 Houdini VSCode Integration (`houdiniVSC.py`)
**Purpose**: Generates VSCode configuration for Houdini Python development.

**Features**:
- Exports Python interpreter path
- Configures Python analysis paths
- Enables proper IntelliSense for Houdini modules
- JSON output for direct VSCode settings integration

### HDAs (Houdini Digital Assets)

All HDAs are LOP (Lighting/USD) nodes designed for modern USD workflows:

#### 📦 MKE Import (`lop_MKE.dev.mke_import.1.0.hdalc`)
- Specialized USD import node with enhanced pipeline integration
- Supports development workflow features

#### 💾 MKE File Cache (`lop_MKE.mke_filecache.1.0.hdalc`)
- Enhanced USD file caching with pipeline-aware features
- Optimized for production file management

#### 🎭 MKE Preference Assign (`lop_MKE.mke_pref_assign.1.0.hdalc`)
- USD preference and metadata assignment
- Streamlined attribute management

#### 🎬 MKE Render Layer (`lop_MKE.mke_render_layer.1.0.hdalc`)
- Advanced render layer management for USD
- Multi-layer rendering workflow support

#### 🚀 MKE Submitter (`lop_MKE.mke_submitter.1.1.hdalc`)
- Render farm submission integration
- Batch processing and queue management

### Shelf Tools

The MKE Tools shelf provides quick access to all utilities:

| Tool | Icon | Description |
|------|------|-------------|
| **Project Setup** | ![Project Setup](config/icons/projectSetup_logo.svg) | Launch project structure creation wizard |
| **RAT Converter** | ![RAT Converter](config/icons/mipmapGenerator_logo.svg) | Open texture conversion interface |
| **Save Up** | ![Save Up](config/icons/saveUp_logo.svg) | Increment version and save scene |
| **Houdini VSC** | ![Houdini VSC](config/icons/houdinivsc_logo.svg) | Generate VSCode configuration |

## Usage

### Quick Start

1. **Create a New Project**:
   - Click the "Project Setup" shelf tool
   - Choose project directory and configure settings
   - Select folder structure and cache location
   - Tool automatically sets up environment variables

2. **Convert Textures to RAT**:
   - Click "RAT Converter" shelf tool
   - Select texture directory
   - Configure threading and subdirectory options
   - Start batch conversion

3. **Version Control**:
   - Use "Save Up" to increment scene versions
   - Maintains `_v####` naming convention

4. **VSCode Integration**:
   - Click "Houdini VSC" to generate settings
   - Copy output to VSCode settings.json
   - Enables proper Python IntelliSense

### Environment Variables

The package sets up the following variables:
- `$JOB`: Project root directory
- `$HIP`: Houdini scene directory
- `$CACHE`: Cache files directory
- `$MKETOOLS_DIR`: Package installation directory

## Project Structure

```
MKE_Tools/
├── MKE_Tools.json          # Package configuration
├── README.md               # This file
├── config/
│   └── icons/             # UI icons and logos
├── otls/                  # Houdini Digital Assets (HDAs)
├── scripts/
│   └── python/            # Python utilities
│       └── ui/            # UI components
└── toolbar/
    └── mke_utils.shelf    # Houdini shelf definition
```

## Requirements

- **Houdini 20.5+** (tested on Houdini 20.5)
- **Python 3.7+** (included with Houdini)
- **PySide2** (included with Houdini)
- **Windows/Linux/macOS** compatible

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes and test thoroughly
4. Submit a pull request

### Development Guidelines

- Follow PEP 8 for Python code
- Include docstrings for all functions
- Test tools in production scenarios
- Update README for new features

## License

This project is part of the MKE Tools pipeline package.

## Support

For issues, feature requests, or questions:
- Create an issue in the repository
- Contact me

---

**MKE Tools** - Streamlining VFX workflows, one tool at a time.