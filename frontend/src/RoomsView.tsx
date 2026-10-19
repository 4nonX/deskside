import { useMemo } from "react";
import type { Row } from "./api";
import { t } from "./i18n";
import { Icon, useIconFor } from "./iconset";
import type { Selection } from "./fields";

/** Rooms with their devices, and under each device what is attached to it. Built from the device list. */
export function RoomsView({ rows, onOpen }: { rows: Row[]; onOpen: (s: Selection) => void }) {
  const iconFor = useIconFor();
  const { rooms, kids } = useMemo(() => {
    const devices = rows.filter((r) => r.type === "device");
    const kids = new Map<number, Row[]>();
    for (const r of devices) if (r.parent_id) kids.set(r.parent_id, [...(kids.get(r.parent_id) ?? []), r]);
    const ids = new Set(devices.map((r) => r.id));
    const tops = devices.filter((r) => !r.parent_id || !ids.has(r.parent_id));
    const rooms = new Map<string, Row[]>();
    for (const r of tops) {
      const key = r.room ?? "";
      rooms.set(key, [...(rooms.get(key) ?? []), r]);
    }
    const sorted = [...rooms.entries()].sort(([a], [b]) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b, undefined, { numeric: true })));
    return { rooms: sorted, kids };
  }, [rows]);

  const line = (r: Row, depth: number) => (
    <div key={r.id} className={`rline d${Math.min(depth, 3)}`}>
      <button className="rdev" onClick={() => onOpen({ kind: "device", id: r.id! })}>
        <Icon name={iconFor(r.kind, r.icon)} size={depth ? 15 : 18} />
        <span className={depth ? "rname small" : "rname"}>{r.name}</span>
        {r.macs.length > 0 && <span className={r.online ? "dot on" : "dot"} />}
        {!depth && r.people[0] && <span className="sub">{r.people[0]}</span>}
      </button>
      {(kids.get(r.id!) ?? []).sort((a, b) => (a.name ?? "").localeCompare(b.name ?? "")).map((c) => line(c, depth + 1))}
    </div>
  );

  if (!rooms.length) return <div className="empty">{t("list.empty")}</div>;
  return (
    <div className="rooms">
      {rooms.map(([room, devs]) => (
        <div key={room || "-"} className="room">
          <div className="room-head">
            <Icon name="door" size={18} />
            <strong>{room || t("rooms.none")}</strong>
            <span className="sub">{t("rooms.count", { n: devs.length })}</span>
          </div>
          {devs.sort((a, b) => (a.name ?? "").localeCompare(b.name ?? "", undefined, { numeric: true })).map((r) => line(r, 0))}
        </div>
      ))}
    </div>
  );
}
