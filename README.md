# CYBERARENA: Autonomous AI Agent Cybersecurity Platform

**CyberArena** is an autonomous AI agent experimentation platform designed for isolated cybersecurity research and security evaluation. It provides an interactive web dashboard for orchestrating, observing, and evaluating autonomous AI agents operating inside dedicated, isolated Linux virtual machines powered entirely by local Large Language Models (via Ollama).

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      Browser (React + TypeScript + Vite)                        │
│   • Phase 1: VM Infrastructure & Live Terminal Controls                         │
│   • Phase 2: Local Inference Diagnostics & Model Selector                       │
│   • Phase 3: Real-Time Multi-Agent Experimentation & Observability              │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │ HTTP REST / SSE / WebSockets
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           CyberArena Backend (FastAPI)                          │
│   • Agent Service: Autonomous ReAct loop (Thought → Tool Call → Observation)   │
│   • Experiment Orchestrator: Multi-agent concurrent execution & scheduling      │
│   • Tool Registry & Security Policy: Guardrails against destructive operations  │
│   • VM Service: Lifecycle management, snapshot management, and SSH isolation    │
└──────────────────┬──────────────────────────────────────────────┬───────────────┘
                   │                                              │
                   ▼                                              ▼
┌──────────────────────────────────────┐     ┌────────────────────────────────────┐
│      Local LLM Inference Engine      │     │      Virtualization & Guest VM     │
│             (Ollama)                 │     │          (Oracle VirtualBox)       │
│  • qwen2.5:1.5b                      │     │  • Host-Only Network: 192.168.32.x │
│  • llama3.2:1b                       │     │  • VM-01: cyberarena-vm-01         │
│  • llama3.2:3b                       │     │           (192.168.32.101)         │
│  • qwen3:4b                          │     │  • VM-02: cyberarena-vm-02         │
│  • Low-latency local streaming       │     │           (192.168.32.102)         │
│  • Zero cloud data leakage           │     │  • Isolated Paramiko SSH execution │
└──────────────────────────────────────┘     └────────────────────────────────────┘
```

---

## Key Capabilities

- **Strict Hypervisor & Network Isolation**: Target virtual machines operate on an isolated Host-Only subnet (`192.168.32.0/24`). All guest operations execute via Paramiko SSH into Ubuntu Linux. The host OS is strictly protected—no host commands can ever be executed by agents.
- **Local Inference Engine**: Powered by locally installed Ollama models (`qwen2.5:1.5b`, `llama3.2:1b`, `llama3.2:3b`, `qwen3:4b`). No API keys or external cloud dependencies required.
- **Autonomous Multi-Agent ReAct Execution**: Agents independently plan steps, execute guest commands, observe actual outputs, adapt strategies based on errors, and synthesize evidence-backed final conclusions.
- **Privileged Guest Tools with Auto-Elevation**: Built-in tools for administrative tasks (`execute_command`, `install_package`, `restart_service`, `modify_system_config`, `create_user`, `read_file`, `write_file`, `list_directory`). Commands encountering permission denials automatically elevate via `sudo` where permitted.
- **Destructive Operation Guardrails**: Strict policy guards intercept and reject potentially destructive commands (such as `rm -rf /`, `mkfs.*`, raw disk block overwrites, fork bombs, and system shutdowns).
- **Anti-Repetition Intelligence**: System prompts and execution loops actively prevent models from repeating failed tool calls or invalid arguments.
- **Real-Time Observability**: Live terminal outputs, model thoughts, tool invocations, and execution timelines stream directly to the browser in real time.
- **Snapshot Rollback**: Instant snapshot creation and state restoration to guarantee a clean baseline between experiment runs.

---

## Directory Structure

```
CyberArena/
├── backend/
│   ├── agents/          # Autonomous agent runtime, ReAct loop, prompts
│   ├── api/             # FastAPI route controllers (VMs, Agents, Experiments, LLM)
│   ├── configs/         # Settings loader and secret resolvers
│   ├── db/              # Database models, migrations, and repository
│   ├── experiments/     # Multi-agent experiment orchestration and event pub/sub
│   ├── llm/             # Ollama provider, model registry, streaming client
│   ├── schemas/         # Pydantic validation schemas
│   ├── services/        # Business logic services (VMService, AgentService, LLMService)
│   ├── tests/           # Full pytest test suite (120 unit and integration tests)
│   ├── tools/           # Tool registry, privileged tools, policy enforcement
│   └── virtualization/  # VMProvider, VirtualBoxProvider, Paramiko SSH client
│
├── frontend/
│   ├── src/
│   │   ├── api/         # Typed API clients (VMs, Agents, Experiments, LLM)
│   │   ├── components/  # Real-time terminals, agent cards, modals, timeline
│   │   ├── types/       # TypeScript interfaces and state models
│   │   └── App.tsx      # Main application dashboard
│   ├── package.json
│   ├── vite.config.ts
│   └── index.html
│
├── configs/
│   ├── vms.json         # VM Registry configuration (VM IDs, IPs, credentials)
│   ├── tool_policy.json # Tool permission policies and whitelists
│   └── .env.example     # Template for environment configuration
│
├── scripts/
│   ├── preflight.ps1    # Automated preflight verification script
│   ├── start-backend.ps1# Script to launch FastAPI backend
│   └── start-frontend.ps1# Script to launch Vite dev server
│
├── .gitignore           # Ignores large ISOs, DBs, caches, node_modules, .env
├── requirements.txt     # Python backend dependencies
└── README.md
```

---

## Step-by-Step Setup Guide (From Scratch)

Follow these steps to set up and run CyberArena from scratch on a Windows host machine.

### Step 1: System Prerequisites

Ensure you have the following installed on your system:
- **Operating System**: Windows 11 x64 (or Windows 10 x64)
- **Python**: **Python 3.13.x**
- **Node.js**: **v18+** or **v20+** with `npm`
- **Hypervisor**: **Oracle VirtualBox 7.x** (with `VBoxManage` accessible in PATH or standard install directory)
- **Local LLM Runner**: **Ollama for Windows** (Download from [ollama.com](https://ollama.com))

---

### Step 2: Install & Pull Local Ollama Models

1. Ensure the Ollama background service is running on your host machine:
   ```powershell
   ollama --version
   ```
2. Pull the required models used by CyberArena agents:
   ```powershell
   ollama pull qwen2.5:1.5b
   ollama pull llama3.2:1b
   ollama pull llama3.2:3b
   ollama pull qwen3:4b
   ```
3. Verify that the models are installed:
   ```powershell
   ollama list
   ```
4. Verify the Ollama HTTP API is reachable at `http://127.0.0.1:11434`:
   ```powershell
   curl http://127.0.0.1:11434/api/tags
   ```

---

### Step 3: Configure VirtualBox & Isolated Ubuntu VMs

CyberArena operates with two isolated Ubuntu Server virtual machines connected to a Host-Only network.

#### 1. Host-Only Network Setup
In VirtualBox:
- Open **VirtualBox** → **Tools** → **Network Manager**.
- Create a Host-Only Network adapter (e.g. `VirtualBox Host-Only Ethernet Adapter #2` or default).
- Configure the Host-Only IPv4 subnet:
  - **IPv4 Address**: `192.168.32.1`
  - **IPv4 Network Mask**: `255.255.255.0`
  - **DHCP Server**: Disabled (or set static IPs on VMs)

#### 2. Configure Guest Virtual Machines
Set up two Ubuntu Server VMs (e.g., Ubuntu 24.04 Server):

| Property | VM 1 (`vm-01`) | VM 2 (`vm-02`) |
| :--- | :--- | :--- |
| **VirtualBox Name** | `cyberarena-vm-01` | `cyberarena-vm-02` |
| **CyberArena ID** | `vm-01` | `vm-02` |
| **Adapter 1** | Host-Only (`192.168.32.x`) | Host-Only (`192.168.32.x`) |
| **Static IP** | `192.168.32.101` | `192.168.32.102` |
| **SSH Port** | `22` | `22` |
| **SSH User** | `labuser` | `labuser` |
| **SSH Password** | `cyberarena_lab_pass` | `cyberarena_lab_pass` |

#### 3. Enable Passwordless Sudo inside both Guest VMs
Log into each VM (via console or SSH) and grant passwordless sudo to `labuser`:
```bash
sudo bash -c 'echo "labuser ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/cyberarena'
sudo chmod 0440 /etc/sudoers.d/cyberarena
```

#### 4. Baseline Snapshot (Recommended)
Take a clean baseline snapshot for each VM in VirtualBox so you can restore them anytime:
```powershell
VBoxManage snapshot cyberarena-vm-01 take baseline-clean
VBoxManage snapshot cyberarena-vm-02 take baseline-clean
```

---

### Step 4: Environment & Project Configuration

1. In the project root directory, create a `.env` file by copying `configs/.env.example`:
   ```powershell
   Copy-Item configs/.env.example .env
   ```
2. Verify the configuration values in `.env`:
   ```env
   CYBERARENA_HOST=127.0.0.1
   CYBERARENA_PORT=8000
   CYBERARENA_ENV=development
   CYBERARENA_CONFIG_PATH=configs/vms.json
   CYBERARENA_VM01_PASSWORD=cyberarena_lab_pass
   CYBERARENA_VM02_PASSWORD=cyberarena_lab_pass
   CYBERARENA_DEFAULT_SSH_TIMEOUT=30
   ```
3. Inspect `configs/vms.json` to ensure the host IP addresses match your Host-Only network adapter settings:
   ```json
   {
     "max_vm": 2,
     "default_provider": "virtualbox",
     "vms": [
       {
         "vm_id": "vm-01",
         "vm_provider": "virtualbox",
         "virtualbox_vm_name": "cyberarena-vm-01",
         "ssh_host": "192.168.32.101",
         "ssh_port": 22,
         "ssh_username": "labuser",
         "ssh_auth_method": "password",
         "ssh_password_env": "CYBERARENA_VM01_PASSWORD"
       },
       {
         "vm_id": "vm-02",
         "vm_provider": "virtualbox",
         "virtualbox_vm_name": "cyberarena-vm-02",
         "ssh_host": "192.168.32.102",
         "ssh_port": 22,
         "ssh_username": "labuser",
         "ssh_auth_method": "password",
         "ssh_password_env": "CYBERARENA_VM02_PASSWORD"
       }
     ]
   }
   ```

---

### Step 5: Backend Setup & Verification

1. Create and activate a Python 3.13 virtual environment:
   ```powershell
   py -3.13 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
2. Upgrade `pip` and install backend dependencies:
   ```powershell
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
3. Run the automated test suite to verify your setup:
   ```powershell
   .\.venv\Scripts\python.exe -m pytest backend/tests/ -v
   ```
   *(All unit, policy, virtualization, and integration tests should pass.)*

4. Start the FastAPI backend server:
   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
   ```
   - API Root: `http://127.0.0.1:8000`
   - Interactive Swagger Docs: `http://127.0.0.1:8000/docs`

---

### Step 6: Frontend Setup & Dashboard Launch

1. Open a new terminal window and navigate to the `frontend/` directory:
   ```powershell
   cd frontend
   ```
2. Install frontend dependencies:
   ```powershell
   npm install
   ```
3. Start the Vite development server:
   ```powershell
   npm run dev
   ```
4. Access the CyberArena Dashboard in your browser:
   ```
   http://localhost:5173
   ```

---

## Using the Platform

### Phase 1: Virtual Machine Management
- View the real-time operational status (RUNNING, STOPPED, ERROR) of all registered laboratory VMs.
- Power on, shut down, or restart VMs directly from the dashboard.
- Create named snapshots or restore to existing snapshots.
- Execute direct commands in guest VMs and view live terminal output.

### Phase 2: Local Inference Diagnostics
- Inspect the local Ollama health status and view all detected local models.
- Run interactive streaming tests using any of the installed models (`qwen2.5:1.5b`, `llama3.2:1b`, `llama3.2:3b`, `qwen3:4b`).
- Evaluate response latencies, tokens-per-second, and model suitability for agent tasks.

### Phase 3: Autonomous Multi-Agent Experiments
- **Create Experiment**: Define target roles, objectives, and iteration limits for agents.
- **Model Assignment**: Assign distinct local LLM models to each agent (e.g. `llama3.2:3b` for Agent 1 on `vm-01`, `qwen2.5:1.5b` for Agent 2 on `vm-02`).
- **Live ReAct Execution**:
  - Watch agents formulate thoughts, invoke guest tools, and inspect command execution observations in real time.
  - Live VM terminal tabs show exactly what commands are executed inside each VM.
- **Evidence-Based Conclusions**:
  - When iterations finish or objectives are reached, each agent generates a comprehensive findings conclusion based strictly on observed command outputs.

---

## Security Model & Host Isolation Guarantees

1. **Strict Host Isolation**: No mechanism exists in the platform to pass commands to the host Windows command prompt or PowerShell. All execution targets are strictly guest VMs.
2. **Network Segmentation**: Guest VMs communicate solely over the private Host-Only subnet.
3. **Destructive Command Blocking**: Built-in security policy intercepts and prohibits filesystem wipes (`rm -rf /`), disk formatting (`mkfs`), block device overwrites (`dd of=/dev/sd*`), fork bombs, and system halts.
4. **Credential Isolation**: VM credentials resolve through host-side environment variables and are never transmitted to LLM prompts or exposed in frontend responses.

---

## License

This project is developed for cybersecurity research, AI safety testing, and automated security experimentation.
