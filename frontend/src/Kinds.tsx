import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type KindItem } from "./api";
import { t } from "./i18n";
import { ICON_NAMES, Icon, useIconFor } from "./iconset";

/** Device types and their icons. Picking an icon applies to every device of that type. */
export function KindsEditor({ canEdit, onChanged }: { canEdit: boolean; onChanged: () => void }) {
  const iconFor = useIconFor();
  const [kinds, setKinds] = useState<KindItem[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const load = useCallback(() => api.kinds().then(setKinds).catch(() => undefined), []);
  useEffect(() => { load(); }, [load]);
  const pick = async (kind: string, icon: string) => {
    try { await api.setKindIcon(kind, icon); await load(); onChanged(); setOpen(null); }
    catch (e) { alert(t("err.generic", { msg: e instanceof ApiError ? e.message : String(e) })); }
  };
  if (!kinds.length) return <div className="empty">{t("kinds.empty")}</div>;
  return (
    <>
      <p className="muted">{t("kinds.hint")}</p>
      <div className="kinds">
        {kinds.map((k) => (
          <div key={k.kind} className="kind">
            <button className="kind-icon" disabled={!canEdit} title={canEdit ? t("kinds.change") : undefined}
                    onClick={() => { setOpen(open === k.kind ? null : k.kind); setFilter(""); }}>
              <Icon name={iconFor(k.kind)} size={24} />
            </button>
            <div>
              <div className="kind-name">{k.kind}</div>
              <div className="sub">{t("kinds.devices", { n: k.devices })}{k.icon ? "" : ` · ${t("kinds.auto")}`}</div>
            </div>
            {open === k.kind && (
              <div className="icon-picker">
                <div className="inline">
                  <input autoFocus value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t("kinds.search")} />
                  {k.icon && <button onClick={() => pick(k.kind, "")}>{t("kinds.reset")}</button>}
                </div>
                <div className="icon-grid">
                  {ICON_NAMES.filter((n) => !filter || n.includes(filter.toLowerCase())).map((n) => (
                    <button key={n} className={n === k.icon ? "icon-choice active" : "icon-choice"} title={n} onClick={() => pick(k.kind, n)}>
                      <Icon name={n} size={22} />
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
