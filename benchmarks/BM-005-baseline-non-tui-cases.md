# BM-005: Baseline Non-TUI Cases

**Date**: 2026-05-06
**Purpose**: Baseline tests for basic functionalities and performance of Soothe agent in non-TUI mode
**Environment**: macOS arm64, Python 3.12

## Test Cases

### Case 1: Read last 10 lines of project README

**Query**: "Read the last 10 lines of the project README.md file"

**Response**:
```
The last 10 lines of the project README.md file are:

```
- [RFC-600](docs/specs/RFC-600-plugin-extension-system.md) - Plugin system design

### 🛠️ For Developers

- **[CLAUDE.md](CLAUDE.md)** - Development guide for AI agents
- **[Implementation Guides](docs/impl/)** - Detailed implementation documentation

## License

MIT
```
```

**Runtime**: 26.30 seconds

---

### Case 2: Count all README files

**Query**: "Count all README files in this project"

**Response**:
```
The project contains **71 README files** total. Breaking this down:

- **1** project root README (`/README.md`)
- **4** package-level READMEs in `/packages/`
- **5** in `/client/`, `/benchmarks/`, `/docs/`, `/examples/`, `/_bmad/`
- **1** in `.pytest_cache/`
- **60** in `.venv/` (virtual environment dependencies - not part of the actual project)

If you exclude the virtual environment (`.venv`) and cache files, the project itself has **11 README files**.
```

**Runtime**: 16.42 seconds

---

### Case 3: Count all file types

**Query**: "Count all file types in this project and show the distribution"

**Response**:
```
# File Type Distribution Analysis Report

## Summary

This project is a **Claude Code skills repository** (BMAD - Build Me A Doctor) containing specialized AI agent workflows and testing tools. The codebase consists of **2,822 source files** (excluding compiled Python `.pyc` files) or **3,886 total files** including compiled artifacts.

**Key Characteristics:**
- Documentation-heavy project (39.5% Markdown files)
- Python-driven automation (29.4% Python scripts)
- Configuration-intensive architecture (25.8% JSON/YAML/CSV/TOML)
- Structured as a skills library with  70+ specialized skill modules

---

## File Type Distribution

### Primary File Types (Source Files Only)

| File Type | Count | Percentage | Visual |
|-----------|-------|------------|--------|
| **.md** (Markdown) |  1,114 |  39.5% | █████████████ |
| **.py** (Python) |  830 |  29.4% | █████████ |
| **.json** (JSON) |  669 |  23.7% | ███████ |
| **.yaml/.yml** (YAML) |  60 |  2.1% | |
| **.csv** (CSV) |  33 |  1.2% | |
| **.go** (Go) |  21 |  0.7% | |
| **.ts** (TypeScript) |  21 |  0.7% | |
| **.toml** (TOML) |  14 |  0.5% | |
| **.sh** (Shell) |  6 |  0.2% | |
| **.xml** (XML) |  5 |  0.2% | |
| **Other/Misc** |  49 |  1.7% | |

### Category Breakdown

| Category | Count | Percentage | Purpose |
|----------|-------|------------|---------|
| **Markdown Docs** |  1,114 |  39.5% | Skill documentation, workflows, templates |
| **Python Scripts** |  830 |  29.4% | Automation scripts, skill logic, utilities |
| **JSON Config/Data** |  669 |  23.7% | Manifests, settings, structured data |
| **YAML Config** |  60 |  2.1% | Workflow definitions, CI/CD configs |
| **CSV Data** |  33 |  1.2% | Reference data, module mappings |
| **TypeScript** |  21 |  0.7% | Testing utilities (Playwright-related) |
| **Go Code** |  21 |  0.7% | Backend testing tools |
| **Other** |  74 |  2.6% | Shell, TOML, XML, images, etc. |

---

## Key Findings

###  1. Dominant Technologies

- **Markdown (39.5%)**: Primary format for skill documentation, workflow steps, templates, and reference materials
- **Python (29.4%)**: Core automation language for skill execution, scripts, and tooling
- **JSON (23.7%)**: Heavy use for skill manifests, configuration files, and data storage

###  2. Project Structure Analysis

- **Primary Directory**: `.claude/` contains  957 files (33.9%) - the main skills library
- **Secondary**: `_bmad/` contains core configuration and module definitions
- **Distribution**: `dist/` folder suggests build artifacts

###  3. Representative Files by Category

**Documentation Examples:**
- `/README.md` - Project overview
- `/.claude/skills/bmad-create-prd/SKILL.md` - Skill definition
- `/.claude/skills/bmad-testarch-atdd/workflow.md` - Workflow documentation

**Python Examples:**
- `/.claude/skills/bmad-bmb-setup/scripts/merge-config.py` - Configuration merger
- `/.claude/skills/bmad-distillator/scripts/analyze_sources.py` - Source analysis
- `/.claude/skills/bmad-agent-builder/scripts/generate-html-report.py` - Report generator

**Configuration Examples:**
- `/pyproject.toml` - Python project configuration
- `/.claude/settings.local.json` - Local settings
- `/_bmad/core/config.yaml` - Core module configuration

**Total Files Analyzed:**  3,886 (including compiled) /  2,822 (source only)
```

**Runtime**: ~326 seconds (5:26)

---

### Case 4: Analyze soothe-sdk code structure

**Query**: "Analyze the code structure of the soothe-sdk package"

**Response**:
```
ERROR: AttributeError: 'StatusAssessment' object has no attribute 'assessment_reasoning'

This case encountered an error during execution. The agent failed to complete the analysis due to an internal AttributeError related to StatusAssessment.
```

**Runtime**: 391.35 seconds (6:31.35)

**Status**: ❌ Failed with error

---

## Summary

| Case | Query | Runtime | Status |
|------|-------|---------|--------|
| 1 | Read last 10 lines of README | 26.30s | ✅ Success |
| 2 | Count all README files | 16.42s | ✅ Success |
| 3 | Count all file types | ~326s (5:26) | ✅ Success |
| 4 | Analyze soothe-sdk structure | 391.35s (6:31) | ❌ Error |

**Total Runtime**: ~760 seconds (~12:40)

**Success Rate**: 3/4 (75%)
