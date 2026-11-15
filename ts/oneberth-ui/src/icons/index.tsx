// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The shell's icons: inline SVG over path data copied from lucide
 * (`./lucide.ts`). An icon is decorative: the control around it carries the
 * name. Sized by the class the caller gives it.
 */
import type { JSX, SVGProps } from "react";

import { LUCIDE } from "./lucide";

export type IconProps = Omit<SVGProps<SVGSVGElement>, "children">;

function icon(name: string) {
  const node = LUCIDE[name] ?? [];
  function Icon({ className, ...rest }: Readonly<IconProps>) {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        width="16"
        height="16"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={className === undefined ? "oneberth-icon" : `oneberth-icon ${className}`}
        aria-hidden="true"
        focusable="false"
        {...rest}
      >
        {node.map(([tag, attrs], at) => {
          const Tag = tag as keyof JSX.IntrinsicElements;
          return <Tag key={at} {...attrs} />;
        })}
      </svg>
    );
  }
  Icon.displayName = `Icon(${name})`;
  return Icon;
}

export const LogOutIcon = icon("log-out");
export const MenuIcon = icon("menu");
export const MonitorIcon = icon("monitor");
export const MoonIcon = icon("moon");
export const SunIcon = icon("sun");
export const XIcon = icon("x");
