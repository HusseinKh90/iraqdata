"""
tests.test_ci_workflow
======================
The CI workflow runs the full test suite and the gatekeeper on
every supported Python version.
"""

import pytest
import yaml

from conftest import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def job(workflow) -> dict:
    assert set(workflow["jobs"]) == {"test", "integrity"}
    return workflow["jobs"]["test"]


@pytest.fixture(scope="module")
def integrity_job(workflow) -> dict:
    return workflow["jobs"]["integrity"]


def test_workflow_triggers_on_push_and_pull_request_to_main(workflow):
    triggers = workflow.get("on", workflow.get(True))  # PyYAML reads a bare `on` key as True
    for event in ("push", "pull_request"):
        assert triggers[event]["branches"] == ["main"], event


def test_workflow_also_runs_weekly_and_cannot_write(workflow):
    triggers = workflow.get("on", workflow.get(True))
    (entry,) = triggers["schedule"]
    minute, hour, *_ = entry["cron"].split()
    assert minute not in ("0", "30")  # scheduled runs on the hour are delayed the most
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is True


def test_matrix_covers_supported_python_versions(job):
    assert job["runs-on"] == "ubuntu-24.04"  # pinned image
    assert job["strategy"]["fail-fast"] is False
    assert job["strategy"]["matrix"]["python-version"] == ["3.10", "3.11", "3.12", "3.13"]


def test_steps_install_then_test_then_validate(job):
    runs = [step.get("run", "") for step in job["steps"]]

    def index_of(fragment: str) -> int:
        matches = [i for i, run in enumerate(runs) if fragment in run]
        assert matches, f"no step runs {fragment!r}"
        return matches[0]

    install = index_of('pip install -c requirements/ci-constraints.txt -e ".[pipeline,dev]"')
    tests = index_of("pytest")
    gate = index_of("python pipeline/validate.py")
    assert install < tests < gate


def test_raw_audit_steps_follow_gatekeeper(job):
    """The manifest check and the raw-layer report run after the gatekeeper."""
    runs = [step.get("run", "") for step in job["steps"]]

    def index_of(fragment: str) -> int:
        matches = [i for i, run in enumerate(runs) if fragment in run]
        assert matches, f"no step runs {fragment!r}"
        return matches[0]

    assert (index_of("pytest") < index_of("python pipeline/validate.py")
            < index_of("raw_audit.py manifest check") < index_of("raw_audit.py report"))


def test_rules_are_checked_before_the_gatekeeper(job):
    """The statistical rules must equal a re-derivation."""
    runs = [step.get("run", "") for step in job["steps"]]
    check = [i for i, run in enumerate(runs) if "python pipeline/derive_rules.py --check" in run]
    gate = [i for i, run in enumerate(runs) if "python pipeline/validate.py" in run]
    assert check and gate and check[0] < gate[0]


def test_catalog_is_checked_against_the_data(job):
    """The series catalog check runs after the gatekeeper."""
    runs = [step.get("run", "") for step in job["steps"]]
    check = [i for i, run in enumerate(runs) if run.strip() == "python pipeline/catalog_check.py"]
    gate = [i for i, run in enumerate(runs) if "python pipeline/validate.py" in run]
    assert check and gate and gate[0] < check[0]


def test_gatekeeper_runs_in_release_mode(job):
    """CI runs the gatekeeper as a release gate."""
    runs = [step.get("run", "") for step in job["steps"]]
    gate = [run for run in runs if "python pipeline/validate.py" in run]
    assert gate and all("--release" in run for run in gate)


def test_integrity_job_runs_on_three_operating_systems(integrity_job):
    """A plain checkout verifies byte-exactly on Linux, macOS and Windows."""
    assert integrity_job["runs-on"] == "${{ matrix.os }}"
    assert integrity_job["strategy"]["matrix"]["os"] == ["ubuntu-24.04", "macos-15", "windows-2025"]
    checkout = [s for s in integrity_job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]
    assert checkout and all(set(s.get("with", {})) <= {"persist-credentials"} for s in checkout)  # no line-ending options
    runs = [step.get("run", "") for step in integrity_job["steps"]]
    assert any("python pipeline/verify_integrity.py" in run for run in runs)


# =====================================================================
# The weekly update check reports and never commits
# =====================================================================

UPDATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "update_check.yml"


@pytest.fixture(scope="module")
def update_workflow() -> dict:
    return yaml.safe_load(UPDATE_WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def update_job(update_workflow) -> dict:
    assert len(update_workflow["jobs"]) == 1
    return next(iter(update_workflow["jobs"].values()))


def test_update_check_is_weekly_and_manual(update_workflow):
    triggers = update_workflow.get("on", update_workflow.get(True))
    (entry,) = triggers["schedule"]
    minute, hour, dom, month, dow = entry["cron"].split()
    assert (hour, dom, month, dow) == ("6", "*", "*", "1") and minute not in ("0", "30")  # Mondays, off the hour
    assert "workflow_dispatch" in triggers


def test_update_check_permissions_cannot_push(update_workflow):
    # Actions: read (read-only) lets it read earlier runs' reports
    assert update_workflow["permissions"] == {"contents": "read", "issues": "write", "actions": "read"}
    assert "contents: write" not in UPDATE_WORKFLOW.read_text(encoding="utf-8")
    assert update_workflow["concurrency"]["group"]


def test_update_check_steps(update_job):
    assert update_job["timeout-minutes"] <= 30
    steps = update_job["steps"]
    runs = [step.get("run", "") for step in steps]
    assert any("python pipeline/update_check.py" in run for run in runs)
    assert any(str(step.get("uses", "")).startswith("actions/upload-artifact") for step in steps)
    # Issues are reconciled by pipeline/update_issues.py, whatever happened; no gh CLI
    assert not any("gh issue" in run or "gh label" in run for run in runs)
    reconcile = [step for step in steps if "pipeline/update_issues.py" in step.get("run", "")
                 and "--report" in step.get("run", "")]
    assert len(reconcile) == 1 and reconcile[0]["if"] == "always()"
    assert "--check-failed" in reconcile[0]["run"] and "--maintainer-fallback" in reconcile[0]["run"]
    assert "data-update-check" not in UPDATE_WORKFLOW.read_text(encoding="utf-8")


def _step_index(steps, fragment):
    found = [i for i, s in enumerate(steps) if fragment in s.get("run", "") or fragment == s.get("name")]
    assert found, fragment
    return found[0]


def test_update_check_streaks_feed_the_check(update_job):
    """Earlier failure counts are read before the check and passed to it."""
    steps = update_job["steps"]
    streaks = _step_index(steps, "--streaks-out")
    check = _step_index(steps, "python pipeline/update_check.py")
    assert streaks < _step_index(steps, "pip install") < check
    assert "--streaks" in steps[check]["run"]


def test_update_check_pings_the_dead_mans_switch(update_job):
    """Start before the check, success and fail after reconciling."""
    steps = update_job["steps"]
    start, success, fail = (_step_index(steps, n) for n in ("Ping start", "Ping success", "Ping fail"))
    reconcile = _step_index(steps, "Reconcile issues")
    assert start < _step_index(steps, "python pipeline/update_check.py") < reconcile < success < fail
    assert steps[success]["if"] == "success()" and steps[fail]["if"] == "failure()"
    assert "/start" in steps[start]["run"] and "/fail" in steps[fail]["run"]
    for i in (start, success, fail):
        assert steps[i]["env"]["HC_PING_URL"] == "${{ secrets.HC_PING_URL }}"
        assert "echo $HC_PING_URL" not in steps[i]["run"] and "set -x" not in steps[i]["run"]
    assert 'if [ -z "$HC_PING_URL" ]' in steps[start]["run"]  # a missing secret fails the run


def test_update_check_start_ping_is_not_fatal_but_a_missing_secret_is(update_job):
    start = next(s for s in update_job["steps"] if s.get("name") == "Ping start")
    assert "exit 1" in start["run"] and "|| echo" in start["run"]


def test_update_check_logs_reach_the_check_failed_issue(update_job):
    steps = {s.get("id"): s for s in update_job["steps"]}
    for step_id in ("install", "check"):
        assert steps[step_id]["shell"] == "bash"            # pipefail: a failing command still fails the step
        assert 'tee -a "$RUNNER_TEMP/check.log"' in steps[step_id]["run"]
    reconcile = next(s for s in update_job["steps"] if s.get("name") == "Reconcile issues")
    assert '--log "$RUNNER_TEMP/check.log"' in reconcile["run"]


def test_second_alert_is_optional_and_never_fails_the_run(update_job):
    steps = update_job["steps"]
    alert = steps[_step_index(steps, "Ping second alert")]
    assert alert["if"] == "always()"
    assert alert["env"]["HC_ALERT_URL"] == "${{ secrets.HC_ALERT_URL }}"
    assert "needs_review" in alert["env"]["NEEDS_REVIEW"] and alert["env"]["CHECK_OUTCOME"] == "${{ steps.check.outcome }}"
    assert 'if [ -z "$HC_ALERT_URL" ]' in alert["run"] and "exit 0" in alert["run"]
    assert "/fail" in alert["run"] and "|| echo" in alert["run"]
    assert "set -x" not in alert["run"] and "echo $HC_ALERT_URL" not in alert["run"]
    assert _step_index(steps, "Reconcile issues") < _step_index(steps, "Ping second alert")


def test_no_checkout_keeps_the_token(workflow, update_workflow):
    for wf in (workflow, update_workflow):
        for job in wf["jobs"].values():
            for step in job["steps"]:
                if str(step.get("uses", "")).startswith("actions/checkout"):
                    assert step["with"]["persist-credentials"] is False


def test_dependabot_keeps_the_pinned_actions_current():
    config = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    (entry,) = config["updates"]
    assert entry["package-ecosystem"] == "github-actions" and entry["directory"] == "/"
    assert entry["schedule"]["interval"] == "weekly"


def test_update_check_secrets_only_where_needed(update_job, update_workflow):
    """The token and the ping URL never reach pip or the check (third-party code)."""
    assert "env" not in update_workflow and "GITHUB_TOKEN" not in update_job.get("env", {})
    assert "HC_PING_URL" not in update_job.get("env", {})
    for step in update_job["steps"]:
        env = step.get("env", {})
        if "pip install" in step.get("run", "") or "pipeline/update_check.py" in step.get("run", ""):
            assert "GITHUB_TOKEN" not in env and "HC_PING_URL" not in env


def test_every_action_is_pinned_and_no_floating_runners():
    """Commit SHAs with a version comment; no *-latest images."""
    import re
    for path in (WORKFLOW, UPDATE_WORKFLOW, PUBLISH_WORKFLOW):
        text = path.read_text(encoding="utf-8")
        uses = re.findall(r"uses:\s*(\S+)(.*)", text)
        assert uses, path.name
        for ref, rest in uses:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), (path.name, ref)
            assert re.search(r"#\s*v\d", rest), (path.name, ref)
        assert "-latest" not in text, path.name


def test_update_check_never_commits(update_job):
    for step in update_job["steps"]:
        run = step.get("run", "")
        for forbidden in ("git commit", "git push", "git add"):
            assert forbidden not in run, (forbidden, step.get("name"))


def test_update_check_installs_pinned_dependencies(update_job):
    """The weekly check uses the same pins as CI."""
    runs = [step.get("run", "") for step in update_job["steps"]]
    assert any("pip install -c requirements/ci-constraints.txt" in run for run in runs)


# ---------------------------------------------------------------------------- publishing to PyPI


@pytest.fixture(scope="module")
def publish_workflow() -> dict:
    return yaml.safe_load(PUBLISH_WORKFLOW.read_text(encoding="utf-8"))


def test_publishing_is_manual_and_only_from_main(publish_workflow):
    triggers = publish_workflow.get("on", publish_workflow.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    assert publish_workflow["jobs"]["build"]["if"] == "github.ref == 'refs/heads/main'"


def test_only_the_upload_job_can_ask_pypi_to_trust_it(publish_workflow):
    assert publish_workflow["permissions"] == {"contents": "read"}
    build, publish = publish_workflow["jobs"]["build"], publish_workflow["jobs"]["publish"]
    assert "permissions" not in build
    assert publish["permissions"] == {"id-token": "write"} and publish["environment"] == "pypi"
    assert publish["needs"] == "build"


def test_publishing_stores_no_password_or_token(publish_workflow):
    assert "secrets." not in PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    for job in publish_workflow["jobs"].values():
        for step in job["steps"]:
            assert not {"password", "user"} & set(step.get("with", {})) and "env" not in step
            if str(step.get("uses", "")).startswith("actions/checkout"):
                assert step["with"]["persist-credentials"] is False


def test_the_build_is_checked_before_it_is_uploaded(publish_workflow):
    build = publish_workflow["jobs"]["build"]["steps"]
    run = " ".join(step.get("run", "") for step in build)
    assert run.index("python -m build") < run.index("twine check dist/*")
    names = [step.get("name", "") for step in publish_workflow["jobs"]["publish"]["steps"]]
    assert names == ["Fetch the files built above", "Upload to PyPI"]
