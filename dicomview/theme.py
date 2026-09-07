"""Dark clinical-reading theme."""

STYLESHEET = """
QWidget { background: #14181d; color: #d7e1eb; }
QMainWindow::separator { background: #232a32; width: 3px; height: 3px; }

QMenuBar { background: #1a1f26; border-bottom: 1px solid #262e38; }
QMenuBar::item { padding: 5px 11px; background: transparent; }
QMenuBar::item:selected { background: #2a3644; }
QMenu { background: #1c222a; border: 1px solid #303a46; padding: 4px; }
QMenu::item { padding: 5px 26px 5px 22px; }
QMenu::item:selected { background: #2b4d66; }
QMenu::separator { height: 1px; background: #2c3540; margin: 4px 8px; }

QToolBar { background: #1a1f26; border: none; spacing: 2px; padding: 3px; }
QToolBar::separator { background: #2c3540; width: 1px; margin: 4px 5px; }
QToolButton {
    background: transparent; border: 1px solid transparent;
    border-radius: 3px; padding: 4px 7px; color: #c3d0de;
}
QToolButton:hover { background: #253141; border-color: #35485c; }
QToolButton:checked { background: #1d4a6b; border-color: #3d8bbd; color: #ffffff; }
QToolButton:pressed { background: #2d5f85; }
QToolButton::menu-indicator { width: 0px; }
/* the ">>" button shown when the toolbar runs out of room */
QToolBarExtension {
    background: #253141; border: 1px solid #3d8bbd; border-radius: 3px;
    qproperty-icon: none;
}
QToolBarExtension:hover { background: #2d5f85; }

QStatusBar { background: #1a1f26; border-top: 1px solid #262e38; color: #93a5b8; }
QStatusBar::item { border: none; }

QDockWidget { titlebar-close-icon: none; font-weight: 600; }
QDockWidget::title {
    background: #1e242c; padding: 5px 8px; border-bottom: 1px solid #2a323c;
}

QListWidget, QTreeWidget, QTableWidget {
    background: #171c22; border: 1px solid #262e38; outline: none;
    alternate-background-color: #1c232b;
}
QListWidget::item { padding: 4px; border-bottom: 1px solid #1f262e; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #1d4a6b; }
QListWidget::item:hover, QTreeWidget::item:hover { background: #212b36; }
QTreeWidget::item { padding: 2px; }
QHeaderView::section {
    background: #1e242c; color: #9fb0c2; padding: 4px 6px;
    border: none; border-right: 1px solid #262e38;
    border-bottom: 1px solid #262e38;
}

QScrollBar:vertical { background: #171c22; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #38434f; min-height: 24px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #48576a; }
QScrollBar:horizontal { background: #171c22; height: 11px; }
QScrollBar::handle:horizontal { background: #38434f; min-width: 24px; border-radius: 5px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSlider::groove:horizontal { height: 4px; background: #2a333d; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #4a9fd0; width: 12px; margin: -5px 0; border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: #63b8e8; }
QSlider::sub-page:horizontal { background: #2f6b91; border-radius: 2px; }

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    background: #1d232b; border: 1px solid #303a46; border-radius: 3px;
    padding: 3px 6px; color: #d7e1eb; selection-background-color: #2b6087;
}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover { border-color: #3f5266; }
QComboBox::drop-down { border: none; width: 16px; }
QComboBox QAbstractItemView {
    background: #1c222a; border: 1px solid #303a46;
    selection-background-color: #2b6087;
}
QPushButton {
    background: #253040; border: 1px solid #35434f; border-radius: 3px;
    padding: 5px 14px;
}
QPushButton:hover { background: #2e3d4f; }
QPushButton:pressed { background: #1d4a6b; }

QCheckBox, QRadioButton { spacing: 6px; }
QLabel { background: transparent; }
QToolTip {
    background: #232b34; color: #dbe6f0; border: 1px solid #3a4654;
    padding: 4px;
}
QProgressBar {
    background: #1d232b; border: 1px solid #303a46; border-radius: 3px;
    text-align: center; color: #cfe0ef;
}
QProgressBar::chunk { background: #2f7fb0; }
QTextBrowser { background: #171c22; border: 1px solid #262e38; }
QSplitter::handle { background: #232a32; }
"""
