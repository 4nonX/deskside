// Thin client for the deskside API. Every call goes through `request` so errors look the same everywhere.

export type Role = "viewer" | "editor" | "admin";
export interface Me { username: string; role: Role; version: string }

export interface NetInfo {
  mac?: string | null;
  ip?: string | null;
  hostname?: string | null;
  hostname_source?: string | null;
  vendor?: string | null;
  switch?: string | null;
  port?: string | null;
  vlan?: number | null;
  port_alias?: string | null;
  port_mac_count?: number | null;
  behind_uplink?: boolean;
  dhcp?: boolean;
  online: boolean;
  first_seen?: number;
  last_seen?: number | null;
  port_since?: number | null;
  sources?: string[];
}

export interface Row extends NetInfo {
  type: "device" | "unknown";
  id: number | null;
  name: string | null;
  kind: string;
  macs: string[];
  pinned: string[];
  room: string | null;
  department: string | null;
  people: string[];
  icon: string;
  parent_id: number | null;
  parent: string | null;
  children: number;
  manufacturer?: string;
  model?: string;
  connection?: string;
  source?: string;
}

export interface DeviceBrief { id: number; name: string; kind: string; icon: string }
export interface Peripheral extends DeviceBrief { connection: string; manufacturer: string; model: string; serial: string; children: number }
export interface SegmentPeer { type: "device" | "unknown"; id?: number; name: string | null; kind?: string; icon?: string; mac?: string; ip?: string | null; vendor?: string | null }
export interface Segment {
  switch: string; port: string; alias: string | null; port_mac_count: number | null; behind_uplink: boolean;
  online: boolean; peers: SegmentPeer[];
}
export interface KindItem { kind: string; icon: string; devices: number }
export interface MapNode {
  type: "device" | "unknown"; id?: number; mac?: string; name: string | null; kind?: string; icon?: string;
  connection?: string; ip?: string | null; vendor?: string | null; online?: boolean; children: MapNode[];
}
export interface MapPort { port: string; alias: string | null; uplink: boolean; macs: number; shared: boolean; items: MapNode[] }
export interface Topology { switches: { name: string; ports: MapPort[] }[]; unplaced: MapNode[] }

export interface Room { id: number; number: string; name: string; building: string; floor: string; description: string; devices?: number; source?: string }
export type RoomInput = Omit<Room, "id" | "devices" | "source">;
export interface Department { id: number; name: string; description: string; source: string; devices?: number; people?: number }
export interface Person {
  id: number; display_name: string; username: string; title: string; department: string | null; department_id: number | null;
  source: string; active: boolean; email?: string; phone?: string; mobile?: string; chat?: string; devices?: number;
}
export interface PersonInput {
  display_name: string; username: string; email: string; phone: string; mobile: string; chat: string; title: string;
  department_id: number | null;
}
export interface PersonLink extends Person { link_id: number; primary: boolean }
export interface RemoteTool { key: string; label: string; needs: "id" | "address"; launch: "link" | "rdp" | "copy" }
export interface RemoteEntry {
  id: number | null; tool: string; tool_label: string; label: string; value: string; username: string;
  href: string | null; download: string | null; copy: string | null; needs: string; automatic: boolean;
}
export interface ProposalItem {
  id: number; kind: string; summary: string; display?: Record<string, string>; status: string; error?: string;
  device_id?: number | null;
  device?: string | null; mac?: string | null; created_at?: number; updated_at: number; decided_by?: string;
}
export interface NetboxInfo {
  id: number; name: string; url: string; location: string | null;
  interfaces: { name: string; macs: string[]; endpoint: string | null; via: string | null }[];
}
export interface HistoryItem { kind: "port" | "ip"; mac: string; switch: string | null; value: string; start: number; end: number | null }
export interface Convention { key: string; pattern: string; kind: string; ip: string | null; next: string }

export interface Note { id: number; text: string; pinned: boolean; author: string; created_at: number; updated_at: number }
export interface EventItem { id?: number; ts: number; kind: string; message: string; mac?: string | null; device_id?: number | null }
export interface DeviceInterface extends NetInfo { id: number; mac: string; label: string; expected_ip: string | null }
export interface DeviceCard {
  type: "device"; id: number; name: string; kind: string; description: string;
  created_at: number; updated_at: number;
  room: Room | null; department: { id: number; name: string } | null; people: PersonLink[];
  icon: string; manufacturer: string; model: string; serial: string; connection: string; source: string;
  parent: DeviceBrief | null; children: Peripheral[]; segment: Segment | null;
  contacts_visible: boolean; naming_warnings: string[]; remote: RemoteEntry[];
  netbox: NetboxInfo | null; netbox_writable: boolean; proposals: ProposalItem[];
  interfaces: DeviceInterface[]; notes: Note[]; events: EventItem[];
}
export interface UnknownCard extends NetInfo { type: "unknown"; mac: string; events: EventItem[]; suggested_name: string | null }
export interface SourceState {
  name: string; type: string; interval: number; last_run: number | null; last_ok: number | null;
  duration: number | null; error: string | null; counts: Record<string, number>;
}
export interface SourcesInfo { last_merge: number | null; sources: SourceState[]; suspect_ports: { switch: string; port: string; macs: number }[] }
export interface UserItem { id: number; username: string; role: Role; last_login: number | null }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "deskside" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, {
    method, headers, credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const data = await res.json();
      msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch { /* keep status text */ }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => request<Me>("GET", "/me"),
  login: (username: string, password: string) => request<Me>("POST", "/login", { username, password }),
  logout: () => request<{ ok: boolean }>("POST", "/logout", {}),
  devices: (q: string, show: string) =>
    request<{ total: number; rows: Row[] }>("GET", `/devices?q=${encodeURIComponent(q)}&show=${show}`),
  device: (id: number) => request<DeviceCard>("GET", `/devices/${id}`),
  mac: (mac: string) => request<UnknownCard | { type: "redirect"; device_id: number }>("GET", `/macs/${encodeURIComponent(mac)}`),
  createDevice: (b: { name: string; kind?: string; mac?: string; parent_id?: number; connection?: string;
    manufacturer?: string; model?: string; serial?: string }) => request<{ id: number }>("POST", "/devices", b),
  updateDevice: (id: number, b: Partial<{ name: string; kind: string; description: string; room_id: number;
    department_id: number; parent_id: number; connection: string; manufacturer: string; model: string; serial: string;
    icon: string; clear: ("room" | "department" | "parent")[] }>) => request("PATCH", `/devices/${id}`, b),
  kinds: () => request<KindItem[]>("GET", "/kinds"),
  setKindIcon: (kind: string, icon: string) => request("PUT", `/kinds/${encodeURIComponent(kind)}`, { icon }),
  topology: () => request<Topology>("GET", "/topology"),
  rooms: () => request<Room[]>("GET", "/rooms"),
  createRoom: (b: RoomInput) => request<{ id: number }>("POST", "/rooms", b),
  updateRoom: (id: number, b: RoomInput) => request("PATCH", `/rooms/${id}`, b),
  deleteRoom: (id: number) => request("DELETE", `/rooms/${id}`),
  departments: () => request<Department[]>("GET", "/departments"),
  createDepartment: (b: { name: string; description: string }) => request<{ id: number }>("POST", "/departments", b),
  updateDepartment: (id: number, b: { name: string; description: string }) => request("PATCH", `/departments/${id}`, b),
  deleteDepartment: (id: number) => request("DELETE", `/departments/${id}`),
  people: (q = "", inactive = false) =>
    request<Person[]>("GET", `/people?q=${encodeURIComponent(q)}&include_inactive=${inactive}`),
  createPerson: (b: PersonInput) => request<{ id: number }>("POST", "/people", b),
  updatePerson: (id: number, b: PersonInput) => request("PATCH", `/people/${id}`, b),
  deletePerson: (id: number) => request("DELETE", `/people/${id}`),
  linkPerson: (deviceId: number, personId: number) => request("POST", `/devices/${deviceId}/people`, { person_id: personId }),
  setPrimary: (linkId: number) => request("PATCH", `/device-people/${linkId}`, { primary: true }),
  unlinkPerson: (linkId: number) => request("DELETE", `/device-people/${linkId}`),
  naming: () => request<Convention[]>("GET", "/naming"),
  proposals: (status: string) =>
    request<{ configured: boolean; read_only: boolean; rows: ProposalItem[] }>("GET", `/proposals?status=${status}`),
  applyProposal: (id: number) => request("POST", `/proposals/${id}/apply`, {}),
  dismissProposal: (id: number) => request("POST", `/proposals/${id}/dismiss`, {}),
  netboxSync: () => request("POST", "/netbox/sync", {}),
  remoteTools: () => request<RemoteTool[]>("GET", "/remote-tools"),
  addRemote: (deviceId: number, b: { tool: string; value: string; username: string; label: string }) =>
    request("POST", `/devices/${deviceId}/remote`, b),
  deleteRemote: (id: number) => request("DELETE", `/remote/${id}`),
  directorySync: () => request<{ ok: boolean; error: string | null }>("POST", "/directory/sync", {}),
  deleteDevice: (id: number) => request("DELETE", `/devices/${id}`),
  addInterface: (id: number, mac: string, label = "") => request("POST", `/devices/${id}/interfaces`, { mac, label }),
  removeInterface: (id: number) => request("DELETE", `/interfaces/${id}`),
  addNote: (id: number, text: string, pinned: boolean) => request("POST", `/devices/${id}/notes`, { text, pinned }),
  updateNote: (id: number, b: Partial<{ text: string; pinned: boolean }>) => request("PATCH", `/notes/${id}`, b),
  deleteNote: (id: number) => request("DELETE", `/notes/${id}`),
  events: (o: { limit?: number; kind?: string; q?: string; before?: number; deviceId?: number } = {}) => {
    const p = new URLSearchParams({ limit: String(o.limit ?? 200) });
    if (o.kind) p.set("kind", o.kind);
    if (o.q) p.set("q", o.q);
    if (o.before) p.set("before", String(o.before));
    if (o.deviceId) p.set("device_id", String(o.deviceId));
    return request<EventItem[]>("GET", `/events?${p}`);
  },
  history: (deviceId: number) => request<HistoryItem[]>("GET", `/history?device_id=${deviceId}`),
  testNotifications: () => request<{ name: string; ok: boolean; error: string | null }[]>("POST", "/notifications/test", {}),
  sources: () => request<SourcesInfo>("GET", "/sources"),
  users: () => request<UserItem[]>("GET", "/users"),
  createUser: (b: { username: string; password: string; role: Role }) => request("POST", "/users", b),
  updateUser: (id: number, b: Partial<{ password: string; role: Role }>) => request("PATCH", `/users/${id}`, b),
  deleteUser: (id: number) => request("DELETE", `/users/${id}`),
};

/** Subscribe to live updates. Returns a function that closes the stream. */
export function subscribe(onMessage: (msg: { type: string }) => void): () => void {
  const es = new EventSource("/api/stream");
  es.onmessage = (ev) => {
    try { onMessage(JSON.parse(ev.data)); } catch { /* ignore malformed */ }
  };
  return () => es.close();
}
