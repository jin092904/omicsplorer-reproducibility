# Production-browser observation: 2026-07-20

The public observation file contains 120 fixed-query browser runs and two timing endpoints per
run (`n=240` rows): submission-to-first-result and submission-to-settled-screen. Thirty queries
were run four times; short, medium, and complex categories each contain 40 observations per
timing endpoint.

The run used one public ingress, one client environment, and one date. Browser contexts were new
for each query, while query and model cache state were not independently established. The data do
not measure concurrency, multiple regions, long-term availability, or an SLA.

`browser_timings_public.jsonl` is derived from the private operational trace. It excludes the
temporary hostname, final URLs, application resource waterfall, and internal dataset identifiers.
The remaining fields are sufficient to recalculate the committed summary CSVs.
