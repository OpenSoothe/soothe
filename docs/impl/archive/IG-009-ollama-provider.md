# Ollama Provider Implementation Guide

**Guide**: IG-009
**Title**: Ollama Provider Support
**Created**: 2026-03-12
**Related RFCs**: RFC-001

## Overview

Add native Ollama support as a Soothe model provider. Ollama runs LLMs locally and
exposes them via an API compatible with langchain-ollama. This guide also fixes a bug
in `_provider_kwargs()` where OpenAI-specific kwargs are unconditionally applied to
all provider types.

## Prerequisites

- [x] IG-008 completed (Config and Docs Revision)
- [x] Ollama installed locally (`ollama serve`)

## Changes

### 1. Optional dependency

Add `langchain-ollama` as an optional extra in `pyproject.toml`, following the same
pattern as `browser`, `claude`, etc.

### 2. Bug fix: `_provider_kwargs()` in `config.py`

`use_responses_api=False` is OpenAI-specific. When passed to `ChatOllama` via
`init_chat_model("ollama:...")`, it causes an unexpected-kwarg error. Guard it
behind a `provider_type == "openai"` check.

### 3. Config examples

Add Ollama provider blocks in `config/config.yml` and `config.dev.yml` showing
the native `provider_type: ollama` approach with common local models.

### 4. Env and docs

Add `OLLAMA_BASE_URL` to `config/env.example` and document the `ollama` extra in
`docs/user_guide.md`.

## Verification

- [ ] `langchain-ollama` listed as optional dep
- [ ] `_provider_kwargs()` does not add `use_responses_api` for non-openai providers
- [ ] `config/config.yml` shows Ollama example
- [ ] `config/env.example` includes `OLLAMA_BASE_URL`
- [ ] `docs/user_guide.md` lists `ollama` extra
- [ ] ruff lint clean

## Related Documents

- [IG-008](./008-config-docs-revision.md) - Config and Docs Revision
- [RFC-001](../specs/RFC-001-core-modules-architecture.md) - Core Modules Architecture Design
