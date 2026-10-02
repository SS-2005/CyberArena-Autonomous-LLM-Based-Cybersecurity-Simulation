from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class VMState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    PAUSED = "paused"
    SAVED = "saved"
    STARTING = "starting"
    STOPPING = "stopping"
    ERROR = "error"
    UNKNOWN = "unknown"


class SSHAuthMethod(str, Enum):
    PASSWORD = "password"
    KEY = "key"


class VMConfig(BaseModel):
    vm_id: str = Field(..., description="Unique logical identifier for the VM within CyberArena")
    vm_provider: str = Field(default="virtualbox", description="Virtualization provider")
    virtualbox_vm_name: str = Field(..., description="Actual VirtualBox VM display name or UUID")
    ssh_host: str = Field(..., description="Host IP address or hostname for SSH connection")
    ssh_port: int = Field(default=22, description="SSH port")
    ssh_username: str = Field(..., description="SSH login username")
    ssh_auth_method: SSHAuthMethod = Field(default=SSHAuthMethod.PASSWORD, description="Authentication mechanism")
    ssh_password_env: Optional[str] = Field(None, description="Environment variable name storing the password")
    ssh_key_path_env: Optional[str] = Field(None, description="Environment variable name storing SSH private key path")
    description: Optional[str] = Field(None, description="Description or role of this VM")


class SystemRegistryConfig(BaseModel):
    max_vm: int = Field(default=2, description="Maximum number of active laboratory VMs permitted")
    default_provider: str = Field(default="virtualbox", description="Default VM provider")
    vms: List[VMConfig] = Field(default_factory=list, description="Configured laboratory VMs")


class VMInfo(BaseModel):
    vm_id: str
    vm_provider: str
    virtualbox_vm_name: str
    state: VMState
    ssh_host: str
    ssh_port: int
    ssh_username: str
    ssh_auth_method: str
    description: Optional[str] = None
    is_healthy: Optional[bool] = None
    last_checked: Optional[str] = None


class SystemConfigResponse(BaseModel):
    max_vm: int
    configured_vm_count: int
    default_provider: str
    vms: List[VMInfo]


class CommandExecutionRequest(BaseModel):
    command: str = Field(..., min_length=1, description="Command to execute inside guest VM via SSH")
    timeout: Optional[int] = Field(default=30, ge=1, le=300, description="Execution timeout in seconds")


class CommandExecutionResult(BaseModel):
    vm_id: str
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration: float
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SnapshotRequest(BaseModel):
    snapshot_name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_\-]+$", description="Snapshot name")
    description: Optional[str] = Field(None, max_length=255, description="Optional snapshot description")


class SnapshotRestoreRequest(BaseModel):
    snapshot_name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_\-]+$", description="Snapshot name to restore")


class VMOperationResult(BaseModel):
    vm_id: str
    operation: str
    success: bool
    message: str
    timestamp: str
    details: Optional[Dict[str, Any]] = None


class HealthCheckResult(BaseModel):
    vm_id: str
    state: VMState
    is_running: bool
    ssh_reachable: bool
    latency_ms: Optional[float] = None
    message: str
    timestamp: str
