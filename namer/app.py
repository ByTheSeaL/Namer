"""Namer — PySide6 (Qt) UI.

Layout: description panel on the left; results tabs on the right —
"Simple" (local generators + Datamuse, free) and "Ask LLM" (OpenRouter).
"""

import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QMainWindow,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import datamuse, generators, llm

STYLE = """
QMainWindow, QWidget { font-size: 13px; }
QPlainTextEdit, QTreeWidget, QComboBox {
    border: 1px solid #c8c8d0; border-radius: 6px; padding: 4px;
    background: palette(base);
}
QPushButton {
    background: #4a6cf7; color: white; border: none; border-radius: 6px;
    padding: 8px 14px; font-weight: 600;
}
QPushButton:hover { background: #3b5be0; }
QPushButton:disabled { background: #a9b4d0; }
QTabWidget::pane { border: 1px solid #c8c8d0; border-radius: 6px; top: -1px; }
QTabBar::tab { padding: 6px 18px; }
QTreeWidget::item { padding: 3px; }
QLabel[hint="true"] { color: #888; }
"""


class Bridge(QObject):
    """Thread-safe channel from worker threads to the UI (queued signals)."""
    models_ready = Signal(list)
    results_ready = Signal(object, list, str)  # tree, rows, status


class NamerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Namer — Name Something")
        self.resize(920, 560)

        self.bridge = Bridge()
        self.bridge.models_ready.connect(self._set_models)
        self.bridge.results_ready.connect(self._show_results)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        self.setCentralWidget(splitter)

        self.statusBar().showMessage(
            "Describe the thing you want to name, then pick a tab.")

        threading.Thread(target=self._load_models, daemon=True).start()

    # ---------- left panel: description ----------

    def _build_left(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 6, 12)

        layout.addWidget(QLabel("Context"))
        self.context = QComboBox()
        self.context.addItems(generators.CONTEXTS)
        layout.addWidget(self.context)

        layout.addSpacing(8)
        layout.addWidget(QLabel("Describe the thing to name"))
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText(
            "e.g. a background service that watches folders and "
            "syncs changed files to the cloud")
        layout.addWidget(self.description, stretch=1)

        self.generate_btn = QPushButton("Generate names")
        self.generate_btn.clicked.connect(self.on_generate)
        self.generate_btn.setShortcut("Ctrl+Return")
        layout.addWidget(self.generate_btn)
        return panel

    # ---------- right panel: tabs ----------

    def _build_right(self):
        self.tabs = QTabWidget()

        # Simple tab
        simple = QWidget()
        s_layout = QVBoxLayout(simple)
        s_layout.setContentsMargins(8, 8, 12, 8)
        self.simple_tree = self._make_tree()
        s_layout.addWidget(self.simple_tree)
        s_layout.addWidget(self._hint_label())
        self.tabs.addTab(simple, "Simple")

        # Ask LLM tab
        llm_tab = QWidget()
        l_layout = QVBoxLayout(llm_tab)
        l_layout.setContentsMargins(8, 8, 12, 8)
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model"))
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(llm.FALLBACK_MODELS)
        model_row.addWidget(self.model, stretch=1)
        l_layout.addLayout(model_row)
        self.llm_tree = self._make_tree()
        l_layout.addWidget(self.llm_tree)
        l_layout.addWidget(self._hint_label())
        self.tabs.addTab(llm_tab, "Ask LLM")

        return self.tabs

    def _make_tree(self):
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels(["Name", "Why"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setColumnWidth(0, 190)
        tree.itemDoubleClicked.connect(self._copy_item)
        return tree

    def _hint_label(self):
        label = QLabel("Double-click a name to copy it")
        label.setProperty("hint", True)
        return label

    def _copy_item(self, item, _column):
        name = item.text(0)
        QGuiApplication.clipboard().setText(name)
        self.statusBar().showMessage(f"Copied “{name}” to clipboard.")

    # ---------- generation ----------

    def _load_models(self):
        self.bridge.models_ready.emit(llm.list_models())

    def _set_models(self, models):
        current = self.model.currentText()
        self.model.clear()
        self.model.addItems(models)
        if current in models:
            self.model.setCurrentText(current)

    def on_generate(self):
        description = self.description.toPlainText().strip()
        if not description:
            self.statusBar().showMessage("Type a description first.")
            return
        context = self.context.currentText()
        self.generate_btn.setEnabled(False)

        if self.tabs.currentIndex() == 0:
            self.statusBar().showMessage("Generating free ideas (local + Datamuse)…")
            threading.Thread(target=self._run_simple, args=(description, context),
                             daemon=True).start()
        else:
            model = self.model.currentText().strip()
            self.statusBar().showMessage(f"Asking {model} via OpenRouter…")
            threading.Thread(target=self._run_llm, args=(description, context, model),
                             daemon=True).start()

    def _run_simple(self, description, context):
        keywords = generators.extract_keywords(description)
        extra = datamuse.associations(keywords)
        rows = generators.generate(keywords, context, extra_words=extra)
        source = "local + Datamuse" if extra else "local only (Datamuse unreachable)"
        if not rows:
            rows = [("—", "No usable keywords found; try a longer description.")]
        self.bridge.results_ready.emit(
            self.simple_tree, rows,
            f"{len(rows)} ideas ({source}). Generate again for a fresh shuffle.")

    def _run_llm(self, description, context, model):
        ok, reason = llm.is_available()
        if not ok:
            self.bridge.results_ready.emit(
                self.llm_tree, [("LLM not configured", reason.replace("\n", " "))],
                "LLM unavailable — Simple tab still works.")
            return
        try:
            keywords = generators.extract_keywords(description)
            seeds = datamuse.associations(keywords)
            rows = llm.suggest(description, context, model, seed_words=seeds)
            self.bridge.results_ready.emit(
                self.llm_tree, rows, f"{len(rows)} ideas from {model}.")
        except Exception as exc:
            self.bridge.results_ready.emit(
                self.llm_tree, [("Error", str(exc))], "LLM request failed.")

    def _show_results(self, tree, rows, status):
        tree.clear()
        for name, why in rows:
            tree.addTopLevelItem(QTreeWidgetItem([name, why]))
        self.statusBar().showMessage(status)
        self.generate_btn.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = NamerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
