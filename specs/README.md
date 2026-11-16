# Spec-driven development

A specification records what users should be able to do and how to verify it.
Keep it in the same pull request as the implementation and update it when the
decision or the user-visible behavior changes.

1. **Specify** the problem, scope, expected behavior, and testable acceptance
   criteria. Update the existing spec when it covers the change, or copy the
   [template](template.md) into a new feature folder.
2. **Plan** the implementation, including affected interfaces, dependencies,
   and data changes where relevant. Keep the plan in the spec or link to it
   from the spec.
3. **Implement** the planned behavior. Add or update checks for the affected
   criteria as appropriate. A focused manual demo can document criteria that
   currently have no automated test.
4. **Verify** the change. Link the spec in the pull request and reference
   criterion IDs in the verification notes. Include the command or manual
   steps, the observed result, and anything still pending.

For an existing demo, first record a dated baseline and the revision used for
verification. Log gaps and possible improvements as follow-up work.

## Specifications

- [001 · Demo baseline](001-demo-baseline/spec.md)
