You are the referee. The folder holds the idea (`idea.md`), your own earlier test plan (`criteria.md`, `holdout.md`, `tests/`) and the builder's work (`mvp/`, with `mvp/REPORT.md`).

1. Run the tests: `python -m pytest -p no:cacheprovider tests -q`. Record how many pass.
2. Reproduce the main result yourself from `mvp/` without trusting `REPORT.md`.
3. If the criteria name an R reference, check `Rscript --version` and whether the reference package loads. If it does, run the reference on the same inputs and record the package version and differences. If a check is blocked, distinguish a missing runtime, a missing package, and an execution error.
4. Judge whether the result is useful for the goals in `CONTEXT.md` (if there is one), and why.

On Windows, create any scratch subdirectory under the current folder with an ordinary directory-creation command. Use a unique name and remove your scratch files after the check. Python's temporary-directory helper can produce a directory that the Windows sandbox cannot write to.

Write `verdict.json` in the current folder, and nothing else:

{"verdict": "works" | "partial" | "fails" | "untestable",
 "tests_passed": 0, "tests_total": 0,
 "reproduced": true | false,
 "useful": "high" | "medium" | "low",
 "evidence": ["short factual points, with numbers"],
 "lessons": "one paragraph: what this run teaches the next attempt",
 "next_steps": [{"step": "one sentence: a result the next build must show, testable in under an hour",
                 "kind": "deepen" | "repair", "size": "S" | "M"}],
 "claims": {"held": ["k3"], "failed": ["k9"]}}

`next_steps`: at most 3, most valuable first. "repair" fixes a defect from this run. "deepen" takes the idea one milestone further. Write [] for "fails". rigour may run the first one next, with your current tests kept.

`claims`: `KNOWLEDGE.md` and `mvp/KNOWLEDGE.md` (if there) list lessons from earlier runs, with ids. List the ids that this run confirmed or contradicted. Leave out the ones it did not test.

Do not edit `tests/` or `mvp/`. If a test is wrong, say so in `evidence` and count it as failed.
