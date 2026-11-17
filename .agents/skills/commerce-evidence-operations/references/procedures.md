# Verified procedure map

These are implementation and isolated-check boundaries, not claims about a shop's
commercial results. Re-run the relevant checks when their source changes.

| Repeated situation | Existing mechanism | Regression / observed limit |
| --- | --- | --- |
| Several fulfillment rows appear to be duplicate products | Store/connection/product grouping; preserve scope IDs | `test_catalog_store_identity`, `test_catalog_media_integration`; real browser catalog-library gate |
| Russian HTML or attribute JSON is shown as unreadable text | Inert readable projection; original/raw disclosure | `catalog-presentation` frontend tests and catalog-library browser gate; no fabricated translation |
| Local pictures cannot be opened from an opaque host iframe | Whole-file SHA checked after bounded chunks; blob image policy | `test_media_library`, actual main browser iframe decode; host desktop versions remain separate acceptance |
| Product description is physically stored under Ozon attribute 4191 | Exact physical source path for a unique simple value | `test_workspace_content_citations`; rewritten prose still needs evidence review |
| Local research planner emits the entire assignment as a query | Bounded provider JSON schema plus short-phrase instructions | `test_market_research_contract`; remote sources can still timeout or reject requests |
| Test source snapshots accidentally include generated client connections | Exclude generated MCP/Hermes/Codex files; retain actual integration code | `scripts.tests.test_verify`; release scanning is still necessary for the final tree/history |
| Same native image is bound to several SKUs | One immutable native output SHA, explicit per-product references | Product evidence/creative APIs; physical variant/color and effective-input lineage require review |
| Store keyword data is mistaken for global hot search | Exact source/window/scope; explicit unknowns | `test_ozon_search_terms`; own-shop API queries only |
| A read-only scheduled workflow succeeds without a useful business finding | Keep actual run and source-bound validation result | `test_intel_opportunities`; empty opportunities are valid, and JSON validity is not commercial quality |
| A submitted platform call has an uncertain result | Original intent, UNKNOWN state and reconciliation | Existing listing submission/action tests; never substitute another idempotency key |

From the project root, use its configured Python interpreter to run affected
unittest modules with `PYTHONPATH=commerce:commerce/qa`. Run `make verify` before
claiming an engineering change complete. The full profile has an explicit module
allowlist; it is not the entire backend suite.

The native image provider, configured independent media provider, local language
model and app-host automation have separate runtime and billing boundaries.
Neither a skill document nor a daily interval proves reboot recovery, all-day
availability, phone delivery or external transaction execution.
