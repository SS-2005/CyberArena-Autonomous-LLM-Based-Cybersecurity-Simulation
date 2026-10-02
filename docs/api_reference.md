# CyberArena Phase 1 API Reference

All endpoints are accessible with or without the `/api` prefix (e.g. `/vms` or `/api/vms`).

---

## 1. System Configuration

### `GET /config`
Retrieve system-wide capacity configuration, dynamic `max_vm`, and active VMs.

**Response `200 OK`**:
```json
{
  "max_vm": 2,
  "configured_vm_count": 2,
  "default_provider": "virtualbox",
  "vms": [
    {
      "vm_id": "vm-01",
      "vm_provider": "virtualbox",
      "virtualbox_vm_name": "cyberarena-vm-01",
      "state": "running",
      "ssh_host": "192.168.56.101",
      "ssh_port": 22,
      "ssh_username": "labuser",
      "ssh_auth_method": "password",
      "description": "Primary isolated laboratory node",
      "last_checked": "2026-09-29T16:30:00Z"
    }
  ]
}
```

---

## 2. Virtual Machine Management

### `GET /vms`
List all registered virtual machines and their current state.

**Response `200 OK`**: Array of `VMInfo` objects.

---

### `GET /vms/{vm_id}`
Retrieve live details for a specific virtual machine.

**Response `200 OK`**: `VMInfo` object.
**Response `404 Not Found`**: If `vm_id` is not registered.

---

### `POST /vms/{vm_id}/start`
Start the specified virtual machine in headless mode via hypervisor.

**Response `200 OK`**:
```json
{
  "vm_id": "vm-01",
  "operation": "start",
  "success": true,
  "message": "VM 'vm-01' started successfully.",
  "timestamp": "2026-09-29T16:30:00Z",
  "details": { "exit_code": 0 }
}
```

---

### `POST /vms/{vm_id}/stop?force=false`
Stop the specified virtual machine.
- `force=false`: ACPI graceful power button signal.
- `force=true`: Immediate power off.

**Response `200 OK`**:
```json
{
  "vm_id": "vm-01",
  "operation": "stop",
  "success": true,
  "message": "Stop request (acpipowerbutton) completed.",
  "timestamp": "2026-09-29T16:30:00Z"
}
```

---

### `POST /vms/{vm_id}/snapshot`
Create a state snapshot for rollback.

**Request Body**:
```json
{
  "snapshot_name": "clean_baseline",
  "description": "Pre-test state"
}
```

**Response `200 OK`**:
```json
{
  "vm_id": "vm-01",
  "operation": "snapshot",
  "success": true,
  "message": "Snapshot 'clean_baseline' created successfully.",
  "timestamp": "2026-09-29T16:30:00Z"
}
```

---

### `POST /vms/{vm_id}/restore`
Restore VM to a previously saved snapshot. If the VM is running, it will be automatically stopped before restoring.

**Request Body**:
```json
{
  "snapshot_name": "clean_baseline"
}
```

**Response `200 OK`**:
```json
{
  "vm_id": "vm-01",
  "operation": "restore_snapshot",
  "success": true,
  "message": "Snapshot 'clean_baseline' restored successfully.",
  "timestamp": "2026-09-29T16:30:00Z"
}
```

---

### `POST /vms/{vm_id}/execute`
Execute command strictly inside the assigned VM via Paramiko SSH.

**Request Body**:
```json
{
  "command": "uname -a",
  "timeout": 30
}
```

**Response `200 OK`**:
```json
{
  "vm_id": "vm-01",
  "command": "uname -a",
  "stdout": "Linux cyberarena-vm-01 6.8.0-generic x86_64\n",
  "stderr": "",
  "exit_code": 0,
  "duration": 0.142,
  "timestamp": "2026-09-29T16:30:00Z"
}
```

---

### `GET /vms/{vm_id}/health`
Test hypervisor status and probe SSH connectivity.

**Response `200 OK`**:
```json
{
  "vm_id": "vm-01",
  "state": "running",
  "is_running": true,
  "ssh_reachable": true,
  "latency_ms": 2.14,
  "message": "Hypervisor State: running. SSH: SSH connection successful",
  "timestamp": "2026-09-29T16:30:00Z"
}
```
