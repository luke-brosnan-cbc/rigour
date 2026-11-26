You are the referee. A different agent will build a minimum version (MVP) of the idea in `idea.md`. You write the tests first, before anything is built, and the builder never sees your test code.

Write these files in the current folder:

1. `criteria.md`: what the MVP must do, as numbered, checkable statements. Include the inputs it gets, the output it must produce (file names and formats), and the result that would count as "works". The builder sees this file.
2. `tests/`: Python tests (pytest, standard library and installed packages only) that check each criterion against the builder's output. The tests import or run the MVP from the folder `../mvp`. Make at least one test check a real result (a number, a match against a known answer), not only that files exist.
3. `holdout.md`: the inputs or cases you keep back from the builder, and what the right answer is for each. Use these in the tests.

Read `RELATED.md` first. Name relevant earlier work in `criteria.md`. If the idea's track in `CONTEXT.md` makes novelty optional, test the proposed workflow or adaptation against a realistic baseline. Check the practical gain the idea claims. For other tracks, test the part that prior work leaves open.

Read `KNOWLEDGE.md` if it is there: lessons from earlier runs, with ids. Follow them unless this idea gives a reason not to.

Keep any data the tests need under 200 MB in total, and tell the builder in `criteria.md` to sample bigger sources.

Keep the MVP small enough to build in under an hour. If the idea cannot be tested that way, write `criteria.md` with the single line `UNTESTABLE: <reason>` and stop.
