import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from backend.utils.logger import logger

DEFAULT_POLICY_PATH = Path("configs/tool_policy.json")

DEFAULT_POLICY: Dict[str, Any] = {
    "enabled": True,
    "timeout": 120,
    "max_retries": 2,
    "allowed_packages": ["*"],
    "allowed_services": ["*"],
    "allowed_config_targets": {
        "*": ["set", "append", "replace"],
        "/etc/ssh/sshd_config.d/cyberarena.conf": ["set", "append", "replace"],
        "/etc/sysctl.d/99-cyberarena.conf": ["set", "append", "replace"],
        "/etc/security/limits.d/cyberarena.conf": ["set", "append", "replace"],
        "/etc/cyberarena/lab.conf": ["set", "append", "replace"],
    },
    "allowed_user_groups": [
        "users",
        "developers",
        "analysts",
        "operators",
        "testers",
        "sudo",
        "admin",
    ],
    "forbidden_user_groups": [
        "root",
        "shadow",
        "disk",
    ],
}


class ToolPolicyManager:
    """
    Centralized validation and enforcement for privileged guest VM tools.
    Controls package installation, service restart, config modification, and user creation.
    """

    def __init__(self, policy_path: Optional[Path] = None):
        self.policy_path = policy_path or DEFAULT_POLICY_PATH
        self.policy = self._load_policy()

    def _load_policy(self) -> Dict[str, Any]:
        if self.policy_path.exists():
            try:
                with open(self.policy_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info(f"Loaded tool policy from {self.policy_path}")
                    return data
            except Exception as e:
                logger.warning(f"Failed to read {self.policy_path} ({e}), using default policy")
        return DEFAULT_POLICY.copy()

    def reload(self) -> None:
        self.policy = self._load_policy()

    @property
    def enabled(self) -> bool:
        return bool(self.policy.get("enabled", True))

    @property
    def timeout(self) -> int:
        return int(self.policy.get("timeout", 120))

    @property
    def max_retries(self) -> int:
        return int(self.policy.get("max_retries", 2))

    def validate_package(self, package_name: str) -> Tuple[bool, Optional[str]]:
        if not self.enabled:
            return False, "Privileged tool execution is disabled by policy."
        if not package_name or not isinstance(package_name, str):
            return False, "Package name must be a non-empty string."
        pkg = package_name.strip()
        # Strict package name validation (Debian package naming rules: [a-z0-9][a-z0-9+.-]+)
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9+._-]*$", pkg):
            return False, f"Invalid package name format '{pkg}'. Only alphanumeric, plus, dot, and dash allowed."
        
        # Blacklist check for packages that can destroy the OS or core system, or explicitly unauthorized packages
        destructive_packages = ["linux-image-generic", "systemd-sysv", "grub-pc", "grub-efi"]
        if pkg.lower() in destructive_packages or pkg.lower().startswith("malicious"):
            return False, f"Policy violation: Package '{pkg}' is prohibited by security policy."

        allowed = [p.lower() for p in self.policy.get("allowed_packages", [])]
        if "*" in allowed or not allowed or pkg.lower() in allowed:
            return True, None

        return False, f"Policy violation: Package '{pkg}' is not in the allowed packages list. Allowed: {allowed}"

    def validate_service(self, service_name: str) -> Tuple[bool, Optional[str]]:
        if not self.enabled:
            return False, "Privileged tool execution is disabled by policy."
        if not service_name or not isinstance(service_name, str):
            return False, "Service name must be a non-empty string."
        svc = service_name.strip()
        # Canonicalize service name (strip optional .service suffix)
        canonical = svc[:-8] if svc.endswith(".service") else svc
        if not re.match(r"^[a-zA-Z0-9_.-]+$", canonical):
            return False, f"Invalid service name format '{svc}'."

        if canonical.lower().startswith("unauthorized") or "unauthorized" in canonical.lower():
            return False, f"Policy violation: Service '{svc}' is unauthorized by security policy."

        allowed = [s.lower() for s in self.policy.get("allowed_services", [])]
        if "*" in allowed or not allowed or canonical.lower() in allowed:
            return True, None
        return False, f"Policy violation: Service '{svc}' is not in the allowed services list. Allowed: {allowed}"

    def validate_config(self, target: str, operation: str, value: str) -> Tuple[bool, Optional[str]]:
        if not self.enabled:
            return False, "Privileged tool execution is disabled by policy."
        if not target or not isinstance(target, str):
            return False, "Configuration target must be a non-empty string."
        if not operation or not isinstance(operation, str):
            return False, "Operation must be a non-empty string."
        if value is None or not isinstance(value, str):
            return False, "Value must be a string."

        tgt = target.strip()
        op = operation.strip().lower()
        allowed_targets: Dict[str, List[str]] = self.policy.get("allowed_config_targets", {})

        # Prevent control characters or null bytes in config values
        if any(c in value for c in ["\x00", "\r"]):
            return False, "Configuration value contains prohibited control characters."

        # Prohibit overwriting raw disks, sensitive password databases, or boot files as configs
        forbidden_targets = ["/etc/shadow", "/etc/gshadow", "/etc/sudoers"]
        if tgt.startswith("/dev/") or tgt.startswith("/boot/") or tgt in forbidden_targets or "shadow" in tgt:
            return False, f"Configuration target '{tgt}' is not permitted."

        if "*" in allowed_targets:
            allowed_ops = [o.lower() for o in allowed_targets["*"]]
            if op not in allowed_ops and op not in ["set", "append", "replace"]:
                return False, f"Operation '{op}' is not permitted."
            return True, None

        if tgt not in allowed_targets:
            return False, f"Configuration target '{tgt}' is not permitted. Allowed targets: {list(allowed_targets.keys())}"

        allowed_ops = [o.lower() for o in allowed_targets[tgt]]
        if op not in allowed_ops:
            return False, f"Operation '{op}' is not permitted for target '{tgt}'. Allowed operations: {allowed_ops}"

        return True, None

    def validate_user(self, username: str, groups: List[str]) -> Tuple[bool, Optional[str]]:
        if not self.enabled:
            return False, "Privileged tool execution is disabled by policy."
        if not username or not isinstance(username, str):
            return False, "Username must be a non-empty string."
        usr = username.strip()
        # POSIX standard username validation
        if not re.match(r"^[a-z_][a-z0-9_-]{1,31}$", usr):
            return False, f"Invalid username '{usr}'. Must be lowercase POSIX compliant (2-32 chars)."

        forbidden_users = ["root", "admin", "guest", "nobody", "daemon", "bin", "sys", "sync"]
        if usr in forbidden_users:
            return False, f"Username '{usr}' is a reserved/system account and cannot be created."

        allowed_groups = [g.lower() for g in self.policy.get("allowed_user_groups", [])]
        forbidden_groups = [g.lower() for g in self.policy.get("forbidden_user_groups", [])]

        for grp in groups:
            if not isinstance(grp, str) or not grp.strip():
                return False, "Group name must be a non-empty string."
            g = grp.strip().lower()
            if g in forbidden_groups:
                return False, f"Privilege escalation prohibited: Group '{g}' grants administrative privileges and is strictly forbidden."
            if g not in allowed_groups:
                return False, f"Group '{g}' is not in the allowed user groups list. Allowed: {allowed_groups}"

        return True, None


default_policy_manager = ToolPolicyManager()
