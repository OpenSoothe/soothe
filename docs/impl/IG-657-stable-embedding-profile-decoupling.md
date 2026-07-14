# IG-657: Stable Embedding Profile Decoupling

## Goal

Keep embedding model selection and embedding dimensions stable across daemon restarts and independent from `/model-router` role switching.

## Scope

- Remove embedding settings from `router_profiles`.
- Introduce top-level `embedding_profile` as the single source of truth for:
  - `model_role` (embedding model spec)
  - `embedding_dims` (vector dimension)
- Keep process-level embedding behavior unchanged by loop-scoped router profile overlays.
- Update config examples, runtime validation, and tests.

## Implementation Notes

1. `ModelRouter` rejects legacy `embedding` field.
2. `RouterProfile` rejects legacy `embedding_dims`.
3. Add `EmbeddingProfile` model and `SootheConfig.embedding_profile`.
4. Resolve:
   - chat roles from active router profile (plus loop override)
   - embedding role/dims from `embedding_profile`
5. Update Skillify/vector-store diagnostics and health checks to reference `embedding_profile`.
6. Migrate project configs (`config/develop`, docker/deploy examples) to top-level embedding profile.

## Validation

- Unit tests for config parsing and router overlay behavior.
- Health check tests for embedding profile detection.
- Full repo verification via `./scripts/verify_finally.sh`.
