# Pinned interoperability subset

These adapters use the existing local Commerce copilot and SQLite run records. They do not instantiate another assistant or model worker. The HTTP transport must enforce the same local-user authentication and host/origin policy as the other Commerce routes. A client label is never authorization. This deployment has one local owner; it is not a multi-tenant delegation server.

## A2UI 0.8

Primary sources inspected:

- [Server-to-client schema](https://raw.githubusercontent.com/google/A2UI/main/specification/v0_8/json/server_to_client.json), SHA-256 `77babf290fcbf0a1ba1574dca2a3d17effc5f67ab78a7c68d7690cf0c7f1d43e`.
- [Standard catalog schema](https://raw.githubusercontent.com/google/A2UI/main/specification/v0_8/json/standard_catalog_definition.json), SHA-256 `1639716885e588f9e0d54f4b34304989dd4e6be01e18d8374741f1d2e6a08a2e`.

The versioned upstream URLs contain `main`; the hashes identify the actual bytes inspected. No runtime schema download occurs. We implement a strict subset of those schemas rather than claim general A2UI compatibility or latest-version support.

`surface(run, context)` emits three server-to-client envelopes: `surfaceUpdate`, `dataModelUpdate`, `beginRendering`. The standard catalog is used. Supported components are Text, Column, Row, Button and TextField. Snapshots have at most 64 components, a tree depth of 16 and 64 KiB serialized size; only flat string data bindings are allowed. The validator rejects unknown properties/components, custom catalogs, missing or shared references, cycles and arbitrary action names. It accepts self-contained snapshots, not general incremental streams. Text, including untrusted source strings, must be escaped by each renderer; it is never HTML, Markdown links or a fetch instruction.

`commerce.review_proposal` is a local human-review action, bound to run ID, proposal ID and result hash. It opens review; it never approves or executes. The real review handler must also rebind the current context hash and use the shared reviewed-action gate. TextField values are questions for the user; editing them does not submit a model call or apply a proposal.

## A2A 0.3.0

Primary source: [A2A 0.3 specification](https://a2a-protocol.org/v0.3.0/specification/), especially AgentCard, Task, Message and sections 7–8.

The bearer-authenticated JSON-RPC endpoint implements `message/send` (nonblocking only), `tasks/get` and `tasks/cancel`. Input is bounded user-role text; files, URI parts, executable data, arbitrary metadata, push and streaming are rejected. `message.metadata.commerce` may contain an explicit validated Commerce context; the default is the general agent workspace. No proposal application method is exposed.

A task ID is the existing immutable runtime run ID; contextId is its persisted copilot thread ID. Polling and cancellation find ownership through SQLite, with no process-local ID map. Queued/running map to submitted/working; missing input and pending local human review map to input-required (review status is also stated in task metadata); completed/cancelled/failed map to completed/canceled/failed. Interrupted or unknown runtime outcomes are surfaced as failed with the original runtime status in metadata and are never retried implicitly. Only active queued/running/cancel-requested runs can be canceled. Cancellation requests may remain working until the shared worker acknowledges them.

Each message creates a task, with `messageId` providing transactional idempotency. Repeat the same request to recover its original task. For conversational follow-up, omit taskId and send a new messageId with the existing contextId. Same-task continuation via taskId is explicitly unsupported (`-32004`), including terminal tasks; it never silently substitutes a new task ID. Context changes require the shared copilot context operation, not remote metadata override. Results contain standard text/data artifacts, with A2UI messages in a data part.

The card declares streaming, push, state-transition history and authenticated extended cards false. Unsupported RPC operations use the versioned specification's errors; exception bodies and local paths are not returned. HTTP authentication and real-host acceptance must be tested separately from these adapter tests.
