# CyberArena Architecture Specification

## Overview

**CyberArena** is an autonomous AI agent experimentation platform designed for isolated cybersecurity research laboratories. The system coordinates autonomous agents operating in controlled virtual machine environments to evaluate model reasoning, planning, and task execution under reproducible conditions.

```
Browser (React + TypeScript + Vite)
    │  (REST API / WebSockets)
    ▼
CyberArena Backend (FastAPI)
    │  (Registry & Lifecycle Management)
    ▼
VM Service & Registry (Config-Driven, Dynamic max_vm)
    │
    ▼
VMProvider Interface (Abstract Interface)
    │
    ├─► VirtualBoxProvider (Concrete Implementation)
    │     ├── VBoxManage (Strict parameterized hypervisor control)
    │     └── Paramiko SSH (Isolated guest command execution channel)
    │
    ▼
Assigned Ubuntu Virtual Machines (Isolated Lab Network)
```

---

## Architectural Principles

### 1. Interface Decoupling (Open/Closed Principle)
Higher-level orchestrators and services interact solely with abstract interfaces:
- **`VMProvider`**: Contract for hypervisor operations (`list_vms`, `get_vm`, `get_state`, `start_vm`, `stop_vm`, `execute`, `snapshot`, `restore_snapshot`, `health_check`).
- **`VirtualBoxProvider`**: Concrete implementation for Oracle VirtualBox. Future providers (QEMU, Libvirt, Cloud Hypervisors) can be dropped in without changing application code.

### 2. Strict Host/Guest Execution Isolation
- **Agent/User actions execute exclusively inside guest VMs via Paramiko SSH**.
- The Windows host operating system is **NEVER** an execution target.
- No endpoints exist for host shell execution (no `/execute-host-command` or host subprocess passthrough).
- Subprocess execution on the host is limited strictly to internal, parameterized hypervisor binaries (`VBoxManage.exe`) without shell invocation (`shell=False`).

### 3. Dynamic Configuration-Driven Resource Limits
- No hardcoded resource caps or VM names.
- The `max_vm` variable governs the active laboratory capacity dynamically.
- VM targets are resolved through `configs/vms.json` rather than caller-supplied hostnames.

---

## Component Layout

```
CyberArena/
├── backend/
│   ├── api/             # FastAPI route controllers and dependencies
│   ├── services/        # VMService business logic and validation
│   ├── virtualization/  # VMProvider interface, VirtualBoxProvider, SSH client
│   ├── schemas/         # Pydantic models for VMs, results, requests
│   ├── configs/         # Pydantic Settings, JSON registry loader, secrets
│   ├── utils/           # Structured logging
│   └── tests/           # Unit and integration test suite
│
├── frontend/
│   ├── src/
│   │   ├── api/         # Frontend typed HTTP client
│   │   ├── components/  # VMCard, CommandTerminal, SnapshotModal, Navbar, StatusBadge
│   │   ├── types/       # TypeScript interfaces
│   │   └── App.tsx      # Dashboard orchestrator
│   └── ...
│
├── configs/             # Registry (vms.json) and environment templates (.env.example)
├── scripts/             # Preflight verification and server startup scripts
└── docs/                # Architecture, setup, and networking guides
```
