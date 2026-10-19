# Changelog

All notable changes to deskside are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Design document describing scope, data sources, matching rules, NetBox handling, remote access and milestones.
- Data sources: SNMP switch MAC tables (SNMP v1, v2c, v3; BRIDGE-, Q-BRIDGE-, IF- and LLDP-MIB), router ARP tables over SNMP, local ARP sweep, DHCP leases from Windows (WinRM or CSV export), dnsmasq, ISC dhcpd, Kea (file or API) and OPNsense, and Netdisco.
- Engine that merges all sources per MAC address: port location with uplink handling, current IP and host name, online state, and events for new, moved, offline and readdressed devices.
- Web interface with live updates: one search over every value, device list, device card with network details, renaming, MAC assignment, notes and pinned warnings, event list, source status and user management.
- Local accounts with viewer, editor and admin roles, and an audit log of every change.
- Docker image, example configuration and documentation for installation, configuration and data sources.
- Rooms (number, name, building, floor), departments and people with phone, mobile, e-mail and chat, maintained on the new Directory page. Devices get a room, a department and any number of users, one of them marked as main user.
- Directory sync from Active Directory or LDAP. Only the attributes named in the configuration are requested and stored; people who leave the directory are kept as inactive.
- Naming conventions such as `WS{nn}`: next free name when creating or renaming a device (taking host names seen on the network into account), name suggestions from host names, and warnings for names or addresses that do not fit.
- Privacy setting for who sees contact details; search by contact details follows the same rule.
- Search also matches rooms, departments, users and their contact details.
- Existing databases gain new tables and columns automatically on start.
- Remote access buttons on the device card: generated `.rdp` files for Remote Desktop, links for RustDesk, TeamViewer, VNC, SSH and web interfaces, and copy-to-clipboard for every ID or address. Tools can be changed, removed or added with link templates; address-based tools can be enabled for whole device types. Remote IDs are searchable.
- NetBox connection: device cards show the linked NetBox device, its location and where each interface's cable path ends. NetBox locations become rooms. DHCP IP objects and an optional last-seen custom field are kept current automatically. MAC addresses, missing cables, moved devices and location changes are collected as proposals on a new NetBox page and applied only when an admin confirms. A read-only mode writes nothing. deskside never deletes anything in NetBox.
- Peripherals and device relations: devices can be attached to another device (monitor to workstation, printer to dock), with connection type, manufacturer, model and serial number. Optional import of peripherals from NetBox by role, attached to their workstation by a configurable name rule.
- Redesigned device card: status, warnings and click-to-copy tiles for IP, MAC, host name and main user at the top; the connection chain (switch port, patch panel, shared segment, device) with other devices on the same port; attached devices; details, notes, history and NetBox in tabs.
- Network map as a diagram in the order traffic flows: Internet, WAN device, gateway (or the hypervisor carrying it), then switches and their ports. Switch cascades from NetBox cables and LLDP, devices behind unmanaged switches on their documented ports, switches without a documented uplink placed where their devices are seen and marked as such, management ports (iLO, iDRAC) as separate lines, hypervisors as boxes with their virtual machines, VPN tunnels at the gateway, peripherals that fold into their device, groups for unknown addresses, and a search that zooms to the hit. Racks from NetBox are drawn as one block each, devices in mounting order with patch panels as rows, cabling inside the rack along its side and the devices behind each rack device to its right. Gateway and WAN device are recognised by device type or set under `map`. Room view with devices and peripherals per room.
- Network map correctness: several devices on one undocumented port are drawn behind a "shared port" box; devices and switches whose live position contradicts NetBox are marked with both positions; network devices assigned to a workstation by name but on a switch port of their own are drawn on that port; MAC addresses next to a known device's address without an IP are counted as that device.
- Where a device is plugged in now reads as a place: the room and the workstation the port leads to by the NetBox cabling, with the switch port and patch panel underneath, "behind" another switch or host where that is the case, and "socket not documented" where NetBox has no cable. Ports read as "Port 7" instead of interface names. Management interfaces are never shown as a device's main address.
- Addresses that only appear in DHCP leases and were never seen on the network (typically random Wi-Fi MACs) are no longer part of the default list; they have their own filter. Reverse DNS names are only used for addresses that are online, since PTR records of pool addresses are often left over from earlier leases.
- NetBox import of infrastructure and virtual machines: `roles: [all]` takes every NetBox device with a network interface, `exclude_roles` leaves roles out, `virtual_machines` imports virtual machines attached to their host. Fixed addresses from NetBox identify servers whose MAC address NetBox does not know.
- Icons per device type, chosen from a bundled set of Tabler Icons, with sensible defaults and a per-device override.
- Click-to-copy for IP and MAC addresses, host names and serial numbers throughout.
- History: where each MAC address was plugged in and which IP address it used, as periods, shown as a timeline on the device card and trimmed after the retention period.
- New events: an address outside the naming scheme, and a switch port that newly carries many addresses. Event messages name the device, not only its MAC address.
- Notifications to chat webhooks (Slack-compatible text), other HTTP endpoints (JSON) and e-mail (SMTP with STARTTLS or TLS). Events are batched per minute, filtered per channel by kind and optionally to known devices, and channel status and a test message are available on the Sources page.
- Events page with filters by kind, text search and paging.

### Fixed

- `update-oui` failed with HTTP 418: the IEEE server rejects clients without a User-Agent. deskside now identifies itself.
- `oui_file` and `directory.ca_file` were read in like secret files and then ignored, so vendor names and a custom LDAP CA never took effect. Keys that name a file deskside opens itself now stay paths.
