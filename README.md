# Namer — Name Something

A small cross-platform desktop app (Windows / Linux / macOS) that helps you
name things: code identifiers, fiction characters, paper titles, products.

## How it works

Type a description of the thing on the **left**, pick a context, and hit
**Generate**. Your description goes to any model on
[OpenRouter](https://openrouter.ai) — the model picker is searchable (type
any substring) and has a "Free only" filter for OpenRouter's no-cost models.

Results come back as names with rationales:

- **Double-click** a name to copy it.
- **Right-click** a name to iterate on it: *More like this* (expand the
  idea), *Variations* (close permutations), or *Refine* (keep what works,
  fix the rest).

The description box learns: uncommon words you've typed before reappear as
grey inline suggestions — press Tab to accept.

## Running from source

Requires Python 3.10+ and PySide6 (Qt for Python, LGPL):

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py        # or: .venv/bin/python -m namer
```

## OpenRouter key

Either set the environment variable:

```sh
export OPENROUTER_API_KEY=sk-or-...
```

or open **File → Settings** in the app and paste it there (stored in
`~/.config/namer/openrouter_key`). Get a key at <https://openrouter.ai/keys>.

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
  app.py         PySide6 (Qt) UI (left: description; right: results + model picker)
  llm.py         OpenRouter client: live model list, suggest + iterate prompts
  wordstore.py   SQLite-backed word store powering the inline autocomplete
  constants.py   contexts and stopwords
run.py           launcher / PyInstaller entry point
```
