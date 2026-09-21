# SF-00 planning evidence

Date: 2026-09-21. Scope: repository/source inspection, architecture and backlog.

## Source and environment

- Inspected application revision: `f8879c1bdb7446d682f9a6c7a58f4f08a012806b`.
- Architecture/backlog checkpoint: `99cc895` (pushed to `origin/main`).
- This evidence file accompanies the ESSRF clarification checkpoint; Git history
  supplies that checkpoint's identity without embedding a self-referential hash.
- Windows PowerShell, Node 25.6.1, npm 11.9.0, Python 3.13.10.
- PyTorch 2.13.0+cu130; `torch.cuda.is_available()` returned true.
- `nvidia-smi`: RTX 3090, total memory 24,576 MiB. No training benchmark performed.
- External source inventory: 11 aircraft, 4 AA and 2 ship project directories.
  Only representative source components were inspected in detail; imports and
  interchange-format compatibility remain SF-04/SF-09 work.

## Checks performed

| Check | Result | Meaning |
| --- | --- | --- |
| `npm run build` | Exit 0 (baseline and architecture checkpoint) | Existing Vite application builds |
| `npx tsc --noEmit` | Exit 0 | Existing TypeScript source typechecks |
| `git diff --check` / staged equivalent | Exit 0 | Documentation has no whitespace errors |
| Python document-link check | Exit 0 | Relative Markdown file targets exist |
| Python backlog check | Exit 0 | SF-00..SF-17 each have a task section, dependencies point backward, only SF-01 is READY |
| Python delimiter check | Exit 0 | Code fences and ESSRF inline/display math delimiters are balanced |

The document checks inspect repository Markdown directly; they are lightweight
planning checks, not an implemented CI or application test suite. Future SF-01
introduces persistent cross-runtime contract validation and CI.

## Results and limits

The plan covers all seven requested capabilities, dataset/label isolation,
first-hit occlusion, thermal/weather models, training/evaluation and incremental
commit/push gates. ESSRF now names static and temporal implementation profiles,
qualifies the surviving-subset limit, and gates the recurrent measurement update
so null fusion preserves the prior algebraically. Implementation verification of
those equations remains in SF-12/SF-14.

No runtime source, dependency or project layout was changed. No lab sensors,
backend, imported assets, dataset or trained model were created. No browser QA,
sensor validation, convergence result, physical calibration or performance
acceptance is claimed by this planning milestone.
