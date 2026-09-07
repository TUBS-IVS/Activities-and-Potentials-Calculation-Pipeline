#!/usr/bin/env python
"""nb_clean_filter.py — git clean filter for notebooks.

Strips editor-injected metadata that changes every time a notebook is opened,
WITHOUT touching the stored results. The notebooks in this repository carry
their cell outputs on purpose: they are the record of the run the README's
figures come from, so a blanket `nbstripout` would destroy the thing we want
to keep.

Removed:
  * `application/vnd.microsoft.datawrangler.viewer.v0+json` output bundles —
    VS Code's Data Wrangler extension writes a full column schema into every
    DataFrame output when the notebook is opened, adding hundreds of lines of
    churn per file.
  * A machine-specific kernelspec — normalised to plain `python3`, so a local
    conda env name never lands in a published notebook.

Kept, deliberately: every stream, execute_result, display_data and error
output, and all execution counts. Only genuinely editor-generated metadata
goes; anything the code actually produced stays.

Wiring (per clone — git filter config is local, never committed):

    git config filter.nbclean.clean "python scripts/nb_clean_filter.py"
    git config filter.nbclean.smudge cat

`.gitattributes` already routes *.ipynb through this filter. A clone that has
not run the config above is unaffected: git ignores an undefined filter, so
nothing breaks, the noise simply is not stripped.
"""
import json
import sys

DROP_MIME = "application/vnd.microsoft.datawrangler.viewer.v0+json"

CANONICAL_KERNELSPEC = {
    "display_name": "Python 3",
    "language": "python",
    "name": "python3",
}


def clean(nb):
    removed_mime = 0

    for cell in nb.get("cells", []):
        for output in cell.get("outputs", []):
            data = output.get("data")
            if isinstance(data, dict) and DROP_MIME in data:
                del data[DROP_MIME]
                removed_mime += 1
            # the same key can appear in the per-output metadata block
            meta = output.get("metadata")
            if isinstance(meta, dict) and DROP_MIME in meta:
                del meta[DROP_MIME]
                removed_mime += 1

    if "kernelspec" in nb.get("metadata", {}):
        nb["metadata"]["kernelspec"] = dict(CANONICAL_KERNELSPEC)

    return removed_mime


def main():
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        sys.stdout.buffer.write(raw)
        return

    try:
        nb = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Never destroy content we cannot parse — pass it through untouched.
        sys.stdout.buffer.write(raw)
        return

    clean(nb)

    # nbformat writes 1-space indent and a trailing newline. Key order is left
    # exactly as read (no sort_keys) so an already-clean notebook round-trips
    # byte-for-byte and the filter introduces no diff of its own.
    out = json.dumps(nb, indent=1, ensure_ascii=False)
    sys.stdout.buffer.write((out + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
