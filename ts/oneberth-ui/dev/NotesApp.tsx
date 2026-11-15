// Copyright 2026 The oneberth Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * The sample Notes application: a left panel of notes, in `ShellPanel`, and
 * a page per note with a text box and a long list to scroll. Its routes are
 * `#/notes/<number>`.
 */
import { ShellPanel, type AppProps } from "../src";
import "./sample.css";

const NOTES = Array.from({ length: 30 }, (_, at) => at + 1);

export default function NotesApp({ route, href }: Readonly<AppProps>) {
  const chosen = Number(route.replace(/^\//, "").split(/[/?]/)[0] ?? "") || null;
  return (
    <div className="sample-app">
      <ShellPanel>
        <nav aria-label="Notes" className="sample-panel">
          <ul className="sample-list">
            {NOTES.map((note) => (
              <li key={note}>
                <a href={href(`/${note}`)} aria-current={note === chosen ? "page" : undefined}>
                  Note {note}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </ShellPanel>
      <main className="sample-page">
        <h1>{chosen === null ? "Notes" : `Note ${chosen}`}</h1>
        <label className="sample-field">
          Draft
          <textarea rows={4} />
        </label>
        <ol className="sample-lines">
          {Array.from({ length: 80 }, (_, at) => (
            <li key={at}>Line {at + 1}</li>
          ))}
        </ol>
      </main>
    </div>
  );
}
