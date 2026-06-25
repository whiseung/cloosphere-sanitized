# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **📄 Document Processing — Per-Extension Extraction Engine Mapping**: Document processing profiles now support an extension → engine mapping instead of a single engine for all files. Within the same knowledge base you can route PDFs through Azure Document Intelligence while sending Excel files to the native `UnstructuredExcelLoader` for better table preservation, and so on.
  - **New ExtractionEngineProfile resource**: Engine credentials are now a reusable unit. Multiple credentials for the same `engine_type` (e.g. DI Prod / DI Dev) can coexist.
  - **Zero-downtime multi-tenant compatibility**: The new `extension_engine_map` column is opt-in. While it remains empty the legacy single-engine path runs unchanged. Admins migrate at their own pace via the "Convert to mapping" button on the profile card; auto-backfill pairs the existing engine with a Native fallback so the same files keep producing the same output. Legacy columns are preserved so a code rollback recovers behavior instantly.
  - **Strict-mode unmapped extensions**: When a profile has an active mapping, uploads of extensions not listed in the mapping are rejected with HTTP 400 — preventing silent engine bypass.

### Fixed

- **📧 Work-Log Email**: When an approval email cannot be sent (no channel configured), the toast no longer shows green success — it shows a yellow warning instead. Work-log approval emails now always include `support-cloosphere@cloocus.com` as CC (CC parameter added to all SMTP / SendGrid / MSGraph / Azure senders).
- **📄 Document Extraction — Hidden Inputs + Silent Fallback**: Fixed invisible Endpoint / URL fields in the document profile modal (Document Intelligence, Tika, Docling, Document AI) — replaced raw `<input>` elements with the shared `Input` component. Also closed the silent fallback where a configured extraction engine with empty credentials would quietly drop to the native loader: this now raises an explicit `ValueError` so admins immediately know their configured engine is being bypassed.

---

## [1.0.3] - 2026-04

Major security & governance release: enterprise-grade KMS (Azure Key Vault envelope, per-classification KEKs, automatic rotation, tamper-evident audit log), MCP tool OAuth/SSO authentication with whitelisting, and a KG `kg_cypher` escape-hatch tool. Also completes the workspace sharing model and tightens external-identity integration. Items already covered by the cumulative 1.0.1 entry above are not repeated.

### Added

- **🔐 Enterprise KMS Integration**: Sensitive configuration values, DbSphere connection credentials, tool connection keys, and user API keys can now be wrapped under an external KEK held in Azure Key Vault. AES-256-GCM data encryption + RSA-OAEP-256 KEK wrapping, with the KEK never leaving the vault. Admins configure the provider in the new Settings → Encryption tab; bulk migration and per-tier health-checks are built in.
  - **Per-Classification KEK Separation**: An optional Restricted KEK URI routes PII / financial classifications to a separate KEK, enabling crypto-shred of PII without touching other secrets.
  - **Automatic KEK Rotation**: When KV's `rotation_policy` produces a newer KEK version, a scheduled check detects it and re-encrypts every envelope under the new KEK. Dry-run mode logs would-rotate decisions for the first activation period.
  - **Tamper-Evident Audit Log**: Every wrap / unwrap / rotate / health-check / migrate is recorded with a SHA-256 prev_hash + row_hash chain. Integrity verification and CSV export (with mandatory reason) are exposed in the new Monitoring → KMS Audit tab; a quick status block lives in Settings → Encryption.
  - **Atomic Save**: Saving the Encryption tab pre-flights a health-check against the new KEK before persisting, and prompts to migrate existing envelopes when the KEK URI changes — so a bad URI never replaces a working configuration.
- **🤝 MCP Tool OAuth / SSO Authentication & Whitelist**: MCP tool connections accept OAuth (per-provider) or Cloosphere SSO token passthrough as an authentication mode, in addition to the existing none / API-key / bearer modes. Each tool exposed by an MCP server can be individually enabled or disabled, so operators can prevent unintended tools from being available to agents.
- **🧠 `kg_cypher` Tool — Read-Only Cypher Escape Hatch**: A new KG tool lets agents run read-only Cypher queries directly against the graph for cases the existing five tools cannot express. A safe-execution layer enforces read-only (mutating queries are blocked), an LLM judge double-checks query safety, and tool results are promoted into the `final_answer` KG context. Includes a built-in guide for the Apache AGE `ORDER BY` alias pitfall to improve first-attempt accuracy.
- **🧠 KG Semantic Memory (5 types)**: `cypher_example`, `kg_schema_doc`, `kg_domain_doc`, `cypher_pattern`, and `cypher_negative` memories help the KG agent reuse successful patterns and avoid repeated mistakes, with deduplication and drift handling built in.
- **🤝 External IDP ID Token Passthrough (Trusted Audiences)**: Externally-issued ID tokens (Entra, Google) can be accepted directly via a trusted-audience allowlist, removing the need for an explicit token exchange when integrating with existing identity providers.
- **📅 Schedule Sharing & Access Control**: Schedules now expose 2-tier (read / write) access_control sharing. Read sharers can view and copy; write sharers can edit, toggle, and trigger. The execution context always pins to the original owner so manual triggers cannot escalate privileges.
- **📚 Glossary Governance UX**: Single-group scope labels, filter chips, and a dedicated Copy modal let read sharers open detail pages and clone glossaries while keeping write actions owner-only.
- **🔐 Workspace Sharing Model Alignment**: Tools, tags, glossaries, and schedules now apply the same read-detail / write-mutate boundary, so resource detail pages remain accessible to read sharers while write controls only appear for owners and write sharers.
- **👤 User Editor Improvements**: The user edit modal now surfaces the user's organization unit assignment and tightens the overall UX.
- **🏷️ Tags Feature Permission**: A new `workspace.tags` permission (read / write) governs who can manage workspace tags.
- **🔧 Worker Queue Auto-Cleanup**: Settings → Data Retention now exposes thresholds for automatically removing zombie / stuck queue messages and consumers, keeping background workers healthy without manual intervention.

### Changed

- **💬 Citation Chip Redesign**: The `[n]` citation chips in chat responses were redesigned for better readability and density.
- **🤝 Teams Bot Multi-Worker Session Sync**: Teams bot session state is shared via Redis, so conversation context survives across multi-worker deployments.
- **🔧 Multi-Worker Config Sync**: PersistentConfig, OAuth credentials, and KMS configuration changes are propagated to every worker in real time via Redis pub/sub, eliminating cross-worker config drift after admin edits.

### Fixed

- **🧠 KG Pipeline Stabilization**: KB chunk extraction now writes `doc_entity` nodes to the AGE graph (previously SQL was populated but the graph was left empty), KG document search results are split per-file as separate sources, and the KG jobs API masks credentials in its response.
- **🔧 Reliability**: Database migrations are now idempotent with explicit zombie-schema verification, the multi-worker `KMSRouter` is automatically reloaded on configuration changes, the audit-log chain is serialized at the SQL layer (preventing cross-worker race breakage), the search-settings modal save no longer throws on `.trim()` for null-ish values, the OpenAI connection masked-secret recovery is now keyed by URL, and OAuth login syncs the user's organization-unit meta on every callback.

---

## [1.0.2] - 2026-04

Patch release covering smaller items not captured in the cumulative 1.0.1 entry.

### Added

- **🔍 Knowledge Base Batch UX**: Extraction progress, re-extraction, and bulk deletion are now exposed for knowledge-base file operations.
- **🔍 Glossary-Type KB Filter + Redis Queue Pipeline**: The KB extraction filter accepts a glossary type, and extraction jobs run through the Redis Queue pipeline.
- **🔧 Admin Onboarding Toggle**: Admins can toggle the first-login onboarding walkthrough on or off.
- **📝 Agent Tool-Description Warning Banner**: The agent editor surfaces a warning banner when a connected tool has no description.
- **🌐 UI Component Unification**: Admin Locales inputs, usage-limit action selector, and the Inquiry modal selector were migrated to the shared component library for consistent behavior.

### Fixed

- **🔧 Reliability**: `stream=false` requests now route through UnifiedAgent, KG-only agents no longer expose standalone KbSphere / DbSphere tools, and tool-call prompts were generalized (removed domain-specific examples).

---

## [1.0.1] - 2026-04

Feature expansion and stabilization update following the 1.0.0 release. Highlights include Microsoft Teams bot integration, Google Workspace directory sync, embed widget expansions, Knowledge Graph Phase 2 structural overhaul, glossary enhancements, and workspace-wide shared tags.

### Added

- **🤝 Microsoft Teams Bot**: An official bot that lets users chat with Cloosphere agents directly inside Microsoft Teams. Supports agent selection, conversation persistence, multilingual responses, and an admin UI for configuration and deployment.
- **🏢 Google Workspace Directory Sync**: Organizations, departments, and groups are automatically synced from Google Admin Directory, including detailed member information. Parallel processing and backoff retries ensure stable sync even for large organizations.
- **💬 Embed Widget Expansion**:
  - **Guest Mode**: Non-authenticated users can now use the embed widget, enabling chatbot deployment on public-facing websites.
  - **SSO Token Exchange**: A new endpoint securely exchanges externally-issued tokens for a Cloosphere session.
  - **Bottom Side Panel Mode**: A new display mode that shows the widget as a fixed panel at the bottom of the page.
  - **User Resize + Host Layout Auto-Shift**: When the user resizes the widget, the host page content automatically shifts so it is not covered.
  - **Admin SSO Tab + Design Option Expansion**: A dedicated SSO settings tab and additional design customization options are provided.
- **🧠 Knowledge Graph Phase 2 — Document Structure Expansion**:
  - **Container/Document/Chunk Node Hierarchy**: Knowledge-base document structure is now represented systematically in the graph.
  - **Automatic Document Type Classification**: Document types are inferred from chunk content and can be used as KB filters.
  - **Edge Catalog Modal**: A dedicated modal and settings screen manage and recommend edge types by category.
  - **Full-Screen Graph View + Edge List**: A full-screen view and edge list screen make it easier to explore large graphs.
  - **Graph-RAG Redesign**: The KG agent now integrates with DbSphere memory to produce more accurate answers.
  - **Global Progress Indicator**: KG sync progress is shown in real time via the top notification center and a global indicator.
- **📚 Glossary Enhancements**:
  - **Category Management**: Glossaries can be organized by category.
  - **Background DB Value Extraction**: Bulk extraction runs in the background, with inline review of extracted terms.
  - **Per-Item Custom Instructions**: Per-item instructions can be passed to the LLM during extraction.
  - **Extraction Source Selection**: Terms can be extracted from the title, body, or the first/last N characters.
  - **Pagination + Single-Item CRUD**: Managing large glossaries is easier, and an index rebuild menu is available.
- **🏷️ Workspace Shared Tags & Filter Tabs**: Shared tags and filter tabs are applied across Agents, Knowledge Bases, Databases, Glossaries, Knowledge (dictionaries), Guardrails, Prompts, and Tools lists, making it easy to classify and find large numbers of resources.
- **📊 DbSphere BigQuery Connector**: Google BigQuery can now be connected directly as a DbSphere data source.
- **🔐 Group ↔ Organization Unit Permission Binding**: Groups can be assigned to organization units from the group editor, and guardrails have been added to the organization-unit permission view for finer-grained access control.
- **💡 Follow-up Question Suggestions**: Natural follow-up questions are suggested automatically after each response to keep the conversation flowing.
- **🔔 Background Job Notification Center Integration**: Progress and results of background jobs across knowledge base filters/uploads, DbSphere, glossary, and knowledge graph are consolidated into the top notification center.
- **📊 User Role Change Audit Log**: User role change history is now recorded in the audit log for full traceability of permission changes.
- **📁 Bulk and Directory Upload**: Entire directories can be uploaded to a knowledge base, with automatic duplicate detection and failure-first sorting.

### Changed

- **🔧 Workspace UI/Permission Alignment**: Screen layouts across Knowledge Bases, Glossaries, and Knowledge Graphs are now unified, and the workspace permission tab order is aligned with the actual menu order.
- **⚡ Google Workspace Sync Performance**: User pre-caching eliminates N+1 queries, default concurrency increases from 5 to 15, and backoff retries are applied — significantly improving sync speed for large organizations.

### Fixed

- **💬 Embed Widget Stabilization**: Fixed an issue where some settings were reset when saving the Edit modal, improved streaming rendering and typing animation, and resolved multi-worker synchronization issues for UI action tools.
- **🔐 Organization Sync Reliability**: Empty responses no longer trigger full deletion, and grandchild OUs are now correctly shown in the list. Google Admin Directory group-member lookup errors and automatic skipping of external-domain members were also improved.
- **🔧 Stability and Compatibility**: Redis connection failures now fast-fail and are surfaced through a health endpoint; alembic migrations now respect a custom database schema; migration conflicts in multi-instance environments are prevented; KG Phase 2 migration branches have been merged.
- **💬 OAuth Login UX**: Removed the brief login-form flash that appeared during the OAuth callback.
- **🔧 UI Polish**: Fixed long-username truncation, audit-log statistics/time-range sync on refresh, and removed accidental auto-save of the access-control modal in the guardrail editor, along with other small UI fixes.

---

## [1.0.0] - 2026-04 🎉 Production Release

The first official release of Cloosphere. All previously introduced features have been stabilized, and this release adds a Knowledge Graph that unifies glossaries, databases, and knowledge bases for smarter agent reasoning, an embeddable chat widget for external sites, and a queue-based worker architecture for reliable large-scale file processing.

### Added

- **🧠 Knowledge Graph**: A unified semantic graph that connects Glossary, DbSphere databases, and Knowledge Base documents, so agents can understand complex business questions like "monthly sales from VIP customers at the Gangnam branch" and answer them with real data.
  - **Three-Source Integration**: Glossary terms, database schemas (tables/columns/FKs), and knowledge base documents are unified into one graph with automatic node and edge generation.
  - **Automatic Schema Sync**: Tables and columns from connected DbSphere databases are imported as nodes; foreign-key relationships become edges, reusing the existing DbSphere schema extraction.
  - **LLM-Powered Entity Extraction**: Documents in connected knowledge bases are analyzed by an LLM to extract entities and relationships (`produces`, `owned_by`, `located_in`, `has_risk`, etc.), enabling multi-hop reasoning across data and documents.
  - **Business Term → Column Resolution**: Terms from the glossary are mapped to database columns with filter expressions, dramatically improving NL-to-SQL accuracy ("VIP customer" → `tier = 'VIP'`).
  - **Candidate Term Review**: Business-term candidates extracted from database dimension values are queued for review; accepted candidates are automatically added to the chosen glossary with a `maps_to` edge.
  - **Knowledge Link**: Database dimension values (e.g., product IDs, supplier codes) can be automatically matched with knowledge base documents, creating direct links between data rows and their descriptions.
  - **Agent Integration**: Knowledge graphs connected to an agent automatically expose 5 tools — `kg_resolve_term`, `kg_explore_context`, `kg_search_concepts`, `kg_find_related_tables`, and `kg_neighbors` — and inherit the KG's linked Glossary/DbSphere/KB resources to the agent.
  - **Graph Visualization**: An interactive Cytoscape-based view lets users explore nodes and edges directly, with filtering and search over the node list by type.
  - **Job Tracking & Progress**: Long-running sync and extraction tasks show progress bars and error details in real time, and can be cancelled from the UI.
- **💬 Embeddable Chat Widget**: Embed Cloosphere AI chat into any external website with a single script tag. Create and customize widgets from the admin settings, then deploy them anywhere.
  - **Multiple Display Modes**: 5 display modes supported — bottom-right bubble, left/right side panel, inline injection, and full screen — to match the host site's layout.
  - **Rich Design Editor**: Customize colors (background, header, message, send button), header text, widget dimensions, position, bubble icon, and send button icon (7 presets + custom upload) with a live preview.
  - **Built-in Login**: When loaded without a token, the widget automatically displays OAuth (Microsoft, Google, GitHub, etc.) and email/password login screens. External services can also pass pre-issued tokens directly.
  - **Direct Page Manipulation**: AI agents can fill forms and click buttons directly on the user's current page. When applied to groupware, request forms, or data entry screens, users can describe tasks in natural language and let the AI handle them on screen.
  - **Domain Security**: Each widget supports an allowed-domains list to prevent unauthorized embedding.
- **⚙️ Reliable Large-Scale File Processing (Queue-Based Worker)**: Knowledge base file uploads now flow through a queue-based worker so the main service stays responsive even with bulk uploads.
  - **Automatic Retry + Failure Visibility**: Transient errors are retried automatically; failed files are surfaced in the UI for user-initiated retry.
  - **Same-Filename Replacement**: Re-uploading a file with the same name now replaces the existing file automatically.
  - **Processing Status Cards**: A unified card view shows in-progress, completed, and failed states at a glance.
- **📝 Semantic Chunking + LLM Vision Stabilization**: PDF/Word/PPT and similar documents are now extracted more accurately and chunked by semantic units, improving search quality. Image and scanned documents are reliably processed via LLM Vision.
- **📧 Email Anonymization**: An option to automatically mask email addresses in chat messages and documents has been added.
- **🤖 Strengthened Ollama Model Integration**: Ollama and other open-source models can now invoke tools and generate responses through the same agent flow as commercial models.

### Changed

- **🔧 Worker Architecture Simplification**: The file processing worker has transitioned from an external process to an in-server queue consumer, simplifying operations while preserving queue-based reliability. No separate container needed.
- **🔧 Same-Filename Upload Policy**: Uploading a file with the same name to a knowledge base now replaces the existing file automatically, preventing duplicate registrations.
- **💬 Multi-Language Response Stability**: Issues where some models truncated responses or returned them as arrays have been resolved, ensuring natural responses.

### Fixed

- **🔧 LLM Vision Pipeline Robustness**: Several stability issues in the image/scanned document extraction pipeline have been resolved, improving processing of varied document formats.
- **📊 Oracle Dashboard Compatibility**: Date function compatibility issues during Oracle-based dashboard auto-generation have been fixed.
- **🛡️ Guardrail Application Accuracy**: Global guardrails now correctly apply even when an organization has its global-guardrail option disabled, as intended.
- **💬 Gemini Model Stabilization**: Fixed response truncation and guide Q&A crashes when using Gemini models.
- **🔍 Korean Input Stabilization**: Fixed an issue where Korean consonants were duplicated in knowledge base filter option inputs.
- **🔧 Modal/UI Stability**: Resolved various UI stability issues including AI assistant panel dropdown clipping and modal backdrop click errors.
- **🔧 Multi-Instance Environment Safety**: Migration races in multi-process environments are now prevented.

---

## [0.8.0] - 2026-04

### Added

- **📊 BI Dashboard**: A new BI Dashboard has been added to the Monitoring menu. Build dashboards with 7 chart types (bar, line, pie, area, scatter, table, card) from connected databases, with period filters and dynamic filters for real-time data exploration. Drag-and-drop panel layout on a 12-column grid with resizing support.
- **📊 AI Dashboard Auto-Generation**: AI analyzes database schemas and automatically generates charts and cards tailored to your goals. Use the multi-turn conversational builder to chat with AI for adding, removing, or repositioning panels.
- **🔧 Agent Flow V2**: Major improvements to the agent flow system.
  - **AI Conversational Flow Builder**: Describe your desired flow in natural language and AI automatically creates nodes and connections. Multi-turn conversation guides you through key decisions like guardrails and routing strategies.
  - **Parallel Execution**: Fan-out pattern runs multiple nodes simultaneously for faster processing.
  - **Execution Trace**: Track each node's input/output and execution time during flow runs for easy debugging.
  - **New Nodes**: Router, Merge, Condition, Transform, and Glossary nodes added.
  - **Variables System**: Define variables within flows and pass data between nodes.
- **📝 Document Processing Profiles**: Apply different extraction and chunking strategies per knowledge base. Manage processing options as profiles, including LLM Vision-based extraction (for images and scanned documents) and Semantic Chunking.
- **🛡️ Hierarchical Guardrail Management**: Configure guardrails at group and organization levels. During chat, guardrails are automatically merged in order: source → group → organization → global. Code Gateway can also follow global and organization guardrails.
- **📧 Service Request (SR) System**: Users can submit service requests from the sidebar, which are automatically sent via MS Graph API email. Each customer receives an auto-generated SR key for identification.
- **🔔 Toast Notification History**: Review past toast notifications from a bell icon dropdown. Includes unread count badge with copy and delete functionality.
- **🔧 Model Selector Type Classification**: Models are automatically categorized as agent, flow, or model types in the selector. Type labels help you quickly find the right model.

### Changed

- **🔐 Workspace Permission Controls**: Save buttons and access control settings are hidden or disabled for users without write permissions. Create buttons on workspace lists are also permission-gated.
- **📊 SQL Query Preview Enhancement**: View DbSphere SQL execution results via a dedicated button with improved query formatting.
- **🔧 Admin Menu Restructure**: Arena model settings moved from Admin > Settings to Admin > Evaluations > Arena tab, consolidating evaluation-related features in one place.
- **💬 Multilingual Error Messages**: Frontend error messages are fully internationalized, displaying in the user's configured language.
- **🔧 Duplicate Name Prevention**: Workspace items and monitoring dashboards now warn when an item with the same name already exists.

### Fixed

- **🔧 Agent LLM Retry**: Automatic retry on LLM call failures during agent execution ensures stable operation through transient errors.
- **💬 Memory Module Stability**: Multiple memory-related bugs fixed for reliable conversation context retention.
- **🔍 Embedding Configuration Stability**: Improved embedding URL handling and vector dimension settings for more reliable knowledge base file uploads.
- **📊 Oracle Dashboard Date Filter**: Period filter date formats are now correctly handled for Oracle database dashboards.
- **🔧 Modal Backdrop Click Fix**: Fixed an issue where clicking outside a modal caused the screen to freeze.

---

## [0.7.7] - 2026-03

### Added

- **📊 Data Analysis Project (Code Interpreter)**: A new "Data Analysis" project type enables uploading CSV/Excel files and analyzing data with Python code in a Jupyter environment, with interactive chart generation.
  - **3-Stage Tool Design**: File overview → column detail inspection → code execution. The LLM progressively understands data structure before writing analysis code.
  - **Plotly Interactive Charts**: Renders pie charts, bar charts, line charts, and more with hover and zoom support.
  - **Code Execution Visibility**: View executed code and results in a modal with copy and download options for output.
  - **Security Sandbox**: Each project's Jupyter kernel is isolated to only access its own workspace files. Cross-project data access is blocked.
  - **Auto File Remount**: Project files are automatically remounted when the Jupyter server restarts — no manual re-upload needed.
  - **Jupyter Docker Image**: A dedicated Docker image with pandas, plotly, scipy, and openpyxl pre-installed.

### Changed

- **🔧 Keycloak Org Sync via Environment Variables**: Keycloak organization sync now uses OIDC environment variables (OPENID_PROVIDER_URL, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET) instead of admin account credentials. Uses client_credentials grant for improved security.

### Fixed

- **🔄 Multi-Worker CONFIG_DATA Overwrite**: Fixed settings loss when one worker's save overwrites another worker's changes in a 4-worker deployment. Read-modify-write with optimistic locking ensures config integrity.
- **🔑 License Cross-Worker Sync**: LICENSE_KEYS, FEATURE_KEYS, and ENABLE_LICENSE_ENFORCEMENT are now registered in AppConfig for Redis-based worker synchronization.
- **🔐 Keycloak Token Endpoint Fix**: Fixed organization sync token requests being hardcoded to the master realm. Tokens are now requested from the realm where the client exists.

---

## [0.7.6] - 2026-03

### Added

- **📊 DBSphere Progressive Context Retrieval**: When querying databases, the agent progressively gathers information in three stages — DB overview, relevant table details, then SQL execution. Only the necessary context is retrieved at each step, significantly reducing token usage and improving response speed.
- **🔧 Two-Stage Tool Selection (Tool Connection)**: The agent first discovers available external tool servers (MCP/OpenAPI), then selectively invokes only the tools relevant to the question. This ensures efficient operation even when many tool servers are connected.
- **💻 Code Gateway Repository Tracking**: Track which project (git repository) AI coding tool requests originate from. Administrators can block specific repositories or enforce a policy requiring repository metadata on all requests.
- **💻 Code Gateway Claude Code Support**: One-click setup for Claude Code users. A single install command provided by the administrator auto-configures helper scripts and authentication, supporting both Linux/macOS and Windows.
- **📈 Monitoring Automation**: Enable monitoring from admin settings, download the bundle, and run a single script to automatically set up a Prometheus + Grafana monitoring environment. Pre-configured dashboards for Node, PostgreSQL, Redis, and application metrics are included.
- **💬 Google Chat Webhook Support**: Google Chat has been added as a notification webhook channel. Receive schedule execution results and test notifications directly in your Google Chat workspace.

### Fixed

- **📝 Unnecessary Citation Markers**: Fixed `[1]`, `[2]` citation markers appearing in responses that did not reference knowledge base documents.
- **💬 Chat Switch Response Loss**: Fixed previous chat responses disappearing when switching between chats.
- **🔍 Knowledge Base Source Tracking**: Source information used in answers is now reliably stored, and detailed per-source content can be reviewed in the trace view.
- **🛡️ PII Email Masking Security**: Fixed a security issue where the full local part of email addresses was exposed during masking.
- **📅 Schedule Job Stability**: Fixed issues where chat models were not selected and other users' chats were mixed in scheduled jobs.

### Changed

- **📊 DBSphere Schema Search Performance**: Server-side filtering is now applied when looking up table schemas, enabling faster retrieval of table information even in large databases.
- **🔍 Knowledge Base Tool Description**: AI-generated tool descriptions now include filter metadata guidance, helping agents perform filter-based searches more effectively.

---

## [0.7.5] - 2026-03

### Added

- **🔍 Knowledge Base Filter Metadata AI Auto-Extraction**: When files are uploaded, the LLM automatically extracts filter metadata by analyzing document content and file title. Supports collection (multi-value) filter type, required field indicators, and 4-level extraction status display.
- **📊 Conversation Logs**: Administrators can view all users' chat and Code Gateway usage logs in a unified view. Includes input/output preview, token usage, and filtering by date, user, and model.
- **🗑️ Data Retention Policy**: Configure automatic deletion policies for chat history. Chat data is automatically cleaned up after the retention period expires.

### Fixed

- **📁 Knowledge Base Multi-File Upload Bug**: Fixed an issue where only the last file remained in the vector index when uploading multiple files simultaneously.
- **💻 Code Gateway Stability Improvements**: Fixed several stability issues including Azure-unsupported field removal in Responses API redirect, NoneType error handling, and Vertex AI OpenAI-compatible path URL building.
- **📊 DbSphere Chart NaN Error**: Fixed chart rendering failure when data contained NaN values due to serialization errors.
- **📋 CSV User Import Encoding Fix**: Fixed Korean text corruption and empty row errors when importing users via CSV files.
- **🛡️ Guardrail Log Improvements**: Fixed custom pattern violation type display and glossary citation references.

### Changed

- **💻 Code Gateway Admin UI Improvements**: Enhanced the Code Gateway connection management interface.
- **🛡️ Guardrail Log Search & Filter**: Improved search and filtering capabilities for guardrail logs.
- **🔐 License Feature Registry Source of Truth**: In developer mode, the feature registry DB now serves as the actual enforcement source for license tier-module mappings. License status is immediately refreshed when the feature registry is modified.
- **🔧 Flows Developer Mode Only**: The workspace Flows (Agent Flow) tab is now visible only in developer mode.

---

## [0.7.4] - 2026-03

### Added

- **💻 Code Gateway Enhancement (Preview)**: The API proxy gateway for AI coding tools has been expanded. Supports Cursor, Codex CLI, and Gemini CLI with unified management of 6 providers (OpenAI, Anthropic, Gemini, Azure OpenAI, AI Foundry, Vertex AI). Includes per-user rate limiting, model allow lists, guardrail integration, and file pattern blocking.
- **📊 Code Gateway Usage Monitoring (Preview)**: Track token usage for AI coding tools by user and model. View detailed logs and statistics in the admin panel.
- **🔄 Responses API Auto-Conversion (Preview)**: When IDEs like Cursor send Responses API format to the Chat Completions endpoint, requests are automatically redirected to the Azure OpenAI Responses API for compatibility.

---

## [0.7.3] - 2026-03

### Added

- **📊 Daily Token Usage Limits**: Set daily token usage limits per user, group, or organization. The most generous value across the 4-level hierarchy (global → user → group → organization) is applied. Choose between warning or blocking behavior when limits are exceeded.
- **⚠️ Graduated Usage Warnings**: Automatic warning toasts appear during chat input when daily usage reaches 80%, 95%, and 100%. In blocking mode, additional requests are blocked when the limit is exceeded.
- **📬 Admin Inquiry System**: Users can send inquiries to administrators from the sidebar. Supports 5 inquiry types (usage limits, features, bugs, account, other) with detailed subtypes. Admins manage and respond to inquiries via kanban board or list view, with green badge notifications for unread responses.

---

## [0.7.2] - 2026-02

### Added

- **🤖 Agent Prompt AI Auto-Generation**: Automatically generate system prompts, task prompts, and answer format prompts for agents using AI. Quickly set up purpose-built agents without writing prompts manually.
- **📝 DbSphere Tool Description AI Auto-Generation**: AI analyzes connected database schemas and auto-generates tool descriptions that guide agents on when and how to query each database.
- **🧠 AI Auto-Write Model Selection**: Choose which LLM model powers AI auto-generation features (prompts, descriptions) from a dedicated dropdown.
- **🔷 AI Foundry Connection**: Connect models from Microsoft AI Foundry directly from Admin Settings > Connections. AI Foundry is also supported as a Code Gateway provider.
- **🛡️ Guardrail "Log Only" Strategy**: A new guardrail violation handling strategy that logs violations without blocking — ideal for monitoring before enforcing strict rules.
- **🎨 Her Theme**: A new "Her" visual theme inspired by the movie is available in user settings.

### Fixed

- **🛡️ Guardrail PII Detection**: Fixed inconsistencies between PII detection and masking that could cause false negatives or incorrect masking.
- **🌐 System Language Context**: The system language is now correctly passed to agents, preventing random-language responses.
- **🔐 Permission Level "none" Bug**: Fixed the "none" permission level being incorrectly treated as truthy, granting unintended access.

---

## [0.7.1] - 2026-02

### Added

- **🔍 Search Reranker Threshold**: Configure a minimum relevance score for reranked search results. Results below the threshold are automatically filtered out, improving answer quality.
- **📊 Trace RETRIEVAL Span**: Knowledge base retrieval steps now appear as dedicated spans in the trace view, including reranking metadata for deeper debugging.
- **🔐 Trace Button Permission Control**: The trace analysis button is now visible only to users with the appropriate group permission level.
- **💻 Code Gateway**: An API proxy gateway for AI coding tools, supporting Vertex AI and other LLM providers with global GCP key integration.
- **🔄 Model Table Auto-Sync**: Changing OpenAI connection settings now automatically synchronizes the model table, ensuring available models are always up to date.
- **📚 Glossary Tool for Unified Agent**: The unified agent can now look up glossary terms during conversations for more accurate domain-specific answers.

### Fixed

- **🌳 Trace Tree Concurrent Tool Fix**: When an agent executes multiple tools in parallel, each tool now correctly appears as a sibling in the trace tree instead of being incorrectly nested.
- **🌙 Dark Mode Logo**: All logos (sidebar, chat placeholder, notifications) now properly switch to their dark variants in dark mode.
- **🔍 Search Score Normalization**: Azure Search and Elasticsearch scores are now normalized consistently, ensuring comparable relevance scores across search engines.
- **📖 Glossary Semantic Search**: Fixed semantic configuration mismatch and field mapping errors that caused glossary searches to fail.

### Changed

- **⚙️ Search Settings Migration**: Search-related settings (Top K, Reranker Top K) have been moved from Documents to the Search Engine settings page for a more logical configuration layout.

---

## [0.7.0] - 2026-02

### Added

- **📄 Google Cloud Document AI**: Extract text from complex document layouts (tables, forms, multi-column pages) using Google Document AI's Layout Parser.
- **🧬 Gemini / Vertex AI Embeddings**: Use Google's Gemini or Vertex AI as embedding engines for knowledge base and glossary vector search. Supports pgvector halfvec format.
- **🗣️ GCP Speech Services**: Google Cloud Speech-to-Text and Text-to-Speech engines, including Gemini TTS, are now available for voice interactions.
- **🔎 pgvector + Reranker**: Full pgvector support with half-precision vectors (halfvec) and a dedicated reranker module for improved search result ranking.
- **💾 Shared Storage Settings**: Configure shared file storage providers (local, S3, GCS, Azure Blob) with independent credentials from Admin Settings.

---

## [0.6.5] - 2026-02

### Added

- **📁 Projects**: Create personal document spaces backed by knowledge bases. Organize files into projects with a tab-based detail UI, share projects with specific users, and chat within project context.
- **☁️ Cloud Storage Integration**: Import files directly from Google Drive, OneDrive, and SharePoint into knowledge bases — no manual download required.
- **👥 Schedule Task Sharing**: Share scheduled tasks with specific users. Sharing creates an independent copy so each user can customize their schedule.
- **👤 Default User Role Group Selection**: Assign a default group to new users during role configuration for streamlined onboarding.

### Fixed

- **⏰ Schedule Time Reset**: Fixed a bug where schedule task times always reverted to 09:00 regardless of user input.

### Changed

- **📊 File Monitoring Integration**: The admin files page has been merged into the Monitoring section as a File Log tab, consolidating all monitoring views.

---

## [0.6.4] - 2026-02

### Added

- **🛡️ File Upload Guardrails**: Define upload rules (allowed file types, size limits) and apply them globally or per scope. Configure guardrails from a dedicated settings tab with real-time test validation.
- **📑 LibreOffice PDF Conversion**: Non-PDF files are automatically converted to PDF on upload using LibreOffice. Configure allowed file extensions from Admin Settings.

---

## [0.6.3] - 2026-02

### Added

- **📅 Scheduled Tasks**: Schedule AI agents or models to run automatically on a cron schedule. Results are saved to a dedicated chat, and notifications can be sent via email or webhook on completion or failure.
- **📨 Multi-Channel Notifications**: Configure multiple email (SMTP / SendGrid) and webhook (Slack / Teams / Discord / Telegram) channels from Admin Settings > Notifications. Each schedule notification can target a different channel with its own title template and message template.
- **📊 Chart Image in Notifications**: When a database agent's response includes charts, they are rendered server-side as PNG images and delivered as inline images in emails or full-width images in webhook notifications.
- **📈 Multi-Chart Support**: Database agents can now generate multiple charts in a single response. Each chart renders independently in the chat interface.
- **🔍 Admin Settings Audit Log**: All administrator setting changes are now recorded in the audit log with before/after values for accountability and compliance.
- **📋 Structured Output (JSON Schema)**: Agent final responses can conform to a JSON Schema `response_format`, enabling structured and parseable outputs.

### Fixed

- **🗄️ SQL Query Validation**: Improved SQL query validation to prevent unsafe operations in database agent execution.

---

## [0.6.2] - 2026-01

### Added

- **🔍 Trace Analysis Report**: When an AI produces incorrect results, an LLM can analyze the full trace context — agent configuration, knowledge bases, databases, guardrails, glossaries, and more — to identify root causes and generate a structured markdown report with actionable recommendations. Reports can be copied or downloaded.
- **🔐 Four-Level Group Permissions**: Group permissions have been refined from a simple ON/OFF toggle to four levels: `none → access → read → write`. This enables fine-grained access control for each workspace and admin menu.

---

## [0.6.1] - 2026-01

### Added

- **🎯 Knowledge Base Dynamic Filters**: Define filter schemas (text, number, date) for each knowledge base and assign metadata values to individual files. Narrow AI search to a specific document subset — for example, search only documents from a particular department or date range.
- **📝 Knowledge Base Tool Description**: Configure a custom description for each knowledge base that guides agents on when and how to use it. AI-generated descriptions are supported for quick setup.
- **🖼️ Image Generation Multi-Connection**: Connect and manage multiple image generation services (Azure OpenAI DALL-E, Gemini, Vertex AI Imagen). Select which provider to use per agent or switch providers directly from the chat input — no admin page required.
- **🏷️ Custom App Name**: Set a personalized application name from Admin Settings > Branding. The name appears in the browser tab, sidebar, and throughout the interface.

### Fixed

- **🔧 File Metadata Sync Reliability**: Saving file metadata no longer triggers duplicate content errors in Azure AI Search. Metadata-only changes are applied in-place without re-embedding documents.

### Changed

- **🗂️ Knowledge Base Settings UI**: Metadata fields are now displayed in a 4-column grid. An explicit Save button in the header gives you clear control over when changes are committed.

---

## [0.6.0] - 2026-01

### Added

- **🗑️ Bulk Delete Extracted Tables**: Delete all AI training data for a database at once from Workspace > Database. Quickly reset incorrect training data and start fresh.

### Fixed

- **🎯 Accurate Table Deletion**: Deleting a table now correctly removes all associated AI training data with no leftovers.
- **📍 Improved AI Trace Accuracy**: Tool execution results and memory retrieval steps are now displayed accurately in the tracing view.
- **🔍 Consistent Search Scores**: AI similarity scores are normalized to a 0–1 range for clear and consistent result confidence.

### Changed

- **🧠 Smarter Date Column Detection**: Columns storing dates as integers are now automatically recognized, generating more accurate SQL for time-based queries.

---

## [0.5.1] - 2025-12

### Added

- **💻 Code Interpreter**: Agents can write and execute Python code to perform data analysis, calculations, and automation tasks on the fly.
- **⚙️ Per-Agent Capability Control**: Toggle web search, image generation, and code interpreter on or off individually for each agent. Optimize each agent for its specific purpose.

### Fixed

- **🎛️ Chat Toggle State Reset**: Feature toggles no longer carry over from the previous chat session when starting a new conversation.

---

## [0.5.0] - 2025-12

### Added

- **🖼️ AI Image Generation**: Agents can generate images mid-conversation. Supports Azure OpenAI DALL-E, Vertex AI Imagen, and more.
- **📁 Image Storage Settings**: Specify where generated images are stored directly from Admin Settings.

---

## [0.4.2] - 2025-12

### Added

- **🤖 Unified AI Agent**: A single agent can now leverage both Database (DbSphere) and Knowledge Base (KbSphere) capabilities simultaneously. Ask questions that combine database lookups with document search.

### Changed

- **🔄 Consolidated Agent Configuration**: Knowledge bases, databases, guardrails, and other agent settings are unified in a single configuration structure for consistent management.

---

## [0.4.1] - 2025-11

### Added

- **🔎 Automatic Schema Extraction**: Automatically analyze connected database table structures and sample data — AI explains each table and column's meaning. Help AI understand your complex DB schema instantly.
- **📊 Extraction Status UI**: Monitor extraction progress and manage the list of extracted tables in real time from Workspace > Database.
- **⚡ Hybrid Search**: Keyword and semantic vector search work together to generate more accurate SQL queries.

---

## [0.4.0] - 2025-11

### Added

- **🧠 AI Memory System V2**: The database agent's learning architecture has been completely redesigned. Successful SQL queries, table definitions, and business rules accumulate over time — the agent gets smarter the more it's used.

### Changed

- **📈 Continuously Improving AI**: Natural language–SQL pairs are stored and reused for similar future questions, enabling faster and more accurate responses as usage grows.

---

## [0.3.2] - 2025-11

### Added

- **🔍 Unified AI Execution Tracing**: Follow the entire agent execution flow — safety filter → query processing → quality evaluation — in one screen. Instantly identify which step caused an issue when something goes wrong.

### Fixed

- **📎 Citations Markdown Rendering**: Document content in the citations popup is now properly formatted and styled.

---

## [0.3.1] - 2025-10

### Added

- **⭐ Automated Quality Evaluation (LLM-as-Judge)**: AI automatically scores agent response quality against criteria like accuracy and completeness. View scores, feedback, and quality trend charts over time.
- **📋 Evaluation Feedback Detail View**: See detailed scores and improvement suggestions for each evaluation result in a dedicated modal.

---

## [0.3.0] - 2025-10

### Added

- **🛡️ Guardrails (Safety Filter) System**: Agents now automatically detect and block PII, sensitive keywords, and inappropriate content. Define custom filter rules in the workspace and apply them to any agent.
- **⚙️ Violation Handling Strategy**: Choose how guardrail violations are handled — block, warn, or allow — for each rule.

---

## [0.2.2] - 2025-10

### Added

- **🌐 Google Vertex AI Gemini Support**: Connect Gemini models from Google Cloud Vertex AI directly to your agents.
- **🔌 External Tool Server Integration (MCP/OpenAPI)**: Connect your organization's internal APIs and tool servers to agents. Supports both the MCP protocol and OpenAPI specifications.
- **🔔 Notification System**: Administrators can configure system notifications that are delivered to users in real time.

---

## [0.2.1] - 2025-09

### Added

- **🔄 Agent Flow Visual Builder**: Build complex AI workflows with drag-and-drop — no coding required. Connect multiple agents with conditional branching to design automated pipelines visually.
- **▶️ Flow as a Model**: Register a completed Flow as a callable model and invoke it directly from chat.

---

## [0.2.0] - 2025-09

### Added

- **📚 Glossary Vector Search**: The glossary is integrated with the AI search engine for more accurate terminology matching in responses.
- **🔍 Unified Search Engine Interface**: Manage and switch between Azure AI Search, Elasticsearch, pgvector, and Vertex AI Search from a single unified interface.
- **🎨 Custom Branding**: Change the logo and other UI elements from Admin Settings to match your organization's brand.
- **📌 Sidebar Menu Aliases**: Assign custom names to sidebar menu items for your team's preferred terminology.

---

## [0.1.2] - 2025-08

### Added

- **📋 Audit Log**: Every user action is recorded with a timestamp. Administrators can review user activity history on the monitoring page to meet compliance requirements.
- **📊 Usage Monitoring**: Track and aggregate token consumption and message counts by agent and user. Embedding API usage is also tracked.

---

## [0.1.1] - 2025-08

### Added

- **🏢 Organization Management**: Group users into organizations and assign access permissions per organization. Separate available features and resources by team or department.
- **📁 SharePoint Integration**: Import documents from Microsoft SharePoint as knowledge base sources. Put your organization's existing document assets to work in AI agents.

---

## [0.1.0] - 2025-07

### Added

- **🗂️ Unified Workspace**: Manage knowledge bases, databases, tools, prompts, and agents all from one workspace screen. Previously scattered configuration pages are now consolidated.
- **🤖 Agents Tab**: Create and configure AI agents directly from the workspace. Connect knowledge bases and databases to build purpose-built AI assistants.

---

## [0.0.2] - 2025-07

### Added

- **👤 Profile Avatars**: Users can upload a profile image displayed in the chat interface.
- **🐘 PostgreSQL Support**: Use PostgreSQL as the backend database in addition to SQLite. Suitable for large-scale production deployments.
- **☁️ Azure Deployment Templates**: Deploy quickly to Azure cloud using Bicep-based infrastructure-as-code templates.

### Fixed

- **📈 Chart Rendering Stability**: Database agent charts now render directly in the browser via Plotly, resulting in faster and more reliable visualization.

---

## [0.0.1] - 2025-06

### Added

- **💬 Cloosphere Launch**: The first version of Cloosphere is now available.
- **🗣️ ReAct AI Agent**: A LangChain 1.0-based ReAct agent supporting tool use, multi-step reasoning, and real-time streaming responses.
- **📚 KbSphere (Knowledge Base Agent)**: AI searches uploaded documents and knowledge bases to deliver accurate answers.
- **🗄️ DbSphere (Database Agent)**: Ask your database in natural language — AI generates the SQL and returns results.
- **🔷 Azure OpenAI Integration**: Model connections and embeddings via Azure OpenAI API.
- **🔷 Azure AI Search Integration**: Use Azure AI Search as a vector database for semantic retrieval.
