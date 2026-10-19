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

### naming

Naming conventions, keyed by a name of your choice. Optional; without them deskside uses whatever names you type or the network provides.

```yaml
naming:
  workstation:
    pattern: "WS{nn}"            # WS01, WS02, ...
    kind: workstation            # only devices of this type are checked against it
    ip: "10.0.10.{100+n}"        # optional: WS09 is expected at 10.0.10.109
  printer:
    pattern: "PRN-{n}"           # PRN-1, PRN-2, ... (no fixed width)
```

| Key | Meaning |
|---|---|
| `pattern` | The name with exactly one number placeholder: `{n}` for any number, `{nn}` for two digits, `{nnn}` for three, and so on. Everything else is literal |
| `kind` | Device type the convention applies to. Without it, the convention is used for suggestions only and never produces warnings |
| `ip` | Expected address per number. `{n}` is the number itself, `{100+n}` adds an offset |
| `match_hostname` | Default `true`: a host name like `ws09.example.org` counts as `WS09` |

What deskside does with a convention:

- Suggests the **next free name** when you create or rename a device. A number counts as taken if a device in deskside has it *or* a host name seen on the network does, so a machine that is not in deskside yet does not get its name handed out twice.
- Offers the convention's form of the host name when you create a device from an unknown address (`ws12.example.org` becomes `WS12`).
- Shows a warning on the card when a device of the convention's type has a name that does not fit, or when its address differs from the expected one.

### netbox

Connection to NetBox: reading, automatic low-risk updates and proposals. See [netbox.md](netbox.md).

### remote_tools

Remote access buttons: changes to the built-in tools and additional ones. See [remote-access.md](remote-access.md).

### privacy

| Key | Default | Meaning |
|---|---|---|
| `contacts_visible_to` | `editor` | Lowest role that sees phone numbers, e-mail addresses and chat handles, and can search by them. Set to `viewer` if your support staff work with the viewer role and need to call people |

Names, job titles and departments of people are visible to every signed-in user.

### directory

People and departments from LDAP or Active Directory. Optional.

```yaml
directory:
  flavor: ad                         # ad or openldap: sets sensible defaults for the settings below
  url: ldaps://dc01.example.org
  user: svc-deskside@example.org     # bind DN or, for AD, user@domain
  password_file: /run/secrets/ldap_password
  base_dn: OU=Staff,DC=example,DC=org
  interval: 3600
```

| Key | Meaning |
|---|---|
| `url` | `ldaps://` (recommended) or `ldap://` with `start_tls: true` |
| `user`, `password` | Account for reading. See [sources.md](sources.md#directory) |
| `base_dn` | Where to search |
| `filter` | LDAP filter for people. AD default: enabled user accounts; OpenLDAP default: `inetOrgPerson` |
| `attributes` | Which deskside field comes from which attribute. **Only the attributes listed here are requested and stored.** Fields: `display_name` (required), `username`, `email`, `phone`, `mobile`, `chat`, `title`, `department` |
| `id_attribute` | Stable identifier. AD default `objectGUID`, OpenLDAP default `entryUUID` |
| `verify_tls`, `ca_file` | Certificate checking for LDAPS / StartTLS. Point `ca_file` at your internal CA if the directory uses one |
| `page_size` | Paged search size, default 500 |
| `interval` | Seconds between syncs, default 3600. Admins can start a sync from the **Directory** page |

Default attribute mapping for `flavor: ad`:

```yaml
attributes:
  display_name: displayName
  username: sAMAccountName
  email: mail
  phone: telephoneNumber
  mobile: mobile
  title: title
  department: department
```

People from the directory are read-only in deskside; change their details in the directory. When someone leaves the directory they are marked inactive rather than deleted, because devices may still list them. Departments named in the `department` attribute are created automatically.

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
| Editor | Additionally create and rename devices, add and remove MAC addresses, attach and detach devices, write, pin and delete notes, choose icons, and maintain rooms, departments, people and who uses which device |
| Admin | Additionally delete devices and manage accounts |

Every change made through the interface or the API is recorded with user and time. Sign-in via OpenID Connect is planned.
