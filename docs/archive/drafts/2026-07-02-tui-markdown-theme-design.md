# TUI Markdown Theme Registry

**Status**: Draft  
**Date**: 2026-07-02  
**Kind**: Design (Platonic Coding — brainstorm handoff)  
**Related**: RFC-500 (CLI TUI architecture), IG-533 (goal-completion TUI lifecycle)  
**Scope**: `soothe-cli` TUI markdown rendering only (headless stdout unchanged)

---

## 1. Problem

Goal-completion and other assistant markdown cards are rendered with **Rich** (`rich.markdown.Markdown`) inside `AssistantMessage`. Today this is split across three ad-hoc mechanisms:

| Concern | Current location | User-facing clarity |
|---------|------------------|---------------------|
| TUI chrome (borders, cognition accent) | `theme.py` → `ThemeEntry.REGISTRY` | Good — `/theme` picker uses display labels |
| Pygments code blocks | `_CODE_THEME_MAP` in `_helpers.py` | Poor — internal Pygments names (`monokai`, `gruvbox-dark`) |
| Rich element styles (headings, links, lists) | `_markdown_styles_from_theme_colors()` | Poor — only enabled via `theme_markdown=True` on goal-completion cards |

A work-in-progress path adds `ThemedMarkdown`, `theme_markdown` on widgets, and `assistant_theme_markdown` on `MessageData`. That fixes goal-completion styling but introduces a **second boolean** instead of a coherent, configurable markdown appearance system.

Users cannot choose how markdown reads in the TUI except toggling `--no-render-markdown`. There is no named preset, no config persistence, and no parity with how TUI themes are registered and labeled.

---

## 2. Goals

1. **One markdown appearance knob** — named presets, CLI flag, optional config file.
2. **User-friendly names everywhere users see them** — CLI help, config comments, future picker; stable internal IDs for scripts.
3. **Polished Rich markdown** — headings, links, blockquotes, lists, tables, inline code, and fenced code blocks feel intentional, not Rich defaults with a random Pygments theme.
4. **Minimal scope** — no daemon protocol changes; resumed transcripts re-render with the **current** markdown theme (same as TUI theme on resume today).

---

## 3. Non-goals (v1)

- Headless / JSONL markdown styling
- Desktop or web clients
- User-defined markdown themes in `config.yml` (defer to v2; registry API should allow it)
- `/markdown-theme` slash command or theme-picker sub-UI (CLI + config sufficient for v1)
- Persisting markdown theme choice per message in the card ledger

---

## 4. Naming model

Follow the existing TUI theme pattern: **stable internal ID** + **display label** + **short description**.

### 4.1 Internal IDs (CLI, config, code)

Lowercase kebab-case. Used in:

- `soothe --markdown-theme <id>`
- `ui.markdown_theme` in `~/SOOTHE_HOME/config/config.yml`
- `MarkdownThemeEntry.REGISTRY` keys

### 4.2 Display labels (help text, logs, future picker)

Title case, plain language. Never expose Pygments or Rich identifiers to users.

### 4.3 Built-in markdown themes (v1)

| ID | Display label | One-line description | Code highlighting* |
|----|---------------|----------------------|--------------------|
| `match-app` | Match App Theme | Headings, links, and inline code follow your current TUI theme | Follows TUI theme (see §4.4) |
| `langchain` | LangChain | LangChain brand colors (dark) | Monokai |
| `langchain-light` | LangChain Light | LangChain brand colors (light) | Default (light) |
| `standard` | Standard | Neutral Rich markdown styling | Monokai (dark) / Default (light) |
| `minimal` | Minimal | Body text first; subdued headings and accents | Same as `standard` |

\* **Code highlighting** is the Pygments theme for fenced blocks. It is bundled inside each markdown theme entry — users never pick Pygments names directly in v1.

**Default**: `match-app` — matches mental model of “markdown looks like the rest of my terminal UI.”

**Renames from earlier internal brainstorm** (do not ship these IDs):

| Old internal name | New ID | Rationale |
|-------------------|--------|-----------|
| `follow-tui` | `match-app` | “Match App Theme” reads naturally in help text |
| `rich-default` | `standard` | Avoid library name in user-facing preset |
| `plain` | `minimal` | “Minimal” describes intent, not “plain text” |
| `langchain-dark` | `langchain` | Align with existing TUI theme id `langchain` |

### 4.4 TUI theme → code highlighting map (internal only)

When `markdown_theme` is `match-app`, fenced blocks use a Pygments theme keyed by the **active TUI theme name**. This replaces `_CODE_THEME_MAP` in `_helpers.py` and lives inside `markdown_theme.py`.

| TUI theme ID | Pygments (internal) |
|--------------|---------------------|
| `langchain`, `textual-dark`, `catppuccin-*`, `tokyo-night`, … | `monokai` |
| `langchain-light`, `textual-light`, `solarized-light`, … | `default` |
| `dracula` | `dracula` |
| `gruvbox` | `gruvbox-dark` |
| `nord` | `nord` |
| `solarized-dark` | `solarized-dark` |
| `atom-one-dark` | `one-dark` |
| `textual-ansi` | `default` |
| Unknown / unset | Infer from background luminance (`monokai` vs `default`) |

Element colors for `match-app` always come from `get_theme_colors(app)` at render time so `/theme` changes apply on the next markdown flush.

---

## 5. Architecture

### 5.1 New module: `soothe_cli/tui/markdown_theme.py`

Single source of truth for markdown appearance (mirrors `theme.py` for TUI chrome).

```python
@dataclass(frozen=True)
class MarkdownThemeEntry:
    id: str                    # registry key, e.g. "match-app"
    label: str                 # "Match App Theme"
    description: str           # one line for CLI help
    dark: bool                 # default polarity for fixed palettes
    code_theme: str            # Pygments name (internal)
    style_source: Literal["app-colors", "fixed"]
    fixed_colors: ThemeColors | None = None  # when style_source == "fixed"
```

**Registry** (class-level, like `ThemeEntry.REGISTRY`):

- `match-app` → `style_source="app-colors"`, code theme from TUI map
- `langchain` / `langchain-light` → fixed `DARK_COLORS` / `LIGHT_COLORS`
- `standard` → app-colors for elements OR fixed neutral recipe (TBD in impl — prefer fixed neutral grays + primary accent only)
- `minimal` → fixed recipe: foreground body, muted headings, no link underline emphasis

**Public API**:

```python
def resolve_markdown_theme(name: str | None = None) -> MarkdownThemeEntry: ...
def build_markdown(content: str, *, widget_or_app: object | None = None) -> Renderable: ...
```

`build_markdown` reads runtime config (`CLIConfig.markdown_theme`), resolves the entry, and returns a Rich renderable (wrapper over `Markdown` with a themed `Console`, as in current `ThemedMarkdown`).

### 5.2 Config resolution order

```
CLI --markdown-theme  →  config ui.markdown_theme  →  default "match-app"
```

Independent from TUI theme selection unless `match-app` is active (then element colors track live TUI theme).

`--no-render-markdown` continues to disable all markdown rendering (unchanged).

### 5.3 Wire-up surfaces

All markdown-rendered widgets call `build_markdown()` when `render_markdown` is enabled:

| Widget | Notes |
|--------|-------|
| `AssistantMessage` | Includes goal-completion synthesis cards |
| `SkillMessage` | Expanded SKILL.md body |
| Hydration / resume | Uses **current** CLI config theme, not per-message snapshot |

**Remove WIP special cases**:

- `AssistantMessage.theme_markdown`
- `MessageData.assistant_theme_markdown`
- Goal-completion-only `theme_markdown=True` in `textual_adapter.py`

**Keep**:

- `render_markdown=False` for `plan_direct` one-liners (not markdown)

### 5.4 File layout after refactor

```
soothe_cli/tui/
  theme.py                 # TUI ThemeEntry (unchanged)
  markdown_theme.py        # MarkdownThemeEntry registry + build_markdown()
  widgets/messages/
    assistant.py           # _render_to_body → build_markdown()
    skill.py                 # same
    _helpers.py              # card/tool helpers only; no markdown maps
```

---

## 6. CLI and config

### 6.1 CLI flag

```bash
soothe --markdown-theme match-app          # default
soothe --markdown-theme langchain
soothe --markdown-theme minimal
soothe --no-render-markdown                # disable markdown entirely
```

Typer help lists **display labels**; values accept **internal IDs**:

```
Markdown appearance preset (Match App Theme, LangChain, Standard, Minimal, …).
Default: match-app.
```

Invalid ID → warning + fallback to `match-app`.

### 6.2 Config file

```yaml
ui:
  theme: textual-dark           # existing TUI theme
  markdown_theme: match-app     # new; optional
```

Add to `config/config.template.yml` and `config/develop/config.yml` when implementing (config sync rule).

### 6.3 `CLIConfig`

```python
markdown_theme: str = "match-app"
render_markdown: bool = True
```

Loaded via existing `set_runtime_config()` path so widgets read a single runtime config without re-parsing Typer on every flush.

---

## 7. Rich markdown polish (recipes)

Each `MarkdownThemeEntry` maps to a **style recipe**: `ThemeColors → dict[str, Style]` for Rich’s `markdown.*` keys.

### 7.1 Shared recipe: `match-app` / `langchain*`

| Element | Style intent |
|---------|----------------|
| `markdown.h1`, `h2` | `primary`, bold |
| `markdown.h3` | `card_header`, bold |
| `markdown.h4`–`h6` | `foreground` → `muted` gradient |
| `markdown.strong` | `foreground`, bold |
| `markdown.em` | `foreground`, italic |
| `markdown.code_inline` | `secondary` on `panel` background |
| `markdown.block_quote` | `muted` text; quote bar uses `card_border` |
| `markdown.link`, `link_url` | `primary`, underline |
| `markdown.hr` | `card_border` |
| `markdown.item.bullet`, `item.number` | `card_activity` |
| `markdown.table.header` | `primary`, bold |
| `markdown.table.border`, `table.cell` | `card_border` / `foreground` |

### 7.2 `minimal` recipe

- All headings: `foreground`, bold only (no primary accent)
- Links: `foreground`, no underline
- Inline code: `muted` on transparent background
- Blockquotes: `muted` only

### 7.3 `standard` recipe

- Close to Rich defaults but force `foreground` body and `primary` links for dark/light consistency

---

## 8. Migration from WIP

If the partial implementation (`ThemedMarkdown` in `_helpers.py`, `theme_markdown` flags) is merged before this work lands:

1. Move `ThemedMarkdown` → `markdown_theme.py`, rename to internal `ThemedMarkdownRenderer` if needed.
2. Delete `_CODE_THEME_MAP` and `_markdown_styles_from_theme_colors` from `_helpers.py`.
3. Revert `MessageData.assistant_theme_markdown` (SDK) unless already released — prefer revert for simpler resume semantics.
4. Replace `theme_markdown=True` call sites with default `build_markdown()` behavior driven by config.

---

## 9. Testing

| Area | Tests |
|------|-------|
| Registry | Every built-in ID resolves; unknown ID falls back |
| Recipes | Snapshot or assert key `Style` colors for `langchain` + `minimal` |
| `match-app` | Changing mock `ThemeColors` changes heading color |
| CLI | `--markdown-theme minimal` flows into `CLIConfig` |
| Integration | `AssistantMessage` renders `ThemedMarkdownRenderer` when markdown enabled |
| Resume | `convert_messages_to_data` does not need markdown flags; hydration uses runtime theme |

---

## 10. Deferred (v2+)

- `[markdown_themes.custom-name]` in user config (override colors / code highlighting)
- `/markdown-theme` slash command or subsection in `/theme` picker
- Per-message markdown theme in card ledger (only if product requires frozen resume appearance)
- Additional presets: `high-contrast`, `solarized` (markdown-only fixed palette)

---

## 11. Recommendation summary

| Decision | Choice |
|----------|--------|
| Default preset | `match-app` (Match App Theme) |
| Unified vs tiered markdown | **Unified** — all markdown surfaces share one preset |
| Config key | `ui.markdown_theme` |
| CLI flag | `--markdown-theme <id>` |
| User-visible names | Display labels in §4.3; never Pygments/Rich ids |
| WIP boolean flags | Remove; replace with registry + config |

---

## 12. Post-draft routing (Platonic Coding)

After you approve this draft, pick a path:

1. **Pause at gates (recommended)** — formalize RFC → IG → implement with confirmation at each step  
2. **Quick pass** — create IG and implement directly (small CLI-only surface)  
3. **Update RFC-500** — add § Markdown rendering to existing CLI TUI RFC instead of new RFC  
4. **New RFC** — `RFC-NNN-tui-markdown-theme.md` if you want a standalone normative spec  
5. **New IG only** — `IG-NNN-tui-markdown-theme.md` (likely sufficient given RFC-500 already covers TUI rendering)  
6. **Update existing IG** — e.g. extend IG-533 if you want goal-completion work grouped there  

**Recommendation**: **5 — New IG only** (`IG-NNN-tui-markdown-theme-registry.md`). RFC-500 already defines `AssistantMessage` as the goal-completion surface; this change is presentation-layer config, not a wire-protocol change. Skip a new RFC unless you want cross-client (desktop) alignment documented normatively.

---

## Appendix A — User-facing copy cheat sheet

Use these strings in CLI help, config template comments, and future UI:

| ID | Help / picker string |
|----|----------------------|
| `match-app` | **Match App Theme** — markdown colors follow your terminal theme |
| `langchain` | **LangChain** — brand dark palette |
| `langchain-light` | **LangChain Light** — brand light palette |
| `standard` | **Standard** — balanced default markdown styling |
| `minimal` | **Minimal** — low visual noise; best for dense logs |

**Avoid in user copy**: `follow-tui`, `rich-default`, `pygments`, `monokai`, `theme_markdown`, `ThemedMarkdown`.
