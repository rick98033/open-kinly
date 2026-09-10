# Evidence and claim boundary

Two retained records support two different claims:

- `clean-room-authoring.json` records the first no-retry model sample against
  Kinly's full candidate capability catalog. The program matched the expected
  five-call graph and passed deterministic compilation. It did not execute a
  phone.
- `pixel-live-candidate.json` records one end-to-end candidate run on a physical
  Pixel. The same request was planned in one call, every action received an
  explicit terminal state, and the video hash binds the included recording.

The public source is a five-capability reference extraction. Its prompt text
matches the approved candidate instruction, but its reduced catalog produces a
different schema, prompt size, and fingerprints from the retained full-catalog
runs. The checked-in golden program makes the compiler and executor behavior
reproducible without a model or a phone.

The live demo used candidate-only percentage inputs for media volume and text
size. Those semantics made the battery percentage directly type-compatible
with both arguments. Kinly production's prompt was not changed for this demo.

No reliability rate, cost comparison, power measurement, training result,
general arbitrary-program synthesis, or production deployment claim is made.
Raw operational logs are intentionally excluded because they contain private
identifiers unrelated to the technical claim.
