# Verifier evaluation: does it catch hallucinated figures?

81 grounded answers (40 offline, 41 Gemini), 367 genuine figures, 315 injected hallucinations. Deterministic (seed 7); run `python -m llm.eval.verifier_eval`.

| Metric | Original verifier | Current verifier |
|---|---|---|
| Real Gemini hallucinations caught (hand-audited, see below) | 0 of 10 | **10 of 10** |
| Hallucinations caught (overall) | 78% | **94%** |
| · true value ±1% | 80% | 96% |
| · true value ±3% | 76% | 89% |
| · true value ±10% | 77% | 95% |
| · true value ±30% | 75% | 93% |
| · true value ×10 slip | 81% | 99% |
| Random 1-decimal % accepted | 29% | **9%** |
| False alarms on genuine figures | 0.0% | **0.0%** (0 of 367) |

Original = differences and % changes allowed between any two numbers in all tool results, no unit check. Current = only between numbers in the same tool object, ₹ figures never match % fields (or vice versa), and a figure in a sentence that names a brand / retailer / variant must come from that entity's tool object.

## The real hallucinations

Two saved Gemini answers were marked *verified* and scored *correct* by the original evaluation, but every rupee figure in them is a lakh/crore slip:

- *Which retailer drives the most revenue for Dettol this year?* → ₹49.39 L, ₹38.96 L, ₹45.34 L, ₹44.34 L
- *Why did Dettol revenue fall this year?* → ₹1.10 Cr, ₹40.67 Cr, ₹63.4L, ₹29.1L, ₹17.9L, ₹164.1L

True values: Amazon ₹4.94 L and BigBasket ₹4.53 L (10× smaller); Dettol's YTD revenue is ₹40.67 **L**, the fall ₹1.10 L, mix ₹0.63 L, volume ₹0.29 L, discount ₹0.18 L, Variant 2 ₹1.64 L (100× smaller). The original verifier accepted them because, with thousands of pairwise differences to choose from, some unrelated difference matched each one.

A figure that is still accepted after a nudge is one that happens to match another real number in the results at the written precision. The verifier proves a figure *exists* in the data, not that it is attached to the right entity; that residual risk is why the tools return compact, labelled results.
