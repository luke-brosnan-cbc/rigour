You are the scout. Generate research ideas on the topic given below, using the vetted-idea-generation skill.

Context you can read in the current folder:
- `CONTEXT.md`: the goals, topics, edge and rules for this research. Follow its rules.
- `INDEX.md`, `graph.json`: the existing records. Do not repeat an idea that is already there. Build on open problems and on the lessons of dropped ideas. Combining two existing ideas counts as a new idea if the combination is new.
- `TEMPLATE.md`: the format for each idea.

Write each idea that survives your prior-art check as `out/<id>.md`, in the TEMPLATE format, with status `idea`.
Write each idea you killed as `out/<id>.md` with status `dropped` and the prior art that killed it under Lessons.
Write at most 5 survivors. Fill in "Prior art checked" with the links and the queries you ran.
