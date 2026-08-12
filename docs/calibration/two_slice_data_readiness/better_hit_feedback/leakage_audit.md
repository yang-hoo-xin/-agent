authority: non_authoritative_derived_presentation

# BetterHitFeedback leakage audit

- The request contains no complete Hook identity or historical run identity.
- The actual retrieval scope is an allowlist of `Assets/Scripts/Modules-ASM` and `Datablocks` under the supplied R8 root.
- Natural API identifiers inside those roots are legitimate source facts.
- Historical BetterHitFeedback implementation, technical annotation, Runtime expected/support records, project/queue documents, fixed-answer tests, and prior Agent/RAG output are explicitly excluded from actual retrieval.
- Current assembly, historical implementation, and Runtime records may support independent annotation review; they are not actual retrieval inputs.
- The validator checks the request for the fixture's fixed complete-answer literals and verifies the manifest allowlist and excluded source classes.

This is a fixture-bound leakage check, not a held-out, promotion, RAG-quality, or Data Readiness claim.
