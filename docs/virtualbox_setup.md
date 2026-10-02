# VirtualBox & Ubuntu VM Setup Guide

This guide details the steps to set up Ubuntu Server virtual machines using the provided ISO image:
`ubuntu-24.04.5-live-server-amd64.iso`.

---

## 1. System Requirements

- **Host OS**: Windows 11 x64
- **Hypervisor**: Oracle VirtualBox 7.x
- **Available ISO**: `ubuntu-24.04.5-live-server-amd64.iso` in project root
- **CPU Allocation**: 2 vCPUs per VM
- **RAM Allocation**: 2048 MB to 4096 MB per VM
- **Disk Allocation**: 20 GB to 30 GB dynamic VDI per VM

---

## 2. Creating VM 1 (`cyberarena-vm-01`)

1. Open **VirtualBox Manager**.
2. Click **New**:
   - **Name**: `cyberarena-vm-01`
   - **Type**: Linux
   - **Version**: Ubuntu (64-bit)
   - **ISO Image**: Browse to `ubuntu-24.04.5-live-server-amd64.iso` in your CyberArena workspace
   - Check *Skip Unattended Installation* (recommended for custom network setup).
3. **Hardware**:
   - Base Memory: 2048 MB
   - Processors: 2 CPUs
4. **Hard Disk**:
   - Create a Virtual Hard Disk now (25 GB VDI, Dynamically allocated).
5. Click **Finish**.

---

## 3. Configuring Network Adapters

To ensure isolated laboratory operation while allowing host SSH access:

1. Right-click `cyberarena-vm-01` -> **Settings** -> **Network**.
2. **Adapter 1**:
   - Attached to: **Host-only Adapter**
   - Name: `VirtualBox Host-Only Ethernet Adapter` (or `vboxnet0`)
   - Promiscuous Mode: Allow VMs
3. *(Optional for initial package installation only)* **Adapter 2**:
   - Attached to: **NAT**
   - *Note*: Disable or disconnect Adapter 2 during live autonomous experiments to enforce complete isolation.

---

## 4. Ubuntu Installation & SSH Configuration

1. Start `cyberarena-vm-01`.
2. Follow Ubuntu Server installer prompts:
   - Language: English
   - Network: Configure static IP on the Host-Only adapter (e.g. `192.168.56.101/24`) or note the DHCP assigned IP.
   - User Account:
     - Your name: `Lab User`
     - Server name: `cyberarena-vm-01`
     - Username: `labuser`
     - Password: Choose a strong password (e.g. `cyberarena_lab_pass`)
   - SSH Setup:
     - Check **Install OpenSSH server**.
3. Complete installation and reboot.

---

## 5. Creating VM 2 (`cyberarena-vm-02`)

Repeat the above steps or clone `cyberarena-vm-01`:
1. Right-click `cyberarena-vm-01` -> **Clone**.
2. **Name**: `cyberarena-vm-02`.
3. MAC Address Policy: **Generate new MAC addresses for all network adapters**.
4. Clone type: **Full clone**.
5. Boot `cyberarena-vm-02`, update hostname to `cyberarena-vm-02`, and assign IP `192.168.56.102/24`.

---

## 6. Baseline Snapshot

Before starting any experiments, create a baseline snapshot for instant rollback:
```powershell
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" snapshot "cyberarena-vm-01" take "baseline_clean" --description "Pre-experiment baseline"
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" snapshot "cyberarena-vm-02" take "baseline_clean" --description "Pre-experiment baseline"
```
Or use the **Snapshot** button directly in the CyberArena web dashboard.
