"""Namer — PySide6 (Qt) UI.

Layout: description panel on the left (context radioset + autocompleting
text box); results tabs on the right — "Simple" (local generators +
Datamuse, free) and "Ask LLM" (OpenRouter) — each with its own
Generate/Regenerate button.
"""

import re
import sys
import threading

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
    QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__, datamuse, generators, llm
from .wordstore import WordStore

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


class CompletingTextEdit(QPlainTextEdit):
    """QPlainTextEdit with inline (ghost-text) autocomplete.

    As you type a word, the best completion from the WordStore appears in
    grey after the cursor; Tab accepts it, Escape dismisses it.
    """

    def __init__(self, store: WordStore):
        super().__init__()
        self._store = store
        self._suggestion = ""  # the not-yet-typed remainder of the match
        self.cursorPositionChanged.connect(self._refresh_suggestion)
        self.textChanged.connect(self._refresh_suggestion)

    def _current_prefix(self) -> str:
        cursor = self.textCursor()
        block_text = cursor.block().text()[:cursor.positionInBlock()]
        match = re.search(r"[a-zA-Z]+$", block_text)
        return match.group(0) if match else ""

    def _refresh_suggestion(self):
        prefix = self._current_prefix()
        word = self._store.complete(prefix) if prefix else None
        # Keep the user's capitalization; suggest only the remainder.
        self._suggestion = word[len(prefix):] if word else ""
        self.viewport().update()

    def keyPressEvent(self, event):
        if self._suggestion and event.key() in (Qt.Key_Tab, Qt.Key_Right) and (
                event.key() == Qt.Key_Tab or event.modifiers() & Qt.ControlModifier):
            self.insertPlainText(self._suggestion)
            self._suggestion = ""
            self.viewport().update()
            return
        if self._suggestion and event.key() == Qt.Key_Escape:
            self._suggestion = ""
            self.viewport().update()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._suggestion:
            return
        rect = self.cursorRect()
        painter = QPainter(self.viewport())
        painter.setFont(self.font())
        painter.setPen(QColor("#9a9aa2"))
        baseline = rect.y() + self.fontMetrics().ascent()
        painter.drawText(QPoint(rect.x() + 1, baseline), self._suggestion)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.key_edit = QLineEdit(llm.get_api_key() or "")
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-or-…")
        form.addRow("OpenRouter API key", self.key_edit)

        show = QCheckBox("Show key")
        show.toggled.connect(lambda on: self.key_edit.setEchoMode(
            QLineEdit.Normal if on else QLineEdit.Password))
        form.addRow("", show)
        layout.addLayout(form)

        note = QLabel(
            'Used by the Ask LLM tab. Get a key at '
            '<a href="https://openrouter.ai/keys">openrouter.ai/keys</a>. '
            'Stored in ~/.config/namer/openrouter_key.')
        note.setWordWrap(True)
        note.setOpenExternalLinks(True)
        note.setProperty("hint", True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        llm.save_api_key(self.key_edit.text())
        super().accept()


class Bridge(QObject):
    """Thread-safe channel from worker threads to the UI (queued signals)."""
    models_ready = Signal(list)
    results_ready = Signal(str, list, str)  # mode, rows, status


class NamerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Namer — Name Something")
        self.resize(920, 560)

        self.store = WordStore()

        self.bridge = Bridge()
        self.bridge.models_ready.connect(self._set_models)
        self.bridge.results_ready.connect(self._show_results)

        self._build_menu()

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self._build_left())
        self.splitter.addWidget(self._build_right())
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([460, 460])  # 50-50
        self.setCentralWidget(self.splitter)

        self.statusBar().showMessage(
            "Describe the thing you want to name, then pick a tab.")

        threading.Thread(target=self._load_models, daemon=True).start()

    # ---------- menu bar ----------

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")
        settings_action = QAction("&Settings…", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._show_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        edit_menu = self.menuBar().addMenu("&Edit")
        copy_action = QAction("&Copy Selected Name", self)
        copy_action.setShortcut("Ctrl+Shift+C")
        copy_action.triggered.connect(self._copy_selected)
        edit_menu.addAction(copy_action)
        clear_action = QAction("Clear &Description", self)
        clear_action.triggered.connect(lambda: self.description.setPlainText(""))
        edit_menu.addAction(clear_action)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction("&About Namer", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_settings(self):
        if SettingsDialog(self).exec() == QDialog.Accepted:
            self.statusBar().showMessage("Settings saved.")

    def _show_about(self):
        QMessageBox.about(
            self, "About Namer",
            f"<b>Namer {__version__}</b><br>Helps you name things — code, "
            "fiction, papers, products.<br><br>Free ideas: local generators + "
            "the Datamuse API.<br>LLM ideas: any model on OpenRouter.<br><br>"
            "<a href='https://github.com/ByTheSeaL/Namer'>github.com/ByTheSeaL/Namer</a>")

    def _copy_selected(self):
        tree = self.simple_tree if self.tabs.currentIndex() == 0 else self.llm_tree
        items = tree.selectedItems()
        if items:
            self._copy_item(items[0], 0)

    # ---------- left panel: context + description ----------

    def _build_left(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 8, 6, 12)
        layout.setSpacing(4)

        layout.addWidget(QLabel("Context"))
        self.context_group = QButtonGroup(self)
        radios = QVBoxLayout()
        radios.setSpacing(2)
        for i, name in enumerate(generators.CONTEXTS):
            radio = QRadioButton(name)
            if i == 0:
                radio.setChecked(True)
            self.context_group.addButton(radio)
            radios.addWidget(radio)
        layout.addLayout(radios)

        layout.addWidget(QLabel("Describe the thing to name"))
        self.description = CompletingTextEdit(self.store)
        self.description.setPlaceholderText(
            "e.g. a background service that watches folders and "
            "syncs changed files to the cloud\n\n"
            "(grey suggestions come from words you've used before — "
            "press Tab to accept)")
        layout.addWidget(self.description, stretch=1)
        return panel

    # ---------- right panel: tabs ----------

    def _build_right(self):
        self.tabs = QTabWidget()

        simple = QWidget()
        s_layout = QVBoxLayout(simple)
        s_layout.setContentsMargins(8, 8, 12, 8)
        self.simple_tree = self._make_tree()
        s_layout.addWidget(self.simple_tree)
        s_layout.addWidget(self._hint_label())
        self.simple_btn = QPushButton("Generate")
        self.simple_btn.clicked.connect(lambda: self.on_generate("simple"))
        s_layout.addWidget(self.simple_btn)
        self.tabs.addTab(simple, "Simple")

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
        self.llm_btn = QPushButton("Generate")
        self.llm_btn.clicked.connect(lambda: self.on_generate("llm"))
        l_layout.addWidget(self.llm_btn)
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

    def _button_for(self, mode):
        return self.simple_btn if mode == "simple" else self.llm_btn

    def on_generate(self, mode):
        description = self.description.toPlainText().strip()
        if not description:
            self.statusBar().showMessage("Type a description first.")
            return
        context = self.context_group.checkedButton().text()
        self.store.learn(description)  # feed the autocomplete database
        self._button_for(mode).setEnabled(False)

        if mode == "simple":
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
            "simple", rows,
            f"{len(rows)} ideas ({source}). Regenerate for a fresh shuffle.")

    def _run_llm(self, description, context, model):
        ok, reason = llm.is_available()
        if not ok:
            self.bridge.results_ready.emit(
                "llm", [("LLM not configured", reason.replace("\n", " "))],
                "LLM unavailable — the Simple tab still works.")
            return
        try:
            keywords = generators.extract_keywords(description)
            seeds = datamuse.associations(keywords)
            rows = llm.suggest(description, context, model, seed_words=seeds)
            self.bridge.results_ready.emit(
                "llm", rows, f"{len(rows)} ideas from {model}.")
        except Exception as exc:
            self.bridge.results_ready.emit(
                "llm", [("Error", str(exc))], "LLM request failed.")

    def _show_results(self, mode, rows, status):
        tree = self.simple_tree if mode == "simple" else self.llm_tree
        tree.clear()
        for name, why in rows:
            tree.addTopLevelItem(QTreeWidgetItem([name, why]))
        self.statusBar().showMessage(status)
        button = self._button_for(mode)
        button.setEnabled(True)
        button.setText("Regenerate")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = NamerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
