// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * Linked devices, at `#/account/devices` (identity.md, "Device pairing").
 *
 * The person's devices, each with **Remove**, and **Link a phone**, which
 * opens the pairing dialog.
 */
import { useCallback, useId, useState } from "react";

import type { Session } from "../session";
import { listDevices, platformName, removeDevice, useListed, type Device } from "./account";
import { LinkDialog } from "./LinkDialog";
import { EndButton, Items, When } from "./parts";

export const NO_DEVICES_LINKED = "No device is linked.";

export function DevicesPage({ session }: Readonly<{ session: Session }>) {
  const [round, setRound] = useState(0);
  const devices = useListed(listDevices, round);
  const [linking, setLinking] = useState(false);
  const refresh = useCallback(() => {
    setRound((count) => count + 1);
  }, []);
  const close = useCallback(() => {
    setLinking(false);
  }, []);
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="oneberth-account-section">
      <div className="oneberth-account-head">
        <h1 id={headingId} className="oneberth-account-title">
          Linked devices
        </h1>
        <button
          type="button"
          onClick={() => {
            setLinking(true);
          }}
          className="oneberth-button oneberth-button-primary"
        >
          Link a phone
        </button>
      </div>
      <Items
        listed={devices}
        empty={NO_DEVICES_LINKED}
        label="Linked devices"
        what="the devices"
        row={(device) => <DeviceRow key={device.id} device={device} onRemoved={refresh} />}
      />
      {linking && <LinkDialog session={session} onClose={close} onLinked={refresh} />}
    </section>
  );
}

function DeviceRow({ device, onRemoved }: Readonly<{ device: Device; onRemoved: () => void }>) {
  return (
    <li className="oneberth-account-item">
      <div className="oneberth-account-what">
        <span className="oneberth-account-name">{device.name}</span>
        <span className="oneberth-account-kind">{platformName(device.platform)}</span>
      </div>
      <dl className="oneberth-account-dates">
        <div className="oneberth-account-date">
          <dt>Linked on</dt>
          <dd>
            <When instant={device.created_at} />
          </dd>
        </div>
        <div className="oneberth-account-date">
          <dt>Last used</dt>
          <dd>
            <When instant={device.last_used_at} />
          </dd>
        </div>
        <div className="oneberth-account-date">
          <dt>Expires</dt>
          <dd>
            <When instant={device.expires_at} />
          </dd>
        </div>
      </dl>
      <EndButton
        label={`Remove ${device.name}`}
        verb="Remove"
        end={() => removeDevice(device.id)}
        onEnded={onRemoved}
      />
    </li>
  );
}
