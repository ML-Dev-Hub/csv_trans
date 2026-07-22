---
title: Cookbooks
description: Runnable recipes for hosted, local, no-key, and fallback translation.
---

Complete, live-run recipes. Each translates only text-like columns, protects
placeholders, and returns a structured [`TranslationResult`](/csv_trans/reference/python-api/).

## Translate a catalog with OpenAI

Translate the text columns of a catalog with a hosted OpenAI model, leaving IDs,
prices, and codes untouched.

```python
import os
from csv_trans import translate
from csv_trans.providers import OpenAICompatibleProvider

openai = OpenAICompatibleProvider(
    model="gpt-4o-mini",
    base_url="https://api.openai.com/v1",
    api_key=os.environ["OPENAI_API_KEY"],
)

result = translate(
    "catalog.csv", "en", "es",
    provider=openai,
    columns=["text"],
    output_path="catalog.es.csv",
    overwrite=True,
)
print(result.status.value, "translated:", result.translated_cells, "cached:", result.cached_cells)
```

Given this input:

```text
id,text,code
1,Hello world,SKU-1
2,Hello world,SKU-2
3,Good morning,SKU-3
```

the output preserves `id` and `code` exactly and translates only `text`:

```text
id,text,code
1,Hola mundo,SKU-1
2,Hola mundo,SKU-2
3,Buenos días,SKU-3
```

`result.cached_cells` is `1` here: `"Hello world"` appears twice but is sent to
the model once and reused. On a 200-row file with ~10 distinct phrases, this
turns 200 cells into ~10 API calls.

### Let the engine pick the columns

Omit `columns` to auto-select. Numeric, identifier, URL/date, and
credential-named columns are skipped, so secrets are never sent:

```python
result = translate("catalog.csv", "en", "es", provider=openai, output_path="catalog.es.csv", overwrite=True)
print([c.name for c in result.selected_columns if c.selected])
```

For a `client_secret,greeting,amount` header this selects only `greeting`;
`client_secret` and `amount` are copied through untouched. See
[Column selection](/csv_trans/how-it-works/#column-selection).

### Placeholders survive

URLs and tokens are held back locally and reinserted byte-for-byte, so
`"Visit https://ex.com for {{n}} items"` becomes
`"Visitar https://ex.com para {{n}} artículos"` — the URL and `{{n}}` are
identical in the output. See
[Placeholder protection](/csv_trans/how-it-works/#placeholder-protection--chunking).

:::note
`OPENAI_API_KEY` is read here by your code, not by the provider. The
[CLI](/csv_trans/reference/cli/) reads `CSV_TRANS_OPENAI_API_KEY` (falling back to
`OPENAI_API_KEY`) for you.
:::

## Translate confidential data locally

Route translation through a local model server (Ollama, vLLM, LM Studio, or
llama.cpp) and set `privacy="local-only"` so no cell can leave the machine. The
mode validates every endpoint as loopback before any text is submitted.

```python
from csv_trans import translate_csv, TranslationConfig
from csv_trans.providers import OpenAICompatibleProvider

ollama = OpenAICompatibleProvider(
    model="qwen2.5:14b-instruct",
    base_url="http://localhost:11434/v1",  # Ollama's OpenAI-compatible endpoint
    api_key=None,                          # local servers usually need no key
    timeout=240.0,
)

config = TranslationConfig(
    source_language="en",
    target_language="es",
    provider=ollama,
    columns=["CIPTitle"],
    privacy="local-only",
)

result = translate_csv("cip_taxonomy.csv", config, output_path="cip_taxonomy.es.csv")
print(result.status.value, result.translated_cells)
```

Run against a real public taxonomy (US CIP program codes), this translates the
`CIPTitle` column while preserving the spreadsheet-guarded codes exactly:

```text
CIPCode,CIPTitle
="01.0000","AGRICULTURAL/ANIMAL/PLANT/VETERINARY SCIENCE AND RELATED FIELDS."
="01.0101","Agriculture, General."
```

becomes

```text
CIPCode,CIPTitle
="01.0000","CIENCIA AGRÍCOLA/ANIMAL/PLANTA/VETERINARIA Y RAMAS AFINES."
="01.0101","Agricultura, general."
```

The `="01.0000"` Excel text-guards pass through byte-for-byte — the engine never
reinterprets field values.

### The boundary is enforced, not advisory

`local-only` rejects a remote endpoint before contacting it:

```python
from csv_trans import PrivacyViolation

remote = OpenAICompatibleProvider(model="gpt-4o-mini", base_url="https://api.openai.com/v1", api_key="sk-...")
try:
    translate_csv("cip_taxonomy.csv", TranslationConfig(
        source_language="en", target_language="es", provider=remote, privacy="local-only",
    ), output_path="out.csv")
except PrivacyViolation as exc:
    print(exc)  # "local-only mode rejected openai-compatible: ..."
```

A non-loopback host on the LAN can be allowed explicitly with
`approved_local_hosts=("model.internal",)`. See
[Privacy modes](/csv_trans/privacy-and-security/) for the exact rules and their
limits.

:::caution
`local-only` verifies the network destination. It cannot make an independently
operated local model trustworthy — deployment, logs, and model retention remain
your responsibility.
:::

## Quick translation with no API key

`GoogleFreeProvider` needs no credentials, which makes it convenient for quick,
non-sensitive jobs.

```python
from csv_trans import translate
from csv_trans.providers import GoogleFreeProvider

result = translate(
    "messages.csv", "en", "es",
    provider=GoogleFreeProvider(),
    columns=["text"],
    output_path="messages.es.csv",
    overwrite=True,
)
```

Placeholders are protected here too — `"Hello {{name}}, good morning"` becomes
`"Hola {{name}}, buen día"`, with `{{name}}` unchanged.

This is also the provider used when you set no provider at all
(`provider=None`), which is why the CLI prints a disclosure warning on that path.

:::caution
This adapter calls undocumented Google web endpoints, not Google Cloud
Translation. It can change, throttle, or stop working without notice and offers
no uptime or privacy guarantee. Use it for experiments, not production or
confidential data.
:::

## Fallbacks and partial results

A run never silently drops a cell. Transient errors retry, and only unresolved
items move to a fallback provider; a cell that still fails keeps its complete
original value and is reported.

### Add a fallback provider

Unresolved items move to `fallback_providers` in order. Here OpenAI is primary
and the no-key Google adapter is the backup:

```python
import os
from csv_trans import translate_csv, TranslationConfig
from csv_trans.providers import OpenAICompatibleProvider, GoogleFreeProvider

config = TranslationConfig(
    source_language="en",
    target_language="es",
    provider=OpenAICompatibleProvider(
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key=os.environ["OPENAI_API_KEY"],
    ),
    fallback_providers=(GoogleFreeProvider(),),
    columns=["text"],
    report_path="run.report.json",
)

result = translate_csv("catalog.csv", config, output_path="catalog.es.csv", overwrite=True)
print(result.status.value, "fallbacks:", result.fallbacks)
```

Privacy is re-checked before every provider call, so a fallback that would cross
your privacy boundary is rejected rather than used.

### Handle a partial run

`status` is `partial` when one or more cells were preserved rather than
translated. Those cells hold their original value in the output CSV, and each
appears in `failures`:

```python
if result.status.value == "partial":
    for failure in result.failures:
        print(f"row {failure.row} col {failure.column_index}: {failure.category} — {failure.message}")
```

Failure `message` and `category` are safe, category-derived strings — never the
source cell text or a credential. See
[Failure recovery](/csv_trans/how-it-works/#failure-recovery) and
[TranslationResult](/csv_trans/reference/python-api/).

### Exit codes for scripts

The [CLI](/csv_trans/reference/cli/) mirrors this: `0` for success, `2` for a partial
result (output written, some cells preserved), `1` for a fatal error.
