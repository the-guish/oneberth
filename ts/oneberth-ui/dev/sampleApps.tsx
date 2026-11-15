// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * Two sample applications, registered as a host registers its own: each
 * with a name, a title, an icon and a loader. Tasks gives the rail a count.
 */
import { createCount, type ShellApp } from "../src";

/** The open tasks of the sample Tasks application. */
export const openTasks = createCount(null);

function Glyph({ d }: Readonly<{ d: string }>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

export const SAMPLE_APPS: readonly ShellApp[] = [
  {
    name: "notes",
    title: "Notes",
    icon: <Glyph d="M4 4h12l4 4v12H4z M8 10h8 M8 14h8" />,
    load: () => import("./NotesApp"),
  },
  {
    name: "tasks",
    title: "Tasks",
    icon: <Glyph d="M4 6h2 M10 6h10 M4 12h2 M10 12h10 M4 18h2 M10 18h10" />,
    load: () => import("./TasksApp"),
    count: openTasks,
  },
];
