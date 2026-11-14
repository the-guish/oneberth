// SPDX-License-Identifier: Apache-2.0
// Copyright The Oneberth Authors

/**
 * The npm licence gate, tested on its own parts.
 *
 * `scripts/check-licences.mjs` passing over this tree proves that this tree
 * passes; it proves nothing about what the gate would refuse. These are the
 * refusals, over fixtures.
 *
 * Ported from Robinauts' `frontend/src/test/licence-gate.test.ts`, from vitest
 * to node's own test runner, so that the package needs no dependency to test
 * its gate. The list of forbidden identifiers is shared with the Python gate
 * through `scripts/licence-fixtures.json`, which
 * `tests/tooling/test_licence_gate.py` reads too: the two gates enforce one
 * policy, so they are held to one list rather than to two that look alike.
 *
 *     node --test tests/check-licences.test.mjs
 */
import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, test } from "node:test";

import {
  ROOT,
  allowedLicences,
  categoryFrom,
  emptyByDeclaration,
  forbiddenIn,
  installed,
  statedClaims,
  isAllowed,
  isUnreadable,
  judge,
  pinProblems,
  readTable,
  readPolicy,
  restrictedIn,
  restrictedLicences,
  statedLicence,
  GateError,
} from "../scripts/check-licences.mjs";

/** @type {{shared: [string, string][], npm_only: [string, string][], restricted: [string, string][]}} */
const fixtures = JSON.parse(
  readFileSync(join(ROOT, "scripts", "licence-fixtures.json"), "utf8"),
);

describe("what the policy forbids outright", () => {
  for (const [identifier, verdict] of [
    ...fixtures.shared,
    ...fixtures.npm_only,
  ]) {
    test(`${identifier} is ${verdict}`, () => {
      // What it names is not the claim here -- `GPL v3` is refused for the
      // `GPL` in it -- only whether anything in it is forbidden.
      const found = forbiddenIn(identifier);
      if (verdict === "forbidden") assert.ok(found.length > 0);
      else assert.deepEqual(found, []);
    });
  }

  test("UNLICENSED and Unlicense are one letter and two verdicts apart", () => {
    assert.deepEqual(forbiddenIn("UNLICENSED"), ["UNLICENSED"]);
    assert.equal(isAllowed("Unlicense"), true);
  });

  test("a forbidden side of a choice is still forbidden", () => {
    assert.deepEqual(forbiddenIn("MIT OR GPL-3.0-only"), ["GPL-3.0-only"]);
  });
});

describe("the allowed list, over SPDX expressions", () => {
  test("a choice needs one allowed side", () => {
    assert.equal(isAllowed("MIT OR CC0-1.0"), true);
    assert.equal(isAllowed("(MIT OR SEE-LICENSE-IN-FILE)"), true);
    assert.equal(isAllowed("MPL-2.0 OR EPL-2.0"), false);
  });

  test("a conjunction needs them all", () => {
    assert.equal(isAllowed("MIT AND ISC"), true);
    assert.equal(isAllowed("(MIT AND CC-BY-3.0)"), false);
  });

  test("CNRI-Python is allowed, and only under its own identifier", () => {
    // A conjunction of two allowed licences passes. The GPL-compatible
    // variant is a different SPDX identifier, on no list.
    assert.equal(isAllowed("CNRI-Python"), true);
    assert.equal(isAllowed("Apache-2.0 AND CNRI-Python"), true);
    assert.equal(isAllowed("CNRI-Python-GPL-Compatible"), false);
    assert.equal(isAllowed("Python-2.0"), false);
  });

  test("an exception makes one thing the list does not name", () => {
    assert.equal(isAllowed("Apache-2.0 WITH LLVM-exception"), false);
  });

  test("what will not parse is not allowed: the gate fails closed", () => {
    assert.equal(isAllowed("MIT AND"), false);
    assert.equal(isAllowed("(MIT"), false);
    assert.equal(isAllowed(""), false);
  });

  test("the restricted family is recognised as such", () => {
    assert.deepEqual(restrictedIn("MPL-2.0"), ["MPL-2.0"]);
    assert.deepEqual(restrictedIn("MIT"), []);
  });
});

const ROW = {
  name: "thing",
  version: "1.0.0",
  scope: "development",
  licence: "BlueOak-1.0.0",
};
const PACKAGE = {
  name: "thing",
  version: "1.0.0",
  licence: "BlueOak-1.0.0",
  development: true,
};
/**
 * @param {typeof PACKAGE[]} packages
 * @param {typeof ROW[]} rows
 */
const problemsOf = (packages, rows) => judge({ packages, rows }).problems;

describe("what a package.json states", () => {
  test("a string, an object and the legacy array all read", () => {
    assert.deepEqual(statedClaims({ license: "MIT" }), ["MIT"]);
    assert.deepEqual(statedClaims({ license: { type: "MIT" } }), ["MIT"]);
    assert.deepEqual(
      statedClaims({ licenses: [{ type: "MIT" }, { type: "ISC" }] }),
      ["MIT", "ISC"],
    );
    assert.deepEqual(statedClaims({}), []);
    assert.equal(statedLicence({}), "");
  });

  test("an array of plain strings is claims, not silence", () => {
    // npm has published every shape of this field. A package saying
    // `"licenses": ["MIT"]` states MIT; reading that as "no licence at all"
    // would fail it for the one thing an exception may never cover.
    assert.deepEqual(statedClaims({ licenses: ["MIT"] }), ["MIT"]);
    assert.deepEqual(statedClaims({ license: ["MIT", "ISC"] }), ["MIT", "ISC"]);
    assert.deepEqual(statedClaims({ licenses: ["MIT", { type: "ISC" }] }), [
      "MIT",
      "ISC",
    ]);
    assert.equal(isAllowed(statedLicence({ licenses: ["MIT"] })), true);
    assert.deepEqual(forbiddenIn(statedLicence({ licenses: ["GPL-3.0"] })), [
      "GPL-3.0",
    ]);
  });

  test("every field is read, and the worst of them decides", () => {
    // A package claiming MIT in one field and the GPL in another is a
    // question for a person, not something to settle in our own favour.
    const twoFaced = { license: "MIT", licenses: [{ type: "GPL-3.0" }] };
    assert.deepEqual(statedClaims(twoFaced), ["MIT", "GPL-3.0"]);
    assert.equal(statedLicence(twoFaced), "MIT AND GPL-3.0");
    assert.deepEqual(forbiddenIn(statedLicence(twoFaced)), ["GPL-3.0"]);

    const problems = problemsOf(
      [{ ...PACKAGE, licence: statedLicence(twoFaced) }],
      [{ ...ROW, licence: "MIT" }],
    );
    assert.equal(problems.length, 1);
    assert.match(problems[0], /DEPENDENCIES\.md forbids/);

    // Two agreeable claims cost nothing.
    assert.equal(
      isAllowed(statedLicence({ license: "MIT", licenses: [{ type: "ISC" }] })),
      true,
    );
  });
});

describe("the exceptions table, against the tree", () => {
  test("a row that matches answers for the package", () => {
    assert.deepEqual(problemsOf([PACKAGE], [ROW]), []);
  });

  test("no row at all", () => {
    assert.match(problemsOf([PACKAGE], [])[0], /has no row/);
  });

  test("a row for another version does not answer for this one", () => {
    assert.match(
      problemsOf([PACKAGE], [{ ...ROW, version: "2.0.0" }])[0],
      /excepts thing only at 2\.0\.0/,
    );
  });

  test("two versions of one package each need their own row", () => {
    const other = { ...PACKAGE, version: "2.0.0" };
    assert.deepEqual(
      problemsOf([PACKAGE, other], [ROW, { ...ROW, version: "2.0.0" }]),
      [],
    );
    assert.match(problemsOf([PACKAGE, other], [ROW])[0], /thing 2\.0\.0/);
  });

  test("a row naming another licence fails: a licence is re-read on a bump", () => {
    assert.match(
      problemsOf([PACKAGE], [{ ...ROW, licence: "MIT-0" }])[0],
      /a licence is re-checked on every bump/,
    );
  });

  test("a development row for something the runtime reaches fails", () => {
    assert.match(
      problemsOf([{ ...PACKAGE, development: false }], [ROW])[0],
      /the runtime dependencies reach it/,
    );
  });

  test("a restricted licence may only be carried by a development row", () => {
    const shipped = { ...PACKAGE, licence: "MPL-2.0", development: false };
    const problems = problemsOf(
      [shipped],
      [{ ...ROW, licence: "MPL-2.0", scope: "runtime" }],
    );
    assert.equal(problems.length, 1);
    assert.match(problems[0], /cannot carry it/);

    // The same package with the honest row: the scope check catches it first.
    assert.match(
      problemsOf([shipped], [{ ...ROW, licence: "MPL-2.0" }])[0],
      /the runtime dependencies reach it/,
    );
    // And development-only, it passes.
    assert.deepEqual(
      problemsOf(
        [{ ...shipped, development: true }],
        [{ ...ROW, licence: "MPL-2.0" }],
      ),
      [],
    );
  });

  test("a forbidden licence is refused whatever the row says", () => {
    const forbidden = { ...PACKAGE, licence: "LGPL-3.0-only" };
    const problems = problemsOf(
      [forbidden],
      [{ ...ROW, licence: "LGPL-3.0-only" }],
    );
    assert.equal(problems.length, 1);
    assert.match(problems[0], /DEPENDENCIES\.md forbids/);
  });

  test("a stale row fails", () => {
    const allowed = { ...PACKAGE, licence: "MIT" };
    assert.match(
      problemsOf([allowed], [{ ...ROW, licence: "MIT" }])[0],
      /needs no exception; remove the row/,
    );
  });
});

describe("the shape of the table", () => {
  /** @param {string} body */
  const table = (body) => () =>
    readTable(`## ${"JavaScript build tooling"}\n\n${body}\n`);

  test("the real document parses, and every row is development", () => {
    // The table is empty today; what is asserted is that it parses, and that
    // whatever is added to it says `development`.
    const rows = readTable(
      readFileSync(join(ROOT, "DEPENDENCIES.md"), "utf8"),
    );
    assert.ok(Array.isArray(rows));
    assert.ok(rows.every((row) => row.scope === "development"));
  });

  test("a renamed heading is the gate's own error, not a crash", () => {
    assert.throws(
      () => readTable("## Something else\n\n| a |\n|---|\n"),
      GateError,
    );
  });

  test("a missing column, a missing table and a bad scope all say so", () => {
    assert.throws(
      table("| package | version | licence |\n|---|---|---|\n"),
      /no "scope" column/,
    );
    assert.throws(table("nothing here"), /has no table/);
    assert.throws(
      table(
        "| package | version | scope | licence |\n|---|---|---|---|\n" +
          "| `thing` | 1.0.0 | someday | MIT |\n",
      ),
      /is not one of/,
    );
    assert.throws(
      table(
        "| package | version | scope | licence |\n|---|---|---|---|\n" +
          "| thing | 1.0.0 | development | MIT |\n",
      ),
      /names no package in backticks/,
    );
  });
});

describe("exact pins", () => {
  test("a range, a wildcard and a choice are all refused", () => {
    assert.deepEqual(pinProblems({ dependencies: { a: "1.0.0" } }), []);
    assert.equal(pinProblems({ dependencies: { a: "^1.0.0" } }).length, 1);
    assert.equal(pinProblems({ devDependencies: { a: "*" } }).length, 1);
    assert.equal(pinProblems({ peerDependencies: { a: ">=1" } }).length, 1);
    assert.equal(pinProblems({ optionalDependencies: { a: "1.x" } }).length, 1);
    assert.match(
      pinProblems({ overrides: { a: { b: "~1.0.0" } } })[0],
      /overrides\.a\.b/,
    );
  });

  test("a prerelease and a build are exact, in semver's order", () => {
    assert.deepEqual(pinProblems({ dependencies: { a: "1.0.0-rc.1" } }), []);
    assert.deepEqual(pinProblems({ dependencies: { a: "1.0.0+build.7" } }), []);
    assert.deepEqual(
      pinProblems({ dependencies: { a: "1.0.0-beta-2+sha.5114f85" } }),
      [],
    );
    assert.deepEqual(pinProblems({ dependencies: { a: "1.0.0+build-rc" } }), []);
    assert.equal(pinProblems({ dependencies: { a: "1.0.0-" } }).length, 1);
    assert.equal(pinProblems({ dependencies: { a: "1.0.0+a+b" } }).length, 1);
  });

  test("a long version that is not exact is refused at once", () => {
    // What made an earlier pattern backtrack exponentially: each "-a" doubled
    // the time, and twenty-eight took seconds.
    const started = performance.now();
    assert.equal(
      pinProblems({ dependencies: { a: `1.0.0${"-a".repeat(28)}!` } }).length,
      1,
    );
    assert.ok(performance.now() - started < 1000);
  });
});

describe("the lists come from the document, not from a second copy", () => {
  // Written out by hand, on purpose. A second parser beside the gate's would
  // agree with it for the same wrong reason; a list somebody typed out of
  // DEPENDENCIES.md disagrees the moment the document is shortened, which is
  // the failure worth catching.
  test("the allowed list is DEPENDENCIES.md's, in full", () => {
    assert.deepEqual(
      [...allowedLicences()].sort(),
      [
        "0bsd",
        "apache-2.0",
        "bsd-2-clause",
        "bsd-3-clause",
        "cc0-1.0",
        "cnri-python",
        "isc",
        "mit",
        "mit-0",
        "postgresql",
        "psf-2.0",
        "unlicense",
        "zlib",
      ],
    );
  });

  test("the restricted list is DEPENDENCIES.md's, CDDL versions and all", () => {
    assert.deepEqual(
      [...restrictedLicences()].sort(),
      ["cddl-1.0", "cddl-1.1", "epl-2.0", "mpl-2.0"],
    );
  });

  test("the policy is read when it is asked for, not when the gate loads", () => {
    // Work that can fail must not happen while a module is being imported:
    // there it is a stack and exit 1, which reads as "a dependency failed".
    assert.throws(() => readPolicy("/nowhere/DEPENDENCIES.md"), GateError);
    assert.throws(
      () => readPolicy("/nowhere/DEPENDENCIES.md"),
      /could not be read/,
    );
    assert.throws(() => categoryFrom("# Other\n\nMIT.\n", "Allowed"), GateError);
  });

  test("a category that contradicted the forbidden list stops the gate", () => {
    assert.throws(
      () =>
        categoryFrom(
          "### Allowed\n\nMIT, GPL-3.0-only.\n\n### Next\n",
          "Allowed",
        ),
      /cannot both be true/,
    );
    assert.throws(
      () => categoryFrom("### Allowed\n\n\n### Next\n", "Allowed"),
      GateError,
    );
  });
});

describe("the restricted family, however it is spelt", () => {
  for (const [claim] of fixtures.restricted) {
    test(`${claim} is restricted`, () => {
      assert.ok(restrictedIn(claim).length > 0);
    });
  }

  test("and a permissive licence is not", () => {
    assert.deepEqual(restrictedIn("MIT"), []);
    assert.deepEqual(restrictedIn("Apache-2.0"), []);
  });

  test("so a runtime row cannot carry one, whatever it is called", () => {
    const shipped = {
      ...PACKAGE,
      licence: "Mozilla Public License 2.0",
      development: false,
    };
    const problems = problemsOf(
      [shipped],
      [{ ...ROW, licence: "Mozilla Public License 2.0", scope: "runtime" }],
    );
    assert.equal(problems.length, 1);
    assert.match(problems[0], /cannot carry it/);
  });
});

describe("claims nobody can look up", () => {
  test("they are refused, and no row may cover them", () => {
    assert.equal(isUnreadable("SEE LICENSE IN LICENSE.txt"), true);
    assert.equal(isUnreadable("SEE LICENCE IN COPYING"), true);
    assert.equal(isUnreadable("NOASSERTION"), true);
    assert.equal(isUnreadable("MIT*"), true);
    assert.equal(isUnreadable("MIT"), false);
    // One unreadable side of a choice makes the claim unreadable: picking the
    // readable side would be settling it in our own favour.
    assert.equal(isUnreadable("MIT OR NOASSERTION"), true);
    assert.equal(isUnreadable("(MIT AND UNKNOWN)"), true);
    assert.equal(isUnreadable("MIT OR ISC"), false);

    const vague = { ...PACKAGE, licence: "NOASSERTION" };
    const problems = problemsOf([vague], [{ ...ROW, licence: "NOASSERTION" }]);
    assert.equal(problems.length, 1);
    assert.match(problems[0], /names no licence anybody can look up/);
  });
});

describe("rows the tree has outgrown", () => {
  test("a row for something the lockfile no longer pins fails", () => {
    const pinned = new Set([`${PACKAGE.name}@${PACKAGE.version}`]);
    const gone = { ...ROW, name: "left", version: "9.9.9" };
    const { problems } = judge({
      packages: [PACKAGE],
      rows: [ROW, gone],
      pinned,
    });
    assert.equal(problems.length, 1);
    assert.match(
      problems[0],
      /excepts left 9\.9\.9, which the lockfile does not pin at any version/,
    );
  });

  test("a row for a version the lockfile still pins elsewhere is left alone", () => {
    // Another platform's binary: pinned, not installed here, and its row is
    // read on the machine that does install it.
    const pinned = new Set([
      `${PACKAGE.name}@${PACKAGE.version}`,
      "thing-win32@1.0.0",
    ]);
    const other = { ...ROW, name: "thing-win32" };
    assert.deepEqual(
      judge({ packages: [PACKAGE], rows: [ROW, other], pinned }).problems,
      [],
    );
  });

  test("a row is stale in an empty tree too", () => {
    // The empty tree passes only with nothing to except: a row there names a
    // package the lockfile does not pin.
    const { problems } = judge({ packages: [], rows: [ROW], pinned: new Set() });
    assert.equal(problems.length, 1);
    assert.match(problems[0], /does not pin at any version/);
  });
});

describe("an empty tree", () => {
  test("passes only when the lockfile pins nothing and nothing is declared", () => {
    const empty = { packages: [], pinned: new Set() };
    assert.equal(emptyByDeclaration(empty, {}), true);
    assert.equal(
      emptyByDeclaration(empty, { dependencies: {}, devDependencies: {} }),
      true,
    );
  });

  test("a lockfile that pins packages nobody installed is refused", () => {
    const uninstalled = { packages: [], pinned: new Set(["a@1.0.0"]) };
    assert.throws(() => emptyByDeclaration(uninstalled, {}), /run `npm ci`/);
  });

  test("a manifest that declares what the lockfile does not pin is refused", () => {
    const empty = { packages: [], pinned: new Set() };
    for (const field of [
      "dependencies",
      "devDependencies",
      "optionalDependencies",
      "peerDependencies",
    ]) {
      assert.throws(
        () => emptyByDeclaration(empty, { [field]: { a: "1.0.0" } }),
        new RegExp(`declares ${field}`),
      );
    }
    // A field of the wrong shape is not an empty declaration either.
    assert.throws(
      () => emptyByDeclaration(empty, { dependencies: "a" }),
      GateError,
    );
  });

  test("a tree with packages is not empty, and is judged as usual", () => {
    const tree = { packages: [PACKAGE], pinned: new Set(["thing@1.0.0"]) };
    assert.equal(emptyByDeclaration(tree, { devDependencies: {} }), false);
  });
});

describe("reading the tree", () => {
  /** @type {string[]} */
  const scratches = [];
  const scratch = () => {
    const where = mkdtempSync(join(tmpdir(), "oneberth-gate-"));
    scratches.push(where);
    return where;
  };
  afterEach(() => {
    for (const where of scratches.splice(0))
      rmSync(where, { recursive: true, force: true });
  });

  /**
   * A tree, written to disk.
   * @param {unknown} lock
   * @param {Record<string, unknown>} [packages]
   */
  function tree(lock, packages = {}) {
    const where = scratch();
    writeFileSync(join(where, "package-lock.json"), JSON.stringify(lock));
    for (const [path, own] of Object.entries(packages)) {
      mkdirSync(join(where, path), { recursive: true });
      writeFileSync(join(where, path, "package.json"), JSON.stringify(own));
    }
    return where;
  }

  test("a lockfile that is missing or will not parse stops the gate", () => {
    assert.throws(() => installed(scratch()), GateError);
    const where = scratch();
    writeFileSync(join(where, "package-lock.json"), "{ not json");
    assert.throws(() => installed(where), /package-lock\.json could not be read/);
  });

  test("a package.json that will not parse stops the gate", () => {
    const where = tree({
      packages: { "": {}, "node_modules/a": { version: "1.0.0" } },
    });
    mkdirSync(join(where, "node_modules/a"), { recursive: true });
    writeFileSync(join(where, "node_modules/a/package.json"), "{ not json");
    assert.throws(() => installed(where), /cannot read/);
  });

  test("a locked package that is simply not installed stops the gate", () => {
    const where = tree({
      packages: { "": {}, "node_modules/a": { version: "1.0.0" } },
    });
    assert.throws(() => installed(where), /is not installed; run `npm ci`/);
  });

  test("an optional package for another platform is counted, not a failure", () => {
    const where = tree({
      packages: {
        "": {},
        "node_modules/a": { version: "1.0.0" },
        "node_modules/b-win32": { version: "1.0.0", optional: true },
        "node_modules/c-win32": { version: "1.0.0", devOptional: true },
      },
    });
    mkdirSync(join(where, "node_modules/a"), { recursive: true });
    writeFileSync(
      join(where, "node_modules/a/package.json"),
      JSON.stringify({ name: "a", version: "1.0.0", license: "MIT" }),
    );

    const { packages, elsewhere, pinned } = installed(where);
    assert.deepEqual(
      packages.map((one) => one.name),
      ["a"],
    );
    // devOptional means npm may leave it out just as optional does.
    assert.deepEqual(elsewhere, ["b-win32 1.0.0", "c-win32 1.0.0"]);
    assert.equal(pinned.has("c-win32@1.0.0"), true);
  });

  test("a lockfile with only the root pins nothing", () => {
    const where = tree({ packages: { "": { name: "x" } } });
    const { packages, pinned } = installed(where);
    assert.deepEqual(packages, []);
    assert.equal(pinned.size, 0);
  });
});
