// Device icons. A curated set of Tabler Icons (MIT, https://tabler.io/icons) is bundled; admins pick one per
// device type, and any device can override it. Icons are static files from the package, never user input.
import { createContext, useContext } from "react";

const files = import.meta.glob(
  "/node_modules/@tabler/icons/icons/outline/{device-desktop,device-imac,device-laptop,device-tablet,device-mobile,device-tv,device-watch,device-speaker,device-gamepad,device-floppy,device-sd-card,device-cctv,device-computer-camera,device-heart-monitor,device-desktop-analytics,device-landline-phone,printer,scan,barcode,receipt,cash-register,credit-card,id-badge-2,fingerprint,lock,key,phone,headset,microphone,camera,video,presentation,keyboard,mouse,usb,plug-connected,battery-charging,bolt,router,access-point,antenna,wifi,network,topology-star-3,topology-ring,switch-horizontal,server,server-2,database,cloud,cpu,shield-lock,wall,box,package,tool,clock,thermometer,bulb,building,home,door,armchair,desk,flask,first-aid-kit,pill,stethoscope,truck,shopping-cart,tag,file-certificate,mail,inbox,archive,cube,stack-2,circle-dot,question-mark}.svg",
  { query: "?raw", import: "default", eager: true },
) as Record<string, string>;

export const ICONS: Record<string, string> = Object.fromEntries(
  Object.entries(files).map(([path, svg]) => [path.split("/").pop()!.replace(".svg", ""), svg]),
);
export const ICON_NAMES = Object.keys(ICONS).sort();

// Readable names and search words per icon: [English, German, more search words]. Icons not listed are found by
// their file name. Labelled icons come first in pickers, since that is what people look for most.
const LABELS: Record<string, [string, string, string]> = {
  "device-desktop": ["Monitor", "Bildschirm", "display screen"],
  "device-imac": ["Desktop PC", "Arbeitsplatz-PC", "computer client workstation"],
  "device-laptop": ["Laptop", "Laptop", "notebook macbook thinkpad"],
  "device-tablet": ["Tablet", "Tablet", "ipad kiosk touch"],
  "device-mobile": ["Mobile phone", "Handy", "smartphone iphone android mobiltelefon"],
  "device-landline-phone": ["Desk phone", "Telefon", "sip voip festnetz"],
  "device-tv": ["TV", "Fernseher", "screen display"],
  "device-watch": ["Watch", "Uhr", "smartwatch"],
  "device-speaker": ["Speaker", "Lautsprecher", "audio"],
  "device-cctv": ["CCTV camera", "Überwachungskamera", "kamera ip camera"],
  "device-computer-camera": ["Webcam", "Webcam", "kamera"],
  "device-heart-monitor": ["Medical device", "Medizingerät", "monitor"],
  "phone": ["Phone", "Telefon", "handy"],
  "printer": ["Printer", "Drucker", "mfp copier kopierer"],
  "scan": ["Scanner", "Scanner", ""],
  "barcode": ["Label printer", "Etikettendrucker", "barcode"],
  "cash-register": ["Cash register", "Kasse", "pos"],
  "credit-card": ["Card terminal", "Kartenterminal", "ec payment"],
  "id-badge-2": ["Time clock", "Zeiterfassung", "terminal badge"],
  "router": ["Router", "Router", "modem"],
  "access-point": ["Access point", "Access-Point", "wlan wifi"],
  "switch-horizontal": ["Switch", "Switch", ""],
  "server": ["Server", "Server", "hypervisor"],
  "server-2": ["Server (rack)", "Server (Rack)", "domain controller"],
  "database": ["Storage", "Speicher", "nas backup"],
  "shield-lock": ["Firewall", "Firewall", "utm"],
  "cube": ["Virtual machine", "Virtuelle Maschine", "vm"],
  "plug-connected": ["Docking station", "Dockingstation", "dock"],
  "battery-charging": ["UPS", "USV", ""],
  "keyboard": ["Keyboard", "Tastatur", ""],
  "mouse": ["Mouse", "Maus", ""],
  "headset": ["Headset", "Headset", ""],
  "camera": ["Camera", "Kamera", ""],
  "presentation": ["Projector", "Beamer", "presentation"],
  "network": ["Patch panel", "Patchfeld", "network"],
};
const GERMAN = (navigator.language || "en").toLowerCase().startsWith("de");

export function iconLabel(name: string): string {
  const l = LABELS[name];
  return l ? (GERMAN ? l[1] : l[0]) : name;
}

/** All icons: the labelled ones first, in label order, then the rest by name. */
export const ICON_CHOICES = [
  ...ICON_NAMES.filter((n) => LABELS[n]).sort((a, b) => iconLabel(a).localeCompare(iconLabel(b))),
  ...ICON_NAMES.filter((n) => !LABELS[n]),
];

/** Icons whose name, label or search words contain the text. */
export function matchIcons(text: string): string[] {
  const q = text.trim().toLowerCase();
  return ICON_CHOICES.filter((n) => !q || [n, ...(LABELS[n] ?? [])].join(" ").toLowerCase().includes(q));
}

// Sensible defaults by keyword, in several languages, so a fresh install looks right before anyone configures icons.
const GUESS: [RegExp, string][] = [
  // Mobile devices first: "Smartphone", "iPhone" or "Mobiltelefon" must not end up as a desk phone.
  [/handy|mobil|smartphone|iphone|android/i, "device-mobile"],
  [/tablet|ipad|kiosk|touch/i, "device-tablet"],
  [/laptop|notebook|macbook|thinkpad/i, "device-laptop"],
  [/monitor|bildschirm|display|screen/i, "device-desktop"],
  [/client|workstation|arbeitsplatz|desktop|pc\b/i, "device-imac"],
  [/label|etikett|dymo|zebra/i, "barcode"],
  [/drucker|printer|mfp|bizhub|kopierer|copier/i, "printer"],
  [/scan/i, "scan"],
  [/telefon|phone|sip/i, "device-landline-phone"],
  [/access.?point|\bap\b|wlan|wifi/i, "access-point"],
  [/switch/i, "switch-horizontal"],
  [/router|modem/i, "router"],
  [/firewall|utm/i, "shield-lock"],
  [/hypervisor|server/i, "server"],
  [/domain.?controller|directory/i, "server-2"],
  [/vm|virtual|test.?umgebung|test.?environment/i, "cube"],
  [/nas|storage|backup/i, "database"],
  [/dock/i, "plug-connected"],
  [/usv|ups/i, "battery-charging"],
  [/kamera|camera|webcam/i, "camera"],
  [/zeiterfassung|time.?clock|terminal/i, "id-badge-2"],
  [/kasse|cash|pos\b/i, "cash-register"],
  [/patch/i, "network"],
  [/tastatur|keyboard/i, "keyboard"],
  [/maus|mouse/i, "mouse"],
  [/headset/i, "headset"],
];

export function guessIcon(kind: string | null | undefined): string {
  const hit = GUESS.find(([rx]) => rx.test(kind ?? ""));
  return hit ? hit[1] : "box";
}

/** Kind -> icon as configured by admins; provided once at the top of the app. */
export const KindIcons = createContext<Record<string, string>>({});

export function useIconFor() {
  const kinds = useContext(KindIcons);
  return (kind: string | null | undefined, own?: string | null, unknown = false): string =>
    (own && ICONS[own] ? own : "") || (kind && kinds[kind] && ICONS[kinds[kind]] ? kinds[kind] : "") ||
    (unknown ? "question-mark" : guessIcon(kind));
}

export function Icon({ name, size = 18, title }: { name: string; size?: number; title?: string }) {
  const svg = (ICONS[name] ?? ICONS["box"]).replace(/width="24"/, `width="${size}"`).replace(/height="24"/, `height="${size}"`)
    .replace(/stroke-width="2"/, 'stroke-width="1.6"');
  return <span className="dicon" title={title} aria-hidden={title ? undefined : true} dangerouslySetInnerHTML={{ __html: svg }} />;
}
