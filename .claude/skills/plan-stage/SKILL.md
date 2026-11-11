---
name: plan-stage
description: Start the PLAN step for a NeonCore stage - planner drafts, evaluator adds metrics, telco and security reviewers comment, then stop for the user's approval.
disable-model-invocation: true
argument-hint: <stage-id, e.g. L0 or 7>
---
# /plan-stage $ARGUMENTS

Stage order (fixed): `W0 L0 7 8 9 10 9B 11 12`. Read `project/WORKFLOW.md` first.

1. **Gate the order.** Find the previous stage in the list. With the **Read tool** (the gate blocks Bash commands that name that folder), read `project/approvals/<prev>.close.sha256` and compare its first field with `sha256sum project/reports/<prev>/close.md`. If the file is missing or the hashes differ, the previous stage is not closed: stop and say so.
2. Write `$ARGUMENTS` to `project/STAGE`. Update `project/STATUS.md` (stage, step = PLAN, blockers, next action).
3. Delegate to **phase-planner**: draft `project/plans/$ARGUMENTS.md` with every section the workflow requires.
4. Delegate to **evaluator**: propose the metrics, thresholds, holdout and baseline section. Merge it into the plan (through phase-planner, which owns the file).
5. Delegate to **telco-reviewer** and **security-reviewer** in parallel: each comments in `project/reports/$ARGUMENTS/{telco,security}.md` (section "Plan review"). Fold blocking points back into the plan through phase-planner.
6. Summarize the plan for the user in under 25 lines: goal, tasks by owner, lab changes and rollback, thresholds, cost, risks, and the decisions they must make.
7. **Stop.** Tell the user to read `project/plans/$ARGUMENTS.md` and, if they approve it, run in their own terminal:
   `scripts/approve.sh $ARGUMENTS plan`
   Silence is not approval. Do not start building.
