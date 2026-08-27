`init` command implemented (was the last remaining CLI stub). Creates a
`kiln.yaml` from a template (`chat` | `train` | `serve`), interactive with
prompts or non-interactive via `--model`/`--data`. Writes through the Pydantic
schema so the result always round-trips via `load_config`. Refuses to
overwrite without `--force`. `tests/test_init.py` covers all four paths.
