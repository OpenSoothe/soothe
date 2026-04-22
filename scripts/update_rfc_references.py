#!/usr/bin/env python3
"""
Update RFC references across the Soothe codebase after consolidation.
Maps old RFC numbers to new merged RFC numbers.

RFC Mapping:
- RFC-201, RFC-202 → RFC-200 (AgentLoop Core Loop)
- RFC-204, RFC-205 → RFC-203 (AgentLoop State & Memory)
- RFC-208, RFC-209, RFC-210 → RFC-207 (Thread Management)
- RFC-214 → RFC-213 (Reasoning Quality)
- RFC-401 → RFC-400 (ContextProtocol)
- RFC-403 → RFC-402 (MemoryProtocol)
- RFC-405 → RFC-404 (PlannerProtocol)
- RFC-407 → RFC-406 (PolicyProtocol)
- RFC-409 → RFC-203 (CheckpointEnvelope moved to Layer 2)
- RFC-411, RFC-412, RFC-413 → RFC-410 (RemoteAgentProtocol)
"""

import re
from pathlib import Path

# RFC mapping from old to new numbers
RFC_MAPPING = {
    "201": "200",
    "202": "200",
    "204": "203",
    "205": "203",
    "208": "207",
    "209": "207",
    "210": "207",
    "214": "213",
    "401": "400",
    "403": "402",
    "405": "404",
    "407": "406",
    "409": "203",  # Moved to Layer 2
    "411": "410",
    "412": "410",
    "413": "410",
}

def update_rfc_references(content: str) -> str:
    """Update RFC references in content."""
    updated = content

    # Pattern: RFC-XXX or RFC-XXXX
    for old_num, new_num in RFC_MAPPING.items():
        # Match RFC-XXX with various formats
        patterns = [
            (rf'RFC-{old_num}', f'RFC-{new_num}'),
            (rf'\[RFC-{old_num}\]', f'[RFC-{new_num}]'),
            (rf'RFC-{old_num}\s', f'RFC-{new_num} '),
            (rf'RFC-{old_num}:', f'RFC-{new_num}:'),
            (rf'RFC-{old_num}\.', f'RFC-{new_num}.'),
            (rf'RFC-{old_num}\)', f'RFC-{new_num})'),
            (rf'see RFC-{old_num}', f'see RFC-{new_num}'),
            (rf'References.*RFC-{old_num}', f'References.*RFC-{new_num}'),
        ]

        for pattern, replacement in patterns:
            updated = re.sub(pattern, replacement, updated)

    return updated

def process_file(file_path: Path) -> bool:
    """Process a single file and update RFC references."""
    try:
        content = file_path.read_text()
        updated_content = update_rfc_references(content)

        if content != updated_content:
            file_path.write_text(updated_content)
            return True
        return False
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False

def main():
    """Main update function."""
    root = Path("/Users/chenxm/Workspace/Soothe")

    # Priority files to update first
    priority_files = [
        "CLAUDE.md",
        "README.md",
        "docs/specs/rfc-index.md",
        "docs/specs/rfc-history.md",
    ]

    # Find all markdown files
    md_files = list(root.rglob("*.md"))

    # Filter out alias files and consolidation docs
    md_files = [
        f for f in md_files
        if not f.name.endswith("-alias.md")
        and "rfc-consolidation" not in f.name
        and "_bmad-output" not in str(f)  # Keep consolidation docs unchanged
    ]

    # Sort by priority
    files_to_process = []
    for priority in priority_files:
        priority_path = root / priority
        if priority_path.exists():
            files_to_process.append(priority_path)

    # Add remaining files
    for f in md_files:
        if f not in files_to_process:
            files_to_process.append(f)

    # Process files
    updated_count = 0
    for file_path in files_to_process:
        if process_file(file_path):
            updated_count += 1
            print(f"✓ Updated: {file_path.relative_to(root)}")

    print(f"\n✅ Updated {updated_count} files")

    # Print summary
    print("\nRFC Reference Mapping Applied:")
    for old, new in RFC_MAPPING.items():
        print(f"  RFC-{old} → RFC-{new}")

if __name__ == "__main__":
    main()