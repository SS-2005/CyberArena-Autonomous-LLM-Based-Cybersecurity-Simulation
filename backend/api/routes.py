from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from backend.schemas.vm import (
    VMInfo,
    VMOperationResult,
    CommandExecutionRequest,
    CommandExecutionResult,
    SnapshotRequest,
    SnapshotRestoreRequest,
    HealthCheckResult,
    SystemConfigResponse,
)
from backend.services.vm_service import VMService, VMNotFoundError
from backend.api.deps import get_vm_service
from backend.utils.logger import logger

router = APIRouter(tags=["Virtual Machines"])


@router.get("/config", response_model=SystemConfigResponse, summary="Get System & VM Configuration")
def get_config(service: VMService = Depends(get_vm_service)):
    """Retrieve system-level configuration including dynamic max_vm and configured VM count."""
    return service.get_system_config()


@router.get("/vms", response_model=List[VMInfo], summary="List Configured Virtual Machines")
def list_vms(service: VMService = Depends(get_vm_service)):
    """List all registered laboratory virtual machines with their live states."""
    return service.list_vms()


@router.get("/vms/{vm_id}", response_model=VMInfo, summary="Get Virtual Machine Details")
def get_vm(vm_id: str, service: VMService = Depends(get_vm_service)):
    """Retrieve details and live state of a single virtual machine."""
    try:
        return service.get_vm(vm_id)
    except VMNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/vms/{vm_id}/start", response_model=VMOperationResult, summary="Start Virtual Machine")
def start_vm(vm_id: str, service: VMService = Depends(get_vm_service)):
    """Start the specified virtual machine in headless mode."""
    try:
        return service.start_vm(vm_id)
    except VMNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting VM '{vm_id}': {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/vms/{vm_id}/stop", response_model=VMOperationResult, summary="Stop Virtual Machine")
def stop_vm(vm_id: str, force: bool = False, service: VMService = Depends(get_vm_service)):
    """Stop the specified virtual machine gracefully or with force."""
    try:
        return service.stop_vm(vm_id, force=force)
    except VMNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error stopping VM '{vm_id}': {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/vms/{vm_id}/snapshot", response_model=VMOperationResult, summary="Create Snapshot")
def create_snapshot(
    vm_id: str,
    request: SnapshotRequest,
    service: VMService = Depends(get_vm_service),
):
    """Create a point-in-time recovery snapshot for the VM."""
    try:
        return service.snapshot(vm_id, snapshot_name=request.snapshot_name, description=request.description)
    except VMNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating snapshot for VM '{vm_id}': {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/vms/{vm_id}/restore", response_model=VMOperationResult, summary="Restore Snapshot")
def restore_snapshot(
    vm_id: str,
    request: SnapshotRestoreRequest,
    service: VMService = Depends(get_vm_service),
):
    """Restore the virtual machine to a previously saved snapshot."""
    try:
        return service.restore_snapshot(vm_id, snapshot_name=request.snapshot_name)
    except VMNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error restoring snapshot for VM '{vm_id}': {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/vms/{vm_id}/execute", response_model=CommandExecutionResult, summary="Execute Guest Command")
def execute_command(
    vm_id: str,
    request: CommandExecutionRequest,
    service: VMService = Depends(get_vm_service),
):
    """
    Execute a command strictly inside the assigned VM via Paramiko SSH.
    Host operating system is NEVER an execution target.
    """
    try:
        return service.execute_command(vm_id, command=request.command, timeout=request.timeout)
    except VMNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error executing command on VM '{vm_id}': {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/vms/{vm_id}/health", response_model=HealthCheckResult, summary="Check VM Health")
def health_check(vm_id: str, service: VMService = Depends(get_vm_service)):
    """Perform health and connectivity check on the virtual machine."""
    try:
        return service.health_check(vm_id)
    except VMNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error checking health for VM '{vm_id}': {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
