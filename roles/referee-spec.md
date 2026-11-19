You are the referee. A different agent will build a minimum version (MVP) of the idea in `idea.md`. You write the tests first, before anything is built, and the builder never sees your test code.

Write these files in the current folder:

1. `criteria.md`: what the MVP must do, as numbered, checkable statements. Include the inputs it gets, the output it must produce (file names and formats), and the result that would count as "works". The builder sees this file.
2. `tests/`: Python tests (pytest, standard library and installed packages only) that check each criterion against the builder's output. The tests import or run the MVP from the folder `../mvp`. Make at least one test check a real result (a number, a match against a known answer), not only that files exist.
3. `holdout.md`: the inputs or cases you keep back from the builder, and what the right answer is for each. Use these in the tests.

Keep the MVP small enough to build in under an hour. If the idea cannot be tested that way, write `criteria.md` with the single line `UNTESTABLE: <reason>` and stop.
