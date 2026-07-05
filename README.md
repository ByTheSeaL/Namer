# Namer — Name Something

A small cross-platform desktop app (Windows / Linux / macOS) that helps you
name things: code identifiers, fiction characters, paper titles, products.

## How it works

Type a description of the thing on the **left**, pick a context, and choose
a tab on the right:

- **Simple** — free and instant. Extracts keywords from your description,
  enriches them with word associations from the [Datamuse API](https://www.datamuse.com/api/)
  (free, no key, works offline in degraded mode), and mashes them into
  portmanteaus, compounds, and affixed coinages styled for your context.
- **Ask LLM** — sends your description (seeded with the Datamuse research)
  to any model on [OpenRouter](https://openrouter.ai). Pick from the live
  model list in the dropdown. Returns names with rationales.

Double-click any result to copy it to the clipboard.

## Running from source

No dependencies beyond Python 3.10+ (Tkinter ships with Python — on some
Linux distros install `python3-tk`). No venv needed.

```sh
python3 run.py        # or: python3 -m namer
```

## OpenRouter key (for the Ask LLM tab)

Either set the environment variable:

```sh
export OPENROUTER_API_KEY=sk-or-...
```

or put the key on the first line of `~/.config/namer/openrouter_key`.
Get a key at <https://openrouter.ai/keys>. The Simple tab works without any key.

## Building standalone binaries (EXE etc.)

[PyInstaller](https://pyinstaller.org) bundles the app plus a Python
interpreter into a single executable. It must run **on the target OS** —
build the Windows EXE on Windows, the macOS app on macOS:

```sh
pip install pyinstaller
pyinstaller --onefile --windowed --name Namer run.py
# result: dist/Namer.exe (Windows), dist/Namer (Linux), dist/Namer.app (macOS)
```

The included GitHub Actions workflow (`.github/workflows/build.yml`) does
this automatically on all three OSes — push a `v*` tag (or trigger it
manually) and download the artifacts from the Actions run.

## Layout

```
namer/
  app.py         Tkinter UI (left: description; right: Simple / Ask LLM tabs)
  generators.py  local offline name generators (portmanteau, affixes, casing)
  datamuse.py    free word-association API client (stdlib urllib)
  llm.py         OpenRouter client with live model list (stdlib urllib)
run.py           launcher / PyInstaller entry point
```
