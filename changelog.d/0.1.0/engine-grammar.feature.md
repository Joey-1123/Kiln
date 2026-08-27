V2 — xgrammar / constrained-decoding passthrough. `GenerateRequest` gains a `grammar`
field; the gateway's OpenAI + Anthropic chat endpoints accept `grammar` and forward
it to the engine. Empty string = unconstrained.
