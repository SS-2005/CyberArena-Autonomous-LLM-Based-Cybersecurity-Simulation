#!/usr/bin/env python3
"""
Provisioning script for CyberArena privileged guest helper scripts and sudoers rules.
Installs root-owned wrappers in /usr/local/sbin/ and configures narrowly scoped
NOPASSWD permissions for 'labuser' on VM-01 and VM-02.
Does NOT print or expose passwords.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import paramiko

# Load .env
load_dotenv()

INSTALL_PACKAGE_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail

PKG="${1:-}"
if [[ -z "$PKG" ]]; then
    echo "ERROR: Package name is required" >&2
    exit 1
fi

if [[ ! "$PKG" =~ ^[a-z0-9][a-z0-9+.-]+$ ]]; then
    echo "ERROR: Invalid package name format: $PKG" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends "$PKG"
echo "SUCCESS: Package '$PKG' successfully installed"
"""

RESTART_SERVICE_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail

SVC="${1:-}"
if [[ -z "$SVC" ]]; then
    echo "ERROR: Service name is required" >&2
    exit 1
fi

SVC="${SVC%.service}"
if [[ ! "$SVC" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
    echo "ERROR: Invalid service name: $SVC" >&2
    exit 1
fi

systemctl restart "$SVC"
STATUS=$(systemctl is-active "$SVC" || true)
echo "SUCCESS: Service '$SVC' restarted (status: $STATUS)"
"""

MODIFY_CONFIG_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-}"
OPERATION="${2:-}"
B64_VALUE="${3:-}"

if [[ -z "$TARGET" || -z "$OPERATION" ]]; then
    echo "ERROR: Target and operation are required" >&2
    exit 1
fi

ALLOWED_TARGETS=(
    "/etc/ssh/sshd_config.d/cyberarena.conf"
    "/etc/sysctl.d/99-cyberarena.conf"
    "/etc/security/limits.d/cyberarena.conf"
    "/etc/cyberarena/lab.conf"
)

TARGET_ALLOWED=0
for allowed in "${ALLOWED_TARGETS[@]}"; do
    if [[ "$TARGET" == "$allowed" ]]; then
        TARGET_ALLOWED=1
        break
    fi
done

if [[ "$TARGET_ALLOWED" -ne 1 ]]; then
    echo "ERROR: Target '$TARGET' is not permitted by CyberArena policy" >&2
    exit 1
fi

mkdir -p "$(dirname "$TARGET")"
VALUE=$(echo "$B64_VALUE" | base64 -d)

case "$OPERATION" in
    set|replace)
        echo "$VALUE" > "$TARGET"
        chmod 644 "$TARGET"
        echo "SUCCESS: Replaced content of '$TARGET'"
        ;;
    append)
        echo "$VALUE" >> "$TARGET"
        chmod 644 "$TARGET"
        echo "SUCCESS: Appended content to '$TARGET'"
        ;;
    *)
        echo "ERROR: Unsupported operation '$OPERATION'" >&2
        exit 1
        ;;
esac
"""

CREATE_USER_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail

USERNAME="${1:-}"
GROUPS="${2:-}"

if [[ -z "$USERNAME" ]]; then
    echo "ERROR: Username is required" >&2
    exit 1
fi

if [[ ! "$USERNAME" =~ ^[a-z_][a-z0-9_-]{1,31}$ ]]; then
    echo "ERROR: Invalid username format: $USERNAME" >&2
    exit 1
fi

FORBIDDEN_USERS=("root" "admin" "guest" "nobody" "daemon" "bin" "sys")
for forbidden in "${FORBIDDEN_USERS[@]}"; do
    if [[ "$USERNAME" == "$forbidden" ]]; then
        echo "ERROR: Cannot create reserved user account: $USERNAME" >&2
        exit 1
    fi
done

if id "$USERNAME" &>/dev/null; then
    echo "ERROR: User '$USERNAME' already exists" >&2
    exit 1
fi

FORBIDDEN_GROUPS=("sudo" "root" "wheel" "admin" "adm" "shadow" "disk")
if [[ -n "$GROUPS" ]]; then
    IFS=',' read -ra GRP_ARRAY <<< "$GROUPS"
    for grp in "${GRP_ARRAY[@]}"; do
        for forbidden in "${FORBIDDEN_GROUPS[@]}"; do
            if [[ "$grp" == "$forbidden" ]]; then
                echo "ERROR: Prohibited group assignment '$grp' grants admin privileges" >&2
                exit 1
            fi
        done
        if ! getent group "$grp" &>/dev/null; then
            groupadd "$grp"
        fi
    done
    useradd -m -s /bin/bash -G "$GROUPS" "$USERNAME"
else
    useradd -m -s /bin/bash "$USERNAME"
fi

echo "SUCCESS: User '$USERNAME' created (groups: ${GROUPS:-none})"
"""

SUDOERS_CONTENT = """# CyberArena Narrowly Scoped Privileged Guest Tools Policy
# Created for labuser - strictly allows approved root wrappers with no interactive password.
labuser ALL=(ALL) NOPASSWD: /usr/local/sbin/cyberarena-install-package, /usr/local/sbin/cyberarena-restart-service, /usr/local/sbin/cyberarena-modify-config, /usr/local/sbin/cyberarena-create-user
"""


def provision_vm(vm_id: str, host: str, user: str, password_env: str):
    password = os.getenv(password_env)
    if not password:
        print(f"[-] Environment variable {password_env} not set. Skipping {vm_id}.")
        return False

    print(f"[*] Provisioning privileged helpers on {vm_id} ({host})...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=host,
            port=22,
            username=user,
            password=password,
            timeout=10,
            allow_agent=False,
            look_for_keys=False,
        )
    except Exception as e:
        print(f"[-] Failed to connect to {vm_id} ({host}): {e}")
        return False

    def run_sudo(cmd: str):
        stdin, stdout, stderr = client.exec_command(f"sudo -S bash -c {cmd!r}")
        stdin.write(password + "\n")
        stdin.flush()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err

    scripts = [
        ("/usr/local/sbin/cyberarena-install-package", INSTALL_PACKAGE_SCRIPT),
        ("/usr/local/sbin/cyberarena-restart-service", RESTART_SERVICE_SCRIPT),
        ("/usr/local/sbin/cyberarena-modify-config", MODIFY_CONFIG_SCRIPT),
        ("/usr/local/sbin/cyberarena-create-user", CREATE_USER_SCRIPT),
    ]

    for path, content in scripts:
        # Write via base64
        import base64
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        write_cmd = f"echo '{b64}' | base64 -d > {path} && chmod 755 {path} && chown root:root {path}"
        code, out, err = run_sudo(write_cmd)
        if code != 0:
            print(f"[-] Failed to install {path}: {err}")
            client.close()
            return False
        print(f"[+] Installed {path}")

    # Write sudoers file
    b64_sudoers = base64.b64encode(SUDOERS_CONTENT.encode("utf-8")).decode("ascii")
    sudoers_path = "/etc/sudoers.d/cyberarena-privileged"
    write_sudoers = f"echo '{b64_sudoers}' | base64 -d > {sudoers_path} && chmod 440 {sudoers_path} && chown root:root {sudoers_path} && visudo -c -f {sudoers_path}"
    code, out, err = run_sudo(write_sudoers)
    if code != 0:
        print(f"[-] Failed to configure sudoers file {sudoers_path}: {err}")
        client.close()
        return False
    print(f"[+] Configured and validated {sudoers_path}")

    # Verify passwordless sudo works for one wrapper
    stdin, stdout, stderr = client.exec_command("sudo -n /usr/local/sbin/cyberarena-restart-service nonexistentsvc || true")
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    print(f"[+] Verification test: exit_code={code}")

    client.close()
    print(f"[+] Successfully provisioned {vm_id}!\n")
    return True


if __name__ == "__main__":
    vms_to_provision = [
        ("vm-01", "192.168.32.101", "labuser", "CYBERARENA_VM01_PASSWORD"),
        ("vm-02", "192.168.32.102", "labuser", "CYBERARENA_VM02_PASSWORD"),
    ]

    success = True
    for vm_id, host, user, pwd_env in vms_to_provision:
        res = provision_vm(vm_id, host, user, pwd_env)
        if not res:
            success = False

    if success:
        print("[+] All VMs successfully provisioned with privileged helper scripts.")
        sys.exit(0)
    else:
        print("[-] One or more VMs failed provisioning.")
        sys.exit(1)
