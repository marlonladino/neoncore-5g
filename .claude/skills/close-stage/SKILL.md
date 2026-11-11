---
name: close-stage
description: Run EVALUATE and DOCUMENT/CLOSE for a NeonCore stage - independent eval and reviews, docs and blog, close report, then stop for the user's close approval.
disable-model-invocation: true
argument-hint: <stage-id>
---
# /close-stage $ARGUMENTS

1. **Evaluate independently.** Delegate in parallel to **evaluator** (harness and holdout, results in `project/reports/$ARGUMENTS/eval/`), **telco-reviewer** and **security-reviewer**. Builders do not take part. Failures go back to developer or lab-ops through `/build-stage` rules (3 failed cycles on one issue → stop and ask).
2. **Document.** Delegate to **docs-writer** (README, DEVLOG root-cause entries, ADRs, runbooks) and **blog-writer** (post plus tutorials; every tutorial command run against a clean lab restore). Every number must trace to a file in `project/reports/`.
3. **Close report.** Write `project/reports/$ARGUMENTS/close.md`:
   - `# Stage $ARGUMENTS close`
   - Exit criteria table: criterion, result (pass/fail/not tested), evidence path
   - Numbers (with source files), spend against `project/budget.yaml`, known limits
   - 5 to 10 questions the user should be able to answer about this stage
4. Update `project/STATUS.md`. Show the user the test and eval output.
5. **Stop.** Ask the user to run in their own terminal: `scripts/approve.sh $ARGUMENTS close`.
6. After they confirm, merge `stage/$ARGUMENTS` into `main` locally (`git merge --no-ff`). Pushing, deploying the site or anything public is a **separate** approval: security-reviewer scrubs first, and the user confirms the employer outside-work policy themself.
