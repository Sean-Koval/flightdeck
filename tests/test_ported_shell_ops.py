"""The ported `shell_ops` reads commands as hangar does: hangar's KAN-279 cases (hangar#491, tests/test_interfaces.py),
copied unchanged, so a drift between the two shows here."""

import time

from flightdeck.ported.hangar_traces import shell_ops as ops


def test_shell_ops_find_tests_in_loops_behind_wrapper_flags_and_in_ci_scripts():
    """KAN-279: the four commands the Nov 2 validation got wrong, and the cases around each fix."""
    assert ops("for f in a b; do pytest $f; done") == ["test"]
    assert ops("uv run --project svc pytest -x") == ["test"]
    assert ops("bash scripts/ci/verify.sh") == ["test"]
    assert ops("python3 -m pytest --version") == []
    # a keyword opens the segment: loops, conditions, groups
    for cmd in ("while true; do npm test; sleep 5; done", "if pytest -q; then echo ok; fi", "{ go test ./...; }",
                "until make check; do sleep 1; done", "if true; then :; else cargo test; fi"):
        assert ops(cmd) == ["test"], cmd
    assert ops("echo do pytest") == [] and ops("for f in *.py; do rm $f; done") == ["delete"]
    # a wrapper flag's value is not the program
    for cmd in ("uv --directory svc run pytest", "uv run --with pytest-xdist --python 3.12 pytest -n 4",
                "poetry -C svc run pytest", "pnpm --dir web exec vitest run", "sudo -u ci pytest",
                "timeout -s KILL 600 make test", "env -C svc pytest", "npx -p jest jest", "nice -n 5 tox"):
        assert ops(cmd) == ["test"], cmd
    assert ops("uv run --project svc python app.py") == [] and ops("uv sync --project svc") == []
    # a test or CI script, by a shell or by its path
    for cmd in ("sh -e ./run_tests.sh", "./scripts/ci/verify.sh", "bash -x scripts/test-all.sh", "zsh ci.sh",
                "scripts/check.sh", "bash tests.sh"):
        assert ops(cmd) == ["test"], cmd
    for cmd in ("bash scripts/deploy.sh", "./checkout.sh", "./testdata.sh", "cat scripts/ci/verify.sh",
                "verify.sh", "bash"):
        assert ops(cmd) == [], cmd
    # a runner asked only to describe itself or list its tests runs none
    for cmd in ("pytest --help", "pytest --collect-only -q tests/", "pytest --co", "jest --listTests",
                "go test -h", "uv run pytest --version", "npm test -- --help"):
        assert ops(cmd) == [], cmd
    assert ops("pytest --version && pytest -q") == ["test"] and ops("pytest -v") == ["test"]
    for cmd in ("go test -list . ./...", "dotnet test --list-tests", "tox -l", "nox -l", "vitest list",
                "rspec --dry-run", "bash scripts/test.sh --help"):
        assert ops(cmd) == [], cmd


def test_shell_ops_read_quotes_heredocs_and_flag_values_as_a_shell_does():
    """KAN-279 review: a separator inside quotes or a here-document is text, so prose that mentions a test is not
    one; flags that take a value (a shell's, a runner's before its subcommand) and `sh -c` are read through."""
    assert ops('git commit -m "make suite green; then pytest passes on CI"') == ["git.commit"]
    assert ops('git commit -m "drop old ci; scripts/ci-deploy.sh is gone"') == ["git.commit"]
    assert ops("git commit -F - <<EOF\nfix\nif pytest -n auto hangs, rerun serially\nEOF\n") == ["git.commit"]
    assert ops("cat > NOTES.md <<'EOF'\nthen ./scripts/ci/verify.sh runs on the tag\nEOF\ngit add -A && "
               "git commit -m notes") == ["git.commit"]
    assert ops("cat <<-EOF > x && pytest -q\n\tpytest in body\n\tEOF\ngit push") == ["test", "git.push"]
    assert ops("pytest -q  # then commit") == ["test"] and ops('echo "a # b"; pytest') == ["test"]
    for cmd in ("./ci-deploy.sh", "bash scripts/ci_publish.sh", "./check-env.sh", "./test-data-gen.sh",
                "bash scripts/verify_signature.sh"):
        assert ops(cmd) == [], cmd
    for cmd in ("bash scripts/unit-test.sh", "scripts/e2e-tests.sh", "bash scripts/runtests.sh",
                "./scripts/test.bash", "bash -euo pipefail scripts/ci/verify.sh", "bash -O extglob scripts/test.sh",
                "bash --rcfile x scripts/test.sh", "sudo -iu ci pytest", "pnpm --filter web test",
                "npm --prefix web test", "yarn --cwd web test", "make -C svc test", "make -j 4 test", "make -j test",
                "mvn -pl svc test", "uv run --index-url https://x/simple pytest", "python -u -m pytest",
                "coverage run -m pytest", "timeout 1.5h pytest", "bash -c './ci.sh'", "bash -ec './ci.sh'",
                "bash -x -c 'pytest -q'"):
        assert ops(cmd) == ["test"], cmd
    assert ops('sh -c "npm test && git commit -m x"') == ["test", "git.commit"] and ops("bash -c 'echo hi'") == []


def test_shell_ops_read_continuations_here_strings_and_nested_quotes():
    """KAN-279 review, round 2: a backslash-newline joins lines, a here-string is not a here-document, a CRLF
    delimiter still ends one, quotes nest inside `$( )`, and a runner's letters are not read as one cluster."""
    assert ops("docker build . && \\\n  ./scripts/ci/verify.sh") == ["test"]
    assert ops("pytest -q \\\n  && git commit -m x") == ["test", "git.commit"]
    assert ops("make -sj test") == ["test"] and ops("mvn -ff test") == ["test"]
    assert ops('grep x <<<"$out"\npytest') == ["test"] and ops("cat <<< hi && git push") == ["git.push"]
    assert ops("cat <<EOF > a\r\nbody\r\nEOF\r\npytest\r\n") == ["test"]
    assert ops("cat <<E\\OF\nbody\nEOF\npytest") == ["test"]
    nested = """git commit -m "$(cat <<'EOF'\nit's 12" wide; pytest\nEOF\n)" && git push"""
    assert ops(nested) == ["git.commit", "git.push"]
    assert ops("echo $'it\\'s; pytest'") == [] and ops("echo $((1<<y)); pytest") == ["test"]
    assert ops("sleep 1 & pytest") == ["test"] and ops("pytest 2>&1 | tee log") == ["test"]


def test_shell_ops_stay_fast_on_huge_commands():
    """A megabyte of quoted text or here-document is read in well under a second."""
    for cmd in ("echo '" + "a; " * 333_333 + "'", "<" * 1_000_000,
                "cat > f <<'EOF'\n" + "x = 'it''s'\n" * 80_000 + "EOF\npytest"):
        t0 = time.monotonic()
        ops(cmd)
        assert time.monotonic() - t0 < 2, cmd[:20]
