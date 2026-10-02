# CyberArena - Phase 2: Local LLM Gateway & Generic Autonomous Agent Runtime

## 1. LLM Architecture & Design Overview

CyberArena Phase 2 introduces the reasoning brain and autonomous execution layer connecting the Phase 1 virtual machine infrastructure to a local, free, open-source Large Language Model (Ollama).

The system operates strictly on the local host CPU without cloud dependencies, paid APIs, or arbitrary host command execution.

### Architectural Flow:

```
Browser (React + TypeScript)
       │
       ▼ (REST API)
FastAPI Backend
       │
   Agent Runtime / Service
   ├── LLMProvider Interface (OllamaProvider) ──► Local Ollama Engine (qwen3:4b on CPU)
   └── ToolRegistry ───────────────────────────► VMProvider (Paramiko SSH) ──► Isolated Lab VM (cyberarena-vm-01)
```

---

## 2. Ollama Provider Implementation

The `OllamaProvider` (`backend/llm/ollama.py`) implements the abstract `LLMProvider` interface (`backend/llm/base.py`):
- Communicates directly with the local Ollama REST API over loopback `http://127.0.0.1:11434`.
- **Health Probing**: Queries `/api/tags` to list installed models and assess daemon responsiveness.
- **Structured JSON Generation**: Sends `/api/generate` with `format="json"` and `stream=False`.
- **CPU Latency & Reasoning Optimization**:
  - `think: false`: Suppresses verbose reasoning tokens on reasoning models (e.g. Qwen3 thinking capability), dropping generation latency from >120s down to ~15s on host CPU.
  - `keep_alive: "30m"`: Prevents Ollama from evicting the model from RAM after 5 minutes of inactivity.
  - `repeat_penalty: 1.1`: Prevents token repetition loops under grammar-constrained JSON decoding.

---

## 3. Configuration-Driven Model Registry

Models are defined in `configs/models.json` without hardcoding specific model identifiers in business logic.

```json
{
  "default_model": "local-qwen3-4b",
  "llm_parallelism": 1,
  "default_iteration_limit": 10,
  "default_timeout": 120,
  "models": [
    {
      "model_id": "local-qwen3-4b",
      "provider": "ollama",
      "model_name": "qwen3:4b",
      "enabled": true,
      "description": "Local Qwen3 4B running on host CPU via Ollama"
    }
  ]
}
```

### Model Distinctions:
The `LLMService` distinguishes four model states:
1. **Configured**: Defined in `configs/models.json`.
2. **Installed**: Physically present in local Ollama daemon.
3. **Available**: Configured, enabled, and installed.
4. **Unavailable**: Configured but disabled or missing from the engine.

---

## 4. Generic Autonomous Agent Runtime

The agent implementation (`backend/agents/agent.py`) is completely generic and role-agnostic:
- **No hardcoded attacker logic (`AttackerAgent` does not exist).**
- **No hardcoded defender logic (`DefenderAgent` does not exist).**
- Agent objectives are user-defined strings (e.g. `"Report the hostname, current user, operating system, and available memory of the assigned VM."`).
- Enforces strict iteration limits (default: 10, user-configurable).
- Enforces command timeouts (default: 120s).
- Supports user-initiated graceful cancellation (`stop`).

### Autonomous ReAct Execution Loop:
1. **Observe**: Assemble conversation history and previous tool observation outputs.
2. **Think / Plan**: Query local LLM via `LLMProvider.generate(..., json_format=True)`.
3. **Validate**: Parse structured JSON output containing `thought`, `tool`, `parameters`, and `summary`.
   - If malformed JSON is returned, the error is caught, formatted as feedback, and fed back to the model as an observation, counting toward the iteration limit.
   - If an invalid tool name is provided, execution is blocked and feedback is returned.
   - If invalid parameters are passed, execution is blocked and feedback is returned.
   - The assigned `vm_id` is immutable; the agent always passes its constructor `self.vm_id` directly to the tool registry.
4. **Execute**: Dispatch tool execution strictly to the assigned VM via `ToolRegistry` and `VMProvider`.
5. **Decide / Repeat**: If tool is `finish`, conclude with `COMPLETED` status. Otherwise, observe output and repeat until `iteration_limit` or stop signal.

---

## 5. Tool Registry & Builtin Tools (`backend/tools/`)

All tools target the assigned VM exclusively through the `VMProvider` interface:

| Tool Name | Description | Security / Isolation Mechanism |
|---|---|---|
| `execute_command` | Execute shell command inside VM | Dispatched via Paramiko SSH into guest. Refuses host execution. |
| `read_file` | Read guest file contents | Executes `head -n {lines} {path}` inside guest. |
| `write_file` | Write text content to guest file | Transferred safely via base64 decoding inside guest. |
| `list_directory` | Directory listing inside VM | `ls -la {path}` inside guest. |
| `process_info` | Inspect guest running processes | `ps aux` inside guest with optional grep filtering. |
| `service_status` | Check systemd service status | `systemctl status {service} --no-pager` inside guest. |
| `network_info` | Inspect guest IP/routes/ports | `ip -4 addr`, `ss -tuln`, and `ip route` inside guest. |

---

## 6. State & Memory Model

The agent maintains structured state at all times:
- `agent_id`: Unique identifier
- `role`: Objective / role instruction
- `model_id`: Configured model identifier
- `vm_id`: Immutable assigned VM
- `allowed_tools`: Whitelist of permitted tools
- `status`: Lifecycle state (`idle`, `running`, `paused`, `completed`, `failed`, `stopped`)
- `current_iteration`: Iteration count
- `iteration_limit`: Maximum allowed cycles
- `command_timeout`: Execution timeout
- `history`: Sequence of `AgentStep` records (step number, action tool/params/summary, observation, success, duration, timestamp)
- `created_at` / `updated_at`: ISO 8601 UTC timestamps
- `error_message`: Optional error details

### Privacy & Chain-of-Thought Protection:
- Internal LLM reasoning is sanitized: only user-facing action summaries, parameters, and sanitized observations are displayed in the frontend UI.
- No host credentials, `.env` secrets, or raw internal reasoning tokens are exposed to the browser.

---

## 7. Resource Control & Concurrency

- **Parallelism Semaphore**: `llm_parallelism: 1` enforced in `AgentService` using a threading semaphore. Only one agent may execute CPU inference at any given time, preventing host RAM thrashing.
- **Model Sharing**: A single, shared Ollama daemon instance is used for all agents; separate model processes are never created per agent.
- **Iteration Cap**: `default_iteration_limit: 10` prevents runaway agent loops.
- **Timeout Protection**: `default_timeout: 120` prevents stuck inference requests.

---

## 8. REST API Reference

### LLM Gateway:
- `GET /llm/health` (and `/api/llm/health`): Engine reachability and installed models.
- `GET /llm/models` (and `/api/llm/models`): Status of configured vs installed models.
- `POST /llm/test` (and `/api/llm/test`): Direct prompt test against local model.
- `POST /llm/test/stream`: Real-time token streaming test via Server-Sent Events (SSE).

### Autonomous Agents:
- `GET /agents/tools` (and `/api/agents/tools`): Available tool schemas.
- `POST /agents` (and `/api/agents`): Create agent (validates VM existence in registry).
- `GET /agents` (and `/api/agents`): List all agents.
- `GET /agents/{id}`: Detailed agent state.
- `POST /agents/{id}/start`: Launch autonomous execution in background.
- `POST /agents/{id}/stop`: Signal running agent to cleanly halt.
- `DELETE /agents/{id}`: Delete logical agent runtime, cancel tasks, and purge telemetry without touching VM.
- `GET /agents/{id}/status`: Quick status and iteration metrics.
- `GET /agents/{id}/history`: Step-by-step action and observation history.
- `GET /agents/{id}/events`: Server-Sent Events (SSE) stream for real-time telemetry, live token generation, and tool activity.


---

## 9. Security & Isolation Verification

1. **Host Execution Prevention**: No endpoint or tool executes shell commands on the host Windows system.
2. **Subprocess Isolation**: VirtualBox management commands are executed as discrete argument lists (`shell=False`).
3. **Paramiko Guest Channel**: Command execution passes strictly through `VMSSHClient` to `192.168.32.101`.
4. **Credential Protection**: Passwords remain exclusively in `.env` (`CYBERARENA_VM01_PASSWORD`) and are never returned in API payloads or UI views.
5. **Target Immutability**: LLM cannot redirect tool execution to other VMs or the host.

---

## 10. Verification and Test Results

### Automated Test Suite:
```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
**Result: 66 passed in 105s (100% pass rate)**
- Phase 1 tests (33 tests): VM Provider, SSH Client, Isolation Boundaries, VM Registry.
- Phase 2 unit tests (31 tests): LLM Provider, Builtin Tools, Agent Runtime, API Routes, Security & Immutability.
- Phase 2 real integration tests (2 tests): Real Ollama provider and live VM-01 execution.

### Frontend Production Build:
```powershell
npm run build
```
**Result: Built in 7.63s with 0 errors.**

---

## 11. Troubleshooting Guide

1. **Ollama Connection Refused**:
   - Verify Ollama daemon is running: `Get-Process -Name "ollama*"`
   - Test connectivity: `curl http://127.0.0.1:11434/api/tags`
2. **Token Repeat Limit Reached**:
   - Ensure `repeat_penalty: 1.1` and `temperature: 0.4` are set in Ollama payload.
3. **Inference Timing Out on CPU**:
   - Ensure `think: false` is configured in `OllamaProvider` to disable multi-minute reasoning monologues on CPU hosts.
4. **SSH Authentication Failure**:
   - Verify `.env` contains valid `CYBERARENA_VM01_PASSWORD`.
   - Ensure VM is in `RUNNING` state before execution.
