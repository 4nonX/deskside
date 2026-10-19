# NetBox

deskside can read your NetBox, show what it knows on each device card, keep a few low-risk fields current, and propose structural changes for an admin to confirm. It talks to NetBox's regular REST API and needs nothing installed on the NetBox side.

## What deskside reads

On every cycle (every five minutes by default):

- devices, their interfaces and MAC addresses,
- the cable path of each interface, as NetBox computes it (through patch panels),
- locations, which become rooms in deskside,
- custom field definitions, to see whether the optional "last seen" field exists.

A deskside device is linked to a NetBox device by MAC address first. If none of its MAC addresses is known to NetBox, it is linked by name, using `name_pattern` (see below).

Each linked device card shows the NetBox device with a link, its location, and for each interface where its cable ends, for example "cabled to core-sw GE7". Switch port names are compared in long and short form, so `GigabitEthernet7` from SNMP matches `GE7` or `Gi7` in NetBox.

## Rooms from NetBox locations

Every NetBox location becomes a room in deskside, with the site as building. These rooms are read-only in deskside; rename them in NetBox. A linked device without a room gets the room of its NetBox location. A room you set by hand is never overwritten. Set `import_locations: false` to keep rooms and locations separate.

## Peripherals from NetBox

If NetBox already lists monitors, printers, phones and other equipment, deskside can take them over and attach them to the right workstation:

```yaml
netbox:
  import_devices:
    roles: [Monitor, Printer, Phone, Scanner, Docking station]   # NetBox device roles to take over
    parent_pattern: '^(?P<parent>WS\d+)-'                         # "WS05-Monitor" belongs to WS05
```

For each NetBox device with one of these roles, deskside creates a device with the role as type, and manufacturer, model and serial number from NetBox. If its name matches `parent_pattern`, it is attached to the deskside device named by the `parent` group. Name, manufacturer, model and serial number stay in sync with NetBox and are read-only in deskside; type, icon, connection and notes can be changed. A parent you set by hand is never overwritten. MAC addresses recorded in NetBox for these devices are added too, so a network printer picks up its live data.

NetBox devices that already correspond to a deskside device (matched by MAC address or `name_pattern`) are not imported twice.

## What deskside writes on its own

Only two things, both switchable:

| What | When | Setting |
|---|---|---|
| The address of an IP object with status **DHCP** assigned to the device's interface | The device now uses a different DHCP address, and no other IP object in NetBox has that address | `auto.dhcp_addresses` |
| A date in the custom field `deskside_last_seen` on the interface | At most once per day per interface, and only if an admin created that field | `auto.last_seen` |

Fixed addresses (status Active or Reserved) are never touched. Every automatic change appears in deskside's event list and, as always, in NetBox's change log.

To enable "last seen", create a custom field in NetBox: name `deskside_last_seen`, type **Date**, object type **DCIM > Interface**, and make it read-only in the UI if you like. Without the field, deskside skips this part.

## What deskside only proposes

Structural changes are collected on the **NetBox** page and on the device card. Nothing changes in NetBox until an admin selects **Apply in NetBox**.

| Proposal | When |
|---|---|
| **MAC** | A MAC address seen for a device is missing on its NetBox interface. Applying creates the MAC address object and sets it as the interface's primary MAC |
| **Cable** | The device was seen on a switch port, its interface (or the front port of the patch panel its interface is cabled to) has no connection to a switch, and the switch port is free. Applying creates the cable |
| **Moved** | NetBox has a cable path to one switch port, the device was seen on another, free port. Applying moves the switch end of the last cable in the path to the new port. In a typical setup that is the patch cord between patch panel and switch |
| **Location** | The room set in deskside is a NetBox location and differs from the device's location in NetBox |

deskside does not propose a cable when:

- the device sits behind a port with many MAC addresses (an unmanaged switch, a hypervisor),
- several known devices share the same switch port (a desk switch, an IP phone with a PC behind it), because a port takes only one cable,
- the target switch port is already connected to something else.

Proposals that stop applying, because someone fixed NetBox by hand or the device moved back, are marked **Resolved** on their own. A dismissed proposal stays dismissed until the situation changes.

deskside never deletes anything in NetBox.

## Setting it up

1. Create a NetBox user for deskside and an API token for it.
   - For read-only use, the user needs view permission on DCIM devices, interfaces, MAC addresses, front ports, locations, IPAM IP addresses and extras custom fields. Set `read_only: true`.
   - To apply proposals and use the automatic updates, additionally grant change permission on DCIM interfaces, cables and devices, add permission on DCIM cables and MAC addresses, and change permission on IPAM IP addresses. No delete permission is needed.
2. Put the token in a secret file and add the section to the configuration:

```yaml
netbox:
  url: https://netbox.example.org
  token_file: /run/secrets/netbox_token
  read_only: true                     # start like this, look at the proposals, then decide
  name_pattern: '^(?P<name>WS\d+)-PC$'  # only needed if NetBox names differ from deskside names
  interval: 300
```

| Key | Default | Meaning |
|---|---|---|
| `url`, `token` | required | NetBox base URL and API token (`token_file` recommended) |
| `verify_tls` | `true` | `false` for a self-signed certificate. Prefer trusting your internal CA in the container instead |
| `read_only` | `false` | Never write: no automatic updates, proposals cannot be applied |
| `auto.dhcp_addresses` | `true` | Keep DHCP IP objects current |
| `auto.last_seen` | `true` | Write the last-seen date, if the custom field exists |
| `last_seen_field` | `deskside_last_seen` | Name of that custom field |
| `name_pattern` | whole name | Regular expression with a group `name`, applied to NetBox device names to get the deskside name. `^(?P<name>WS\d+)-PC$` links NetBox `WS09-PC` to deskside `WS09` |
| `interface_name` | | When a NetBox device has several interfaces and none carries the MAC yet, the interface with this name is used for MAC proposals |
| `import_locations` | `true` | Turn NetBox locations into deskside rooms |
| `interval` | `300` | Seconds between comparisons. Admins can also start one from the NetBox page |

## A sensible way to start

Run with `read_only: true` for a few days and look through the proposals. If they match reality, switch `read_only` off and apply them one by one. Most installations end up with a handful of proposals per week, typically after someone moved a desk or swapped a patch cord.
