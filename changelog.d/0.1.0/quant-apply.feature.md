Quantization is now applied through a single torch-free `QuantSpec` registry
(`src/kiln/quant/apply.py`). The serve path (`CUDABackend.load_model`, gateway
`/v1/load`, `LoadModelRequest.quantization`) and the training path (`sft`/`dpo`)
both route through it: `none`/`4bit`/`8bit` are applied at load/train time,
while `gptq`/`awq` load pre-quantized artifacts (their `config.json` carries the
quantizer). Unknown scheme names raise a mapped USAGE error. Capability probes
for gptq/awq/auto-gptq/auto-awq were added to `_compat.py`.
