import datetime as dt
import unittest
from pathlib import Path

from tools.ci import nightly
from tools.ci import nightly_set as ns

NOW = "2026-10-28T12:00:00+00:00"
PATTERNS = ns.guarded_patterns((Path(__file__).resolve().parents[1] / ".github/CODEOWNERS").read_text())


def pr(n, head="h", state="open", files=("crates/horizon-world/src/lib.rs",), base="main"):
    return ns.PullRequest(n, state, f"{head}{n}", f"Fix {n}", f"dev{n}", base, list(files))


def lookup(*prs):
    known = {p.number: p for p in prs}
    return lambda n: known.get(n)


def run(state, text, login="kacpherek", *prs):
    return ns.apply(state, ns.parse(text), ns.Actor(login, 101 if login == "kacpherek" else 9999), NOW,
                    lookup(*prs), PATTERNS)

T = dt.datetime(2026, 10, 28, 12, 0, tzinfo=dt.timezone.utc)


def merged_pr(n, title, labels, issues=(), paths=("crates/horizon-world/src/lib.rs",)):
    return {"number": n, "title": title, "labels": labels, "issues": list(issues), "author": f"dev{n}",
            "paths": list(paths)}


def notes(chosen=None, picked=(), left_out=(), merged=(), issues=()):
    chosen = chosen or nightly.Ref("main", "b" * 40, T)
    return nightly.notes("2026-10-28", chosen, nightly.Ref("main", "m" * 40, T), list(picked), list(left_out),
                         list(merged), list(issues))


class NightlyTests(unittest.TestCase):
    def test_only_old_dated_nightlies_are_pruned(self):
        tags = [{"tagName": "nightly", "isPrerelease": True},
                {"tagName": "nightly-2026-10-20", "isPrerelease": True},
                {"tagName": "nightly-2026-10-21", "isPrerelease": True},
                {"tagName": "nightly-2026-10-19", "isPrerelease": False},
                {"tagName": "v0.2.80", "isPrerelease": False},
                {"tagName": "nightly-2026-10-15-extra", "isPrerelease": True}]
        self.assertEqual(nightly.stale(tags, dt.date(2026, 10, 28), 7), ["nightly-2026-10-20"])

    def test_notes_list_what_reached_main_as_a_release_did(self):
        merged = [merged_pr(1, "Fix pistons", ["feature"], issues=[7]), merged_pr(2, "Water flows", []),
                  merged_pr(3, "CI only", ["skip-release"]), merged_pr(4, "Docs", [], paths=[])]
        text = notes(merged=merged, issues=["- Known thing"])
        self.assertIn("Nightly 2026-10-28 · bbbbbbb: main (mmmmmmm), built from `main`", text)
        self.assertIn("### New\n- Fix pistons (#1, fixes #7)", text)
        self.assertIn("### Fixed\n- Water flows (#2)", text)
        self.assertNotIn("CI only", text)
        self.assertNotIn("Docs", text)
        self.assertIn("### Known issues\n- Known thing", text)
        self.assertIn("Thanks to @dev1, @dev2.", text)
        self.assertNotIn("### Not merged yet", text)
        self.assertIn("Nothing new for players on main", notes())

    def test_notes_open_with_the_way_to_the_launcher(self):
        # A raw HTML line that launchers skip, as on a game release.
        self.assertTrue(notes().startswith(nightly.train.PLAYERS + "\n\nNightly 2026-10-28 · bbbbbbb: "))

    def test_notes_name_the_commit_and_its_permanent_source_tag(self):
        sha = "0c0206714abc" + "0" * 28
        text = notes(chosen=nightly.Ref("main", sha, None))
        self.assertIn(f"Source: commit {sha}, kept for good as the tag `nightly-source/2026-10-28-0c02067`", text)

    def test_the_source_tag_outlives_every_prune(self):
        tag = nightly.source_tag("2026-10-20", "a" * 40)
        self.assertEqual(nightly.stale([{"tagName": tag, "isPrerelease": True}], dt.date(2026, 11, 28), 7), [])
        self.assertIsNone(nightly.DATED.match(tag))



class ScheduledTests(unittest.TestCase):
    def test_the_scheduled_nightly_drops_merged_closed_and_refused_ones(self):
        state = run({}, "/nightly 1 2 3 4", "kacpherek", pr(1), pr(2), pr(3), pr(4)).state
        get = lookup(pr(1, head="new"), pr(2, state="merged"), pr(3, state="closed"),
                     pr(4, files=[".github/workflows/x.yml"]))
        kept, left_out = nightly.refresh(state["prs"], get, PATTERNS)
        self.assertEqual([(e["number"], e["head"]) for e in kept], [(1, "h1")])
        self.assertEqual(len(left_out), 3)
        self.assertIn("merged", left_out[0])

    def test_the_scheduled_nightly_builds_the_head_that_was_picked(self):
        state = run({}, "/nightly 1", "kacpherek", pr(1)).state
        kept, left_out = nightly.refresh(state["prs"], lookup(pr(1, head="new")), PATTERNS)
        self.assertEqual([(e["number"], e["head"]) for e in kept], [(1, "h1")])
        self.assertEqual(left_out, [])

    def test_an_unreviewed_pull_request_stays_in_the_scheduled_set(self):
        # No review is looked at: a pull request nobody reviewed is kept as long as nothing else refuses it.
        state = run({}, "/nightly 1", "kacpherek", pr(1)).state
        kept, left_out = nightly.refresh(state["prs"], lookup(pr(1)), PATTERNS)
        self.assertEqual([e["number"] for e in kept], [1])
        self.assertEqual(left_out, [])

    def test_notes_list_each_pull_request_and_who_picked_it(self):
        prs = run({}, "/nightly 1 2", "kacpherek", pr(1), pr(2)).state["prs"]
        text = notes(chosen=nightly.Ref("nightly/build-2026-10-28-1", "b" * 40, None), picked=prs,
                     left_out=["#3 Fix 3: closed, left out"])
        self.assertIn("main (mmmmmmm) with 2 pull requests merged in", text)
        self.assertIn("### Not merged yet (2)\n- Fix 1 (#1) by dev1, at h1, picked by kacpherek", text)
        self.assertIn("### Left out (1)", text)

if __name__ == "__main__":
    unittest.main()


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


class UntrustedBuildTests(unittest.TestCase):
    """A nightly can hold pull requests nobody reviewed: nothing its build leaves may reach a release (game-build.yml)."""

    def setUp(self):
        self.game = (WORKFLOWS / "game-build.yml").read_text()

    def test_game_release_and_branch_publishing_workflows_are_absent(self):
        for name in ("release.yml", "nightly-build.yml", "nightly-command.yml", "native-hook-stamp.yml"):
            self.assertFalse((WORKFLOWS / name).exists(), name)
        audit = (WORKFLOWS / "nightly.yml").read_text()
        self.assertIn("workflow_dispatch:", audit)
        self.assertNotIn("schedule:", audit)
        self.assertNotIn("issues: write", audit)
        self.assertNotIn("parity_issues.py", audit)
        self.assertIn("default: false", self.game.split("trusted:", 1)[1].split("developer_id:", 1)[0])

    def test_an_untrusted_build_neither_shares_nor_saves_the_release_cache(self):
        self.assertIn("shared-key: ${{ inputs.trusted && 'release' || 'nightly' }}-${{ matrix.name }}", self.game)
        self.assertIn("save-if: ${{ inputs.trusted }}", self.game)
        self.assertEqual(self.game.count("Swatinem/rust-cache"), 1)

    def test_an_untrusted_build_never_runs_on_the_release_runner(self):
        runs_on = [line for line in self.game.splitlines() if "runs-on:" in line]
        self.assertEqual(len(runs_on), 2)
        # The nightly's own runner: never the release runner, and never behind pull requests' parity queue.
        nightly_runner = "fromJSON('[\"self-hosted\", \"macOS\", \"horizon-nightly\"]')"
        for line in runs_on:
            self.assertIn(f"inputs.trusted && vars.MAC_RUNNER || {nightly_runner}", line)

    def test_a_trusted_build_never_reads_the_shared_sccache(self):
        calls = self.game.count("bash tools/ci/runner-env.sh")
        self.assertEqual(self.game.count("HORIZON_NO_SCCACHE: ${{ inputs.trusted && '1' || '' }}"), calls)
        env = (Path(__file__).resolve().parents[1] / "tools/ci/runner-env.sh").read_text()
        self.assertEqual(env.count('-z "${HORIZON_NO_SCCACHE:-}"'), 2)


class PruneBuildsTests(unittest.TestCase):
    TODAY = dt.date(2026, 11, 10)

    def test_only_old_unpublished_builds_go(self):
        branches = {
            "nightly/build-2026-10-27-1": "a",   # old: goes
            "nightly/build-2026-10-27-2": "pub",  # old, but a published nightly-<date> points to it: stays
            "nightly/build-2026-11-02-1": "c",   # old enough by one day: goes
            "nightly/build-2026-11-03-1": "d",   # exactly 7 days: stays
            "nightly/build-2026-11-09-3": "e",   # recent: stays
        }
        self.assertEqual(nightly.stale_builds(branches, {"pub"}, self.TODAY, 7),
                         ["nightly/build-2026-10-27-1", "nightly/build-2026-11-02-1"])

    def test_the_newest_build_always_stays(self):
        branches = {"nightly/build-2026-10-01-1": "a", "nightly/build-2026-10-01-2": "b"}
        self.assertEqual(nightly.stale_builds(branches, set(), self.TODAY, 7), ["nightly/build-2026-10-01-1"])
        self.assertEqual(nightly.stale_builds({"nightly/build-2026-10-01-1": "a"}, set(), self.TODAY, 7), [])
        # the newest by number, not by text: -10 is newer than -9
        branches = {"nightly/build-2026-10-01-9": "a", "nightly/build-2026-10-01-10": "b"}
        self.assertEqual(nightly.stale_builds(branches, set(), self.TODAY, 7), ["nightly/build-2026-10-01-9"])

    def test_nothing_else_is_touched(self):
        branches = {"nightly-state": "s", "nightly/build-x": "x", "main": "m", "nightly/build-2026-10-01-1-fix": "f",
                    "feature/nightly/build-2026-10-01-1": "g", "nightly/build-2026-10-02-1": "n"}
        self.assertEqual(nightly.stale_builds(branches, set(), self.TODAY, 7), [])
