# IG-055: Add Essential Progress Events to Builtin Tools

**Implementation Guide**
**Created**: 2026-03-25
**Status**: In Progress
**Related**: RFC-0018, IG-052, IG-054

## Summary

This guide tracks the addition of essential progress events to all builtin tools that currently have empty `events.py` files. Per RFC-0018, all tools should expose started/completed/failed events to enable observability and user feedback.

## Motivation

### Problem

9 builtin tools have empty `events.py` files with no custom events defined:
- audio/, code_edit/, data/, datetime/, execution/, file_ops/, goals/, image/, video/

This violates RFC-0018's requirement for plugin extensibility and observability.

### Solution

Add comprehensive progress events following the self-contained pattern from IG-052 and IG-054.

## Implementation Plan

### Phase 1: High Priority Tools (Long-Running Operations)

#### 1.1 execution/ - Shell and Python execution

**Status**: Pending

**Events to Add**:
- `CommandStartedEvent`: command, timeout
- `CommandCompletedEvent`: command, exit_code, duration_ms
- `CommandFailedEvent`: command, error, timeout_occurred
- `CommandTimeoutEvent`: command, timeout_seconds
- `PythonExecutionStartedEvent`: session_id
- `PythonExecutionCompletedEvent`: session_id, success
- `BackgroundProcessStartedEvent`: command, pid
- `ProcessKilledEvent`: pid
- `ShellRecoveryEvent`: reason

**Files**:
- `src/soothe/tools/execution/events.py` - Event definitions
- `src/soothe/tools/execution/shell_tool.py` - Emit events
- `src/soothe/tools/execution/python_tool.py` - Emit events
- `src/soothe/tools/execution/background_tool.py` - Emit events
- `src/soothe/tools/execution/kill_process_tool.py` - Emit events

#### 1.2 video/ - Video analysis with Gemini

**Status**: Pending

**Events to Add**:
- `VideoUploadStartedEvent`: video_path, file_size_mb
- `VideoUploadCompletedEvent`: video_path, file_name
- `VideoProcessingEvent`: file_name, state
- `VideoAnalysisStartedEvent`: video_path, question
- `VideoAnalysisCompletedEvent`: video_path
- `VideoAnalysisFailedEvent`: video_path, error

**Files**:
- `src/soothe/tools/video/events.py` - Event definitions
- `src/soothe/tools/video/video_analysis.py` - Emit events
- `src/soothe/tools/video/video_info.py` - Emit events (if needed)

#### 1.3 audio/ - Audio transcription with Whisper

**Status**: Pending

**Events to Add**:
- `AudioTranscriptionStartedEvent`: audio_path, is_url
- `AudioTranscriptionCompletedEvent`: audio_path, duration, language
- `AudioTranscriptionFailedEvent`: audio_path, error
- `AudioCacheHitEvent`: audio_path
- `AudioDownloadEvent`: url

**Files**:
- `src/soothe/tools/audio/events.py` - Event definitions
- `src/soothe/tools/audio/audio_tools.py` - Emit events

#### 1.4 data/ - Data inspection and text extraction

**Status**: Pending

**Events to Add**:
- `DataInspectionStartedEvent`: file_path, domain
- `DataInspectionCompletedEvent`: file_path, result_summary
- `DataQualityCheckEvent`: file_path, issues_found
- `TextExtractionStartedEvent`: file_path
- `TextExtractionCompletedEvent`: file_path, char_count

**Files**:
- `src/soothe/tools/data/events.py` - Event definitions
- Multiple tool files - Emit events

### Phase 2: Medium Priority Tools

#### 2.1 image/ - Image analysis

**Status**: Pending

**Events to Add**:
- `ImageAnalysisStartedEvent`: image_path, prompt
- `ImageAnalysisCompletedEvent`: image_path
- `ImageOCREvent`: image_path
- `ImageOCRCompletedEvent`: image_path, text_length

#### 2.2 file_ops/ - File operations

**Status**: Pending

**Events to Add**:
- `FileReadEvent`: path, bytes_read
- `FileWriteEvent`: path, bytes_written, mode
- `FileDeleteEvent`: path, backup_created
- `FileSearchStartedEvent`: pattern, path
- `FileSearchCompletedEvent`: matches_count
- `BackupCreatedEvent`: original_path, backup_path

### Phase 3: Lower Priority Tools

#### 3.1 code_edit/ - Code editing

**Status**: Pending

**Events to Add**:
- `FileEditStartedEvent`: path, operation
- `FileEditCompletedEvent`: path, lines_removed, lines_added
- `FileEditFailedEvent`: path, error
- `DiffAppliedEvent`: path

#### 3.2 goals/ - Goal management

**Status**: Pending

**Events to Add**:
- `GoalCreatedEvent`: goal_id, description, priority
- `GoalCompletedEvent`: goal_id
- `GoalFailedEvent`: goal_id, reason
- `GoalListedEvent`: count, status_filter

### Phase 4: Skip

#### datetime/ - No events needed

Trivial operation, no meaningful progress to report.

## Implementation Pattern

Follow the pattern from IG-052/IG-054:

1. **Define Event Classes** in `events.py`
2. **Register Events** using `register_event()`
3. **Export Constants** for event type strings
4. **Emit Events** in tool implementation using `custom_event()`

## Verification

After each tool:
1. Run `./scripts/verify_finally.sh`
2. Manual test with TUI/CLI
3. Verify event rendering

## Progress Tracking

- [ ] Phase 1.1: execution/ events
- [ ] Phase 1.2: video/ events
- [ ] Phase 1.3: audio/ events
- [ ] Phase 1.4: data/ events
- [ ] Phase 2.1: image/ events
- [ ] Phase 2.2: file_ops/ events
- [ ] Phase 3.1: code_edit/ events
- [ ] Phase 3.2: goals/ events
- [ ] Final verification and documentation

## Related Documentation

- [RFC-0018: Plugin Extension Specification](../specs/RFC-0018.md)
- [IG-052: Event System Optimization](IG-052.md)
- [IG-054: Event Constants Self-Containment](054-event-constants-self-containment.md)
