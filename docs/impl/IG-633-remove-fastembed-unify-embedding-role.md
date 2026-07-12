# IG-633: Remove fastembed — unify on embedding LLM role

**Created**: 2026-07-12  
**Status**: Implemented  
**Related**: [IG-411](archive/IG-411-worker-pool-robustness.md) (historical fastembed warmup)

---

## Summary

Removed `fastembed` / `onnxruntime` from core `soothe` dependencies. Local ONNX embeddings in `soothe.utils.similarity` had no production callers; Skillify, MemU, and vector stores already use `config.create_embedding_model()` (router `embedding` role).

---

## Removed

- `fastembed` from `packages/soothe/pyproject.toml`
- `packages/soothe/src/soothe/utils/similarity.py`
- `scripts/warmup_embedding_model.py`
- `soothed warmup` CLI command
- Docker embedding-cache warmup stage
- `embedding_warmup_check` health check

---

## Added / replaced

- `embedding_role_check` — doctor verifies `router.embedding` is explicitly set

---

## Verification

```bash
./scripts/verify_finally.sh
```
