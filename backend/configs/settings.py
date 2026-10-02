import os
import shutil
import json
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from dotenv import load_dotenv
from backend.schemas.vm import SystemRegistryConfig, VMConfig, SSHAuthMethod
from backend.utils.logger import logger

load_dotenv()


def find_vboxmanage() -> Optional[str]:
    """Auto-detect VBoxManage executable location on the host system."""
    env_vbox = os.getenv("VBOX_MANAGE_PATH")
    if env_vbox and os.path.isfile(env_vbox):
        return env_vbox

    # Check system PATH
    which_vbox = shutil.which("VBoxManage")
    if which_vbox:
        return which_vbox

    # Common Windows installations
    common_paths = [
        r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
        r"C:\Program Files (x86)\Oracle\VirtualBox\VBoxManage.exe",
    ]
    for path in common_paths:
        if os.path.isfile(path):
            return path

    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "CyberArena"
    env: str = Field(default="development", alias="CYBERARENA_ENV")
    host: str = Field(default="127.0.0.1", alias="CYBERARENA_HOST")
    port: int = Field(default=8000, alias="CYBERARENA_PORT")
    config_path: str = Field(default="configs/vms.json", alias="CYBERARENA_CONFIG_PATH")
    models_config_path: str = Field(default="configs/models.json", alias="CYBERARENA_MODELS_PATH")
    ollama_base_url: str = Field(default="http://127.0.0.1:11434", alias="OLLAMA_BASE_URL")
    vboxmanage_path: Optional[str] = Field(default_factory=find_vboxmanage, alias="VBOX_MANAGE_PATH")
    default_ssh_timeout: int = Field(default=30, alias="CYBERARENA_DEFAULT_SSH_TIMEOUT")
    max_vm_override: Optional[int] = Field(default=None, alias="CYBERARENA_MAX_VM")


settings = Settings()


def resolve_project_root() -> Path:
    """Resolve repository workspace root directory."""
    current = Path(__file__).resolve().parent
    # Navigate up until we find configs/ or .git or workspace root
    for parent in [current.parent.parent, current.parent, current]:
        if (parent / "configs").exists() or (parent / "ubuntu-24.04.5-live-server-amd64.iso").exists():
            return parent
    return Path.cwd()


def load_registry_config(config_file_path: Optional[str] = None) -> SystemRegistryConfig:
    """
    Load and parse the VM registry configuration file.
    Validates max_vm dynamically and ensures configured VMs do not exceed max_vm.
    """
    root = resolve_project_root()
    path_to_load = Path(config_file_path) if config_file_path else root / settings.config_path

    if not path_to_load.is_file():
        # Fallback to local configs directory
        fallback = root / "configs" / "vms.json"
        if fallback.is_file():
            path_to_load = fallback
        else:
            logger.warning(f"VM registry config file not found at {path_to_load}. Returning default configuration.")
            return SystemRegistryConfig(max_vm=settings.max_vm_override or 2, vms=[])

    try:
        with open(path_to_load, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read VM registry config at {path_to_load}: {e}")
        raise ValueError(f"Invalid JSON configuration at {path_to_load}: {e}")

    registry = SystemRegistryConfig(**data)

    # Apply environment override for max_vm if configured
    if settings.max_vm_override is not None:
        registry.max_vm = settings.max_vm_override

    # Enforce dynamic max_vm limit on configured VMs
    if len(registry.vms) > registry.max_vm:
        logger.warning(
            f"Configured VM count ({len(registry.vms)}) exceeds max_vm limit ({registry.max_vm}). "
            f"Truncating active registry to max_vm limit."
        )
        registry.vms = registry.vms[:registry.max_vm]

    return registry


def load_model_registry(config_file_path: Optional[str] = None) -> Any:
    """
    Load and parse the LLM model registry configuration file.
    Decoupled from specific model names.
    """
    from backend.schemas.llm import ModelRegistryConfig

    root = resolve_project_root()
    path_to_load = Path(config_file_path) if config_file_path else root / settings.models_config_path

    if not path_to_load.is_file():
        fallback = root / "configs" / "models.json"
        if fallback.is_file():
            path_to_load = fallback
        else:
            logger.warning(f"Model registry config file not found at {path_to_load}. Returning default configuration.")
            return ModelRegistryConfig(
                default_model="local-qwen3-4b",
                llm_parallelism=1,
                default_iteration_limit=10,
                default_timeout=60,
                models=[],
            )

    try:
        with open(path_to_load, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read model registry config at {path_to_load}: {e}")
        raise ValueError(f"Invalid JSON configuration at {path_to_load}: {e}")

    return ModelRegistryConfig(**data)


def get_vm_secret(vm_config: VMConfig) -> Dict[str, Optional[str]]:
    """
    Securely resolve credentials for a VM from environment variables.
    Never stores real passwords or private keys in source control.
    """
    password = None
    key_path = None

    if vm_config.ssh_password_env:
        password = os.getenv(vm_config.ssh_password_env)

    if vm_config.ssh_key_path_env:
        key_path = os.getenv(vm_config.ssh_key_path_env)

    # Secondary fallback check using standard naming convention
    safe_vm_id = vm_config.vm_id.upper().replace("-", "_")
    if not password:
        password = os.getenv(f"CYBERARENA_PASSWORD_{safe_vm_id}")
    if not key_path:
        key_path = os.getenv(f"CYBERARENA_KEY_PATH_{safe_vm_id}")

    return {
        "password": password,
        "key_path": key_path,
    }
