# IG-295: DeepXiv Integration

## Overview

Integrate DeepXiv SDK into Soothe for academic paper search and progressive reading capabilities.

## Requirements (from deepxiv_integration.md)

1. **Create DeepXiv toolkit** with 7 tools:
   - `deepxiv_search`: Paper search (semantic)
   - `deepxiv_paper_brief`: Quick summary (TLDR)
   - `deepxiv_paper_metadata`: Structure overview
   - `deepxiv_read_section`: Section content
   - `deepxiv_get_full_paper`: Complete paper
   - `deepxiv_trending`: Hot papers
   - `deepxiv_websearch`: Web search (20 tokens)

2. **Integrate tool to research subagent** as academic source

3. **Optimize research subagent**:
   - Move Wikipedia to web source
   - Remove BrowserSource
   - Enhance CLISource with tools: glob, grep, ls, read_file, file_info

## Files to Modify

### New Files
- `packages/soothe/src/soothe/toolkits/deepxiv.py` - DeepXiv toolkit implementation

### Modified Files
- `packages/soothe/src/soothe/core/resolver/_resolver_tools.py` - Add deepxiv dispatch
- `config/config.template.yml` - Add deepxiv config section
- `config/config.dev.yml` - Add deepxiv config section
- `packages/soothe/src/soothe/subagents/research/sources/academic.py` - Use DeepXiv instead of ArXiv
- `packages/soothe/src/soothe/subagents/research/sources/web.py` - Add Wikipedia
- `packages/soothe/src/soothe/subagents/research/sources/browser.py` - Remove (or deprecate)
- `packages/soothe/src/soothe/subagents/research/sources/cli.py` - Add file tools
- `packages/soothe/src/soothe/subagents/research/implementation.py` - Update source selection

## Implementation Plan

### Phase 1: DeepXiv Toolkit
- Create toolkit following Pattern 2 (Toolkit + BaseTool)
- Implement lazy Reader initialization
- Add comprehensive error handling
- Follow existing toolkit patterns (wizsearch, image, etc.)

### Phase 2: Research Subagent Optimization
- Update academic source to use DeepXiv
- Move Wikipedia from academic to web source
- Remove BrowserSource from default sources
- Enhance CLISource with filesystem tools

### Phase 3: Configuration
- Add deepxiv section to config files
- Add dispatch in resolver

### Phase 4: Verification
- Run `./scripts/verify_finally.sh`

## Progress

- [ ] DeepXiv toolkit created
- [ ] Resolver dispatch added
- [ ] Config updated
- [ ] Academic source updated
- [ ] Web source updated
- [ ] Browser source removed
- [ ] CLI source enhanced
- [ ] Tests passing
