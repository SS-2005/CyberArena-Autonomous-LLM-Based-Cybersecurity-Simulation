# Laboratory Network Isolation Architecture

## 1. Network Design Principles

CyberArena is designed for cybersecurity research involving autonomous agents. Because autonomous agents generate actions dynamically, strict network isolation boundaries must be enforced:

1. **No External/Public Targets**: Agents must never interact with public IP addresses, external internet hosts, or production corporate networks.
2. **Controlled Inter-VM Communication**: Target virtual machines communicate exclusively through a private virtual network.
3. **Controlled Host Management Interface**: The Windows host accesses the guest VMs solely via a local, host-only adapter for lifecycle management and telemetry.

---

## 2. Recommended Topology: Host-Only Network

```
+--------------------------------------------------------------+
|                         Windows Host                         |
|  VirtualBox Host-Only Ethernet Adapter: 192.168.56.1/24       |
|                                                              |
|   CyberArena Backend (127.0.0.1:8000)                        |
|   CyberArena Frontend (127.0.0.1:5173)                       |
+------------------------------┬-------------------------------+
                               │ (Management SSH over 192.168.56.x)
                               │
            ┌──────────────────┴──────────────────┐
            │   Private Host-Only Subnet          │
            │   (192.168.56.0 / 24)               │
            │   - No Default Gateway to Internet  │
            │   - Promiscuous Mode: Allow VMs     │
            └──────────┬──────────────────┬───────┘
                       │                  │
         ┌─────────────┴──────┐    ┌──────┴─────────────┐
         │       VM-01        │    │       VM-02        │
         │  192.168.56.101/24 │◄──►│  192.168.56.102/24 │
         │   Ubuntu Server    │    │   Ubuntu Server    │
         └────────────────────┘    └────────────────────┘
```

---

## 3. Configuration Steps

### VirtualBox Host-Only Network Setup
1. In VirtualBox, go to **Tools** -> **Network Manager**.
2. Under the **Host-only Networks** tab, verify an adapter exists:
   - **Name**: `VirtualBox Host-Only Ethernet Adapter`
   - **IPv4 Address**: `192.168.56.1`
   - **IPv4 Network Mask**: `255.255.255.0`
   - **DHCP Server**: Enabled (or configure static IPs manually).

### Assigning VM Interfaces
- **VM-01**:
  - Network Adapter 1: Attached to *Host-only Adapter*, Name: `VirtualBox Host-Only Ethernet Adapter`.
  - Static IP: `192.168.56.101/24`
- **VM-02**:
  - Network Adapter 1: Attached to *Host-only Adapter*, Name: `VirtualBox Host-Only Ethernet Adapter`.
  - Static IP: `192.168.56.102/24`

---

## 4. Internet Access During Setup vs. Experiment Mode

> [!WARNING]
> While installing dependencies (e.g. `apt update && apt install ...`), VMs may temporarily use a secondary NAT adapter.
> **However, this NAT adapter MUST be disconnected or disabled before starting autonomous experiments.**
> The experiment network must never permit agents to contact public systems.

To disconnect external access before an experiment:
```powershell
# Disable second adapter (NAT) on VM-01
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" modifyvm "cyberarena-vm-01" --cableconnected2 off

# Disable second adapter (NAT) on VM-02
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" modifyvm "cyberarena-vm-02" --cableconnected2 off
```
