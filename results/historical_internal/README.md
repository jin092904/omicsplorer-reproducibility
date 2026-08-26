# Historical internal aggregates

These CSV files preserve aggregate outputs from development-time hard-query runs. They are kept
for manuscript auditability, not as a frozen submission result.

Known limitations:

- the per-query raw result rows were not retained here;
- the complete effective server configuration and fallback trace were not retained;
- the corpus and model lineage are not bound to these files by a release manifest;
- the queries and facet expectations were created internally.

The tables may be used only with those limitations stated. A submission claim must be replaced
by a validated frozen rerun or explicitly labeled as a historical descriptive observation.
