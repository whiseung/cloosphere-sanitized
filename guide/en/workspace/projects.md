# Projects

> Projects are personal document spaces. Organize your files backed by knowledge bases, and chat with AI within the project context. Share projects with team members to collaborate on the same documents.

---

## What is a Project?

A project is a **personal document space backed by a knowledge base**. When you select a project in chat, the AI references only the documents in that project.

### Projects vs Knowledge Bases

| Aspect | Projects | Knowledge Bases |
|--------|----------|----------------|
| **Purpose** | Personal/team document space | Knowledge store for agents |
| **Ownership** | Personally owned, selectively shared | Shared across workspace |
| **Access** | Direct access from sidebar | Connected through agents |
| **Chat** | Dedicated chat within project | Referenced in agent chats |

### Use Cases

- **Work documents**: Gather project documents and ask AI questions
- **Team collaboration**: Share department documents with team members
- **Research**: Organize research materials and analyze with AI

---

## Project List

View your projects and shared projects in the **Projects** section at the bottom of the sidebar.

---

## Creating a Project

### Step 1: Create New Project

Click the **"+"** button in the Projects section of the sidebar.

### Step 2: Enter Basic Information

| Field | Description | Example |
|-------|-------------|---------|
| **Name** | Project display name | "2026 Marketing Strategy" |
| **Description** | Project purpose | "Q1 marketing campaign materials" |

### Step 3: Save

Click **"Create"** to create the project.

---

## File Management

### Uploading Files

Upload files from the project detail screen.

**Supported file formats:**
- PDF, DOCX, PPTX, XLSX, CSV
- TXT, MD (Markdown)
- Others (when LibreOffice PDF conversion is enabled)

**Upload methods:**
1. **Drag and drop**: Drag files into the project area
2. **File picker**: Click the upload button and select files
3. **Cloud storage**: Import directly from Google Drive, OneDrive, or SharePoint

### File List

Uploaded files appear in the **Files** tab of the project detail screen.

| Info | Description |
|------|-------------|
| **Filename** | Uploaded file name |
| **Size** | File size |
| **Status** | Processing status (uploading, completed, error) |
| **Upload date** | File upload date |

### Deleting Files

Click **Delete** from the file's context menu. Deleted files are also removed from the vector database.

---

## Sharing Projects

Share projects with specific users.

### How to Share

1. Go to the **Settings** tab in the project detail screen
2. Search for users in the **"Share"** section
3. Select users to share with
4. Save

### Sharing Behavior

- An **independent copy** is created for each shared user
- Files from the original project are copied for independent management
- Each user can freely modify their own copy after sharing

---

## Chatting in Projects

### Project Context Chat

When you start a chat with a project selected, the AI references only that project's documents.

**How to use:**
1. Click a project in the sidebar
2. Type your question in the chat input
3. AI searches project documents and responds

**Example:**
```
Q: What's our marketing budget plan for this quarter?
A: Based on the project documents, this quarter's marketing budget is...
   [Source: Q1_Marketing_Plan.pdf, page 12]
```

### Project Chat Management

Chats within a project appear in the **Chat** tab of the project detail screen. Project chats are not shown in the main sidebar chat list, keeping it organized.

---

## Project Settings

Modify project information in the **Settings** tab of the project detail screen.

| Item | Description |
|------|-------------|
| **Name** | Change project name |
| **Description** | Update project description |
| **Sharing** | Manage user sharing |

---

## Deleting a Project

Deleting a project removes all included files and chat history.

> **Warning:** Deleted projects cannot be recovered. Copies owned by shared users are not affected.

---

## New Features (Since March 2025)

### Data Analysis Projects (Code Interpreter)

A Jupyter notebook-based code execution environment is now available within projects. The AI writes and executes Python code to perform data analysis, visualization, file conversion, and more.

<!-- Screenshot: Data analysis project screen
     - Jupyter notebook execution results (charts, tables, etc.)
     - Interactive code execution with AI
     Filename: images/projects-code-interpreter.png
-->

**Key features:**
- Data analysis and visualization through Python code execution
- Directly analyze uploaded files (CSV, XLSX, etc.)
- View charts, graphs, and statistical results within the conversation
- Download analysis result files

**Usage example:**
```
Q: Analyze the sales_data.csv file and create a monthly trend chart
A: I've analyzed the sales data. Here's the monthly trend:
   [Chart: Monthly Sales Trend Graph]
   
   Key findings:
   - March saw a 23% increase in sales compared to the previous month
   - Second half average sales were 15% higher than the first half
```

### Automatic File Remounting

Project files are automatically remounted even when the Jupyter kernel restarts. You can continue working immediately after a kernel restart without needing to re-upload files.

<!-- Screenshot: Files persisted after kernel restart
     Filename: images/projects-auto-remount.png
-->

**How it works:**
- Project files are automatically restored to the working directory when the Jupyter kernel restarts
- File paths remain consistent across sessions
- No manual re-upload required

### Kernel Security Sandbox

Each project runs in an isolated workspace. The code execution environment for each project is completely separated from other projects, ensuring security and stability.

<!-- Screenshot: Per-project isolated execution environment diagram
     Filename: images/projects-sandbox.png
-->

**Security features:**
- Independent workspace per project with file system isolation
- No access to other projects' data
- Resource usage limits ensure system stability

### 3-Tier Tools + Enhanced File Metadata

Project tool capabilities have been expanded to three tiers, and file metadata has been enhanced.

<!-- Screenshot: Project tools and file metadata settings screen
     Filename: images/projects-tools-metadata.png
-->

**3-tier tools:**

| Tier | Description |
|------|-------------|
| **Tier 1: Basic Tools** | File search and document reference |
| **Tier 2: Analysis Tools** | Code Interpreter-based data analysis |
| **Tier 3: Extended Tools** | External API integration and advanced processing |

**Enhanced file metadata:**
- Detailed per-file metadata (file type, size, page count, processing status, etc.)
- Metadata-based file sorting and filtering
- Processing history tracking

---

## FAQ

**Q: Is there a file limit per project?**
> It depends on system settings. Generally there's no file count limit, but file size limits follow admin settings.

**Q: Does sharing sync in real-time?**
> No, sharing creates an independent copy. Changes to the original are not reflected in shared copies.

**Q: Can I convert an existing knowledge base to a project?**
> Direct conversion is not available. Create a new project and re-upload the files.

---

## Next Steps

- 📚 [Build a Knowledge Base](./knowledge.md)
- 🤖 [Create an Agent](./agents.md)
- 🛡️ [Set Up Guardrails](./guardrails.md)
