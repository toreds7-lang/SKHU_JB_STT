# SPEC-SETTINGS-001: Settings Management Tab

## Metadata

| Field | Value |
|-------|-------|
| SPEC ID | SPEC-SETTINGS-001 |
| Title | Settings Management Tab with LLM-Powered Q&A and Editing |
| Status | DRAFT |
| Priority | High |
| Created | 2026-07-11 |
| Target Release | v1.1 |
| Related | SPEC-AGENTIC-001 (reuse agentic mode logic), SPEC-NOTEBOOK-CHAT-001 (similar UI patterns) |

---

## 1. Overview

### 1.1 Product Context

SKHU Agent is a PyQt6-based RAG chat application with Jupyter notebook indexing and multi-mode query execution (RAG, Force, Agentic). Users currently configure the application through:
- **env.txt** — API keys, model names, base URLs
- **config.txt** — RAG tuning parameters (top-k, weights, decay factors, etc.)
- **prompts/ folder** — Custom system prompts (7 files for different modes)

**Problem**: Users must manually edit these text files outside the GUI, without understanding what each parameter does or how it affects system behavior.

### 1.2 Solution

Add a **Settings Tab** that provides:
1. **Interactive documentation** — Users ask about any config parameter and get LLM-generated explanations
2. **Safe editing** — Users can edit values directly in the GUI with real-time file sync
3. **Organized discovery** — Browse all available settings organized by category (API, Retrieval, Agentic, etc.)
4. **Instant feedback** — Changes take effect immediately; no app restart required (for config-dependent components)

### 1.3 Target Users

- Researchers tuning RAG parameters for different use cases
- Faculty deploying custom models or local LLM servers
- Users optimizing performance or accuracy on their own notebooks

### 1.4 Scope Boundaries

**Included in this SPEC**:
- env.txt (API keys, model selection)
- config.txt (RAG tuning parameters)
- 7 custom prompt files in prompts/ folder

**Explicitly NOT included**:
- Database connection strings or credentials
- External service configuration (beyond OpenAI API)
- Plugin or extension configuration
- User project-specific settings

Future versions can extend to other config files, but this SPEC focuses on core RAG system tuning.

---

## 2. Detailed Requirements (EARS Format)

### 2.1 UI Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Settings Tab (beside Knowledge Graph)                      │
├────────────────────┬────────────────────────────────────────┤
│                    │                                        │
│  File Selector     │    Chat Panel (Top)                   │
│  ┌──────────────┐  │    ┌────────────────────────────────┐ │
│  │ env.txt      │  │    │ Q: "What is VECTOR_K?"        │ │
│  │ config.txt   │  │    │ A: Vector retriever returns  │ │
│  │ system_p.txt │  │    │    top-k results per query.  │ │
│  │ force_p.txt  │  │    │    Default 5. Increase for   │ │
│  │ ... (more)   │  │    │    broader coverage...        │ │
│  │              │  │    └────────────────────────────────┘ │
│  │              │  │    Q: "Can I use local models?"  │
│  │              │  │    A: Yes via LLM_BASE_URL...    │
│  │              │  │                                   │
│  │              │  │    [Chat Input Box]               │
│  │              │  │    [Ask] [Preview] [Edit]         │
│  └──────────────┘  │                                    │
│                    │    ─────────────────────────────── │
│  [Reload Files]    │                                    │
│  [Save Changes]    │    File Content (Bottom)          │
│  [Reset to Defaults]  │    ┌────────────────────────────────┐ │
│                    │    │ [Edit Mode Toggle]              │ │
│  Category Filter   │    │ ─────────────────────────────── │ │
│  ☐ All            │    │ VECTOR_K=5                      │ │
│  ☐ API            │    │ BM25_K=5                        │ │
│  ☐ Retrieval      │    │ GRAPH_K=5                       │ │
│  ☐ Agentic        │    │ ...                             │ │
│  ☐ Performance    │    │                                 │ │
│                    │    │ [Unstaged Changes: 3 items]     │ │
│                    │    └────────────────────────────────┘ │
│                    │                                    │
└────────────────────┴────────────────────────────────────────┘
```

### 2.2 Functional Requirements

#### F-SETTINGS-1: File Selection & Display

**GIVEN** user opens Settings tab  
**WHEN** the tab loads  
**THEN** display a list of editable configuration files in left panel:
- env.txt (highest priority)
- config.txt
- prompts/system_prompt.txt
- prompts/force_prompt.txt
- prompts/agentic_planner_prompt.txt
- prompts/agentic_sufficiency_prompt.txt
- prompts/agentic_synthesis_prompt.txt
- prompts/notebook_chat_prompt.txt
- prompts/summary_prompt.txt

Files that don't exist should be visually distinguished (grayed out) but still selectable.

#### F-SETTINGS-2: File Content Display

**GIVEN** user selects a file from the list  
**WHEN** the file exists  
**THEN** display its raw content in the bottom-right panel with:
- Read-only view by default
- Raw text display (no syntax highlighting required)
- Line numbers (left margin, monospace font)
- Vertical scrollbar for navigation
- File path + encoding indicator (e.g., "env.txt · UTF-8")
- "Edit Mode" toggle button

#### F-SETTINGS-3: Interactive Q&A About Settings (Hybrid: CONFIG_METADATA + LLM)

**GIVEN** user types a question in the chat input (top-right)  
**WHEN** user presses Enter or clicks [Ask]  
**THEN**:
1. Parse the question to detect referenced config keys (using fuzzy matching against CONFIG_METADATA keys)
2. If key detected (e.g., "What is VECTOR_K?"):
   - Extract metadata from CONFIG_METADATA[file_type][key_name]
   - Build authoritative answer:
     ```
     Parameter: {key_name}
     Description: {metadata.description}
     Type: {metadata.type}
     Default: {metadata.default}
     Range/Constraints: {metadata.min}-{metadata.max} (if numeric)
     Category: {metadata.category}
     Current value: {current_value}
     Affects rebuild: {metadata.affects_rebuild}
     ```
3. Send to LLM with prompt (Option C - Hybrid):
   ```
   You are a settings expert for SKHU Agent RAG application.
   
   User question: {user_question}
   
   Here is the authoritative parameter information:
   {authoritative_answer_from_metadata}
   
   Rewrite this information in conversational Korean (2-3 sentences).
   Include:
   - What this parameter does
   - How it affects the RAG system  
   - Recommended values and trade-offs
   - (If current value differs from default) note the current value vs default
   
   Do NOT add information not in the authoritative answer above.
   Do NOT hallucinate parameter ranges or defaults.
   Base your response ONLY on the provided metadata.
   ```
4. Display streamed LLM response in chat panel (conversational tone, Korean)
5. Log Q&A to chat history (persist in `cache_store.py`)

**Key constraint**: If user asks about an unknown parameter (not in CONFIG_METADATA), respond: "I don't have documentation for '{param_name}'. This may be a custom or experimental setting. Please check your config file or documentation."

#### F-SETTINGS-4: Edit Mode Activation

**GIVEN** user reads an explanation  
**WHEN** user clicks [Edit] button (next to chat input or in file panel)  
**THEN**:
1. Transition file display to editable mode (QPlainTextEdit)
2. Highlight any changes made since last save (background color or gutter marker)
3. Show "[Unstaged Changes: N items]" summary
4. Disable file selection (lock to current file until changes saved/discarded)
5. Show "Save" and "Discard" buttons
6. Enable undo/redo:
   - Ctrl+Z: Undo last edit (full QPlainTextEdit undo stack)
   - Ctrl+Y or Ctrl+Shift+Z: Redo
   - [Discard] button clears undo stack and reverts to last saved version
7. Auto-save recovery: Every 30 seconds, save current edits to `.rag_cache/settings_recovery/{filename}.recovery`
   - On app crash/restart, offer to restore from recovery file
   - Recovery file deleted on successful [Save] or [Discard]

#### F-SETTINGS-5: Inline Value Editing

**GIVEN** user is in edit mode and wants to change a specific value  
**WHEN** user clicks on a config line (e.g., `VECTOR_K=5`)  
**THEN**:
1. Auto-detect the key=value pattern
2. Show inline editor or dialog to change just the value
3. Suggest valid ranges based on documented constraints:
   - VECTOR_K: 1-20 (higher = more context, slower)
   - BM25_K: 1-20
   - GRAPH_K: 1-20
   - GRAPH_HOPS: 1-5
   - SEQ_DECAY: 0.0-1.0
   - VAR_DECAY: 0.0-1.0
   - Weights (VECTOR_WEIGHT, BM25_WEIGHT, etc.): 0.0-1.0
4. Validate on save (reject invalid types/ranges)

#### F-SETTINGS-6: File Sync & Reload with Confirmation

**GIVEN** user clicks [Save] in edit mode  
**WHEN** changes exist  
**THEN**:
1. Show confirmation dialog: "Are you sure you want to save changes to {filename}?" with [Cancel] and [Save] buttons
2. If user clicks [Cancel]: Return to edit mode (retain edits)
3. If user clicks [Save]:
   - Validate all key=value pairs (type, range, format)
   - If validation fails: Show error dialog, stay in edit mode
   - If validation passes:
     - Create backup: `.rag_cache/backups/{filename}.{YYYYMMDD_HHMMSS}.bak`
     - Write file to disk (env.txt, config.txt, or prompts/*.txt)
     - **For config.txt only**: Detect if "retriever K" parameters changed (VECTOR_K, BM25_K, GRAPH_K, GRAPH_HOPS, SEQ_DECAY, VAR_DECAY):
       - If YES: Show dialog: "Retriever settings changed. Rebuild RAG indices?" with [Rebuild Now] [Rebuild Later] [Cancel] buttons
         - [Cancel]: Revert changes, stay in edit mode
         - [Rebuild Later]: Save config.txt, show toast "✓ config.txt saved. Rebuild indices? [Rebuild]", return to read-only
         - [Rebuild Now]: Save config.txt + trigger RagBuildWorker to rebuild FAISS/BM25/Graph indices
       - If NO (only LLM params changed): Proceed to next step
     - Update in-memory `RAG_CONFIG` dict (if config.txt)
     - Reload affected components:
       - If env.txt: Log status "env.txt updated (takes effect after restart)"
       - If config.txt with LLM params only (LLM_TEMPERATURE, etc.): Notify LLMWorker to reload on next query
       - If prompts/*.txt: Notify all LLM workers to reload prompts immediately
     - Show success toast: "✓ {filename} saved and reloaded"
     - Return to read-only view

**GIVEN** user clicks [Discard]  
**WHEN** unsaved changes exist  
**THEN**:
1. Show confirmation dialog: "Discard unsaved changes to {filename}?" with [Cancel] and [Discard] buttons
2. If [Cancel]: Return to edit mode
3. If [Discard]:
   - Reload file from disk (restore original content)
   - Clear undo/redo stack
   - Delete recovery file (.rag_cache/settings_recovery/{filename}.recovery)
   - Show toast: "Changes discarded"
   - Return to read-only view

**GIVEN** Settings tab detects unsaved changes when user tries to switch tabs  
**WHEN** user clicks another tab  
**THEN**:
1. Show dialog: "Discard unsaved changes to {filename}?" with [Save] [Discard] [Cancel] buttons
2. [Cancel]: Stay on Settings tab, return to edit mode
3. [Discard]: Clear edits, switch to clicked tab
4. [Save]: Save changes (with validation + rebuild prompt if needed), then switch tabs

#### F-SETTINGS-7: File Status Monitoring

**GIVEN** user has Settings tab open  
**WHEN** a config file is modified externally (by another process)  
**THEN**:
1. Detect the change (monitor file mtime in background thread)
2. Show warning banner: "⚠️ This file was modified outside SKHU Agent"
3. Offer [Reload] button to sync with disk
4. Do NOT auto-reload (preserve user edits)

#### F-SETTINGS-8: Category Filtering

**GIVEN** user has many config parameters  
**WHEN** user selects a category (API, Retrieval, Agentic, etc.)  
**THEN**:
1. Filter the file display to show only relevant section
2. Highlight matching keys in the file view
3. Update Q&A prompt to include category context

**Mapping**:
- **API**: OPENAI_API_KEY, LLM_MODEL, EMBEDDING_MODEL, LLM_BASE_URL, EMBEDDING_BASE_URL
- **STT**: STT_MODEL_SIZE, FORCE_WORKERS (audio-related)
- **Retrieval**: VECTOR_K, BM25_K, GRAPH_K, GRAPH_HOPS, SEQ_DECAY, VAR_DECAY, KEYWORD_BOOST, VECTOR_WEIGHT, BM25_WEIGHT, MAX_DOCS
- **Agentic**: AGENTIC_MAX_ITERS, AGENTIC_FANOUT_K, AGENTIC_MAX_SNIPPETS, AGENTIC_MAX_QUERIES
- **Debug**: TRACE_DEBUG

#### F-SETTINGS-9: "I want to edit" Shorthand

**GIVEN** user types `/edit` or says "I want to edit env.txt"  
**WHEN** chat processes this  
**THEN**:
1. Auto-detect the file from context or query
2. Activate edit mode for that file
3. Show confirmation: "Edit mode activated for {filename}"
4. Do NOT send the query to LLM (treat as internal command)

#### F-SETTINGS-10: Preview Before Save

**GIVEN** user clicks [Preview] button  
**WHEN** edits exist  
**THEN**:
1. Show a side-by-side diff:
   - Left: original file content
   - Right: edited content
   - Highlight added/removed/changed lines
2. User can still [Save], [Discard], or [Continue Editing]

#### F-SETTINGS-11: Reset to Defaults

**GIVEN** user clicks [Reset to Defaults] button  
**WHEN** they confirm the action  
**THEN**:
1. Restore config.txt to built-in defaults (or from .git if version-controlled)
2. Restore each prompt file to its built-in version
3. Offer to save or discard the reset
4. Do NOT touch env.txt (user API keys are precious)

#### F-SETTINGS-12: LLM-Assisted Prompt Modification

**GIVEN** user is viewing a prompt file (e.g., `prompts/system_prompt.txt`)  
**WHEN** user clicks [Modify via LLM] button (in file header)  
**THEN**:
1. Show input dialog: "What would you like to change about this prompt?"
2. User types their modification request (e.g., "Make it more concise", "Add examples")
3. Send to LLM with prompt:
   ```
   You are a prompt engineer for SKHU Agent.
   
   Current prompt type: {category} (e.g., "RAG Chat System Prompt")
   Purpose: {description from CONFIG_METADATA}
   
   Current prompt:
   {full_prompt_text}
   
   User request:
   {user_modification_request}
   
   Generate an improved prompt that addresses the request while maintaining 
   the original purpose. Keep Korean language support if present.
   Return only the new prompt text (no explanations).
   ```
4. Display LLM-generated prompt alongside original in side-by-side diff view
5. User can [Accept] or [Reject]:
   - [Accept]: Save modified prompt to disk, show success toast "✓ Prompt updated"
   - [Reject]: Discard generated version, return to read-only view
6. All prompt modifications follow same backup + confirmation pattern as file edits

**Note**: Prompt files have NO validation (Option A). Users can write any text. If broken, they see broken responses and can revert via [Reject] or [Reset to Defaults].

---

## 3. Non-Functional Requirements

### N-SETTINGS-1: Performance

- File loading: < 100ms (files are small, <50KB)
- LLM Q&A response: < 5s first token (network-dependent)
- UI responsiveness: No freezing during file operations or Q&A
- Implement file operations in background thread (QThread)
- **RAG rebuild time**: 30-60s (user expects this; shown with progress bar). Do NOT block UI during rebuild.
- **LLM param reload**: < 100ms (on next query, no rebuild needed)

### N-SETTINGS-2: Data Safety

- **No accidental data loss**:
  - Prompt [Discard] before destructive operations
  - Show diff preview before saving
  - Auto-backup original file (copy to `.rag_cache/backups/`)
- **API key protection**:
  - Do NOT log env.txt values in trace logs
  - Do NOT display API keys in chat responses
  - Mask keys in diff view (show `sk-***`)

### N-SETTINGS-3: Accessibility

- Keyboard shortcuts:
  - Alt+E: Toggle Edit mode
  - Ctrl+S: Save
  - Ctrl+Z: Undo (in edit mode)
  - Tab: Switch between chat and file panels
- Screen reader support: Label all controls with ARIA attributes

### N-SETTINGS-4: Internationalization

- UI labels: Korean (match SKHU Agent's main language)
- Chat responses: User's conversation_language (from language.yaml or auto-detect)
- Config keys: Always English (standard)

### N-SETTINGS-5: Extensibility

- Settings structure should support future additions without refactor:
  - Database config (PostgreSQL connection string)
  - Cache settings (Redis configuration)
  - Plugin configuration files
- Use category-based registration pattern (add new category → auto-discover)

---

## 4. UI Component Architecture

### Component Hierarchy

```
SettingsTab (QWidget)
├── LeftPanel (QWidget)
│   ├── FileListWidget (QListWidget)
│   │   └── [env.txt, config.txt, system_prompt.txt, ...]
│   ├── CategoryFilterWidget (QGroupBox)
│   │   └── [All, API, Retrieval, Agentic, Debug checkboxes]
│   └── ActionButtonsWidget (QHBoxLayout)
│       ├── [Reload Files] (QPushButton)
│       ├── [Save Changes] (QPushButton)
│       └── [Reset to Defaults] (QPushButton)
│
└── RightPanel (QSplitter, vertical)
    ├── ChatPanel (QWidget) [top, 50% height]
    │   ├── ChatDisplayWidget (QWebEngineView)
    │   │   └── Markdown chat history
    │   └── ChatInputWidget (QWidget)
    │       ├── QPlainTextEdit (query input)
    │       └── [Ask] [Preview] [Edit] buttons
    │
    └── FilePanel (QWidget) [bottom, 50% height]
        ├── FileHeaderWidget (QHBoxLayout)
        │   ├── File path label + encoding
        │   ├── [Edit Mode] toggle
        │   └── [Diff Preview] button
        │
        └── FileContentDisplay (QPlainTextEdit or QTextEdit)
            ├── Syntax highlighting
            ├── Line numbers
            └── Edit controls (if in edit mode)
```

### Key Classes to Create/Modify

| Class | Purpose | Location |
|-------|---------|----------|
| `SettingsTab` | Main tab widget | `ui/settings_tab.py` (new) |
| `SettingsWorker` | Q&A + file I/O thread | `workers/settings_worker.py` (new) |
| `ConfigMetadata` | Constraint + description for each config key (rebuilt at startup) | `rag_core.py` (extend) |
| `SettingsCache` | Store Q&A + Settings chat history | `cache_store.py` (extend) |

### Settings Chat History Storage

```python
# In cache_store.py, add:
SETTINGS_CHAT_HISTORY = "cache/settings_chat.json"

# Schema:
{
  "conversations": [
    {
      "id": "YYYYMMDD_HHMMSS",
      "timestamp": "ISO-8601",
      "file": "config.txt or env.txt or prompts/system_prompt.txt",
      "exchanges": [
        {
          "role": "user",
          "content": "What is VECTOR_K?",
          "timestamp": "ISO-8601"
        },
        {
          "role": "assistant", 
          "content": "Vector retriever top-k...",
          "timestamp": "ISO-8601"
        }
      ]
    }
  ],
  "current_exchange": []  # Active conversation in current session
}
```

Load on app startup (in SettingsTab.__init__). Append new exchanges to `current_exchange`. On SettingsWorker.on_final_answer(), save to disk.

### ConfigMetadata Rebuild Process (at App Startup)

```python
def build_config_metadata():
    """
    Rebuild ConfigMetadata at app startup by parsing actual config files.
    Returns dict structure with validation rules + descriptions.
    """
    metadata = {
        'env': _parse_env_metadata(),      # Read env.txt, discover all KEY=VALUE
        'config': _parse_config_metadata(), # Read config.txt, discover all KEY=VALUE
        'prompts': _discover_prompts()      # List all .txt files in prompts/
    }
    return metadata

# Call at app startup (in main.py or MainWindow.__init__)
CONFIG_METADATA = build_config_metadata()
```

**Structure**:
```python
CONFIG_METADATA = {
    'env': {
        'OPENAI_API_KEY': {
            'type': 'str',
            'required': True,
            'category': 'API',
            'default': None,
            'description': 'OpenAI API key (sk-...)',
            'mask_in_ui': True,  # Hide in diffs/logs
        },
        'LLM_MODEL': {
            'type': 'str',
            'required': False,
            'category': 'API',
            'default': 'gpt-4o',
            'description': 'LLM model name (gpt-4o, gpt-4-turbo, etc.)',
            'mask_in_ui': False,
        },
        # ... more env keys
    },
    'config': {
        'VECTOR_K': {
            'type': 'int',
            'required': False,
            'category': 'Retrieval',
            'default': 5,
            'min': 1,
            'max': 20,
            'description': 'Vector retriever top-k results per query',
            'affects_rebuild': True,  # Changing this requires RAG rebuild
        },
        # ... more config keys
    },
    'prompts': {
        'system_prompt.txt': {
            'type': 'file',
            'category': 'Prompt',
            'description': 'Main RAG chat system prompt',
            'affects_rebuild': False,  # Prompt changes don't require rebuild
        },
        # ... more prompt files
    }
}
```

**Benefits**:
- Auto-discovers new keys added to config files
- Metadata loaded fresh each startup (always in sync)
- Validation rules baked into one place
- Easy to add descriptions incrementally without code changes

---

## 5. Data Flow

### 5.1 Q&A Flow

```
User Input (Chat)
  ↓
SettingsWorker.ask_about_setting()
  ├── Load currently selected file
  ├── Parse query for referenced keys
  ├── Build LLM prompt (file + question + category context)
  ├── Call llm.stream()
  └── Emit chunk_received signals
  ↓
SettingsTab.on_chunk_received()
  ├── Append token to chat display
  ├── Update file highlighting (if key mentioned)
  └── Emit final_answer signal (for caching)
  ↓
ChatDisplayWidget
  └── Render markdown + syntax highlighting
```

### 5.2 Edit Flow

```
User Clicks [Edit]
  ↓
SettingsTab._on_edit_mode_toggled()
  ├── Convert QPlainTextEdit to editable
  ├── Show [Save] [Discard] buttons
  └── Lock file selection
  ↓
User Modifies Content
  ↓
SettingsTab.on_text_changed()
  ├── Detect changes (diff against original)
  ├── Highlight changed lines
  ├── Update status bar: "[Unstaged Changes: N items]"
  └── Enable validation preview
  ↓
User Clicks [Preview]
  ↓
SettingsTab._show_diff_preview()
  ├── Render side-by-side diff
  ├── Mask sensitive values (API keys)
  └── Show [Save], [Discard], [Continue] buttons
  ↓
User Clicks [Save]
  ↓
SettingsWorker.save_file()
  ├── Validate each key=value (type, range)
  ├── [IF config.txt] Detect parameter changes:
  │   ├── Read old config.txt from disk (source of truth)
  │   ├── Parse new config from UI
  │   ├── Diff to identify changed keys
  │   ├── Filter for keys with affects_rebuild=True in CONFIG_METADATA
  │   ├── IF any rebuild-affected keys changed:
  │   │   └── Show dialog: "Retriever settings changed. Rebuild?"
  │   │       ├── [Rebuild Now]: Save + trigger RagBuildWorker
  │   │       ├── [Rebuild Later]: Save + show toast with [Rebuild] button
  │   │       └── [Cancel]: Don't save, return to edit mode
  │   └── IF only LLM/other params changed: Proceed to save
  ├── Create backup (.rag_cache/backups/{filename}.{timestamp})
  ├── Write to disk
  ├── Update RAG_CONFIG (if config.txt)
  ├── Reload affected workers based on what changed:
  │   ├── Retriever K changed: RagBuildWorker rebuilds indices
  │   ├── LLM params changed: LLMWorker/AgenticWorker reload on next query
  │   └── Prompts changed: Notify all workers to reload immediately
  └── Emit save_complete signal
  ↓
SettingsTab.on_save_complete()
  ├── Show success toast
  ├── Return to read-only view
  ├── Unlock file selection
  └── Clear unsaved changes indicator
```

### 5.3 File Monitoring Flow

```
SettingsTab.__init__()
  ├── Start FileMonitorThread (QThread)
  └── Connect mtime_changed signal
  
FileMonitorThread.run()
  ├── Every 2 seconds:
  │   ├── Poll file mtimes for all config files
  │   ├── Compare with last known mtime
  │   └── If changed: emit external_change_detected signal
  
SettingsTab.on_external_change_detected()
  ├── If file currently being edited: show warning banner
  ├── If file not being edited: silently update timestamp
  └── Offer [Reload] button if user needs fresh content
```

---

## 6. Integration Points

### 6.1 With Existing Systems

#### Config Loading (rag_core.py)

**Current behavior**: `_load_config()` reads config.txt at app startup once.

**Change required**: 

1. Add function to detect which parameters changed:
```python
def classify_config_changes(old_config, new_config):
    """
    Classify changed parameters into categories.
    Handles both known keys (in CONFIG_METADATA) and unknown keys gracefully.
    
    Returns: dict { 
        'requires_rebuild': bool,
        'affected_keys': [list of changed keys],
        'unknown_keys': [keys not in CONFIG_METADATA, treated as pass-through]
    }
    
    Unknown key handling (Option B):
    - Unknown keys are accepted silently (no validation)
    - Treated as safe to save (no rebuild trigger unless explicitly marked)
    - Allows backward compat with old config keys or experimental settings
    """
```

2. Add reload function for LLM-only params (no rebuild needed):
```python
def reload_rag_config_llm_only():
    """Reload config.txt and update RAG_CONFIG dict (LLM params only)"""
    global RAG_CONFIG
    RAG_CONFIG = _load_config()
    # Notify listeners (LLMWorker, AgenticWorker) to reload
    config_reloaded_llm_only.emit()
```

3. **IMPORTANT CONSTRAINT**: Retriever K parameters (VECTOR_K, BM25_K, GRAPH_K, GRAPH_HOPS, SEQ_DECAY, VAR_DECAY) require full RAG system rebuild:
   - These affect FAISS index ranking and BM25 scoring
   - Runtime changes do NOT re-rank existing indices
   - When user changes these values in Settings tab, trigger RagBuildWorker to rebuild all indices
   - This is expensive (~30-60s) so user must explicitly confirm

Affected components by change type:
- **Retriever K changes** → RagBuildWorker (rebuild FAISS/BM25/Graph indices)
- **LLM params only** → LLMWorker, AgenticWorker (reload on next query, no indices affected)
- **Agentic params** → AgenticWorker (reload on next agentic query)
- **Prompt changes** → All LLM workers (reload immediately)

#### Prompt Loading (agentic_rag.py, rag_core.py)

**Current behavior**: Prompts loaded once at app startup or when worker starts.

**Change required**: Add reload hooks:
```python
def reload_system_prompt():
    """Reload system_prompt.txt from disk"""
    return load_system_prompt()  # Already exists

# Similar for other prompts:
# reload_force_prompt()
# reload_agentic_planner_prompt()
# reload_agentic_sufficiency_prompt()
# reload_agentic_synthesis_prompt()
# reload_notebook_chat_prompt()
# reload_summary_prompt()
```

When Settings tab saves a prompt file, emit signal to all affected workers to reload.

#### env.txt Handling

**Current behavior**: Loaded once at app startup via env_loader.py.

**Change required**: env.txt is typically loaded at startup and shouldn't need runtime reload (API keys don't change per session). However:
- Settings tab can display env.txt
- User can edit it
- On save, log a message: "⚠️ env.txt changes take effect after app restart"
- Do NOT require restart for this version (future enhancement)

### 6.2 UI Integration

**Add to MainWindow**:
1. Tab order: Insert SettingsTab before or after graph_tab
2. Connect SettingsTab signals to MainWindow for worker coordination
3. Forward llm_stop_requested signal to SettingsWorker (for stopping Q&A)

**Update config_panel.py**:
- Add "Open Settings Tab" quick link button (optional)
- When user changes LLM model in config panel, sync with Settings tab's env display

---

## 7. Testing Strategy

### Unit Tests

| Test | Target | Coverage |
|------|--------|----------|
| `test_config_validation()` | Validate key=value constraints | 100% of ConfigMetadata rules |
| `test_file_load_save()` | Read/write files with backup | Happy path + error cases |
| `test_diff_generation()` | Side-by-side diff rendering | Format correctness |
| `test_llm_prompt_building()` | Q&A prompt construction | Injection safety, category filtering |
| `test_key_detection()` | Parse questions for config keys | Typo tolerance, multi-key queries |

### Integration Tests

| Test | Scenario |
|------|----------|
| `test_end_to_end_ask_edit_save()` | User asks → edits → saves workflow |
| `test_external_file_change()` | Another process modifies file while open |
| `test_unsaved_changes_on_tab_switch()` | User leaves tab with edits → returns |
| `test_config_reload_affects_retriever()` | Save config → next RAG query uses new params |

### Manual Testing Checklist

- [ ] Open Settings tab, select env.txt — display content correctly
- [ ] Ask "What is VECTOR_K?" — get sensible LLM explanation
- [ ] Click [Edit], change a value, click [Preview] — diff shown correctly
- [ ] Click [Save], verify file written to disk
- [ ] Modify config.txt externally (edit in VS Code) — Settings tab detects change
- [ ] Edit a config value, click [Reset to Defaults] — confirm restores original
- [ ] Try invalid value (e.g., VECTOR_K=0) — validation catches it, shows error
- [ ] STT Mode: Activate Voice Input, select Settings tab, verify no conflicts

---

## 8. Success Metrics

### User-Facing

1. **Discoverability**: Users can find explanations for 95%+ of config parameters via Q&A (measured by coverage of ConfigMetadata)
2. **Ease of editing**: Users can change a config value in < 30 seconds (measured in UX testing)
3. **Safety**: 100% of saves are confirmed with "Are you sure?" dialog; no accidental overwrites
4. **Data integrity**: All saves are backed up before overwrite; no data loss incidents (measured by error logs)
5. **Adoption**: 30%+ of active users interact with Settings tab per session (telemetry)

### System-Facing

1. **Correctness**: All saved values validate against ConfigMetadata constraints (100%)
2. **Performance**: File operations < 100ms; LLM Q&A first token < 5s
3. **Reliability**: No crashes on malformed edits; graceful error handling
4. **Maintainability**: ConfigMetadata serves as single source of truth for all config docs

---

## 9. Dependencies & Risk Analysis

### Dependencies

| Component | Required | Notes |
|-----------|----------|-------|
| LangChain ChatOpenAI | ✅ | Already available |
| PyQt6 text widgets | ✅ | Already available |
| cache_store.py | ✅ | Extend for Settings chat history |
| rag_core.py | ✅ | Extend for ConfigMetadata + reload hooks |

### Risks & Mitigation

| Risk | Severity | Mitigation |
|------|----------|-----------|
| User breaks config with invalid values | Medium | Validation + constraints in ConfigMetadata + backup files |
| API key accidentally logged | High | Mask keys in diff/logs; validate no logging of env values |
| File corruption during save | Low | Write to temp file, then atomic rename; backup before write |
| LLM Q&A hallucinating wrong parameter names | Medium | Prompt injection testing; provide correct parameter list in prompt |
| User changes retriever K but expects immediate effect | Medium | **Explicit dialog + rebuild confirmation required**. Never apply retriever K changes silently. |
| Long RAG rebuild blocks chat queries | Medium | Run RagBuildWorker in background; chat queries still work with old indices until rebuild completes |
| In-flight queries see inconsistent indices (old + new) | Low | Mark RAG system "rebuilding" state; queries queue or use old system until rebuild finishes |
| RAG rebuild fails (corrupted notebook, FAISS error) | Medium | **Option A**: Show error dialog, keep old RAG system running. User can retry rebuild or fix issue. Never rollback config (too complex). |
| Config.txt modified during rebuild | Low | **Create backup of config.txt before starting rebuild**. If rebuild fails, user can manually restore from backup if needed. |

---

## 10. Acceptance Criteria

- [ ] Settings tab displays all 9 config file entries
- [ ] Q&A returns sensible answers for ≥80% of config parameters
- [ ] User can edit a value and save it to disk without corruption
- [ ] File changes are backups to .rag_cache/backups/ before overwrite
- [ ] Validation prevents invalid values (e.g., VECTOR_K > 20 or < 1)
- [ ] Category filtering works and highlights relevant keys
- [ ] Diff preview shows exact changes before save
- [ ] External file changes are detected and offered for reload
- [ ] No unsaved edits are lost when switching tabs (prompt if needed)
- [ ] **Retriever K changes trigger rebuild dialog** (VECTOR_K, BM25_K, GRAPH_K, GRAPH_HOPS, SEQ_DECAY, VAR_DECAY)
  - [ ] Dialog offers [Rebuild Now] [Rebuild Later] [Cancel] options
  - [ ] [Cancel] reverts all changes, stays in edit mode
  - [ ] [Rebuild Later] saves config, shows toast with [Rebuild] button
  - [ ] [Rebuild Now] saves config, triggers RagBuildWorker, shows progress bar
- [ ] **LLM param changes apply immediately** (no rebuild needed, take effect on next query)
- [ ] **Prompt file changes reload immediately** (all workers notified)
- [ ] RAG rebuild progress shown in UI (not blocking main chat)
- [ ] Chat queries work normally during RAG rebuild (use old indices)
- [ ] All unit & integration tests pass
- [ ] Confirmation dialogs appear on all destructive operations (Save, Discard, Reset)
- [ ] Backups are created for every file save
- [ ] No API keys exposed in logs, diffs, or Q&A responses

---

## 11. Implementation Phases

### Phase 0: Metadata Infrastructure (Early in Week 1)
- [ ] Implement `build_config_metadata()` function (reads env.txt, config.txt, prompts/ at startup)
- [ ] Create CONFIG_METADATA dict with validation rules + descriptions for all ~25 parameters
- [ ] Call `build_config_metadata()` in main.py before creating MainWindow
- [ ] Pass CONFIG_METADATA to MainWindow for use by all tabs/workers
- [ ] Add unit tests for metadata parsing + validation rules

### Phase 1: Foundation (Week 1)
- [ ] Create `SettingsTab` class with basic file selection UI
- [ ] Create `SettingsWorker` for file I/O
- [ ] Implement file display (read-only) for all 9 config files
- [ ] Add to MainWindow tab bar
- [ ] Use CONFIG_METADATA for validation

### Phase 2: Q&A & Chat (Week 2)
- [ ] Implement `SettingsWorker.ask_about_setting()` with LLM prompt
- [ ] Build chat display panel (reuse ChatTab's QWebEngineView pattern)
- [ ] Test Q&A accuracy for 20 key parameters

### Phase 3: Editing & Validation (Week 2-3)
- [ ] Implement edit mode toggle
- [ ] Build ConfigMetadata with validation rules for all parameters
- [ ] Implement inline value editor + validation
- [ ] Add [Preview] diff display
- [ ] Test save/reload workflow

### Phase 4: Advanced Features (Week 3-4)
- [ ] File monitoring (external change detection)
- [ ] Category filtering
- [ ] Reset to defaults
- [ ] Backup management
- [ ] Keyboard shortcuts

### Phase 5: Polish & Testing (Week 4)
- [ ] Integration testing (end-to-end workflows)
- [ ] Performance optimization (file loading, Q&A)
- [ ] Error handling & edge cases
- [ ] Documentation & tooltips

---

## 12. Future Enhancements

- [ ] **Real-time parameter suggestions** — As user types a value, suggest valid ranges with tooltip
- [ ] **Impact visualization** — Show which system components are affected by each parameter
- [ ] **Presets** — Save/load config preset combinations (e.g., "Fast & Shallow", "Slow & Deep")
- [ ] **History tracking** — Show who changed what config when (git-based audit trail)
- [ ] **Multi-profile support** — Switch between different config profiles per use case
- [ ] **Performance tuning wizard** — Guided flow to optimize settings based on notebook size & query patterns
- [ ] **Advanced config files** — Extend to .moai/ configuration if SKHU Agent adopts MoAI project structure

---

## Version

- **Version**: 1.0 DRAFT
- **Last Updated**: 2026-07-11
- **Author**: MoAI Plan Workflow
- **Status**: Awaiting user feedback & approval
