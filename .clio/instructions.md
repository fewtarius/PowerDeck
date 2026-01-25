# CLIO Project Instructions - PowerDeck Distribution

**Project:** PowerDeck Distribution Package  
**Language:** TypeScript/React (frontend) + Python (backend) + C (RyzenAdj)  
**Type:** Decky Loader Plugin for Steam Deck and Handheld Gaming Devices  
**Purpose:** Advanced power management and performance tuning for handheld devices


## CRITICAL: READ FIRST BEFORE ANY WORK

### The Unbroken Method (Core Principles)

This project follows **The Unbroken Method** for human-AI collaboration. This isn't just project style—it's the core operational framework.

**The Seven Pillars:**

1. **Continuous Context** - Never break the conversation. Maintain momentum through collaboration checkpoints.
2. **Complete Ownership** - If you find a bug, fix it. No "out of scope."
3. **Investigation First** - Read code before changing it. Never assume.
4. **Root Cause Focus** - Fix problems, not symptoms.
5. **Complete Deliverables** - No partial solutions. Finish what you start.
6. **Structured Handoffs** - Document everything for the next session.
7. **Learning from Failure** - Document mistakes to prevent repeats.

**If you skip this, you will violate the project's core methodology.**

### Collaboration Checkpoint Discipline

**Use `user_collaboration` tool at EVERY key decision point:**

| Checkpoint | When | Purpose |
|-----------|------|---------|
| Session Start | Always | Confirm context & plan |
| After Investigation | Before implementation | Share findings, get approval |
| After Implementation | Before commit | Show results, get OK |
| Session End | When work complete | Summary & handoff |

**[FAIL]** Create documentation/implementations alone  
**[OK]** Investigate freely, but checkpoint before committing changes


## Quick Start for NEW DEVELOPERS

### Before Touching Code

1. **Understand the system:**
   ```bash
   cat README.md                    # Distribution overview
   ls -la dist/ backend/            # Check package structure
   cat plugin.json                  # Plugin manifest
   ls -la RyzenAdj/                 # Power management tool
   ```

2. **Know the standards:**
   - Distribution packages are **pre-built artifacts** ready to deploy
   - VERSION file must be synchronized with source repository
   - `plugin.json` must be valid JSON with complete metadata
   - RyzenAdj binaries must be architecture-specific (x86_64, aarch64)
   - All artifacts must be reproducible from source
   - Power management affects **device stability** - testing is critical

3. **Use the toolchain:**
   ```bash
   # Verify package integrity
   cat VERSION
   cat plugin.json
   ls -la dist/ backend/ RyzenAdj/
   
   # Check git status
   git status
   git log --oneline -10
   ```

### Core Workflow

```
1. Read current state (investigation)
2. Use collaboration tool (get approval)
3. Update artifacts/metadata (implementation)
4. Verify completeness (testing on actual hardware)
5. Commit with clear message (handoff)
```


## Key Directories & Files

### Distribution Contents
| File/Directory | Purpose | Status |
|----------------|---------|--------|
| `VERSION` | Current plugin version (sync with source) | **CRITICAL** |
| `plugin.json` | Plugin manifest and metadata | **CRITICAL** |
| `README.md` | User-facing documentation | [OK] Complete |
| `dist/` | Compiled React frontend bundle | [OK] Pre-built |
| `backend/` | Python plugin backend code | [OK] Pre-built |
| `main.py` | Backend entry point | [OK] Complete |
| `RyzenAdj/` | Power management tool binaries | **CRITICAL** |
| `build.sh` | Build script (if applicable) | [OK] Reference |
| `create-dist.sh` | Distribution creation script | [OK] Reference |

### Hardware Support
| Platform | CPU | Status | Notes |
|----------|-----|--------|-------|
| Steam Deck | AMD Zen 2 (Van Gogh APU) | [OK] Primary target |
| ROG Ally | AMD Zen 4 (Phoenix APU) | [OK] Supported |
| GPD Win | Various Intel/AMD | [OK] Partial support |
| Other handhelds | ARM, AMD, Intel | [VARIES] Device-specific |

### Key Features to Document
- **TDP Control** - Thermal Design Power adjustment
- **CPU/GPU Frequency** - Performance tuning
- **Fan Curves** - Custom fan speed profiles
- **Per-Game Profiles** - Automatic power settings per game
- **Battery Management** - Charge limiting, power draw monitoring
- **Performance Overlays** - Real-time stats display


## Architecture Overview

```
Steam Deck / Handheld Device (Decky Loader)
    v
PowerDeck Plugin Loaded
    v
React Frontend (dist/)
    ├─ TDP Slider Controls
    ├─ Fan Curve Editor
    ├─ Per-Game Profile Manager
    ├─ Performance Monitoring Display
    └─ Settings Panel
    v
Python Backend (backend/)
    ├─ Game Detection (Steam library)
    ├─ Profile Management (load/save/apply)
    ├─ RyzenAdj Integration (call binary)
    ├─ System Monitoring (temps, power, etc.)
    └─ Hardware Detection (CPU/GPU model)
    v
RyzenAdj Tool (C binary)
    ├─ CPU Power Limits (PPT, TDC, EDC)
    ├─ GPU Power/Frequency
    ├─ Thermal Limits
    └─ Direct Hardware Access (MSRs, PCI)
    v
Hardware (CPU/GPU/Fans)
```


## Code Standards: MANDATORY

### Version Management
```bash
# [CORRECT] Always sync VERSION with source tag
echo "2.1.0" > VERSION
# Update plugin.json to match
```

### Plugin Manifest (plugin.json)
```json
{
  "name": "PowerDeck",
  "version": "2.1.0",
  "author": "Author Name",
  "description": "Advanced power management for handheld gaming devices",
  "main": "main.py",
  "api_version": 1
}
```

**Requirements:**
- Must be valid JSON (no trailing commas, proper escaping)
- Version must match VERSION file exactly
- All required fields present
- Description is user-facing, clear and concise

### RyzenAdj Binary Management
```bash
# [CORRECT] Architecture-specific binaries
RyzenAdj/ryzenadj_x86_64    # For AMD64/x86_64 systems
RyzenAdj/ryzenadj_aarch64   # For ARM64 systems (if supported)

# [FAIL] Single binary for all architectures
RyzenAdj/ryzenadj           # Won't work across platforms
```


## Distribution Maintenance Standards

### Before ANY Commit

```bash
# 1. Verify VERSION file is current
cat VERSION

# 2. Verify plugin.json is valid JSON
python3 -m json.tool plugin.json > /dev/null && echo "Valid JSON"

# 3. Check that version numbers match
grep '"version"' plugin.json
cat VERSION

# 4. Verify all artifacts present
ls -la dist/index.js backend/main.py RyzenAdj/ryzenadj*

# 5. README matches current features
cat README.md

# 6. Check RyzenAdj binary permissions (must be executable)
ls -l RyzenAdj/ryzenadj*
```

### Checklist Before Release

- [ ] VERSION file updated to new version
- [ ] `plugin.json` version matches VERSION file
- [ ] `plugin.json` is valid JSON
- [ ] All compiled artifacts present in `dist/`
- [ ] Backend Python code is complete in `backend/`
- [ ] RyzenAdj binaries present for target architectures
- [ ] RyzenAdj binaries have execute permissions
- [ ] README.md is current and user-friendly
- [ ] Changelog/release notes updated
- [ ] Plugin loads successfully in Decky Loader
- [ ] Core features verified working (TDP, fan curves, profiles)
- [ ] **CRITICAL: Tested on actual hardware** (power management can break devices)
- [ ] No debug output or development artifacts
- [ ] Known limitations documented


## Testing Requirements

### CRITICAL: Hardware Testing is MANDATORY

**PowerDeck controls critical system hardware. Incorrect power settings can:**
- Overheat the device
- Cause system crashes
- Reduce hardware lifespan
- Drain battery faster than charging

**Before ANY release, test on actual hardware.**

### Manual Plugin Testing

```bash
# 1. Deploy to Steam Deck / handheld test device
# (Copy plugin directory to Decky plugins folder)

# 2. Restart Decky Loader service
sudo systemctl restart plugin_loader

# 3. Verify plugin appears in Decky menu

# 4. Test core features (SAFELY):
# - Apply conservative TDP settings (start low)
# - Monitor temperatures during gameplay
# - Test fan curve adjustments (listen for fan changes)
# - Create and apply per-game profile
# - Verify settings persist across reboots
# - Test battery charge limiting
# - Check performance overlay accuracy

# 5. Monitor for issues:
# - System crashes or freezes
# - Thermal throttling
# - Unexpected shutdowns
# - Fan behavior abnormalities

# 6. Check for errors in Decky logs
journalctl -u plugin_loader -n 100

# 7. Verify RyzenAdj output
# Backend should log RyzenAdj command results
```

### Safety Testing Checklist

- [ ] TDP limits are within safe ranges for device
- [ ] Temperature monitoring works correctly
- [ ] Fan control doesn't disable fans completely
- [ ] CPU/GPU frequencies are within spec
- [ ] System remains stable under load
- [ ] Battery management doesn't damage battery
- [ ] Settings revert to safe defaults if plugin disabled


## Commit Workflow

### Commit Message Format
```bash
type(scope): brief description

Problem: What was missing/incorrect/outdated
Solution: How you fixed it
Testing: How you verified the fix (INCLUDE HARDWARE TESTING)
```

**Types:** release, fix, docs, chore  
**Scope:** version, manifest, dist, backend, ryzenadj, docs

**Example:**
```bash
git add VERSION plugin.json README.md
git commit -m "release(version): update PowerDeck to v2.1.0

Problem: Distribution package out of sync with source v2.1.0
Solution: Updated VERSION, plugin.json, README with new fan curve features
Testing: Verified on Steam Deck - TDP control, fan curves, profiles all functional, temps stable under load"
```


## Anti-Patterns: NEVER DO THESE

| Anti-Pattern | Why | What To Do Instead |
|--------------|-----|-------------------|
| Edit built artifacts directly | Changes will be overwritten | Update source, rebuild |
| Mismatched version numbers | Breaks Decky update mechanism | Always sync VERSION and plugin.json |
| Invalid JSON in plugin.json | Plugin won't load | Validate with `json.tool` |
| Skip hardware testing | Can damage devices | **ALWAYS test on real hardware** |
| Assume safe power limits | Different devices have different specs | Research device-specific limits |
| Release without monitoring temps | Can cause overheating | Test under load, monitor temps |
| Hardcode device-specific values | Breaks compatibility | Detect hardware, use appropriate values |
| Missing RyzenAdj binary | Plugin core feature breaks | Always include binaries for target platforms |


## Release Process

```
1. Confirm source repository is ready
   - All features complete and tested on hardware
   - Source tagged with version number
   
2. Build artifacts from source
   - Frontend: npm run build
   - Backend: ensure all .py files present
   - RyzenAdj: compile for target architectures or include pre-built
   
3. Update VERSION file
   - Match source repository tag
   
4. Update plugin.json
   - Version matches VERSION file
   - Validate JSON syntax
   
5. Update README.md
   - Document new features
   - Update safety warnings if power limits changed
   - Document supported devices
   
6. HARDWARE TEST (MANDATORY)
   - Deploy to test device (Steam Deck, ROG Ally, etc.)
   - Test all power management features
   - Monitor system stability
   - Verify safe operation under load
   - Check temperature and fan behavior
   
7. Check for errors
   - Review Decky Loader logs
   - Verify no crash dumps
   
8. Commit and tag
   - Clear commit message with testing details
   - Tag with version: git tag v2.1.0
   
9. Push to repository
   - Push commits: git push
   - Push tags: git push --tags
```


## Session Handoff Procedures (MANDATORY)

### CRITICAL: Session Handoff Directory Structure

When ending a session, **ALWAYS** create a properly structured handoff directory:

```
ai-assisted/YYYYMMDD/HHMM/
├── CONTINUATION_PROMPT.md  [MANDATORY] - Next session's complete context
├── AGENT_PLAN.md           [MANDATORY] - Remaining priorities & blockers
├── CHANGELOG.md            [OPTIONAL]  - User-facing changes (if applicable)
└── NOTES.md                [OPTIONAL]  - Additional technical notes
```

**NEVER COMMIT** `ai-assisted/` directory to git. Always verify before committing:

```bash
git status  # Ensure no ai-assisted/ files staged
git add -A
git status  # Double-check
git commit -m "message"
```


## Documentation

### What Needs Documentation

- **New features** - Update README.md with user-facing description
- **Version changes** - Update VERSION and plugin.json
- **Breaking changes** - Document in README with migration guide
- **Safety warnings** - Prominently display any new risks
- **Device support changes** - Update supported device list
- **Known issues** - Add to README or separate KNOWN_ISSUES.md
- **Installation changes** - Update installation instructions

### Documentation Standards

- **User-focused** - Readers are handheld device owners, not developers
- **Safety-first** - Warn about risks before features
- **Clear and concise** - Short paragraphs, bullet points
- **Actionable** - Tell users what to do, not just what exists
- **Device-specific** - Note which features work on which devices
- **Current** - Remove outdated information immediately


## Notes

- This is a **distribution package** - source code lives elsewhere
- Keep synchronized with source repository for consistency
- Users depend on VERSION and plugin.json for updates
- README is the primary user documentation - keep it accurate
- **Power management is safety-critical** - thorough testing is mandatory
- Different devices have different power limits - document clearly
- RyzenAdj requires root permissions - handle errors gracefully
- Monitor community feedback for device-specific issues
- Performance tuning is iterative - users will experiment
- Battery health features are important - don't skip them
