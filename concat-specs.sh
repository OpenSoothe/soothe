#!/bin/bash

# Script to concatenate all markdown files under specs/ into full-specs.md
# Each file is separated by "---" and blank lines

OUTPUT_FILE="full-specs.md"
SPECS_DIR="docs/specs"

# Remove output file if it exists
rm -f "$OUTPUT_FILE"

# Find all markdown files in specs directory (excluding .pages files)
# Sort them for consistent ordering
FILES=$(find "$SPECS_DIR" -type f -name "*.md" ! -name ".pages" | sort)

FIRST_FILE=true

for file in $FILES; do
    # Skip if file is empty
    if [ ! -s "$file" ]; then
        continue
    fi

    # Add separator before each file except the first
    if [ "$FIRST_FILE" = false ]; then
        echo "" >> "$OUTPUT_FILE"
        echo "---" >> "$OUTPUT_FILE"
        echo "" >> "$OUTPUT_FILE"
        echo "" >> "$OUTPUT_FILE"
    fi

    # Add file path as a comment header
    echo "# File: $file" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"

    # Append file contents
    cat "$file" >> "$OUTPUT_FILE"

    FIRST_FILE=false
done

echo "Concatenated all specs into $OUTPUT_FILE"
