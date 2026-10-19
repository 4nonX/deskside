import { useEffect, useState } from "react";
import { api, type DeviceCard, type RemoteEntry, type RemoteTool } from "./api";
import { t } from "./i18n";
import { IconCopy, IconLink, IconPlus } from "./icons";

type Wrap = (fn: () => Promise<unknown>) => () => Promise<void>;

function copyText(text: string) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const ta = document.createElement("textarea");
  ta.value = text; document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); } finally { ta.remove(); }
  return Promise.resolve();
}

function RemoteButton({ e }: { e: RemoteEntry }) {
  const [copied, setCopied] = useState(false);
  const title = [e.tool_label, e.label, e.value].filter(Boolean).join(" · ");
  const text = e.label ? `${e.tool_label} (${e.label})` : e.tool_label;
  return (
    <span className="remote">
      {e.download ? (
        <a className="btn" href={e.download} download title={title}><IconLink /> {text}</a>
      ) : e.href ? (
        <a className="btn" href={e.href} title={title}><IconLink /> {text}</a>
      ) : (
        <span className="btn static" title={title}>{text}</span>
      )}
      {e.copy && (
        <button className="icon" title={copied ? t("remote.copied") : t("remote.copy", { value: e.copy })}
                onClick={() => copyText(e.copy!).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); })}>
          <IconCopy />{copied && <span className="copied">{t("remote.copied")}</span>}
        </button>
      )}
    </span>
  );
}

export function RemoteSection({ d, canEdit, wrap }: { d: DeviceCard; canEdit: boolean; wrap: Wrap }) {
  const [tools, setTools] = useState<RemoteTool[]>([]);
  const [adding, setAdding] = useState(false);
  const [tool, setTool] = useState("");
  const [value, setValue] = useState("");
  const [username, setUsername] = useState("");
  const [label, setLabel] = useState("");
  useEffect(() => { if (canEdit) api.remoteTools().then(setTools).catch(() => undefined); }, [canEdit]);
  const sel = tools.find((x) => x.key === tool);
  if (!d.remote.length && !canEdit) return null;
  return (
    <section>
      <h3>{t("remote.title")}</h3>
      <div className="remote-row">
        {d.remote.map((e) => <RemoteButton key={`${e.tool}:${e.id ?? "auto"}`} e={e} />)}
        {!d.remote.length && <span className="muted">{t("remote.none")}</span>}
      </div>
      {canEdit && d.remote.some((e) => e.id !== null) && (
        <ul className="plain remote-list">
          {d.remote.filter((e) => e.id !== null).map((e) => (
            <li key={e.id}>
              <span>{e.tool_label}{e.label ? ` (${e.label})` : ""}</span>
              <span className="mono sub">{[e.username, e.value].filter(Boolean).join(" @ ")}</span>
              <button className="link danger" onClick={wrap(() => api.deleteRemote(e.id!))}>{t("card.remove")}</button>
            </li>
          ))}
        </ul>
      )}
      {canEdit && !adding && <button className="link" onClick={() => setAdding(true)}><IconPlus /> {t("remote.add")}</button>}
      {canEdit && adding && (
        <form className="remote-form" onSubmit={(ev) => {
          ev.preventDefault();
          wrap(async () => {
            await api.addRemote(d.id, { tool, value, username, label });
            setAdding(false); setTool(""); setValue(""); setUsername(""); setLabel("");
          })();
        }}>
          <select value={tool} onChange={(e) => setTool(e.target.value)}>
            <option value="">{t("remote.tool")}</option>
            {tools.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
          </select>
          {sel && (
            <>
              <input className="mono" value={value} onChange={(e) => setValue(e.target.value)}
                     placeholder={sel.needs === "id" ? t("remote.id") : t("remote.address")} />
              {sel.needs === "address" && <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder={t("remote.user")} />}
              <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t("remote.label")} />
            </>
          )}
          <div className="row-actions">
            <button className="primary" disabled={!sel || (sel.needs === "id" && !value.trim())}>{t("dir.save")}</button>
            <button type="button" onClick={() => setAdding(false)}>{t("dir.cancel")}</button>
          </div>
          {sel?.launch === "copy" && <div className="muted">{t("remote.copyonly", { tool: sel.label })}</div>}
        </form>
      )}
    </section>
  );
}
