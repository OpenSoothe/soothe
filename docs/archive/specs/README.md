# RFC Archive

This directory contains deprecated RFCs that have been archived after their 90-day deprecation period.

## Purpose

Archived RFCs are retained for historical reference and to maintain a complete record of the project's design evolution. These documents are no longer active and should not be referenced in new development.

## Archive Policy

RFCs are moved to this archive when:

1. They have been marked as **Deprecated** for a minimum of 90 days
2. They have been superseded by newer specifications
3. All dependent systems have been updated to reference replacement RFCs

For details on the deprecation process, see [RFC-900: RFC Deprecation List and Number Segment Reclassification Scheme](../RFC-900-deprecation-reclassification-scheme.md).

## Archived RFCs

| RFC | Title | Archived Date | Superseded By |
|-----|-------|---------------|---------------|
| RFC-200 | Autonomous Goal Management Loop | 2026-06-19 | RFC-222, RFC-625 |
| RFC-203 | StrangeLoop State & Memory Architecture | 2026-06-19 | RFC-626 |
| RFC-216 | StrangeLoop Multi-Thread Infinite Lifecycle | 2026-06-19 | RFC-207 |
| RFC-300 | Context and Memory Architecture Design | 2026-06-19 | RFC-302, RFC-303 |
| RFC-411 | Event Stream Replay & History Reconstruction | 2026-06-19 | RFC-413 |
| RFC-605 | Explore Subagent and Parallel Spawning | 2026-06-19 | RFC-613 |

## Usage Guidelines

- **Do not** reference archived RFCs in new code or documentation
- **Do not** update archived RFCs with new content
- **Do** consult archived RFCs for historical context when investigating legacy systems
- **Do** refer to the superseding RFCs for current specifications

## Related Documentation

- [RFC Index](../rfc-index.md) - Active RFC listing
- [RFC-900](../RFC-900-deprecation-reclassification-scheme.md) - Deprecation policy and process
- [RFC Naming Conventions](../rfc-namings.md) - RFC naming standards