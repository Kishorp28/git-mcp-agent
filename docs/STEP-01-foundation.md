# Step 1: MCP Foundations & Project Scaffold

This document is your mentor guide for **Step 1** of building the GitHub AI Engineer.

---

## 1. What is MCP?

**Model Context Protocol (MCP)** is an open standard that lets AI applications connect to external data sources and tools through a unified interface — like USB-C for AI integrations.

Without MCP, every AI app builds custom integrations for GitHub, databases, filesystems, etc. With MCP, you write (or reuse) **servers** that expose capabilities, and any **host** can connect to them.

### The three roles

| Role | What it is | In our project |
|------|-----------|----------------|
| **MCP Host** | The AI application that coordinates everything | Our Python backend + Next.js UI |
| **MCP Client** | Maintains a 1:1 connection to one MCP server | FastMCP `Client` (one client, multiple servers) |
| **MCP Server** | Exposes tools, resources, and prompts | GitHub, Filesystem, Git servers |

### Architecture (Step 1)

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP HOST                                  │
│  ┌──────────────────┐         ┌──────────────────────────────┐  │
│  │  Next.js Frontend │  HTTP   │  Python Backend (FastAPI)   │  │
│  │  - Chat UI        │◄───────►│  - agent.py (LLM loop)      │  │
│  │  - Tool logs      │  SSE    │  - mcp_client.py (MCP mgr)  │  │
│  │  - Status bar     │         │  - services/llm.py          │  │
│  └──────────────────┘         └──────────────┬───────────────┘  │
│                                               │                  │
│                                    ┌──────────▼──────────┐       │
│                                    │  FastMCP Client     │       │
│                                    │  (multi-server)     │       │
│                                    └──┬────────┬────────┬─┘       │
└───────────────────────────────────────┼────────┼────────┼─────────┘
                                        │ stdio  │ stdio  │ stdio
                          ┌─────────────▼──┐ ┌───▼────┐ ┌─▼────────┐
                          │ GitHub MCP     │ │ Files  │ │ Git MCP  │
                          │ Server         │ │ System │ │ Server   │
                          │ (Docker)       │ │ (npx)  │ │ (uvx)    │
                          └────────────────┘ └────────┘ └──────────┘
```

---

## 2. MCP Primitives (concepts you'll use throughout)

### Tools
**Functions the LLM can call.** Example: `search_code`, `create_issue`, `read_file`.

- Registered by the server with a **name**, **description**, and **JSON Schema** for parameters
- The host discovers tools via `list_tools()` and invokes them via `call_tool(name, args)`

### Resources
**Read-only data identified by URI.** Example: `file:///repo/README.md`.

- Discovered via `list_resources()`, read via `read_resource(uri)`
- Good for static context; we'll use tools heavily in early steps

### Prompts
**Reusable prompt templates** with parameters. Example: `review_pr` with `{pr_number}`.

- Retrieved via `get_prompt(name, args)`
- We'll add custom prompts in a later step

### JSON Schemas
Every tool parameter set is a JSON Schema. The LLM uses this to know *what* arguments to pass. FastMCP auto-generates schemas from Python type hints when you build servers; when consuming external servers, we read their published schemas.

### Tool discovery & invocation flow

```
1. Client connects → initialize handshake (capabilities exchange)
2. Client calls list_tools() → receives tool catalog
3. LLM sees tools → decides to call "github_search_code"
4. Client calls call_tool("github_search_code", {query: "JWT"})
5. Server executes → returns structured result
6. LLM reads result → continues reasoning or responds to user
```

---

## 3. Why this architecture?

| Decision | Reason |
|----------|--------|
| Python backend | FastMCP is Python-native; async fits MCP I/O |
| FastAPI + SSE | Industry-standard streaming to the React frontend |
| FastMCP Client | Handles stdio subprocesses, multi-server config, schema parsing |
| Separate MCP servers | Security isolation; reuse official GitHub/filesystem/git servers |
| Next.js frontend | Rich chat UI, markdown, syntax highlighting |

---

## 4. Files created in Step 1

### Backend

| File | Purpose |
|------|---------|
| `app.py` | FastAPI entry — `/health`, `/tools`, `/chat/stream` |
| `agent.py` | LLM ↔ MCP tool loop (ReAct pattern) |
| `mcp_client.py` | Multi-server MCP connection manager |
| `config/settings.py` | Environment-based configuration |
| `services/llm.py` | OpenAI + Anthropic tool-calling adapter |
| `prompts/system.py` | System prompt for the coding assistant |

### Frontend

| File | Purpose |
|------|---------|
| `components/ChatInterface.tsx` | Main layout |
| `hooks/useChat.ts` | SSE streaming state management |
| `components/ToolLogPanel.tsx` | Live MCP tool execution log |
| `components/MarkdownRenderer.tsx` | Markdown + syntax highlighting |

---

## 5. How to run Step 1

### Prerequisites

- Python 3.12+
- Node.js 20+
- Docker (for GitHub MCP server)
- [uv](https://docs.astral.sh/uv/) (for Git MCP via `uvx`)
- OpenAI or Anthropic API key
- GitHub Personal Access Token

### Setup

```bash
# 1. Clone / enter project
cd ai-git-agent

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys and GitHub token

# 3. Backend
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn app:app --reload --port 8000

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 — you should see the chat UI and MCP status bar.

### Verify

```bash
curl http://localhost:8000/health
curl http://localhost:8000/tools
```

---

## 6. Test checklist

- [ ] `/health` returns `mcp_connected: true` and lists servers
- [ ] `/tools` returns discovered MCP tools (may take 10–30s on first connect)
- [ ] Frontend status bar shows green MCP + LLM badges
- [ ] Sending "List available tools" triggers tool discovery in the agent
- [ ] Tool log panel shows MCP invocations

---

## 7. What's next (Step 2 preview)

In **Step 2** we will:

1. Deep-dive into **GitHub MCP tools** (search, read files, issues, PRs)
2. Build the **Repository Explorer** UI component
3. Add **resource reading** for file trees
4. Implement targeted prompts for security review

---

## 8. Troubleshooting

| Issue | Fix |
|-------|-----|
| `Backend offline` in UI | Start uvicorn; check `NEXT_PUBLIC_API_URL` |
| 0 MCP tools | Ensure Docker is running; check GitHub token |
| Filesystem server fails | Verify `FILESYSTEM_ALLOWED_PATH` is absolute |
| Git server fails | Install uv: `pip install uv` or use official installer |
| LLM not configured | Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` |
