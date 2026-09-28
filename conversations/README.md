# Complete Fable conversation transcripts

These are all the generated conversations from the recorded pilot: **20 attempts, 19 accepted, 1 rejected, 53 dialogue lines**. They are synthetic conversations from Fable's Jev → joint writer → appraisal pipeline, not quotations from the original fictional works. No dialogue has been extended or rewritten.

| Run | Sampler seed | Accepted/attempted | Dialogue lines | Dialogue words |
| --- | ---: | ---: | ---: | ---: |
| [Romeo and Juliet — run 1](romeo-juliet-run-1.md) | 20260927 | 5/5 | 12 | 111 |
| [Romeo and Juliet — run 2](romeo-juliet-run-2.md) | 20260928 | 4/5 | 14 | 141 |
| [Susan and George — run 1](susan-george-run-1.md) | 20260927 | 5/5 | 14 | 186 |
| [Susan and George — run 2](susan-george-run-2.md) | 20260928 | 5/5 | 13 | 153 |

Each file includes every attempt in order, the complete dialogue, the sampled approach, affection before and after, and the appraiser's warmth ratings with their quoted evidence. Romeo and Juliet, run 2, attempt 2 was rejected: it changed neither the state nor model time, and its ratings were not applied.

The approach labels are candidates supplied to Jev. Selection is probabilistic; a selected label is not necessarily the highest-rated candidate or a discovered personality trait. The warmth scores are automated interpretations, not independent measurements of the characters' feelings.

Models: `jev-1.13.0` rates approaches; `moonshot.kimi-k2-thinking` writes both voices; `us.meta.llama4-scout-17b-instruct-v1:0` appraises the result. Sampler seeds control local approach selection only. Accepted encounters advance model time by 0.5; rejected ones do not.

The [public source JSON](../fable-pilot-results.json) retains the numeric data at full precision. Displayed affection values are rounded to six decimal places; dialogue and evidence quotes are verbatim. Dialogue word counts use whitespace-separated words and include the rejected attempt.

To regenerate these pages, run `python3 export-conversations.py` from the supplement directory. Run `python3 export-conversations.py --check` to verify all exported speech against the JSON without writing files.
