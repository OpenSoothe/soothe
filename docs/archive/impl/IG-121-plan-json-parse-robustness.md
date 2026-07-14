# IG-121: Robust LLM plan / reason JSON parsing

Enhance `soothe.cognition.planning.simple._load_llm_json_dict` to tolerate malformed model JSON: balanced `{`…`}` extraction (string-aware), optional trailing-comma repair, BOM strip. Reduces `JSONDecodeError` → forced replan loops.

Status: completed — `simple.py` helpers + `tests/unit/test_planning_simple_json_parse.py`; `./scripts/verify_finally.sh` passed.
