---
name: build-stage
description: Run the BUILD step for an approved NeonCore stage plan on branch stage/<id>, delegating each task to its owner agent and verifying in the live lab.
disable-model-invocation: true
argument-hint: <stage-id>
---
# /build-stage $ARGUMENTS

1. Check that `project/STAGE` is `$ARGUMENTS`. With the **Read tool**, read `project/approvals/$ARGUMENTS.plan.sha256` and compare its first field with `sha256sum project/plans/$ARGUMENTS.md`. Missing or different: the plan is not approved (or was edited since), so stop and ask the user to review and run `scripts/approve.sh $ARGUMENTS plan`.
2. Create or switch to branch `stage/$ARGUMENTS` (never on `main`).
3. Turn the plan's task list into the session task list. For each task, delegate to its owner agent (developer, lab-ops, evaluator, docs-writer, blog-writer) with: the plan section, the files it may touch, the acceptance test that proves it, and the instruction to append raw notes to `project/notes/$ARGUMENTS.md`.
4. Lab changes go only to **lab-ops**. Snapshot before any destructive campaign.
5. Every change is deployed to the lab and verified there; "imports cleanly" is not proof. Small commits with tests.
6. Track failures per issue. After **3 failed cycles on the same issue**, stop and bring it to the user with options.
7. A change to scope, architecture, lab topology, budget or exit criteria: stop, have phase-planner amend the plan (this voids the approval), and ask the user to approve again.
8. Keep `project/STATUS.md` current after each task. When all tasks pass their acceptance tests, tell the user the build is ready for `/close-stage $ARGUMENTS`.
