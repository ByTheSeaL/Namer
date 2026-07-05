"""Namer — Tkinter UI.

Layout: description panel on the left; results notebook on the right with
two tabs — "Simple" (local generators + Datamuse, free) and "Ask LLM".
"""

import queue
import threading
import tkinter as tk
from tkinter import ttk

from . import datamuse, generators, llm


class NamerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Namer — Name Something")
        self.geometry("860x520")
        self.minsize(680, 400)

        # Worker threads never touch Tk directly — they post results here,
        # and the main loop drains the queue. Must exist before any panel
        # spawns a background thread.
        self._results = queue.Queue()

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=2, minsize=260)
        root.columnconfigure(1, weight=3)
        root.rowconfigure(0, weight=1)

        self._build_left(root)
        self._build_right(root)

        self.status = tk.StringVar(value="Describe the thing you want to name, then pick a tab.")
        ttk.Label(self, textvariable=self.status, anchor="w", padding=(10, 2)).pack(fill="x")

        self.after(100, self._poll_results)

    def _poll_results(self):
        try:
            while True:
                kind, payload = self._results.get_nowait()
                if kind == "models":
                    self.model.configure(values=payload)
                else:  # kind is a tree; payload is (rows, status)
                    rows, status = payload
                    self._fill(kind, rows)
                    self.status.set(status)
                    self.generate_btn.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._poll_results)

    # ---------- left panel: description ----------

    def _build_left(self, parent):
        left = ttk.Frame(parent)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        ttk.Label(left, text="Context").grid(row=0, column=0, sticky="w")
        self.context = ttk.Combobox(left, values=list(generators.CONTEXTS), state="readonly")
        self.context.set("Code")
        self.context.grid(row=1, column=0, sticky="ew", pady=(2, 10))

        ttk.Label(left, text="Describe the thing to name").grid(row=2, column=0, sticky="nw")
        left.rowconfigure(3, weight=1)
        self.description = tk.Text(left, wrap="word", height=10, undo=True)
        self.description.grid(row=3, column=0, sticky="nsew", pady=(2, 10))

        self.generate_btn = ttk.Button(left, text="Generate names", command=self.on_generate)
        self.generate_btn.grid(row=4, column=0, sticky="ew")
        self.description.bind("<Control-Return>", lambda e: self.on_generate())

    # ---------- right panel: tabs ----------

    def _build_right(self, parent):
        self.tabs = ttk.Notebook(parent)
        self.tabs.grid(row=0, column=1, sticky="nsew")

        self.simple_tree = self._make_results_tab("Simple")

        llm_frame = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(llm_frame, text="Ask LLM")
        llm_frame.columnconfigure(0, weight=1)
        llm_frame.rowconfigure(1, weight=1)

        model_row = ttk.Frame(llm_frame)
        model_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        model_row.columnconfigure(1, weight=1)
        ttk.Label(model_row, text="Model").grid(row=0, column=0, padx=(0, 6))
        self.model = ttk.Combobox(model_row, values=llm.FALLBACK_MODELS)
        self.model.set(llm.FALLBACK_MODELS[0])
        self.model.grid(row=0, column=1, sticky="ew")
        threading.Thread(target=self._load_models, daemon=True).start()

        self.llm_tree = self._make_tree(llm_frame, row=1)

    def _load_models(self):
        self._results.put(("models", llm.list_models()))

    def _make_results_tab(self, label):
        frame = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(frame, text=label)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return self._make_tree(frame, row=0)

    def _make_tree(self, frame, row):

        tree = ttk.Treeview(frame, columns=("name", "why"), show="headings", selectmode="browse")
        tree.heading("name", text="Name")
        tree.heading("why", text="Why")
        tree.column("name", width=170, anchor="w")
        tree.column("why", width=320, anchor="w")
        tree.grid(row=row, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=row, column=1, sticky="ns")

        ttk.Label(frame, text="Double-click a name to copy it", foreground="gray").grid(
            row=row + 1, column=0, sticky="w", pady=(4, 0))
        tree.bind("<Double-1>", self._copy_selected)
        return tree

    def _copy_selected(self, event):
        tree = event.widget
        sel = tree.selection()
        if sel:
            name = tree.item(sel[0], "values")[0]
            self.clipboard_clear()
            self.clipboard_append(name)
            self.status.set(f"Copied “{name}” to clipboard.")

    def _fill(self, tree, rows):
        tree.delete(*tree.get_children())
        for name, why in rows:
            tree.insert("", "end", values=(name, why))

    # ---------- generation ----------

    def on_generate(self):
        description = self.description.get("1.0", "end").strip()
        if not description:
            self.status.set("Type a description first.")
            return
        context = self.context.get()
        active = self.tabs.index(self.tabs.select())  # 0 = Simple, 1 = Ask LLM

        self.generate_btn.configure(state="disabled")
        if active == 0:
            self.status.set("Generating free ideas (local + Datamuse)…")
            threading.Thread(target=self._run_simple, args=(description, context),
                             daemon=True).start()
        else:
            model = self.model.get().strip()
            self.status.set(f"Asking {model} via OpenRouter…")
            threading.Thread(target=self._run_llm, args=(description, context, model),
                             daemon=True).start()

    def _run_simple(self, description, context):
        keywords = generators.extract_keywords(description)
        extra = datamuse.associations(keywords)
        rows = generators.generate(keywords, context, extra_words=extra)
        source = "local + Datamuse" if extra else "local only (Datamuse unreachable)"
        if not rows:
            rows = [("—", "No usable keywords found; try a longer description.")]
        self._results.put((self.simple_tree,
                           (rows, f"{len(rows)} ideas ({source}). Generate again for a fresh shuffle.")))

    def _run_llm(self, description, context, model):
        ok, reason = llm.is_available()
        if not ok:
            self._results.put((self.llm_tree,
                               ([("LLM not configured", reason.replace("\n", " "))],
                                "LLM unavailable — Simple tab still works.")))
            return
        try:
            keywords = generators.extract_keywords(description)
            seeds = datamuse.associations(keywords)
            rows = llm.suggest(description, context, model, seed_words=seeds)
            self._results.put((self.llm_tree, (rows, f"{len(rows)} ideas from {model}.")))
        except Exception as exc:
            self._results.put((self.llm_tree, ([("Error", str(exc))], "LLM request failed.")))


def main():
    NamerApp().mainloop()


if __name__ == "__main__":
    main()
