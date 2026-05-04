# IG-379: Langfuse Cost Dashboard bridge

## Goal

Make Soothe LLM runs easy to attribute and price in Langfuse’s **Cost Dashboard**: optional trace tags and user id in Runnable metadata, plus operator documentation for model definitions and verification.

## Scope

- `observability.langfuse.tags` (optional string list) and `observability.langfuse.user_id` (optional string, supports `${ENV}`) on `LangfuseIntegrationConfig`.
- `merge_langfuse_runnable_config` sets `langfuse_tags` / `langfuse_user_id` metadata when absent (LangChain `CallbackHandler` reads these for trace attributes).
- Template [`packages/soothe/src/soothe/config/config.yml`](packages/soothe/src/soothe/config/config.yml) and dev defaults [`config/config.dev.yml`](config/config.dev.yml).
- This guide: Cost Dashboard checklist, custom **model** `match_pattern` examples for Soothe / LangChain model ids, manual verification steps.

## Cost Dashboard checklist

1. **Dependencies**: `pip install 'soothe[langfuse]'` (see [`packages/soothe/pyproject.toml`](packages/soothe/pyproject.toml)).
2. **Soothe config**: `observability.langfuse.enabled`, keys, `host` (see [IG-367](IG-367-langfuse-observability.md)). Optional: `tags`, `user_id` (this IG).
3. **Langfuse UI**: After a run, open a **trace** → **Observations** → **generation** rows. Confirm **usage** (input/output tokens) is non-empty when the provider returns usage to LangChain.
4. **Pricing**: **Project Settings → Models** in Langfuse. Built-in catalog matches common API model ids (e.g. `gpt-4o`). For custom or prefixed ids, add a model definition with a **`match_pattern`** regex (see below).

## Model definition examples (Langfuse Project Settings → Models)

Langfuse matches the **generation `model`** string from LangChain/Langfuse ingestion to each definition’s `match_pattern`.

Typical Soothe paths use `init_chat_model("provider:model_id")`; Langfuse often records the **API model id** (e.g. `gpt-4o`, `claude-sonnet-4-5`) on `ChatOpenAI` / `ChatAnthropic`, which usually align with Langfuse’s maintained catalog. If your traces show a different string (gateway prefix, deployment name, Ollama tag), add a **custom model** with a regex, for example:

| Trace `model` example | Suggested `match_pattern` (illustrative) |
|----------------------|---------------------------------------------|
| `my-org-gpt-4o` | `(?i)^my-org-gpt-4o$` |
| `openai:gpt-4o` if shown literally | `(?i)^openai:gpt-4o$` |
| Local Ollama id | `(?i)^llama3\\.1:8b$` |

Set per-unit prices for the **usage detail keys** Langfuse shows for that provider (often `input` / `output`; OpenAI-style keys are mapped per [Langfuse model usage docs](https://langfuse.com/docs/model-usage-and-cost)).

## Manual verification (generations + usage)

1. Start Langfuse (e.g. `docker compose up -d` per IG-367).
2. Run Soothe with Langfuse enabled (e.g. `config/config.dev.yml`).
3. In Langfuse, pick a trace → expand a **Chat** / **generation** observation → confirm **Model** and **Usage** fields.
4. Open **Cost** / project cost views and confirm totals move after new traffic (pricing must exist for that model).

## Verification

Run `./scripts/verify_finally.sh` before merge.

Optional: `soothe doctor --config config/config.dev.yml --category observability` (Langfuse row should pass when keys and package are present).
