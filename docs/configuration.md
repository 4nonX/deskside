# Configuration

deskside reads one YAML file, by default `/config/config.yaml`. [config.example.yaml](../config.example.yaml) is a commented starting point.

## Keeping secrets out of the file

Two mechanisms work anywhere in the file:

- A key ending in `_file` is read from that file and used without the suffix. `community_file: /run/secrets/snmp` sets `community` to the file's content, minus trailing whitespace and line breaks.
- `${NAME}` inside a value is replaced by the environment variable `NAME`. A variable that is not set stops deskside with a clear message instead of silently becoming empty.

## Sections

### server

| Key | Meaning |
|---|---|
| `secret_key` | At least 32 random characters. Signs session cookies. Changing it signs everyone out |
| `admin_password` | Used only when the database has no users yet, to create the account `admin` |

### database

| Key | Default | Meaning |
|---|---|---|
| `url` | `sqlite:///data/deskside.db` | SQLAlchemy URL. SQLite is enough for thousands of devices. PostgreSQL support is planned but not yet tested |

### live

| Key | Default | Meaning |
|---|---|---|
| `offline_after` | `900` | Seconds without being seen in a switch table or ARP before a device counts as offline |
| `uplink_mac_threshold` | `4` | A port with more MAC addresses than this and no known neighbour is flagged: probably an unmanaged switch, a hypervisor or a docking station |
| `retention_days` | `90` | Events older than this are removed |

### dns

| Key | Default | Meaning |
|---|---|---|
| `reverse` | `true` | Reverse-resolve addresses that no other source names. Uses the host's resolver, runs in the background, results are cached for an hour |

### oui_file

Path to the IEEE vendor list, see [installation.md](installation.md#vendor-names). Optional.

### sources

A list of data sources. See [sources.md](sources.md).

## How deskside combines its sources

- **Location.** A MAC address is located at the switch port where it is learned. If several switches see it (because they are chained), the port that is not an uplink and carries the fewest addresses wins: that is the one closest to the device. A port counts as an uplink when a neighbour is known on it (LLDP, Netdisco, or `uplinks` in the configuration).
- **Address.** ARP wins over DHCP, because it shows what the device uses right now. DHCP and Netdisco fill in when there is no ARP entry.
- **Name.** DHCP host name first, then Netdisco (DNS or NetBIOS), then reverse DNS. A name from a lease is only used if the lease is for the address the device currently has.
- **Online.** Only a switch table or ARP entry counts as proof that a device is on. DHCP leases outlive a switched-off device by days.
- **Stale data.** A source's last result is used for up to three of its intervals. After that it is ignored, so one failing source does not keep old data alive.

## Events

deskside records these events, shown under **Events** and on each device card:

| Event | When |
|---|---|
| `discovery` | The very first collection run (summarised in one event, not one per device) |
| `new` | A MAC address appears that deskside has never seen |
| `online` | A known address is seen again after being offline |
| `offline` | A device was not seen for `offline_after` seconds |
| `moved` | A device appears on a different switch port |
| `ip_changed` | A device uses a different IP address |

## Accounts and roles

Accounts are managed under **Users** (admins only). Passwords need at least 12 characters and are stored as scrypt hashes.

| Role | Can |
|---|---|
| Viewer | Search and read everything |
| Editor | Additionally create and rename devices, add and remove MAC addresses, and write, pin and delete notes |
| Admin | Additionally delete devices and manage accounts |

Every change made through the interface or the API is recorded with user and time. Sign-in via OpenID Connect is planned.
