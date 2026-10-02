# CyberArena Phase 3: Multi-Agent Concurrency & Experiment Orchestration

## 1. Overview & Architecture

Phase 3 introduces dynamic multi-agent experiment orchestration, asynchronous concurrent execution, dedicated VM Terminal Panels, WebSocket/SSE telemetry streaming, and SQLite persistence.

```
                    ┌───────────────────────────────────────────────┐
                    │            Browser React Dashboard            │
                    │ (Builder, Live Agents, Timelines, VM Console) │
                    └───────────────────────┬───────────────────────┘
                                            │ REST & WebSockets (WS /ws/experiments/{id})
                                            ▼
                    ┌───────────────────────────────────────────────┐
                    │              FastAPI Backend                  │
                    │   (/experiments, /ws, /vms, /llm, /agents)    │
                    └───────────────────────┬───────────────────────┘
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
       ┌───────────────────────────┐                 ┌───────────────────────────┐
       │   SQLite Persistence DB   │                 │     ExperimentService     │
       │ (experiments, agents, ev) │                 │  Concurrent Orchestration │
       └───────────────────────────┘                 └─────────────┬─────────────┘
                                                                   │
                                     ┌─────────────────────────────┴─────────────────────────────┐
                                     │                                                           │
                                     ▼                                                           ▼
                      ┌─────────────────────────────┐                             ┌─────────────────────────────┐
                      │      Agent 1 Runtime        │                             │      Agent 2 Runtime        │
                      │  (ReAct Observation Loop)   │                             │  (ReAct Observation Loop)   │
                      └──────────────┬──────────────┘                             └──────────────┬──────────────┘
                                     │                                                           │
                      ┌──────────────┴──────────────┐                             ┌──────────────┴──────────────┐
                      ▼                             ▼                             ▼                             ▼
       ┌─────────────────────────────┐┌───────────────────────────┐┌─────────────────────────────┐┌───────────────────────────┐
       │     Ollama LLM Gateway      ││        ToolRegistry       ││     Ollama LLM Gateway      ││        ToolRegistry       │
       │   (Local CPU Inference)     ││  (execute_command, etc.)  ││   (Local CPU Inference)     ││  (execute_command, etc.)  │
       └─────────────────────────────┘└─────────────┬─────────────┘└─────────────────────────────┘└─────────────┬─────────────┘
                                                    │                                                           │
                                                    │ Paramiko SSH                                              │ Paramiko SSH
                                                    ▼                                                           ▼
                                      ┌───────────────────────────┐                               ┌───────────────────────────┐
                                      │    cyberarena-vm-01       │                               │    cyberarena-vm-02       │
                                      │   (192.168.32.101:22)     │                               │   (192.168.32.102:22)     │
                                      └───────────────────────────┘                               └───────────────────────────┘
```

---

## 2. Dynamic Experiment Builder (1 → max_vm)

- **Configuration-Driven**: Agent count is bounded dynamically by `max_vm` (read from `configs/vms.json` or `GET /config`).
- **Unique VM Assignments**: Enforces that each agent is bound to a distinct laboratory virtual machine.
- **Model Decoupling**: Each agent dynamically resolves its model from the configuration-driven model registry (`configs/models.json`).
- **Flexible Roles**: User-defined objectives without hardcoded attack or defense sequences.

---

## 3. Asynchronous Concurrency & Failure Isolation

- **Async Task Orchestration**: Uses `asyncio.create_task` and `asyncio.gather(*tasks, return_exceptions=True)` to execute all agents concurrently in non-blocking thread workers.
- **Inference Semaphore**: `threading.Semaphore(llm_parallelism)` coordinates host CPU inference requests while guest VM operations (commands, port scans, process audits) execute in true physical parallelism.
- **Failure Isolation**: An unhandled exception or network fault on VM 1 does not abort execution on VM 2. Each agent operates with independent memory, history, and status tracking.

---

## 4. SQLite Persistence Layer

Database location: `data/cyberarena.db` (with WAL mode and foreign keys enabled).

- **`experiments` Table**: Stores experiment UUID, display name, description, status (`created`, `running`, `completed`, `failed`, `stopped`), raw JSON config, timestamps, and completion duration.
- **`experiment_agents` Table**: Tracks agent ID, assigned VM, model, status, current iteration, limit, error messages, and serialized history.
- **`experiment_events` Table**: Appends all real-time events (`experiment_started`, `agent_started`, `llm_chunk`, `tool_started`, `tool_completed`, `observation_received`, `agent_completed`).

---

## 5. Dedicated VM Terminal Panels

- Real-time guest execution inspection per assigned VM.
- Each terminal panel tracks:
  - Timestamp
  - Executing agent ID
  - Command issued over SSH
  - Stdout and Stderr outputs
  - Execution duration and exit codes

---

## 6. Real-Time Telemetry: WebSockets & SSE

- **WebSocket**: `/ws/experiments/{experiment_id}` provides bidirectional communication, automatic replay of past events upon connection, and real-time event pushing.
- **SSE Stream**: `GET /experiments/{experiment_id}/events` provides Server-Sent Events with keep-alive ping support.
- **Streaming Thoughts**: Displays raw reasoning tokens during generation and renders clean structured summaries upon completion.

---

## 7. API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/experiments` | Create new multi-agent experiment (validates 1 to `max_vm`, unique VMs) |
| `GET` | `/experiments` | List all experiments with status, agent count, duration |
| `GET` | `/experiments/{id}` | Get experiment details, agent states, and step histories |
| `POST` | `/experiments/{id}/start` | Launch concurrent autonomous execution of all agents |
| `POST` | `/experiments/{id}/stop` | Cleanly halt running agents in the experiment |
| `DELETE` | `/experiments/{id}` | Purge experiment records and cascaded history |
| `GET` | `/experiments/{id}/events` | SSE telemetry stream |
| `GET` | `/experiments/{id}/events/history` | Query recorded events from SQLite |
| `WS` | `/ws/experiments/{id}` | WebSocket bidirectional streaming endpoint |
