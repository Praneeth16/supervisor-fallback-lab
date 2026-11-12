# Gradings made before gradings were kept

Until 2026-11-12 a new grading of a run replaced the old one. Two gradings were lost that way. Their
row-level verdicts are gone. Only the summary lines printed at the time are left, in the text files (only the summary lines were kept)
in this folder. They are copied here so that the first result of each run stays on record next to
the later ones.

| Run | Arm | Grading | Passed | Correct | What changed afterwards |
|---|---|---|---|---|---|
| v1 | A: Genie One | first, lost | 88% | 88% | Grading notes that were unfair to both arms were relaxed, and the answers were graded again |
| v1 | B: custom agent | first, lost | 92% | 93% | Same |
| v1 | A: Genie One | second, kept as grading 1 | 93% | 95% | |
| v1 | B: custom agent | second, kept as grading 1 | 95% | 97% | |
| v2-hard | A: Genie One | first, lost | 82% | 83% | One request (ad04) was changed from "must refuse" to "partly answer", and the answers were graded again |
| v2-hard | B: custom agent | first, lost | 83% | 83% | Same |
| v2-hard | A: Genie One | second, kept as grading 1 | 83% | 83% | |
| v2-hard | B: custom agent | second, kept as grading 1 | 83% | 83% | |

The notes that were relaxed for v1: lt02 (what counts as an active agreement), cs06 (flat against
slightly down), cs08 (what "lately" covers), lt01 (naming the licensor), ties in rounded rankings,
and cd01 (extra correct detail).

From 2026-11-12 answers are saved once and every grading is kept, in `eval/results/<label>/` and
in the lab's Delta tables. `eval/report.py` shows all gradings of a run side by side.
