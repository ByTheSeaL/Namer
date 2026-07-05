"""Namer — PySide6 (Qt) UI.

Layout: description panel on the left (context radioset + autocompleting
text box); LLM results on the right with a searchable model picker.
Right-click a result to iterate on it (expand / variations / refine).
"""

import re
import sys
import threading

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QCompleter, QDialog,
    QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QSplitter, QStackedWidget, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__, llm, prefs
from .constants import CONTEXTS
from .icon import app_icon
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
QTreeWidget::item { padding: 3px; }
QLabel[hint="true"] { color: #888; }
QLabel[error="true"] { color: #c0392b; font-weight: 600; }
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
        self._suggestion = word[len(prefix):] if word else ""
        self.viewport().update()

    def keyPressEvent(self, event):
        if self._suggestion and event.key() == Qt.Key_Tab:
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
    def __init__(self, store: WordStore, parent=None):
        super().__init__(parent)
        self._store = store
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
            'Used to generate names. Get a key at '
            '<a href="https://openrouter.ai/keys">openrouter.ai/keys</a>. '
            f'Stored in {llm.KEY_FILE}.')
        note.setWordWrap(True)
        note.setOpenExternalLinks(True)
        note.setProperty("hint", True)
        layout.addWidget(note)

        self.clear_words_btn = QPushButton(
            f"Clear autocomplete word database ({store.count()} words)")
        self.clear_words_btn.clicked.connect(self._clear_words)
        layout.addWidget(self.clear_words_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _clear_words(self):
        answer = QMessageBox.question(
            self, "Clear words",
            f"Delete all {self._store.count()} learned autocomplete words?")
        if answer == QMessageBox.Yes:
            self._store.clear()
            self.clear_words_btn.setText("Autocomplete word database cleared")
            self.clear_words_btn.setEnabled(False)

    def accept(self):
        llm.save_api_key(self.key_edit.text())
        super().accept()


class Bridge(QObject):
    """Thread-safe channel from worker threads to the UI (queued signals)."""
    models_ready = Signal(list)
    results_ready = Signal(int, list, str)  # request seq, rows, status
    error_ready = Signal(int, str)          # request seq, message (no history entry)


class NamerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Namer — Name Something")
        self.resize(920, 560)

        self.store = WordStore()
        self.prefs = prefs.load()
        self._all_models: list[str] = list(llm.FALLBACK_MODELS)
        self._history: list[tuple[list, str]] = []  # (rows, status) per result set
        self._hist_pos = -1
        self._last_description: str | None = None
        self._req_seq = 0  # bumping this orphans any in-flight request

        self.bridge = Bridge()
        self.bridge.models_ready.connect(self._set_models)
        self.bridge.results_ready.connect(self._show_results)
        self.bridge.error_ready.connect(self._show_error)

        self._build_menu()

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self._build_left())
        self.splitter.addWidget(self._build_right())
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([460, 460])  # 50-50
        self.setCentralWidget(self.splitter)

        last_model = self.prefs.get("last_model")
        if last_model:
            self.model.setCurrentText(last_model)

        self.statusBar().showMessage(
            "Describe the thing you want to name, then hit Generate.")

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
        if SettingsDialog(self.store, self).exec() == QDialog.Accepted:
            self.statusBar().showMessage("Settings saved.")

    def _show_about(self):
        QMessageBox.about(
            self, "About Namer",
            f"<b>Namer {__version__}</b><br>Helps you name things — code, "
            "fiction, papers, products.<br><br>Powered by any model on "
            "OpenRouter.<br><br>"
            "<a href='https://github.com/ByTheSeaL/Namer'>github.com/ByTheSeaL/Namer</a>")

    def _copy_selected(self):
        items = self.tree.selectedItems()
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
        for i, name in enumerate(CONTEXTS):
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

    # ---------- right panel: model picker + results ----------

    def _build_right(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 8, 12, 12)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model"))
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.NoInsert)
        model_row.addWidget(self.model, stretch=1)
        self.free_only = QCheckBox("Free only")
        self.free_only.toggled.connect(self._apply_model_filter)
        model_row.addWidget(self.free_only)
        layout.addLayout(model_row)
        self._apply_model_filter()

        nav_row = QHBoxLayout()
        self.back_btn = QToolButton()
        self.back_btn.setArrowType(Qt.LeftArrow)
        self.back_btn.setToolTip("Back to the previous list of results")
        self.back_btn.clicked.connect(lambda: self._go(-1))
        self.fwd_btn = QToolButton()
        self.fwd_btn.setArrowType(Qt.RightArrow)
        self.fwd_btn.setToolTip("Forward to the next list of results")
        self.fwd_btn.clicked.connect(lambda: self._go(+1))
        nav_row.addWidget(self.back_btn)
        nav_row.addWidget(self.fwd_btn)
        self.hist_label = QLabel("")
        self.hist_label.setProperty("hint", True)
        nav_row.addWidget(self.hist_label)
        nav_row.addStretch(1)
        layout.addLayout(nav_row)
        self._update_nav()

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Name", "Why"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 190)
        self.tree.itemDoubleClicked.connect(self._copy_item)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)

        loading_page = QWidget()
        load_layout = QVBoxLayout(loading_page)
        load_layout.addStretch(1)
        self.loading_label = QLabel("")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setWordWrap(True)
        self.loading_label.setProperty("hint", True)
        load_layout.addWidget(self.loading_label)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self._cancel_request)
        load_layout.addWidget(cancel_btn, alignment=Qt.AlignCenter)
        load_layout.addStretch(1)

        error_page = QWidget()
        e_layout = QVBoxLayout(error_page)
        e_layout.addStretch(1)
        self.error_label = QLabel("")
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setWordWrap(True)
        self.error_label.setProperty("error", True)
        e_layout.addWidget(self.error_label)
        dismiss = QPushButton("Dismiss")
        dismiss.clicked.connect(lambda: self.results_stack.setCurrentIndex(0))
        e_layout.addWidget(dismiss, alignment=Qt.AlignCenter)
        e_layout.addStretch(1)

        self.results_stack = QStackedWidget()
        self.results_stack.addWidget(self.tree)      # page 0: results
        self.results_stack.addWidget(loading_page)   # page 1: loading (cancellable)
        self.results_stack.addWidget(error_page)     # page 2: error
        layout.addWidget(self.results_stack, stretch=1)

        hint = QLabel("Double-click to copy · right-click a name to iterate on it")
        hint.setProperty("hint", True)
        layout.addWidget(hint)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self.on_generate)
        self.generate_btn.setShortcut("Ctrl+Return")
        layout.addWidget(self.generate_btn)
        return panel

    def _apply_model_filter(self):
        current = self.model.currentText()
        models = self._all_models
        if self.free_only.isChecked():
            models = [m for m in models if m.endswith(":free")] or models
        recents = self.prefs.get("recent_models", [])
        self.model.clear()
        if recents:
            self.model.addItems(recents)  # "recently chosen" section on top
            self.model.insertSeparator(len(recents))
        self.model.addItems(models)
        # Searchable dropdown: type any substring to filter, case-insensitive.
        completer = QCompleter(recents + models, self.model)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.model.setCompleter(completer)
        if current:
            self.model.setCurrentText(current)

    def _remember_model(self, model):
        recents = [model] + [m for m in self.prefs.get("recent_models", [])
                             if m != model]
        self.prefs["recent_models"] = recents[:prefs.MAX_RECENT]
        self.prefs["last_model"] = model
        prefs.save(self.prefs)
        self._apply_model_filter()

    def _load_models(self):
        self.bridge.models_ready.emit(llm.list_models())

    def _set_models(self, models):
        self._all_models = models
        self._apply_model_filter()

    # ---------- results: copy + iterate ----------

    def _copy_item(self, item, _column):
        name = item.text(0)
        QGuiApplication.clipboard().setText(name)
        self.statusBar().showMessage(f"Copied “{name}” to clipboard.")

    def _tree_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        name = item.text(0)
        menu = QMenu(self)
        copy = menu.addAction(f"Copy “{name}”")
        copy.triggered.connect(lambda: self._copy_item(item, 0))
        menu.addSeparator()
        expand = menu.addAction("More like this — expand the idea")
        expand.triggered.connect(lambda: self._iterate(name, "expand"))
        variations = menu.addAction("Variations — close permutations")
        variations.triggered.connect(lambda: self._iterate(name, "variations"))
        refine = menu.addAction("Refine — keep what works, fix the rest")
        refine.triggered.connect(lambda: self._iterate(name, "refine"))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _iterate(self, name, kind):
        description = self.description.toPlainText().strip()
        if not description:
            self.statusBar().showMessage("Type a description first.")
            return
        extra = llm.ITERATE[kind].format(name=name)
        self._start_llm(description, extra=extra,
                        status=f"Iterating on “{name}” ({kind})…")

    # ---------- generation ----------

    def on_generate(self):
        description = self.description.toPlainText().strip()
        if not description:
            self.statusBar().showMessage("Type a description first.")
            return
        if description != self._last_description:
            # A genuinely new naming task: start history fresh.
            self._history.clear()
            self._hist_pos = -1
            self._last_description = description
            self.generate_btn.setText("Generate")
            self._update_nav()
        self.store.learn(description)  # feed the autocomplete database
        self._start_llm(description, status=None)

    def _start_llm(self, description, extra="", status=None):
        context = self.context_group.checkedButton().text()
        model = self.model.currentText().strip()
        self._remember_model(model)
        self.generate_btn.setEnabled(False)
        message = status or f"Asking {model} via OpenRouter…"
        self.statusBar().showMessage(message)
        self.loading_label.setText(message)
        self.results_stack.setCurrentIndex(1)
        self._req_seq += 1
        threading.Thread(target=self._run_llm,
                         args=(self._req_seq, description, context, model, extra),
                         daemon=True).start()

    def _cancel_request(self):
        # Soft cancel: orphan the in-flight request; its late reply is ignored.
        self._req_seq += 1
        self.results_stack.setCurrentIndex(0)
        self.generate_btn.setEnabled(True)
        self.statusBar().showMessage("Request cancelled.")

    def _run_llm(self, seq, description, context, model, extra):
        ok, reason = llm.is_available()
        if not ok:
            self.bridge.error_ready.emit(
                seq, reason.replace("\n", " ") + " (File → Settings)")
            return
        try:
            rows = llm.suggest(description, context, model, extra=extra)
            self.bridge.results_ready.emit(seq, rows, f"{len(rows)} ideas from {model}.")
        except Exception as exc:
            self.bridge.error_ready.emit(seq, str(exc))

    def _show_results(self, seq, rows, status):
        if seq != self._req_seq:
            return  # response from a cancelled/superseded request
        # New result set: drop any forward history, then append.
        del self._history[self._hist_pos + 1:]
        self._history.append((rows, status))
        self._hist_pos = len(self._history) - 1
        self._render()

    def _go(self, delta):
        new_pos = self._hist_pos + delta
        if 0 <= new_pos < len(self._history):
            self._hist_pos = new_pos
            self._render()

    def _show_error(self, seq, message):
        """Overlay an error on the results area — no history entry is made."""
        if seq != self._req_seq:
            return  # error from a cancelled/superseded request
        self.error_label.setText(message)
        self.results_stack.setCurrentIndex(2)
        self.statusBar().showMessage("LLM request failed.")
        self.generate_btn.setEnabled(True)

    def _render(self):
        rows, status = self._history[self._hist_pos]
        self.tree.clear()
        for name, why in rows:
            self.tree.addTopLevelItem(QTreeWidgetItem([name, why]))
        self.results_stack.setCurrentIndex(0)
        self.statusBar().showMessage(status)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Regenerate")
        self._update_nav()

    def _update_nav(self):
        self.back_btn.setEnabled(self._hist_pos > 0)
        self.fwd_btn.setEnabled(self._hist_pos < len(self._history) - 1)
        if len(self._history) > 1:
            self.hist_label.setText(f"{self._hist_pos + 1} / {len(self._history)}")
        else:
            self.hist_label.setText("")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(app_icon())
    window = NamerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
