# Media tool routing

Short approvals such as “ok, proceed” and “use the tools and launch them” can
continue a recent unfinished media request in the same conversation. An already
queued job or cancellation blocks replay. Assistant promises alone never grant
render permission. Plural images, videos and clips retain the right output type.

Verified local workflows support 1–6 separate takes of one resolved visual brief.
Each take has a separate job ID, immutable graph snapshot and randomized sampling
seed. Job associations persist on the originating user message, so retrying a
partially queued batch fills missing slots rather than duplicating completed slots.
The assistant reports database-backed job IDs/statuses, not model promises.

Different shot descriptions within one batch are not yet supported: generate each
shot separately. Numbered/first–second–third requests stop for clarification rather
than queueing repeated copies of a combined subject. Larger batches must be split.

Project permissions, active-project reference bindings, graph validation and paid
workflow approval requirements remain in effect. A video request cannot queue an
image workflow. MiniMax/API nodes still require manual review; local-render
permission does not authorize external spending.
