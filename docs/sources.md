# Data sources

Each source is one entry under `sources:` in the configuration. Every entry has a `type`, a unique `name` (shown on the **Sources** page) and an optional `interval` in seconds. Set `enabled: false` to switch a source off without deleting it.

All sources only read. Wherever a source needs an account, give it a read-only one; this page says how.

Tested status, so you know what to expect:

| Source | Status |
|---|---|
| `snmp-switch`, `local-arp`, `dhcp-file` (`windows-csv`) | tested against real equipment |
| `dhcp-file` (other formats) | tested with sample files |
| `snmp-arp`, `dhcp-windows`, `dhcp-kea`, `dhcp-opnsense`, `netdisco` | written against the vendor documentation, not yet tested against a live system. Reports welcome. |

## snmp-switch

Reads which MAC addresses each port has learned. Works with any managed switch that implements the standard bridge MIBs, which is nearly all of them.

| Setting | Required | Meaning |
|---|---|---|
| `host` | yes | Address of the switch |
| `version` | | `1`, `2c` (default) or `3` |
| `community` | v1/v2c | Read-only community. Use `community_file` to keep it out of the configuration |
| `user`, `auth_protocol`, `auth_key`, `priv_protocol`, `priv_key` | v3 | SNMPv3 credentials. Protocols: `md5`, `sha`, `sha224`, `sha256`, `sha384`, `sha512`; `des`, `aes`, `aes192`, `aes256` |
| `display_name` | | Name shown in deskside. Defaults to the switch's `sysName`, which is often just "Switch" |
| `uplinks` | | Ports that lead to other switches, when LLDP does not report them |
| `ignore_ports` | | Ports to leave out entirely |
| `port`, `timeout`, `retries` | | Defaults 161, 3 s, 1 |

What it reads: `BRIDGE-MIB` and `Q-BRIDGE-MIB` (learned MAC addresses, per VLAN where the switch supports it), `IF-MIB` (port names and descriptions), `LLDP-MIB` (neighbours). It never sends SNMP SET.

**Least access.** Create a dedicated read-only community or, better, an SNMPv3 user with authentication and privacy, restricted to the deskside host if your switch allows that. Many switches ship with a read-write community enabled; deskside does not need one, and you should not reuse it.

## snmp-arp

Reads the ARP table of a router or layer-3 switch, so deskside learns which IP address each MAC currently uses, including devices with fixed addresses. Same SNMP settings as `snmp-switch`. Uses `IP-MIB` (`ipNetToPhysicalTable`, falling back to `ipNetToMediaTable`).

## local-arp

For flat networks where nothing exposes an ARP table over SNMP. deskside sends one empty UDP packet to every address in the listed networks, which makes the operating system resolve each address, and then reads its own ARP cache. No special privileges are needed.

| Setting | Required | Meaning |
|---|---|---|
| `networks` | yes | List of IPv4 networks, at most /20 each |
| `sweep` | | `false` reads the ARP cache without sending anything |
| `settle_seconds` | | Wait after the sweep before reading, default 3 |

The deskside host must be directly attached to these networks; in a container that means `network_mode: host`.

## dhcp-file

Reads a lease file or an export on disk. Mount the file read-only into the container.

| `format` | Produces it |
|---|---|
| `windows-csv` | `Get-DhcpServerv4Scope \| Get-DhcpServerv4Lease \| Export-Csv <path> -NoTypeInformation -Encoding UTF8` on the Windows DHCP server, for example as a scheduled task every five minutes |
| `windows-mmc` | "Export List" in the DHCP console (tab-separated; any language) |
| `dnsmasq` | dnsmasq's lease file, usually `/var/lib/misc/dnsmasq.leases` |
| `isc` | ISC dhcpd's `dhcpd.leases` |
| `kea-csv` | Kea's memfile, usually `kea-leases4.csv` |

## dhcp-windows

Reads leases from a Windows DHCP Server over WinRM, without a file in between.

| Setting | Required | Meaning |
|---|---|---|
| `host` | yes | DHCP server |
| `user`, `password` | yes | Account, as `DOMAIN\user` or `user@domain` |
| `transport` | | `ntlm` (default) or `kerberos` |
| `scheme` | | `https` (default, port 5986) or `http` (port 5985) |
| `verify_tls` | | `false` to accept a self-signed WinRM certificate |

**Least access.** Create a dedicated account. Add it to the built-in group **DHCP Users** on the DHCP server (read access to DHCP) and to **Remote Management Users** (permission to use WinRM). It does not need to be an administrator.

## dhcp-kea

Kea control agent API. Settings: `url` (for example `http://kea-ctrl-agent:8000/`), optional `user` and `password` for basic authentication, `verify_tls`. Uses the `lease4-get-all` command.

## dhcp-opnsense

OPNsense API. Settings: `url`, `key`, `secret` (an API key pair), `backend` (`isc` or `kea`, matching the DHCP service you use), `verify_tls`.

**Least access.** Create a dedicated OPNsense user with only the privilege to read DHCP leases ("Status: DHCP leases" for ISC, "Services: Kea DHCP" for Kea), and generate the API key for that user.

## netdisco

Uses an existing Netdisco installation instead of, or in addition to, polling switches directly. Useful for large or mixed networks, where Netdisco's long-standing vendor support pays off.

| Setting | Required | Meaning |
|---|---|---|
| `url` | yes | Netdisco base URL |
| `token` | yes | API token of a Netdisco user with the `api` role (read-only) |
| `devices` | | Only these switches (by IP). Default: every device Netdisco knows |
| `verify_tls` | | `false` for a self-signed certificate |

deskside reads `search/device`, `object/device/{ip}/ports` and `object/device/{ip}/nodes` (active nodes with their IPs, NetBIOS names and vendor). It never queues jobs in Netdisco.
