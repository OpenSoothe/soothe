#!/usr/bin/env python3
"""Remove RFC-XXX/IG-XXX references from docstrings and description fields.

Keeps references in comments (# ...) and internal docs. Per AGENTS.md §17:
"Never reference external design docs, reports, or category taxonomies
(e.g. "report 5.3", "category I", IG-XXX/RFC-XXX) in docstrings;
docstrings must stand alone."
"""

from __future__ import annotations

import os
import re
import sys


def remove_rfc_ig_refs(text: str) -> str:
    """Remove RFC-XXX and IG-XXX references from a text string.

    Only modifies text that contains RFC- or IG- references.
    Preserves surrounding whitespace/indentation.
    """
    if "RFC-" not in text and "IG-" not in text:
        return text

    result = text

    # Pattern: (RFC-XXX / IG-XXX) or (IG-XXX / RFC-XXX) etc - parenthetical with multiple refs
    result = re.sub(
        r"\s*\([Rr][Ff][Cc]-\d+[Ss§]*[\d\.]*\s*"
        r"(?:[/,]\s*)?"
        r"(?:[Rr][Ff][Cc]-\d+[Ss§]*[\d\.]*\s*)*"
        r"(?:[/,]\s*)?"
        r"(?:[Ii][Gg]-\d+\s*)*"
        r"(?:[/,]\s*)?"
        r"(?:[Rr][Ff][Cc]-\d+[Ss§]*[\d\.]*\s*)*\)",
        "",
        result,
    )

    # Pattern: (IG-XXX) or (RFC-XXX) - simple parenthetical
    result = re.sub(r"\s*\((?:RFC-\d+[Ss§]*[\d\.]*|IG-\d+)\)", "", result)

    # Pattern: (RFC-XXX ... anything ... ) where it starts with RFC or IG
    result = re.sub(r"\s*\((?:RFC-\d+[^)]*|IG-\d+[^)]*)\)", "", result)

    # Pattern: per RFC-XXX
    result = re.sub(r"\s+per\s+RFC-\d+", "", result, flags=re.IGNORECASE)

    # Pattern: RFC-XXX: at start or after whitespace
    result = re.sub(r"RFC-\d+\s*§[\d\w]*\s*[:\s]*", "", result)

    # Pattern: RFC-XXX §...
    result = re.sub(r"RFC-\d+\s*§[\d\.\w]*", "", result)

    # Pattern: RFC-XXX revised
    result = re.sub(r"RFC-\d+\s+revised", "", result)

    # Pattern: RFC-XXX Phase X
    result = re.sub(r"RFC-\d+\s+Phase\s+\d+[Ss]?", "", result)

    # Pattern: RFC-XXX,
    result = re.sub(r"RFC-\d+\s*,\s*", "", result)

    # Pattern: RFC-XXX (standalone or followed by space)
    result = re.sub(r"RFC-\d+\s*", " ", result)

    # Pattern: IG-XXX (standalone or followed by space)
    result = re.sub(r"IG-\d+\s*", " ", result)

    # Clean up: remove double spaces (but preserve leading whitespace)
    stripped = result.lstrip()
    leading_ws = result[: len(result) - len(stripped)]
    result = leading_ws + re.sub(r"  +", " ", stripped)

    # Clean up: trailing space before closing punctuation
    result = re.sub(r"\s+\.", ".", result)
    result = re.sub(r"\s+,", ",", result)

    # Clean up: dangling comma after removing ref: "(read-only, )" -> "(read-only)"
    result = re.sub(r",\s*\)", ")", result)

    # Clean up: "whether  requires" -> "whether requires" (double space already handled above)

    # Clean up: trailing space
    result = result.rstrip()

    # Clean up: leading dash on content (after whitespace)
    result = re.sub(r"^(\s*)—\s*", r"\1", result)
    result = re.sub(r"^(\s*)\.\s*", r"\1", result)

    # Clean up: trailing " — " with nothing after (leftover dash)
    result = re.sub(r"\s+—\s*$", "", result)

    return result


def fix_file(filepath: str, dry_run: bool = False) -> tuple[bool, int]:
    """Fix RFC-/IG- references in docstrings and description fields.

    Returns (changed, fix_count).

    Strategy: use a state machine to track whether we're inside a
    triple-quoted string (docstring). Only modify lines that are:
    1. Inside a triple-quoted docstring AND contain RFC-/IG-
    2. description="..." fields with RFC-/IG-
    3. Lines that are part of multi-line string literals with RFC-/IG-

    Comments (# ...) are always preserved.
    """
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    original = content
    lines = content.split("\n")
    new_lines = []
    fix_count = 0

    in_triple_docstring = False
    docstring_char = None

    for i, line in enumerate(lines):
        stripped = line.lstrip()

        # Pure comment line - keep as is (unless inside docstring)
        if stripped.startswith("#") and not in_triple_docstring:
            new_lines.append(line)
            continue

        # If inside a triple-quoted docstring, fix the line
        if in_triple_docstring:
            # Check if this line ends the docstring
            if docstring_char in line:
                # The docstring closes on this line
                idx = line.find(docstring_char)
                before = line[:idx]
                after = line[idx + len(docstring_char) :]

                # Fix the content part (before the closing quotes) only if it has RFC-/IG-
                if "RFC-" in before or "IG-" in before:
                    fixed_before = remove_rfc_ig_refs(before)
                    if fixed_before != before:
                        fix_count += 1
                else:
                    fixed_before = before

                # After closing quotes could be code or comment - leave as is
                new_line = fixed_before + docstring_char + after

                in_triple_docstring = False
                docstring_char = None
                new_lines.append(new_line)
                continue
            else:
                # Inside docstring, fix the line only if it has RFC-/IG-
                if "RFC-" in line or "IG-" in line:
                    fixed_line = remove_rfc_ig_refs(line)
                    if fixed_line != line:
                        fix_count += 1
                    new_lines.append(fixed_line)
                else:
                    new_lines.append(line)
                continue

        # Not in docstring - check for description= or docstring start

        # Check for description="..." or description='...' (single line)
        desc_match = re.search(r'(description\s*=\s*)(["\'])(.*?)(\2)', line)
        if desc_match and ("RFC-" in desc_match.group(3) or "IG-" in desc_match.group(3)):
            prefix = desc_match.group(1)
            quote = desc_match.group(2)
            content_str = desc_match.group(3)
            suffix = desc_match.group(4)
            fixed_content = remove_rfc_ig_refs(content_str)
            line = (
                line[: desc_match.start()]
                + prefix
                + quote
                + fixed_content
                + suffix
                + line[desc_match.end() :]
            )
            fix_count += 1

        # Check for triple-quoted strings on this line
        for tq in ['"""', "'''"]:
            if tq in line:
                count_tq = line.count(tq)
                if count_tq >= 2 and count_tq % 2 == 0:
                    # Single-line docstring/string: """content"""
                    # Fix content between first and last occurrence
                    first_idx = line.find(tq)
                    last_idx = line.rfind(tq)
                    before = line[: first_idx + len(tq)]
                    content = line[first_idx + len(tq) : last_idx]
                    after = line[last_idx:]

                    if "RFC-" in content or "IG-" in content:
                        fixed_content = remove_rfc_ig_refs(content)
                        if fixed_content != content:
                            fix_count += 1
                    else:
                        fixed_content = content

                    line = before + fixed_content + after
                    # Don't enter docstring mode

                elif count_tq % 2 == 1:
                    # We enter a docstring (odd count means unclosed)
                    last_tq_idx = line.rfind(tq)
                    before_open = line[:last_tq_idx]
                    after_open = line[last_tq_idx + len(tq) :]

                    # Fix the content after opening quote only if it has RFC-/IG-
                    if "RFC-" in after_open or "IG-" in after_open:
                        fixed_after = remove_rfc_ig_refs(after_open)
                        if fixed_after != after_open:
                            fix_count += 1
                    else:
                        fixed_after = after_open

                    line = before_open + tq + fixed_after
                    in_triple_docstring = True
                    docstring_char = tq
                    break  # Don't check other tq type

        new_lines.append(line)

    new_content = "\n".join(new_lines)

    if new_content != original:
        if not dry_run:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
        return True, fix_count
    return False, 0


def main():
    dry_run = "--dry-run" in sys.argv
    packages = [
        "/Users/chenxm/Workspace/soothe/packages/soothe/src",
        "/Users/chenxm/Workspace/soothe/packages/soothe-daemon/src",
    ]

    total_files = 0
    total_fixes = 0
    changed_files = []

    for pkg in packages:
        for root, dirs, files in os.walk(pkg):
            for f in sorted(files):
                if f.endswith(".py"):
                    filepath = os.path.join(root, f)
                    changed, fixes = fix_file(filepath, dry_run=dry_run)
                    if changed:
                        total_files += 1
                        total_fixes += fixes
                        changed_files.append(
                            filepath.replace("/Users/chenxm/Workspace/soothe/", "")
                        )

    mode = "DRY RUN" if dry_run else "APPLIED"
    print(f"\n{mode}: {total_files} files changed, {total_fixes} lines fixed")
    for f in changed_files:
        print(f"  {f}")


if __name__ == "__main__":
    main()
