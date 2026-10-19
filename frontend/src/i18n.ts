// Interface texts. Add a language by copying the "en" block; missing keys fall back to English.

const en = {
  "app.search": "Search name, IP, MAC, port, note …",
  "app.devices": "Devices", "app.events": "Events", "app.sources": "Sources", "app.users": "Users",
  "app.signout": "Sign out", "app.live": "Live", "app.offline": "Connection lost, retrying",
  "filter.all": "All", "filter.known": "Known", "filter.unknown": "Unknown", "filter.online": "Online",
  "list.count": "{shown} of {total}", "list.empty": "Nothing matches.", "list.unnamed": "Unknown device",
  "col.name": "Name", "col.ip": "IP address", "col.mac": "MAC address", "col.location": "Location", "col.seen": "Status",
  "status.online": "online", "status.offline": "offline", "status.since": "since {t}", "status.lastseen": "last seen {t}",
  "status.never": "not seen yet",
  "login.title": "Sign in", "login.user": "User name", "login.password": "Password", "login.submit": "Sign in",
  "card.close": "Close", "card.network": "Network", "card.notes": "Notes", "card.history": "Recent events",
  "card.rename": "Rename", "card.save": "Save", "card.cancel": "Cancel", "card.kind": "Type", "card.description": "Description",
  "card.mac": "MAC address", "card.ip": "IP address", "card.hostname": "Host name", "card.vendor": "Vendor",
  "card.port": "Switch port", "card.vlan": "VLAN", "card.addressing": "Addressing", "card.dhcp": "DHCP",
  "card.fixed": "fixed or reserved", "card.sources": "Seen by", "card.firstseen": "First seen", "card.portsince": "On this port since",
  "card.behind": "This port carries {n} MAC addresses. The device is probably behind another switch or a hypervisor, so the exact port is unknown.",
  "card.nointerfaces": "No MAC address assigned yet.",
  "card.addmac": "Add MAC address", "card.removemac": "Remove", "card.delete": "Delete device",
  "card.deleteconfirm": "Delete {name}? Notes are deleted too. Live data stays.",
  "card.unknown": "Not assigned to a device yet.",
  "card.create": "Create device", "card.assign": "Assign to existing device", "card.assignsearch": "Search device …",
  "note.add": "Add note", "note.placeholder": "What should the next person know?", "note.pin": "Pin as warning",
  "note.pinned": "Pinned", "note.unpin": "Unpin", "note.delete": "Delete", "note.by": "{author}, {t}",
  "events.empty": "No events yet.",
  "sources.title": "Data sources", "sources.ok": "OK", "sources.error": "Error", "sources.never": "not run yet",
  "sources.lastok": "Last success {t}", "sources.every": "every {n} s", "sources.took": "took {n} s",
  "sources.busy": "Ports with many MAC addresses",
  "sources.busyhint": "More addresses than the threshold, and no known neighbour. Usually an unmanaged switch, a hypervisor or a docking station.",
  "users.title": "Users", "users.add": "Add user", "users.role": "Role", "users.lastlogin": "Last sign-in",
  "users.password": "New password (at least 12 characters)", "users.delete": "Delete", "users.never": "never",
  "users.setpassword": "Set password",
  "role.viewer": "Viewer", "role.editor": "Editor", "role.admin": "Admin",
  "time.now": "just now", "time.min": "{n} min ago", "time.h": "{n} h ago", "time.d": "{n} d ago",
  "err.generic": "Something went wrong: {msg}",
};

type Key = keyof typeof en;

const de: Partial<Record<Key, string>> = {
  "app.search": "Name, IP, MAC, Port, Notiz suchen …",
  "app.devices": "Geräte", "app.events": "Ereignisse", "app.sources": "Quellen", "app.users": "Benutzer",
  "app.signout": "Abmelden", "app.live": "Live", "app.offline": "Verbindung unterbrochen, neuer Versuch",
  "filter.all": "Alle", "filter.known": "Bekannt", "filter.unknown": "Unbekannt", "filter.online": "Online",
  "list.count": "{shown} von {total}", "list.empty": "Keine Treffer.", "list.unnamed": "Unbekanntes Gerät",
  "col.name": "Name", "col.ip": "IP-Adresse", "col.mac": "MAC-Adresse", "col.location": "Anschluss", "col.seen": "Status",
  "status.online": "online", "status.offline": "offline", "status.since": "seit {t}", "status.lastseen": "zuletzt {t}",
  "status.never": "noch nicht gesehen",
  "login.title": "Anmelden", "login.user": "Benutzername", "login.password": "Passwort", "login.submit": "Anmelden",
  "card.close": "Schließen", "card.network": "Netzwerk", "card.notes": "Anmerkungen", "card.history": "Letzte Ereignisse",
  "card.rename": "Umbenennen", "card.save": "Speichern", "card.cancel": "Abbrechen", "card.kind": "Typ", "card.description": "Beschreibung",
  "card.mac": "MAC-Adresse", "card.ip": "IP-Adresse", "card.hostname": "Hostname", "card.vendor": "Hersteller",
  "card.port": "Switch-Port", "card.vlan": "VLAN", "card.addressing": "Adressvergabe", "card.dhcp": "DHCP",
  "card.fixed": "fest oder reserviert", "card.sources": "Gesehen von", "card.firstseen": "Zuerst gesehen", "card.portsince": "An diesem Port seit",
  "card.behind": "An diesem Port hängen {n} MAC-Adressen. Das Gerät sitzt vermutlich hinter einem weiteren Switch oder einem Hypervisor, der genaue Port ist daher unbekannt.",
  "card.nointerfaces": "Noch keine MAC-Adresse zugeordnet.",
  "card.addmac": "MAC-Adresse hinzufügen", "card.removemac": "Entfernen", "card.delete": "Gerät löschen",
  "card.deleteconfirm": "{name} löschen? Die Anmerkungen werden mitgelöscht. Live-Daten bleiben erhalten.",
  "card.unknown": "Noch keinem Gerät zugeordnet.",
  "card.create": "Gerät anlegen", "card.assign": "Vorhandenem Gerät zuordnen", "card.assignsearch": "Gerät suchen …",
  "note.add": "Anmerkung hinzufügen", "note.placeholder": "Was sollte die nächste Person wissen?", "note.pin": "Als Warnung anheften",
  "note.pinned": "Angeheftet", "note.unpin": "Lösen", "note.delete": "Löschen", "note.by": "{author}, {t}",
  "events.empty": "Noch keine Ereignisse.",
  "sources.title": "Datenquellen", "sources.ok": "OK", "sources.error": "Fehler", "sources.never": "noch nicht gelaufen",
  "sources.lastok": "Zuletzt erfolgreich {t}", "sources.every": "alle {n} s", "sources.took": "Dauer {n} s",
  "sources.busy": "Ports mit vielen MAC-Adressen",
  "sources.busyhint": "Mehr Adressen als der Schwellwert und kein bekannter Nachbar. Meist ein nicht verwalteter Switch, ein Hypervisor oder eine Dockingstation.",
  "users.title": "Benutzer", "users.add": "Benutzer anlegen", "users.role": "Rolle", "users.lastlogin": "Letzte Anmeldung",
  "users.password": "Neues Passwort (mindestens 12 Zeichen)", "users.delete": "Löschen", "users.never": "nie",
  "users.setpassword": "Passwort setzen",
  "role.viewer": "Lesen", "role.editor": "Bearbeiten", "role.admin": "Admin",
  "time.now": "gerade eben", "time.min": "vor {n} Min.", "time.h": "vor {n} Std.", "time.d": "vor {n} Tagen",
  "err.generic": "Das hat nicht geklappt: {msg}",
};

const tables: Record<string, Partial<Record<Key, string>>> = { en, de };
const lang = (navigator.language || "en").slice(0, 2).toLowerCase();
const table = tables[lang] ?? en;
export const locale = tables[lang] ? navigator.language : "en";

export function t(key: Key, vars: Record<string, string | number> = {}): string {
  const s = table[key] ?? en[key];
  return s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
}

export function ago(ts: number | null | undefined): string {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return t("time.now");
  if (s < 3600) return t("time.min", { n: Math.floor(s / 60) });
  if (s < 86400) return t("time.h", { n: Math.floor(s / 3600) });
  return t("time.d", { n: Math.floor(s / 86400) });
}

export function datetime(ts: number | null | undefined): string {
  return ts ? new Date(ts * 1000).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" }) : "";
}
