---
title: Getting started
description: Install csv-trans and translate a CSV in Python and from the CLI — offline with echo, then with a real provider.
---

Install csv-trans, prove the pipeline end-to-end with the offline `echo`
provider, then point the same code and commands at a real endpoint.

## Install

```bash
python -m pip install csv-trans
```

`csv-trans` `2.0.0` runs on CPython **3.11, 3.12, 3.13, and 3.14** with **no
third-party runtime dependencies** — the engine uses the standard library alone.

Installation provides two identical console scripts, and the package is also
runnable as a module:

```bash
csv-trans --help
csv_trans --help
python -m csv_trans --help
```

Verify the install, then confirm an end-to-end run with the offline `echo`
provider, which needs no credentials or network:

```bash
python -c "import csv_trans; print(csv_trans.__version__)"   # 2.0.0

printf 'id,text\n1,hello\n' > smoke.csv
csv-trans -f smoke.csv -sl en -tl fr --provider echo --columns text \
  --output smoke.out.csv --privacy local-only --quiet
```

For local development, an editable install works the same way:

```bash
git clone https://github.com/ML-Dev-Hub/csv_trans
cd csv_trans
python -m pip install -e .
```

## Quickstart: translate offline

The examples use this catalog:

```text title="catalog.csv"
id,title,description,price
1,Wireless mouse,Ergonomic 2.4GHz mouse,19.99
2,USB-C cable,Braided 1m cable,7.50
```

The `echo` provider returns text unchanged, so this runs anywhere and exercises
the full pipeline — column selection, structure preservation, atomic write, and
the structured result:

```python
from csv_trans import translate
from csv_trans.providers import EchoProvider

result = translate("catalog.csv", "en", "fr", provider=EchoProvider())

print(result.status.value)        # "success"
print(result.output_path)         # translated_fr_catalog.csv
print(result.translated_cells)    # cells whose translation fully succeeded
print(result.skipped_cells)       # id/price columns skipped automatically
for column in result.selected_columns:
    print(column.index, column.name, column.selected, column.reason)
```

`translate(input_path, source_language, target_language, sep=None, *, output_path=None, **options)`
is the ergonomic wrapper: it builds a
[`TranslationConfig`](/csv_trans/reference/python-api/) from your keyword options and calls
the engine. Automatic selection keeps `id` and `price` out of the request;
`title` and `description` are translated. Headers are preserved unless you pass
`translate_headers=True`. When you already hold a config object, call
[`translate_csv`](/csv_trans/reference/python-api/) directly:

```python
from csv_trans import TranslationConfig, translate_csv
from csv_trans.providers import EchoProvider

config = TranslationConfig(
    source_language="en",
    target_language="fr",
    provider=EchoProvider(),
    columns=("title", "description"),   # names or zero-based indexes
)
result = translate_csv("catalog.csv", config, output_path="catalog.fr.csv")
```

:::note
In the Python API, `provider=` takes a **provider object** (such as
`EchoProvider()`), not a string. The short aliases like `echo` or `openai` are a
convenience of the [CLI](/csv_trans/reference/cli/) only.
:::

## From the CLI

The equivalent command, with an explicit output path:

```bash
csv-trans -f catalog.csv -sl en -tl fr \
  --provider echo \
  --output catalog.fr.csv \
  --privacy local-only
```

`--dry-run` inspects column selection without contacting any provider — it never
needs a key and never writes a CSV:

```bash
csv-trans -f catalog.csv -sl en -tl fr --dry-run
# dry-run: translated=0, failed=0, skipped=...; selected-columns=#1='title' (text-like values), ...
```

## Point at a real provider

Credentials come from the environment, not a flag. Point at any
OpenAI-compatible endpoint:

```bash
export CSV_TRANS_OPENAI_API_KEY="sk-..."
export CSV_TRANS_OPENAI_MODEL="gpt-4o-mini"

csv-trans -f catalog.csv -sl en -tl fr --provider openai --privacy restricted
```

The same run in Python constructs the provider explicitly:

```python
import os
from csv_trans import TranslationConfig, translate_csv
from csv_trans.providers import OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    model=os.environ["CSV_TRANS_OPENAI_MODEL"],
    base_url="https://api.openai.com/v1",
    api_key=os.environ["CSV_TRANS_OPENAI_API_KEY"],
)
config = TranslationConfig(
    source_language="en",
    target_language="fr",
    provider=provider,
    privacy="restricted",
    allowed_providers=(provider.provider_id,),
)
result = translate_csv("catalog.csv", config)
```

To keep data on a machine you control, point `base_url` at a local
OpenAI-compatible server (Ollama, vLLM, LM Studio, llama.cpp) under `local-only`
privacy. See [Providers](/csv_trans/providers/) for every adapter and
[Privacy and security](/csv_trans/privacy-and-security/) for the loopback rule
and its threat-model limits.

If a cell cannot be translated after all recovery, its original value is
preserved and the run is reported as `partial`; from the CLI a partial run exits
with code `2`. See [How it works](/csv_trans/how-it-works/) for selection,
recovery, and reports.
