// Small stroke icons, 16x16, drawn in currentColor.
import type { JSX } from "react";

const base = { width: 16, height: 16, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor",
  strokeWidth: 1.5, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };

export const IconSearch = (): JSX.Element => <svg {...base}><circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5 14 14" /></svg>;
export const IconClose = (): JSX.Element => <svg {...base}><path d="M4 4l8 8M12 4l-8 8" /></svg>;
export const IconPin = (): JSX.Element => <svg {...base}><path d="M6 2h4l-.5 4 2.5 2.5H4L6.5 6z" /><path d="M8 8.5V14" /></svg>;
export const IconWarn = (): JSX.Element => <svg {...base}><path d="M8 2 1.5 13.5h13z" /><path d="M8 6.5v3.5M8 12v.01" /></svg>;
export const IconTrash = (): JSX.Element => <svg {...base}><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.5 9h6l.5-9" /></svg>;
export const IconEdit = (): JSX.Element => <svg {...base}><path d="M10.5 2.5l3 3L6 13H3v-3z" /></svg>;
export const IconPlus = (): JSX.Element => <svg {...base}><path d="M8 3v10M3 8h10" /></svg>;
export const IconPort = (): JSX.Element => <svg {...base}><rect x="2.5" y="4" width="11" height="8" rx="1" /><path d="M5.5 12V9.5h5V12M6.5 9.5V8M9.5 9.5V8" /></svg>;
export const IconLink = (): JSX.Element => <svg {...base}><path d="M6.5 9.5l3-3M7 4.5l1-1a2.5 2.5 0 0 1 3.5 3.5l-1 1M9 11.5l-1 1A2.5 2.5 0 0 1 4.5 9l1-1" /></svg>;
