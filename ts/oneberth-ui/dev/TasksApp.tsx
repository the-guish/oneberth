// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The sample Tasks application: the open tasks are the count on the rail,
 * and a stand-in long poll runs only while the application is shown.
 */
import { useEffect, useState } from "react";

import type { AppProps } from "../src";
import { openTasks } from "./sampleApps";
import "./sample.css";

const POLL_MS = 1000;

export default function TasksApp({ visible }: Readonly<AppProps>) {
  const [done, setDone] = useState<readonly number[]>([]);
  const [polls, setPolls] = useState(0);
  const tasks = [1, 2, 3];
  const open = tasks.length - done.length;

  useEffect(() => {
    openTasks.set(open);
  }, [open]);

  // A long poll asks again as soon as it is answered; hidden, it stops.
  useEffect(() => {
    if (!visible) return;
    const timer = setInterval(() => {
      setPolls((count) => count + 1);
    }, POLL_MS);
    return () => {
      clearInterval(timer);
    };
  }, [visible]);

  return (
    <div className="sample-app">
      <main className="sample-page">
        <h1>Tasks</h1>
        <p>{`Long poll: ${visible ? "running" : "stopped"}. Polls: ${polls}.`}</p>
        <ul className="sample-list">
          {tasks.map((task) => (
            <li key={task}>
              <label>
                <input
                  type="checkbox"
                  checked={done.includes(task)}
                  onChange={(event) => {
                    setDone(event.target.checked ? [...done, task] : done.filter((one) => one !== task));
                  }}
                />
                Task {task}
              </label>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}
