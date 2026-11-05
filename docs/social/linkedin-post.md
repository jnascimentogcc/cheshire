# LinkedIn post for v0.2.0

Attach `linkedin-card.png` (1200 x 627, exported at 2x). Replace nothing but the link if you
publish from another account.

---

Which way should I go? "That depends on where you want to get to," said the Cheshire Cat.

That is the idea behind Cheshire, an open-source tool I have been building: it takes a requirement written in plain language and orients you towards the architectural building blocks it needs, the solutions in your catalog that are eligible, and why. The choice stays with the human.

What I care about most is where it does NOT use AI:

• Decisions come from explicit, versioned rules in your own catalog. The rule engine is deterministic and has no LLM dependency.
• The model only translates free text into the catalog's vocabulary and writes the explanation from the rule trace. Everything it returns is validated against the catalog, and every sentence of the rationale cites the trace entry it rests on.
• It never ranks or scores solutions. Options are listed neutrally, with their declared facts side by side.
• "Unknown" is a real answer. A missing fact becomes a question, not a guess.
• Gaps ("nothing in the catalog covers this") are shown as results, with the same weight as a recommendation, and they feed a work queue for architects.

v0.2.0 is out: consultations, catalog maintenance with an impact preview before every change, and per-item discussions where whoever opens one decides and closes it, with a decision record.

It is early. A few limits I would rather say up front: the OpenAI adapter has not been exercised much against the live API, there has been no accessibility audit yet, and the example catalog is fictional.

If you work on architecture, enterprise or solution, I would love feedback on the model: building blocks, rules, and a rationale you can audit.

https://github.com/jnascimentogcc/cheshire

#SoftwareArchitecture #EnterpriseArchitecture #OpenSource #ExplainableAI #ArchitectureDecisionRecords
