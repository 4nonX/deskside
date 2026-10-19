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
