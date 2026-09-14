# Token Usage and Cost Analysis

## Summary

The pipeline that produced the submitted `output.csv` (`python3 main.py --requests
requests.csv --out output.csv`) makes **zero live model/API calls**. It is a deterministic
Python engine: CSV parsing, arithmetic (currency conversion, recurring-cadence detection,
90-day balance simulation), and rule-based text classification/generation. There is no
model provider, no API key, and no per-request token cost for the run that generated the
submitted predictions.

| Metric (final full-dataset run) | Value |
|---|---|
| Model provider / model name | None -- no live model call in the run |
| Model calls | 0 |
| Input tokens | 0 |
| Output tokens | 0 |
| Total tokens | 0 |
| Requests processed | 250 |
| Average tokens / request | 0 |
| Estimated total cost | $0.00 |
| Estimated cost / request | $0.00 |
| Wall-clock run time (250 requests) | ~0.57 s (measured on the development machine) |

## Why there is no model-call cost to report

This solution was developed and run in a sandbox with no `ANTHROPIC_API_KEY` (or any other
model-provider credential) available and no network access to model endpoints. Two design
choices follow from that constraint, both explained in `README.md`:

1. **Message understanding** (`message_rules.py`) is implemented as a rule-based classifier
   over a small, fixed set of ~40 semantic templates that the `messages.csv` generator
   reuses across users and languages (English/Indonesian). Every one of the 215 messages in
   the provided dataset is classified via a distinctive, language-agnostic key phrase, then
   amounts/dates/percentages are pulled out with regex. This was verified to reach 100%
   classification coverage on `messages.csv` (see development notes in `log.txt`).
2. **Image understanding** (`image_amounts.py`) -- the 16 `financial_events.csv` rows with a
   blank `amount` were resolved once by directly viewing the corresponding PNG in
   `dataset/media/images/` and reading the clearest authoritative total on each document
   (payslip net pay, receipt total, invoice grand total, etc.). The result is a fixed
   `event_id -> amount` lookup table, not a per-run vision-model call.

Both of these interpretation steps were performed once, by Claude, during development --
not as part of the `output.csv`-producing run, and not through the metered Anthropic API,
so there is no per-token API usage or dollar cost to attribute to them. That development-time
conversation is provided as this submission's `chat_transcript`.

## If a live model were substituted

`message_rules.py`'s `classify()` function is the natural integration point for a live
model call (e.g., structured-output extraction of the same `action` / `amount` / `date` /
`percent` fields) for messages outside this dataset's fixed template set, and
`image_amounts.py`'s lookup table could be replaced by a per-request vision-model call
against `dataset/media/images/<image_id>.png`. Rough order-of-magnitude estimate if that
were wired up using a model such as Claude Sonnet (as of this writing, ~$3 / MTok input,
~$15 / MTok output):

| Component | Est. calls / full run | Est. input tokens / call | Est. output tokens / call | Est. cost / full run |
|---|---|---|---|---|
| Message classification (215 messages, batched ~10/call) | ~22 | ~800 | ~300 | ~$0.02 |
| Image amount extraction (16 images, 1 call each, vision) | 16 | ~1,200 (incl. image) | ~50 | ~$0.07 |
| **Total (illustrative only, not incurred)** | ~38 | -- | -- | **~$0.09** |

These figures are provided only to show the order of magnitude if a live-model variant were
used; they were not incurred in producing the submitted `output.csv`, whose model-call count
and cost are both exactly zero as stated above.
