// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The theme toggle on the rail: one button that goes from the operating
 * system's theme to light, to dark, and back (shell.md, "Styles").
 */
import { useState } from "react";

import { MonitorIcon, MoonIcon, SunIcon } from "./icons";
import { applyTheme, nextTheme, rememberedTheme, THEME_LABELS, type Theme } from "./theme";

const ICONS = { system: MonitorIcon, light: SunIcon, dark: MoonIcon } as const;

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(rememberedTheme);
  const Icon = ICONS[theme];
  const next = nextTheme(theme);
  const label = `Theme: ${THEME_LABELS[theme]}. Change to ${THEME_LABELS[next]}`;
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={() => {
        applyTheme(next);
        setTheme(next);
      }}
      className="oneberth-rail-button"
      data-theme-choice={theme}
    >
      <Icon className="oneberth-rail-icon" />
    </button>
  );
}
