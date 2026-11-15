/*
 * Icon path data copied from lucide-react 1.61.0 (ISC, and MIT for the icons
 * lucide derives from Feather; see LICENSE.lucide beside this file). Data,
 * not code: each entry is the SVG child elements of one icon, with lucide's
 * React keys dropped. The entries were taken from Robinauts'
 * frontend/src/icons/lucide.ts, which records the source in its
 * docs/legal/ip-clearance.md, 2026-11-04. Nothing here is edited.
 */
export type IconNode = readonly (readonly [string, Readonly<Record<string, string>>])[];

export const LUCIDE: Readonly<Record<string, IconNode>> = {
  "log-out": [
    ["path", { d: "m16 17 5-5-5-5" }],
    ["path", { d: "M21 12H9" }],
    ["path", { d: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" }],
  ],
  menu: [
    ["path", { d: "M4 5h16" }],
    ["path", { d: "M4 12h16" }],
    ["path", { d: "M4 19h16" }],
  ],
  monitor: [
    ["rect", { width: "20", height: "14", x: "2", y: "3", rx: "2" }],
    ["line", { x1: "8", x2: "16", y1: "21", y2: "21" }],
    ["line", { x1: "12", x2: "12", y1: "17", y2: "21" }],
  ],
  moon: [
    [
      "path",
      {
        d: "M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401",
      },
    ],
  ],
  sun: [
    ["circle", { cx: "12", cy: "12", r: "4" }],
    ["path", { d: "M12 2v2" }],
    ["path", { d: "M12 20v2" }],
    ["path", { d: "m4.93 4.93 1.41 1.41" }],
    ["path", { d: "m17.66 17.66 1.41 1.41" }],
    ["path", { d: "M2 12h2" }],
    ["path", { d: "M20 12h2" }],
    ["path", { d: "m6.34 17.66-1.41 1.41" }],
    ["path", { d: "m19.07 4.93-1.41 1.41" }],
  ],
  x: [
    ["path", { d: "M18 6 6 18" }],
    ["path", { d: "m6 6 12 12" }],
  ],
};
