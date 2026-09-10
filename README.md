# Open Kinly

Open Kinly is a small, runnable reference implementation of a pattern we call
**schema-constrained semantic compilation**:

```text
natural-language request + typed capability catalog
                         |
                         v
              bounded JSON program
                         |
                         v
               typed action graph
                         |
                         v
        authorized execution + explicit outcomes
```

The model proposes an inert program in one planning call. Deterministic code
owns schema generation, semantic validation, dependency lowering, per-action
authorization, execution, and outcome truth.

## The toy request

> Check my battery percentage. Use that number for both media volume and text
> size, turn on the flashlight, and lower the brightness if the battery is
> below 20 percent.

The resulting five-node graph has one battery read, two consumers of that
result, an independent flashlight action, and a conditional brightness action:

```text
c1 device_battery.get_status
 |- c2 media_volume.set(ref c1.battery_percent)
 |- c3 text_size.set(ref c1.battery_percent)
 `- c5 brightness.decrease(when c1.battery_percent < 20)

c4 flashlight.on
```

[Watch the Pixel demo](media/kinly-l5-pixel-demo.mp4).

## Run the deterministic replay

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
open-kinly --program examples/l5_program.json --execute-toy --battery 80
```

This prints the authored program, its typed graph, and one terminal outcome for
every node. No phone is controlled by this repository.

To make one real planning call against a compatible local endpoint:

```bash
open-kinly \
  --base-url http://127.0.0.1:8080/v1 \
  --model Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8 \
  --utterance "Check my battery percentage. Use that number for both media volume and text size, turn on the flashlight, and lower the brightness if the battery is below 20 percent." \
  --execute-toy
```

The included prompt is the exact approved clean-room candidate instruction.
The included catalog is only the five-capability projection needed for this
example; adding declarations expands the language without adding routing
branches.

## Retained evidence

The clean-room run used an off-the-shelf Qwen model, temperature 0, thinking
disabled, one model call, and no retry. It authored the expected five calls
against Kinly's full candidate catalog in 2,851 prompt tokens and 207 completion
tokens. Generation took 6,349.9 ms and deterministic compilation took 0.395 ms.

The live candidate then ran the same request on a physical Pixel. That one
planning call used 2,877 prompt tokens and 207 completion tokens in 6,220.7 ms.
At battery 80, the two references materialized as 80, the flashlight completed,
and the guarded brightness action reported `skipped`.

See [evidence/README.md](evidence/README.md) for the exact claim boundary and
sanitized records.

## Scope

This repository demonstrates direct same-type result references, fan-out, one
simple comparison guard, independent work, failure propagation, and explicit
per-node outcomes. It does not claim compound Boolean control, transformation
or formatting nodes, arbitrary code generation, or autonomous authority.

The in-memory phone adapter is intentionally a toy. Kinly's production identity,
policy, signed authorization, connectors, device runtime, and recovery machinery
are not included.
