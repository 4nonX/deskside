# Using deskside

## Finding a device

There is one search field, and it searches everything: device names, host names, IP addresses, MAC addresses, switch ports, rooms, departments, users, contact details (for roles allowed to see them) and the text of notes. The list narrows as you type.

A few things that help:

- **Several words narrow the result.** `lab printer` finds devices that match both words, for example a printer in a room called "Lab".
- **Partial addresses work.** `.109` finds `10.0.10.109`. MAC addresses match in any notation and from four hex digits on: `00005e`, `00-00-5E` and `00:00:5e` find the same device.
- **Ports match long and short names.** `ge7`, `gi7` and `GigabitEthernet7` all find the device on that port.
- **Keyboard:** `/` jumps to the search field, Enter opens the first result, Escape closes the card.
- The search is part of the address (`?q=...`), so a search can be bookmarked or sent to a colleague.

The filters above the list show all devices, only the ones you have named (**Known**), only addresses nobody has named yet (**Unknown**), what is **Online** right now, or only **Peripherals**. Attached devices such as monitors are left out of the plain list so it stays readable; they appear as soon as you search, and on their parent's card.

IP addresses, MAC addresses, host names and serial numbers copy themselves when you click them, in the list and on the card.

## Three ways to look at the network

The switch above the list changes the view:

- **List**: everything in one table, filtered by the search.
- **Network map**: the network as a diagram, in the order traffic flows. See [The network map](#the-network-map) below.
- **Rooms**: one tile per room with its devices, and under each device its peripherals.

## Icons

Every device type has an icon, used in the list, on cards and in the network map. deskside picks a sensible one from the type name (printer, monitor, phone, switch, …). Editors can choose a different one under **Directory > Device types**, and any single device can have its own icon in its edit dialog. The icons come from the open-source Tabler set.

## The device card

Selecting a row opens the card. The top part answers a support call at a glance; the rest sits in tabs.

At a glance:

- **Name, type, room and status** ("online since 2 h"), and the remote access buttons.
- **Pinned warnings**, for things the next person must know ("power connector is loose").
- **IP, MAC, host name and main user** as tiles. Click a tile to copy its value; the main user's phone number is a link.
- **Connection**: switch port, the patch panel port in front of it (from NetBox), a shared segment if there is one, and the device itself. Other devices on the same switch port are listed below and can be opened from there.
- **Attached devices**: monitors, printers, scanners, docking stations and the like, with how they are connected and the model. Editors can add a new one or attach an existing device.

In the tabs: **Details** (users, room and department, device data, network details per interface, remote access entries), **Notes**, **History** and **NetBox**.

**History** shows where the device was plugged in and which addresses it had, as a timeline with durations ("GigabitEthernet7, 12.10. – now, 7 days"), followed by its events. That answers "was this PC on the network last Tuesday, and where?" without digging through switch logs.

## Where a device is

The connection column, the device card and the network map name the place first and the switch port second, for example "Lab 2" with "core-sw · Port 7 · patch panel 1 F11" beneath it. The place comes from the cabling in NetBox: from the switch port through the patch panel to the device at the far end and its location. A device on a port that leads to another switch or a host is shown as "behind core-sw2". Where NetBox knows the switch but no cable on that port, deskside says "socket not documented" instead of guessing. Without NetBox, you see the switch and port.

Management ports (iLO, iDRAC, interfaces NetBox marks management-only) are never used as a device's main address or position.

## Addresses that only a DHCP lease knows

Phones and laptops with "private Wi-Fi address" turned on use a new random MAC address per network, and every one of them gets its own lease, valid for days after the device left. deskside does not list addresses that only appear in leases and were never seen in a switch or ARP table under **All**; they have their own filter, **Only in DHCP leases**, and a search still finds them. Names from reverse DNS are only used for addresses that are on the network right now, because a PTR record for a pool address often still names an earlier device.

## The network map

The map starts at the top with the Internet, the WAN device (modem, router) and the gateway. If the gateway is a virtual machine, the hypervisor carrying it stands in that place, drawn as a box with all its virtual machines: a server that runs the firewall is upstream of the LAN, not one device among many. Below it comes the switch the gateway is plugged into, then further switches, and on each switch the devices on its ports.

If NetBox knows your racks, the map draws each rack as one block, the way it looks from the front: devices in their mounting order with the unit number beside them, patch panels and shelves as thin rows, loose items (on a shelf) at the bottom. Cables between devices in the rack run along its left side. What hangs off a rack device, such as the desks on a switch, branches out to the right at the height of that device. Without rack data, the map is drawn as a tree from the Internet down.

How each line comes about:

| Line | Meaning |
|---|---|
| Thick blue | Internet connection: Internet, WAN device, gateway |
| Thick grey | Switch to switch, or gateway to switch, from NetBox cables or LLDP |
| Thin | A device on a switch port, as the switch reports it right now |
| Dashed | Behind a further switch: seen on the port that leads to an unmanaged switch |
| Dashed yellow | Derived, not documented: a switch without a documented uplink, placed where its devices are seen |
| Dotted, around the side | A management port (iLO, iDRAC, IPMI). It never decides where a device is drawn |

The map never hides a contradiction or invents a cable:

- **Shared port.** Several devices seen on one switch port that leads to no documented switch are drawn behind a "shared port" box: a small switch, a phone with a PC port or an access point sits there and is not documented yet.
- **Conflict.** If NetBox places a device somewhere the switch tables contradict (NetBox says it is on an office switch, the core switch sees it on a port that does not lead there), the device stays where NetBox puts it and is marked in yellow with where it is actually seen. The same applies to a switch whose own address appears on a different port than its documented uplink.
- **A device assigned to a workstation by name but plugged into its own switch port** (a network printer named after the desk) is drawn on its port. Only virtual machines and peripherals without a network connection of their own are drawn with their device; the dotted line for those means "assigned", not "cabled".
- **Addresses next to a known one.** Switches and access points often use a few consecutive MAC addresses. An address without an IP that differs from a known device's address only in the last byte (by up to 3) counts as that device.

Devices that hang off one switch are packed into columns along a shared line, sorted by port; switches, hypervisors and workstations with opened peripherals follow to the right as their own branches. The port and address are shown in each box. Peripherals are folded into their device (the `+3` button opens them, or **Show peripherals** opens all). More than three unknown addresses on one port become a single box you can open.

Search highlights matches and zooms to them; a virtual machine or a folded peripheral marks the box it is in. Live updates keep the view where you left it. Click any box to open the device card. **Not in the map** lists devices that no switch sees right now and that NetBox does not place either.

The map needs no configuration. If the gateway or the WAN device is not recognised from its device type, name them under `map` in the configuration, see [configuration.md](configuration.md#map).

## Events

The **Events** page lists everything deskside noticed, newest first: new and vanished devices, moves between ports, address changes, addresses outside the naming scheme, and ports that suddenly carry many devices. Filter by kind with the buttons, search the text, and load older events at the bottom. Clicking an event opens the device. Admins can have events sent to chat or e-mail, see [notifications.md](notifications.md).

What the card shows in detail:

- **Remote access** buttons: Remote Desktop, RustDesk, TeamViewer, VNC, SSH, a web interface, or whatever your admin configured. Each button has a copy icon for the ID or address. See [remote-access.md](remote-access.md) for which tool opens how.
- **Users**, with the main user first, their job title and department, and phone, mobile and e-mail as links you can click.
- **Place**: room and department.
- **Network**: for every MAC address of the device, its IP address, host name, vendor, switch and port, whether the address is fixed or from DHCP, whether it is online, and since when it has been on its current port. If a port carries many addresses, the card says so: the device then sits behind another switch or a hypervisor, and the exact port is not known.
- **Notes**, newest first, with author and time. Any note can be pinned as a warning.
- **Recent events** for the device: new, online, offline, moved, readdressed.

If a naming convention is configured, the card warns when the name does not fit or the address differs from the one the convention expects.

## Turning an unknown address into a device

Unknown addresses are in the list too, in italics. Open one and either

- **create a device**: the name field is pre-filled from the host name (in the form of your naming convention, if one matches), and the next free name is offered as an alternative; or
- **assign it to an existing device**, for example a laptop's second network card or a docking station.

From then on everything deskside learns about that address shows up on the device's card.

## The Directory page

- **Rooms**: number, name, building, floor, description. Number or name is enough.
- **Departments**: created by hand or from the directory. Departments from the directory cannot be renamed or deleted here.
- **People**: everyone who can be assigned to a device. People from the directory are read-only here; their details change in the directory and arrive with the next sync. Admins can start a sync with **Sync directory now**.

## Roles

Viewers can search and read. Editors can also change devices, notes, rooms, departments, people and assignments. Admins can also delete devices and manage accounts. Whether viewers see phone numbers and e-mail addresses is a configuration setting. Every change is recorded with user and time.
