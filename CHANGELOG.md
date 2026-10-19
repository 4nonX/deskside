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
- Network map: a diagram per switch with every port, the devices on it and their peripherals, shared ports as groups, and search highlighting. Room view with devices and peripherals per room.
- Icons per device type, chosen from a bundled set of Tabler Icons, with sensible defaults and a per-device override.
- Click-to-copy for IP and MAC addresses, host names and serial numbers throughout.
