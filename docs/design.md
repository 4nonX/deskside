# deskside: design draft

Status: agreed design. Milestones 1 to 5 are implemented; OpenID Connect sign-in is still open.

## What problem this solves

When someone calls support, the person on the other end usually needs the same handful of facts: which machine it is, where it stands, who uses it and how to reach them, what is known to be wrong with it, how it is connected, and how to get onto it remotely. In most networks those facts are spread across a DHCP server, a directory, a switch, an inventory system, a spreadsheet and someone's memory.

deskside puts them on one card per device and keeps the network part of that card current on its own. You type anything you know (a name, part of an IP or MAC, a room, a phone extension, a word from a note) and get the device, with everything support needs on one screen and a button for each remote tool.

## Goals

- One search field that matches every stored and observed value, and filters the list as you type.
- A device card with identity, live network state, location, department, users and their contact details, pinned warnings and notes, and remote access links.
- Live network data without manual upkeep: which MAC is on which switch port, which IP it has, since when it is online.
- Works in networks that look nothing like the one it was first built for. Every source is optional and every convention is configuration, not code.
- Optional two-way connection to NetBox, where structural changes are proposed and confirmed, never written silently.

## Non-goals

- Monitoring and alerting on metrics. Tools like LibreNMS or Zabbix do this well.
- Configuring network equipment. deskside reads from switches. It never writes to them.
- Storing credentials for remote sessions. deskside opens the remote tool; the tool handles authentication.
- Replacing an inventory system. It can work without one, and with one it stays a companion, not a competitor.

## Core concepts

| Concept | Meaning |
|---|---|
| Device | Anything with a network presence or a support history: workstation, printer, phone, access point, server. Has a name, a type and any number of interfaces. |
| Interface | A MAC address, optionally with a fixed or expected IP. Live observations attach here. |
| Room | Free-form: number, name, and optionally building and floor. |
| Department | Free-form label, optionally synced from the directory. |
| Person | A user of one or more devices, with contact details (phone, mobile, e-mail, chat handle). Manual or from the directory. |
| Note | Free text with author and timestamp. A note can be pinned, which shows it as a highlighted warning at the top of the card ("PSU connector is loose, handle with care"). |
| Remote access | A per-device list of entries, each pointing to a remote tool and the value that tool needs (address or ID). |
| Observation | Something the collectors saw: MAC on port X, MAC with IP Y, hostname Z. Kept with first-seen and last-seen times. |
| Proposal | A change deskside suggests for an external system (for example a new cable in NetBox) that waits for a human to accept or dismiss it. |

## Where the data comes from

All sources are adapters. A site enables the ones it has and leaves out the rest. Each adapter has its own polling interval and reports its health on a status page, so a silent source is visible instead of quietly leaving stale data.

### Switches (port location)

- SNMP v2c or v3, read-only.
- Standard MIBs only: `BRIDGE-MIB` and `Q-BRIDGE-MIB` for the MAC address table (per VLAN where supported), `IF-MIB` for port names and state, `LLDP-MIB` for neighbours.
- Which switches to poll comes from configuration or, when NetBox is connected, from devices carrying a configurable tag.
- Uplinks are recognised from LLDP, from known cabling, or flagged when a port carries many MACs and is not a known uplink ("probably an unmanaged switch behind this port").
- Netdisco as an alternative source, included from the first release. Sites that already run Netdisco, or have large or very mixed networks where its mature vendor handling pays off, point deskside at Netdisco's REST API instead of polling switches directly. The adapter reads, per switch, the active nodes with their IPs, NetBIOS names and vendor, plus ports and layer-2 neighbours. It needs a read-only Netdisco API key and never queues jobs in Netdisco.

### Addresses (MAC to IP)

- ARP tables of routers or layer-3 switches via SNMP (`IP-MIB`).
- A local ARP sweep from the deskside host, for flat networks where nothing else holds the ARP table.
- DHCP leases: Windows DHCP Server (read-only account in the built-in "DHCP Users" group), Kea (control API), dnsmasq (lease file), OPNsense and pfSense (API).

### Names and people

- DNS (forward and reverse) and DHCP hostnames.
- LDAP or Active Directory: computer objects for names, user objects for people, phone, e-mail and department attributes.
- Optional NetBIOS and mDNS lookups for devices that answer nothing else.

### NetBox (optional)

See the NetBox section below.

## How a MAC becomes a named device

For each observed MAC, deskside tries, in this order, and stops at the first match:

1. A device in deskside that already owns this MAC.
2. NetBox, by MAC address or interface (if connected).
3. A DHCP lease or ARP entry, then the hostname behind that IP from DHCP, DNS or the directory.
4. The vendor part of the MAC (OUI), as a hint only ("probably a printer").

Unmatched MACs land in an "unknown" list with port, IP and vendor hint. One click creates a device or assigns the MAC to an existing one.

### Naming conventions

Naming is configuration. A convention has a pattern and optional rules, for example:

```yaml
naming:
  workstation:
    pattern: "WS{nn}"          # WS01, WS02, ...
    match_hostname: "^WS(\\d+)$"
    ip_scheme: "10.0.10.{100+nn}"   # optional: expected address per number
```

With a convention in place, deskside suggests the next free name, flags a device whose name or address does not fit, and can derive the number from a hostname or an address. Without one, it simply uses whatever names the sources provide.

## Search

- One field, matching every value on every card: name, IP (full or partial, `.109` finds `10.0.10.109`), MAC in any notation (`2c58b9`, `2C-58-B9`, `2c:58:b9`), switch and port (`GE7`), room number and name, department, person, phone number, note text, remote IDs.
- Results filter while typing. Several terms narrow the result (`lab printer` finds printers in rooms called "Lab").
- Selecting a result opens the card. The card is meant to answer a support call without a second click.

## Remote access

Each remote tool is an entry in configuration with a link template. New tools need configuration, not code:

```yaml
remote_tools:
  vnc:       { label: "VNC",       link: "vnc://{ip}" }
  ssh:       { label: "SSH",       link: "ssh://{user}@{ip}" }
  anydesk:   { label: "AnyDesk",   link: "anydesk:{anydesk_id}" }
  rustdesk:  { label: "RustDesk",  link: "rustdesk://{rustdesk_id}" }
  web:       { label: "Web console", link: "https://console.example.org/#/client/{console_id}" }
  rdp:       { label: "Remote Desktop", file: rdp }   # generated .rdp file
```

- RDP is offered as a generated `.rdp` file, because Windows does not register a URL scheme for it by default.
- Link schemes differ between tool versions and platforms. Each built-in template will be verified against the current release of the tool before it ships, and the documentation will list what was tested.
- A device can have several entries. The card shows one button per entry, in the configured order.

## NetBox

When connected, NetBox is read on every cycle and written to under two rules:

| Change | Handling |
|---|---|
| Last seen, current DHCP address of an interface marked as dynamic, switch port as information | written automatically |
| New device, new cable, MAC assignment, room change, anything structural | proposed, waits for confirmation |
| Fixed addresses and reservations | never changed; deviations are reported |
| Deletions | never, only marked as stale |

Mapping, configurable:

| deskside | NetBox |
|---|---|
| Room | Location |
| Department | Tenant or custom field |
| Person and contact details | Contact and contact assignment |
| Pinned note and notes | Journal entries |
| Switch port of a device | Cable path, including patch panels |

The NetBox connection uses the regular REST API. It does not depend on Diode or other components with restricted licences.

## Live view and events

- Collectors run on short intervals (switch tables every minute by default, DHCP and directory every five minutes).
- The interface updates without reloading (server-sent events).
- Events: new device, device moved to another port, device offline for longer than a threshold, address outside its expected scheme, many MACs behind a non-uplink port.
- Notifications are optional adapters (webhook, e-mail, chat via webhook).
- History keeps who was where and when, with a configurable retention period.

## Access and roles

- Sign-in via OpenID Connect (any provider), plus one local admin account for setup and emergencies.
- Roles: read (support), edit (cards, notes, rooms), admin (sources, conventions, remote tools).
- Every change is recorded with user and time.

## Privacy

deskside stores personal data: names, phone numbers, e-mail addresses, and when someone's machine was online. That needs care, and the defaults reflect it:

- Directory sync imports only the attributes listed in configuration.
- History retention is limited by default and can be shortened.
- The read role sees contact details only if the admin enables it.
- The documentation will include a short section on what is stored and why, to help with a privacy assessment.

## Secrets

- SNMP credentials, directory and DHCP accounts, and the NetBox token come from environment variables or files (Docker secrets). An optional adapter reads them from HashiCorp Vault or OpenBao.
- Read-only accounts everywhere. Setup documentation shows how to create them for each source.

## Deployment

- One container image, one `compose.yml`.
- SQLite by default, which is plenty for a few thousand devices. PostgreSQL optional.
- Runs behind any reverse proxy. Language files and branding (name, logo, colours) are configuration.

## Proposed stack

- Backend: Python, FastAPI, background collectors in the same process at first.
- SNMP: a maintained Python SNMP library, wrapped so collectors only see "MAC table", "ARP table", "neighbours".
- Frontend: TypeScript, React, server-sent events for live updates.
- Licence: Apache-2.0.

## Milestones

1. **Read-only map.** Switch (direct SNMP or Netdisco), ARP and DHCP collectors, device list, search, card with live network data, manual names and notes.
2. **People and places.** Rooms, departments, persons, contact details, directory sync, naming conventions.
3. **Remote access.** Tool templates, `.rdp` generation, verified templates for common tools.
4. **NetBox.** Read sync, automatic low-risk writes, proposal queue.
5. **Events and history.** Event list, notifications, retention.

Each milestone is usable on its own.

## Decisions

| Question | Decision |
|---|---|
| Licence | Apache-2.0 |
| Netdisco adapter | Part of the first release |
| Where people, rooms, notes and departments live | deskside's own database, with optional sync to NetBox and the directory |
| People and contact details | From LDAP / Active Directory when available, otherwise maintained in deskside |
| SNMP write access (for example port shutdown) | Out of scope |
