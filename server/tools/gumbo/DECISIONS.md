
**D29. The Q4 is dropped; the quality comparison the user means is full attention vs hybrid (user).** "I don't
see any reason to assume 27B Q4_K_M is worth it, it's only marginally faster and does worse" (D25: 12.0 vs
13.7 s a call, 66/90 both, commands 20 vs 21, adjudicator errors 3 vs 2). So the dense candidate is the Q6
(`qwen27b`); the queued two-pass trial moves to it (`q27-twopass`); `qwen27b-q4` stays as a profile only. The
comparison that matters for quality is **Qwen3-32B (full attention in every layer) vs Qwen3.5-27B (hybrid,
three linear layers in four)**: on the key the 32B judged worse (56/88, 18+3/24 against 66/90, 23/24), but the
key measures the structured roles on Sonnet-narrated turns; the user's criteria (D26) are long contexts and the
prose, which need a played game and the user's own reading. Per D26 the 32B profile now uses the card: CTX
65536 (21k a slot, about 29 GB) instead of 49152. *Note for the comparison:* every Qwen3.5 size is the hybrid
layout, so a full-attention model of this class is another family or the older Qwen3; also on gumbo already and
full-attention: TheDrummer's Cydonia-24B v4.3 (Mistral Small base; Q5/Q6/Q8) and Skyfall-31B v4.2, prose
finetunes whose structured output is untested here.
