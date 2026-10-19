import { t } from "./i18n";

/** Where a switch port leads by the cabling documented in NetBox. */
export interface PortPlace {
  documented: boolean; panel?: string | null; endpoint?: string | null; room?: string | null;
  switch?: boolean;            // the port leads to another switch
}

/** "GigabitEthernet7", "GE7", "Gi1/0/7" and "port7" all read as "Port 7"; 10G ports as "10G port 1". */
export function portName(port: string | null | undefined): string {
  if (!port) return "";
  const ten = port.match(/^(?:TenGigabitEthernet|XGE|Te)\s*([\d/]+)$/i);
  if (ten) return t("place.port10g", { n: ten[1] });
  const m = port.match(/^(?:GigabitEthernet|FastEthernet|Ethernet|GE|Gi|Fa|Eth|port)\s*([\d/]+)$/i);
  return m ? t("place.port", { n: m[1] }) : port;
}

/**
 * The place of a switch port in words: the workstation or room it leads to first, the switch port second.
 * `self` is the device being shown, so a PC is not described as being "at" itself.
 */
export function where(sw: string | null | undefined, port: string | null | undefined, place?: PortPlace | null,
                      self?: string | null, alias?: string | null, behind = false): { main: string; sub: string } {
  const switchPort = [sw, portName(port)].filter(Boolean).join(" · ");
  const extra = alias ? [alias] : [];
  // Seen on a port that leads to another switch or a host: the port's far end is not where the device is.
  if ((behind || place?.switch) && place?.documented && place.endpoint && place.endpoint.toLowerCase() !== (self ?? "").toLowerCase()) {
    return { main: t("place.behind", { name: place.endpoint }), sub: [switchPort, ...extra].join(" · ") };
  }
  if (place?.documented) {
    const at = place.endpoint && place.endpoint.toLowerCase() !== (self ?? "").toLowerCase()
      ? t("place.at", { name: place.endpoint }) : "";
    const main = [at, place.room].filter(Boolean).join(" · ");
    if (main) return { main, sub: [switchPort, place.panel, ...extra].filter(Boolean).join(" · ") };
    return { main: switchPort, sub: [place.panel, ...extra].filter(Boolean).join(" · ") };
  }
  if (place && !place.documented) return { main: switchPort, sub: [t("place.unknown"), ...extra].join(" · ") };
  return { main: switchPort, sub: extra.join(" · ") };
}
