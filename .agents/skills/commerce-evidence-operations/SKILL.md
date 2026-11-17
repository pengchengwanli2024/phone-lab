---
name: commerce-evidence-operations
description: Reuse verified Phone-Lab procedures for store-specific product evidence, media fidelity, search-term interpretation, listing preparation, and recovery of repeated collection failures.
---

# Commerce evidence operations

Use the project's current tools and original task/case IDs. Read the applicable
`AGENTS.md` and current tool schema before acting. This skill supplies methods,
not shop credentials, product facts, spending authority, or a publication approval.

## Resolve the product before repeating work

Read `commerce_catalog_list` / `commerce_catalog_get`. Product identity includes
the store connection, platform and platform product ID; SKU alone is insufficient.
Inventory/fulfillment scopes are retained beneath the primary product card.
Research candidates are not inventory. Do not create another card to recover a
failed read or merge same-SKU products from different stores.

## Reuse the existing checks

Run `commerce_operating_pipeline_get` with the exact case, platform, store and
market to obtain current gaps and continuation tools. The companion
[read-only skill template](readonly-skill.json) can be imported, tested and enabled
in the existing extension runtime. A successful inspection means the inspection
ran; it does not mean a product was approved, purchased or published.

The extension scope uses `store_id`; the underlying pipeline tool uses `store_ref`.
The template maps these deliberately. Include `case_id/platform/store_id/market`
in each actual run; do not infer the store from a display name.

- Source text: Russian is valid original content. HTML and attribute JSON have
  readable projections; retain raw values and field paths. Corrected editorial
  copy is a proposal until supported by the exact source contract.
- Media: use original asset IDs/SHA and the existing chunked readers. Verify the
  complete SHA before preview or download. For AI edits, inspect printed text,
  markings, counts, colors and geometry against the effective model input, which
  may differ from the archive slot. Retain rejected versions. Visual consistency
  does not prove physical identity, ownership or a safe age claim.
- Search terms: use the configured shop's exact API snapshot and date range.
  This is not a platform-wide trend ranking. Null stays unknown; preserve the
  original currency; GMV is not an order count; do not sum unique users across terms.
- Finance: a retail price is not procurement cost. Missing fees, stock basis and
  model billing remain unknown. A local shared budget ledger does not impose a
  global cap on host image-generation billing.
- Publishing: update an existing platform product rather than creating a duplicate.
  Freeze the reviewed content/media/target version and compare the current platform
  values. Use the original listing submission adapter and read back its task and
  product state. Do not mark owner review complete on the owner's behalf.

## Recover repeated failures

Keep the first failure and exact request identity. Retry a read only when the
original tool permits it; use the original resume/reconcile API for persisted work.
For a known direct CDN-image failure, use the exercised
[normal-transport recovery](references/image-transport-recovery.md), preserving
the exact original URL, detected file format, size/SHA and source-scoped upload.
An UNKNOWN external result is queried, never blindly submitted again. Do not
replace blocked browser collection with invented demand, quotes or successful runs.
For local research planning, use a compact Russian search phrase, at most 120
characters, with at most one clarification question. The provider schema enforces
those limits; enforcement does not guarantee useful research or reachable sources.
If the original task failed a known planning validation before any capture, the
existing resume tool accepts an explicit `query_ru` with its exact revision and
idempotency key. Use a phrase supported by the original request; this skips only
the failed planner. An UNKNOWN result, collected evidence or an analysis result
cannot be replaced through this option. Read its preserved prior error and the
new collection receipts; never treat queueing as completed research.

Record a reusable lesson only after observing the relevant result and its limits.
Bind it to the tool/source versions and a reproducer; source drift makes it a
candidate for revalidation. See [verified procedures](references/procedures.md)
for existing checks. Business evidence belongs in the product dossier; private
receipts and shop identities must stay outside the public skill.
