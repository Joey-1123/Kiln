New `kiln quantize` command produces persistent quantization artifacts from a
fine-tuned model. `gptq` runs full GPTQ via auto-gptq; `awq` runs auto-awq and
additionally emits a GGUF for CPU serving. Calibration data (JSONL) is required.
The torch-free `QuantJob` validates scheme/model/calibration before any heavy
import. A new `[quant]` extra holds the (heavy) auto-gptq/auto-awq deps so the
fast suite stays light.
