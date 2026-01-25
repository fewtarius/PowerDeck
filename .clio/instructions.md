# PowerDeck-dist - CLIO Instructions

**Project:** PowerDeck Distribution Package  
**Language:** TypeScript/React (frontend) + Python (backend)  
**Type:** Decky Loader Plugin distribution for Steam Deck  

## Project Overview

PowerDeck-dist is the distribution package for PowerDeck, an advanced power management plugin for Decky Loader on Steam Deck and handheld gaming devices.

**Distribution Contents:**
- Compiled React frontend bundle
- Python backend power management logic
- Build artifacts and compiled libraries
- Plugin manifest and configuration

## Code Standards

### Distribution Package
- **Artifacts**: Pre-built, ready-to-deploy binaries
- **Version Synchronization**: VERSION file matches source
- **Plugin Manifest**: Valid `plugin.json` with correct metadata
- **Build Scripts**: Reproducible builds from source

### Backend Components (RyzenAdj, etc.)
- **C Libraries**: Cross-platform power management tools
- **Build System**: CMake for portable compilation
- **Platform Support**: Various handheld architectures (AMD, ARM, Intel)

## Using CLIO With This Project

### Common Tasks

**Verify distribution package:**
```bash
clio --input "Check that PowerDeck-dist contains all necessary files and is ready to ship"
```

**Update version information:**
```bash
clio --input "Update VERSION and plugin.json to reflect new PowerDeck release"
```

**Document build process:**
```bash
clio --input "Review build scripts and create documentation for building PowerDeck from source"
```

## Distribution Checklist

- [ ] VERSION file is current
- [ ] `plugin.json` is valid JSON and complete
- [ ] All compiled artifacts present and current
- [ ] README.md is accurate and user-friendly
- [ ] Plugin loads successfully in Decky Loader
- [ ] Features documented for users
- [ ] Known issues/limitations documented
- [ ] Build instructions present if applicable

## Key Files

| File | Purpose |
|------|---------|
| `VERSION` | Plugin version |
| `plugin.json` | Plugin metadata and manifest |
| `README.md` | User documentation |
| `dist/` | Compiled frontend React bundle |
| `backend/` | Python plugin backend |
| `RyzenAdj/` | Power management tool source |
| Build scripts | `build.sh`, `create-dist.sh`, etc. |

## Release Workflow

1. Confirm all features complete in source
2. Update VERSION file with new version
3. Update plugin.json manifest
4. Rebuild all artifacts (`create-dist.sh`)
5. Test plugin loads and functions in Decky
6. Update README.md with any new features
7. Tag release in git
8. Create GitHub release with changelog

## Notes

- PowerDeck is a production plugin—stability is critical
- Version management must be precise for updates to work
- Users depend on clear documentation
- Power management affects device stability—test thoroughly before releasing
