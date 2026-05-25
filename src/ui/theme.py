"""
theme.py – Global stylesheets for SSH Win Manager.
"""

from pathlib import Path


_ICON_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"
_CHECKMARK_URL = str(_ICON_DIR / "check.svg").replace("\\", "/")
_CHEVRON_URL = str(_ICON_DIR / "chevron-down.svg").replace("\\", "/")

THEME_COLORS = {
    "dark": {
        "background": "#0d0d12",
        "surface": "#0D1117",
        "text": "#c8d6e5",
        "accent": "#00b4d8"
    },
    "light": {
        "background": "#f0f2f5",
        "surface": "#ffffff",
        "text": "#1a2332",
        "accent": "#0077b6"
    }
}

def get_stylesheet(theme: str = "dark") -> str:
    """Return the stylesheet for the given theme ('dark' or 'light')."""
    sheet = LIGHT_STYLESHEET if theme == "light" else STYLESHEET
    return (
        sheet.replace("__CHECKMARK_URL__", _CHECKMARK_URL)
        .replace("__CHEVRON_URL__", _CHEVRON_URL)
    )


STYLESHEET = """
/* ============================================================
   NEO SSH-Win Manager – Modern Cyber Theme (v2.0)
   ============================================================ */

/* ---- Custom Titlebar (dark) ------------------------------- */
#customTitlebar {
    background-color: #0d0d12;
    border-bottom: 1px solid #1a1a2e;
}
#customTitlebarTitle {
    color: #c8d6e5;
    font-family: "Segoe UI", sans-serif;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
#customTitlebarVersion {
    color: #8fa4b8;
    font-family: "Consolas";
    font-size: 10px;
    background: transparent;
    padding: 0 4px;
}
#fwOuter {
    background-color: #0d0d12;
}

/* ---- Global Bases ----------------------------------------- */
QWidget {
    color: #c8d6e5;
    font-family: "Inter", "Segoe UI", sans-serif;
    font-size: 13px;
    border: none;
    outline: none;
}

QLabel, QCheckBox, QRadioButton, QGroupBox {
    background: transparent;
}

/* ---- Checkboxes ------------------------------------------- */
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1.5px solid #243243;
    background-color: #14141f;
}
QCheckBox::indicator:hover {
    border-color: #3a5068;
}
QCheckBox::indicator:checked {
    width: 16px;
    height: 16px;
    background-color: #00b4d8;
    border: 1.5px solid #0090ae;
    image: url("__CHECKMARK_URL__");
}
QCheckBox::indicator:checked:hover {
    width: 16px;
    height: 16px;
    background-color: #22c4e8;
    border: 1.5px solid #00a0c0;
    image: url("__CHECKMARK_URL__");
}

/* ---- Main Window ------------------------------------------ */
#MainWindow {
    background-color: #0d0d12;
}

/* ---- Sidebar / Left Panel --------------------------------- */
#sidePanel {
    background-color: #0a0a0f;
    border-right: 1px solid #1a1a2e;
}

/* ---- Scroll Area ------------------------------------------ */
#connectionScroll {
    background-color: transparent;
    border: none;
}

/* --- Dialog Elements --- */
#dialogTitle {
    color: #00b4d8;
    font-size: 18px;
    font-weight: bold;
    margin-bottom: 5px;
}

#dialogIconLarge {
    font-size: 36px;
    background: transparent;
    margin-bottom: 5px;
}

#sectionLabel {
    color: #00b4d8;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    padding-top: 10px;
}

#fieldLabel {
    color: #8b949e;
    font-size: 12px;
}

#hintLabel {
    color: #5a6d7e;
    font-size: 11px;
}

#ctrlRowLabel {
    color: #9ab0c5;
    font-size: 12px;
    font-weight: 600;
}

/* ---- Settings Cards (per-section) ------------------------ */
#settingsGroupCard {
    background-color: #0f1720;
    border: 1px solid #1a2738;
    border-radius: 14px;
}

#settingsRow {
    background: transparent;
    border-radius: 0px;
}

#settingsRow:hover {
    background: rgba(255, 255, 255, 0.025);
}

#rowSep {
    background-color: rgba(255, 255, 255, 0.05);
    max-height: 1px;
    min-height: 1px;
    margin: 0 14px;
}

#rowLabel {
    color: #c8d6e5;
    font-size: 13px;
}

QPushButton#settingsActionBtn {
    background-color: #141d28;
    border: 1px solid #243243;
    border-radius: 10px;
    color: #9ab0c5;
    font-size: 12px;
    font-weight: 600;
    padding: 0 14px;
    text-align: center;
}
QPushButton#settingsActionBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
    color: #deebf7;
}
QPushButton#settingsActionBtn[btn_type="primary"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #00b4d8, stop:1 #0077b6);
    border: none;
    color: #fff;
    font-weight: 700;
}
QPushButton#settingsActionBtn[btn_type="primary"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #22c4e8, stop:1 #0088c8);
}

#errorLabel {
    color: #ef4444;
    font-size: 12px;
}

#mutedLabel {
    color: #6a7a8a;
    font-size: 12px;
}

#accentLabel {
    color: #00b4d8;
    font-size: 11px;
}

#secondaryTitle {
    color: #e4eaf0;
    font-size: 11px;
    font-weight: bold;
}

#divider {
    background-color: rgba(255, 255, 255, 0.05);
}

#dialogHeroCard, #dialogSectionCard {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 18px;
}

#dialogLead {
    color: #8fa4b8;
    font-size: 13px;
}

#dialogPill {
    background-color: #0f2430;
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 10px;
    font-weight: 700;
    border: 1px solid rgba(125, 223, 255, 0.24);
    border-radius: 8px;
    padding: 4px 10px;
}

QLabel#dialogLink {
    color: #7ddfff;
    font-size: 13px;
    font-weight: 600;
}

QPushButton#dialogMaximizeBtn {
    background-color: #141d28;
    border: 1px solid #243243;
    border-radius: 10px;
}
QPushButton#dialogMaximizeBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
}
QPushButton#dialogMaximizeBtn:checked {
    background-color: rgba(0, 180, 216, 0.15);
    border: 1px solid rgba(0, 180, 216, 0.42);
}

#sysinfoHeroCard, #sysinfoSectionCard, #sysinfoStateCard {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 18px;
}

#sysinfoLoadingOverlay {
    background-color: rgba(8, 12, 18, 120);
}
#sysinfoLoadingCard {
    background-color: rgba(17, 24, 34, 246);
    border: 1px solid rgba(71, 195, 255, 0.26);
    border-radius: 18px;
    min-width: 260px;
}
#sysinfoLoadingIcon {
    color: #7ddfff;
    font-size: 26px;
}
#sysinfoLoadingTitle {
    color: #edf4fb;
    font-size: 14px;
    font-weight: 700;
}
#sysinfoLoadingDots {
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 16px;
    font-weight: 700;
    min-height: 18px;
}

#sysinfoHeroTitle {
    color: #edf4fb;
    font-size: 18px;
    font-weight: 700;
}

#sysinfoHeroMeta {
    color: #8fa4b8;
    font-size: 12px;
}

#sysinfoStatePill {
    background-color: #0f2430;
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 10px;
    font-weight: 700;
    border: 1px solid rgba(125, 223, 255, 0.24);
    border-radius: 8px;
    padding: 8px 10px;
}
#sysinfoStatePill[connected="false"] {
    background-color: rgba(239, 68, 68, 0.12);
    color: #ff8d8d;
    border: 1px solid rgba(239, 68, 68, 0.30);
}

#sysinfoStateText {
    color: #8fa4b8;
    font-size: 12px;
}

#sysinfoErrorText {
    color: #ff8d8d;
    font-size: 12px;
}

#sysinfoStatLabel {
    color: #6f8599;
    font-size: 11px;
    font-weight: 600;
}

#sysinfoStatValue {
    color: #deebf7;
    font-size: 12px;
    font-weight: 700;
}

QProgressBar#sysinfoProgress {
    background-color: #0d1720;
    border-radius: 3px;
}
QProgressBar#sysinfoProgress::chunk {
    background-color: #00b4d8;
    border-radius: 3px;
}
QProgressBar#sysinfoProgress[level="warn"]::chunk {
    background-color: #f59e0b;
    border-radius: 3px;
}
QProgressBar#sysinfoProgress[level="error"]::chunk {
    background-color: #ef4444;
    border-radius: 3px;
}

QMenu {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 8px;
    color: #c8d6e5;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: #182232;
    color: #7ddfff;
}
QMenu::item:disabled {
    color: #3a4a5a;
}
QMenu::separator {
    height: 1px;
    background: #1f2b3a;
    margin: 4px 2px;
}

QMenu#trayMenu {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 12px;
    color: #deebf7;
    padding: 6px;
}
QMenu#trayMenu::item {
    padding: 8px 18px;
    border-radius: 8px;
}
QMenu#trayMenu::item:selected {
    background-color: #182232;
    color: #7ddfff;
}
QMenu#trayMenu::separator {
    height: 1px;
    background: #1f2b3a;
    margin: 6px 2px;
}

#debugSurface {
    background-color: #0d1117;
}

#debugToolbar {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 18px;
}

#debugTitle {
    color: #edf4fb;
    font-size: 18px;
    font-weight: 700;
}

#debugMeta {
    color: #8fa4b8;
    font-size: 12px;
}

QCheckBox#debugCheck {
    color: #9ab0c5;
    font-size: 12px;
    font-weight: 600;
}

QTextEdit#debugLogView {
    background-color: #111822;
    color: #deebf7;
    border: 1px solid #1f2b3a;
    border-radius: 18px;
    padding: 14px;
}

#loadingOverlay {
    background-color: rgba(8, 12, 18, 170);
}

#loadingFrame {
    background-color: rgba(17, 24, 34, 246);
    border: 1px solid rgba(71, 195, 255, 0.26);
    border-radius: 18px;
}

#loadingText {
    color: #edf4fb;
    font-size: 18px;
    font-weight: 700;
}

#loadingDots {
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 18px;
    font-weight: 700;
}

#loadingHint {
    color: #8fa4b8;
    font-size: 12px;
}

/* User Management Row */
#userBox {
    background: #141d28;
    border: 1px solid #1e1e30;
    border-radius: 14px;
}

#userBox[current="true"] {
    border: 1px solid rgba(0, 180, 216, 0.42);
    background: rgba(0, 180, 216, 0.12);
}

#userBox QLabel[state="user_row"] {
    color: #c8d6e5;
    font-size: 13px;
    background: transparent;
    border: none;
}

#userAvatar {
    background: #101925;
    border: 1px solid #31465d;
    border-radius: 14px;
    color: #d8e4f0;
    font-family: "Consolas";
    font-size: 13px;
    font-weight: 700;
}

#userAvatar[admin="true"] {
    background: rgba(0, 180, 216, 0.14);
    border: 1px solid rgba(0, 180, 216, 0.42);
    color: #7ddfff;
}

#userMetaSub {
    color: #8fa4b8;
    font-size: 11px;
    font-family: "Consolas";
}

#userRowName {
    color: #edf4fb;
    font-size: 13px;
    font-weight: 600;
}

#userRoleBadge {
    padding: 3px 8px;
    border-radius: 8px;
    background: #101925;
    border: 1px solid #243243;
    color: #8fa4b8;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
}

#userRoleBadge[variant="accent"] {
    background: rgba(0, 180, 216, 0.15);
    border: 1px solid rgba(0, 180, 216, 0.42);
    color: #7ddfff;
}

#connectionList {
    background-color: transparent;
}

QScrollBar:vertical {
    background: transparent;
    width: 4px;
    margin: 2px 0;
    border-radius: 2px;
}
QScrollBar::handle:vertical {
    background: rgba(170, 180, 196, 0.35);
    border-radius: 2px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(170, 180, 196, 0.65);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* ---- Connection Card -------------------------------------- */
#connectionContainer {
    background: transparent;
    margin-bottom: 0px;
}

#connectionCard {
    background-color: #13131E;
    border: 1px solid #1f2b3a;
    border-radius: 16px;
    margin: 0px;
    padding: 0px;
}

#connectionCard:hover {
    background-color: #16202c;
    border: 1px solid #31465d;
}

/* Mounted State Properties */
#connectionCard[mounted="true"] {
    background-color: #10202a;
    border: 1px solid rgba(0, 180, 216, 0.48);
}

/* Selected State */
#connectionCard[selected="true"] {
    border: 1px solid #47c3ff;
    background-color: #172531;
}

/* Mounted overrides selected blue highlight */
#connectionCard[mounted="true"][selected="true"] {
    border: 1px solid rgba(0, 180, 216, 0.48);
    background-color: #10202a;
}

/* Expanded/Panel Open State */
#connectionCard[expanded="true"] {
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
    margin-bottom: 0px;
    border-bottom: none;
}

#cardInfoWrapper {
    background: transparent;
}

#connName {
    color: #e4eaf0;
    font-size: 14px;
    font-weight: 600;
}
#connDetail {
    color: #556070;
    font-size: 11px;
}

#cloudIcon {
    font-size: 22px;
    color: #2a3a4a;
}
#cloudIcon[mounted="true"] {
    color: #00b4d8;
}

#cloudIcon[state="large"] {
    font-size: 48px;
    padding: 8px;
}

#driveBadge {
    background-color: #0f2430;
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 700;
    border-radius: 9px;
    padding: 2px 4px;
    border: 1px solid rgba(125, 223, 255, 0.24);
}
#driveBadge[mounted="true"] {
    background-color: rgba(0, 212, 100, 0.10);
    color: #00d464;
    border: 1px solid rgba(0, 212, 100, 0.42);
}

/* ---- System Info Panel (Inside Card) ---------------------- */
#systemInfoPanel {
    background-color: #0f1218;
    border: 1px solid #1e1e30;
    border-top: none;
    border-bottom-left-radius: 12px;
    border-bottom-right-radius: 12px;
    margin: 0 12px 12px 12px;
    padding: 8px;
}

/* System info as full right panel content */
#sysinfoFullPanel {
    background-color: transparent;
    border: none;
    margin: 0;
    padding: 0;
}

#sectionFrame {
    background-color: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 6px;
}

#sectionTitle {
    color: #58a6ff;
    font-size: 10px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

#infoLabel { color: #8b949e; font-size: 10px; }
#valueLabel { color: #e6edf3; font-size: 11px; font-weight: 500; }
#bigValue { color: #e6edf3; font-size: 15px; font-weight: bold; }

/* ---- Sidebar (Left) --------------------------------------- */
#sidebar {
    background-color: #0a0a0f;
    border-right: 1px solid #1a1a2e;
    min-width: 60px;
    max-width: 60px;
}

/* ---- Connections Panel (Center) --------------------------- */
#connectionsPanel {
    background-color: #0d0d12;
}

#connectionsHeader {
    background-color: #0E0E19;
    border-bottom: 1px solid #1c2633;
    min-height: 52px;
    max-height: 52px;
}

#connectionsKicker {
    color: #00b4d8;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
}

#connectionsTitle {
    color: #edf4fb;
    font-size: 16px;
    font-weight: 700;
}

#connectionsBadge {
    background-color: #14141F;
    color: #607489;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 600;
    border: 1px solid rgba(96, 116, 137, 0.26);
    border-radius: 8px;
    min-height: 32px;
    max-height: 32px;
    padding: 0 8px;
}

/* ---- Splitter handle ---------------------------------------- */
#bodySplitter::handle {
    background: transparent;
}
#bodySplitter::handle:hover {
    background: transparent;
}

/* ---- Right Panel (System Info) ---------------------------- */
#rightPanel {
    background-color: #0E0E19;
    border-left: 1px solid #1c2633;
}

#rightPanelHeader {
    background-color: #0E0E19;
    border-bottom: 1px solid #1f2b3a;
    min-height: 52px;
    max-height: 52px;
    padding: 0 16px;
}

#rightPanelKicker {
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 1.4px;
}

#rightPanelTitle {
    color: #edf4fb;
    font-size: 16px;
    font-weight: 700;
}

#rightPanelEmpty {
    color: #607489;
    font-size: 12px;
}

#rightPanelPlaceholderTitle {
    color: #edf4fb;
    font-size: 20px;
    font-weight: 700;
    padding: 0;
}

#rightPanelPlaceholderBody {
    color: #8fa4b8;
    font-size: 13px;
    padding: 0;
    min-height: 45px;
    max-height: 45px;
}

#rightPanelPlaceholder,
#connectionsTitleWrap,
#rightPanelTitleWrap,
#fullscreenContent {
    background: transparent;
}

#fullscreenPanel {
    background-color: #0d1117;
}

#fullscreenForm {
    background-color: transparent;
}

#fullscreenSectionCard {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 18px;
}

/* ---- Sidebar Buttons -------------------------------------- */
QPushButton#sidebarBtn {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 12px;
    min-width: 42px;
    max-width: 42px;
    min-height: 42px;
    max-height: 42px;
}
QPushButton#sidebarBtn:hover {
    background-color: #182232;
    border: 1px solid #31465d;
}
QPushButton#sidebarBtn[active="true"] {
    background-color: rgba(0, 180, 216, 0.15);
    border: 1px solid rgba(0, 180, 216, 0.42);
}
QPushButton#sidebarBtn[btn_type="danger"] {
    border: 1px solid #1f2b3a;
}
QPushButton#sidebarBtn[btn_type="danger"]:hover {
    background-color: rgba(239, 68, 68, 0.12);
    border: 1px solid rgba(239, 68, 68, 0.32);
}
QPushButton#sidebarBtn[btn_type="warning"] {
    border: 1px solid #1f2b3a;
}
QPushButton#sidebarBtn[btn_type="warning"]:hover {
    background-color: rgba(245, 158, 11, 0.12);
    border: 1px solid rgba(245, 158, 11, 0.32);
}

/* ---- Small Add button in header --------------------------- */
QPushButton#headerAddBtn {
    background-color: 14141F;
    border: 1px solid #243243;
    border-radius: 10px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#headerAddBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
}

/* ---- Mount/Dismount All Buttons ------------------------- */
QPushButton#headerActionBtn {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 12px;
    min-height: 30px;
    max-height: 30px;
    min-width: 30px;
    max-width: 30px;
}
QPushButton#headerActionBtn:hover {
    background-color: #182232;
    border: 1px solid #31465d;
}

/* ---- Groups Filter Dropdown ---------------------------- */
QComboBox#headerGroupsCombo {
    background-color: #111822;
    color: #deebf7;
    border: 1px solid #00b4d8;
    border-radius: 12px;
    padding: 4px 10px;
    font-size: 12px;
    min-height: 22px;
}
QComboBox#headerGroupsCombo:hover {
    border: 1px solid #7ddfff;
}
QComboBox#headerGroupsCombo::drop-down {
    border: none;
    width: 20px;
}
QComboBox#headerGroupsCombo::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #deebf7;
    width: 0;
    height: 0;
}
QComboBox#headerGroupsCombo QAbstractItemView {
    background-color: #111822;
    color: #deebf7;
    border: 1px solid #1f2b3a;
    border-radius: 8px;
    selection-background-color: #182232;
    selection-color: #7ddfff;
}

/* ---- Version label in status bar -------------------------- */
#versionLabel {
    color: #607489;
    font-size: 11px;
    font-family: "Consolas";
}

/* ---- Right Panel – content elements ----------------------- */
#rightPanelScroll {
    background-color: transparent;
    border: none;
}
#rightPanelContent {
    background-color: transparent;
    min-width: 100%;
}

/* Info body rows */
#rpInfoBody {
    background-color: transparent;
}
QFrame#rpInfoField {
    background-color: #14141F;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
}
QFrame#rpInfoField QLineEdit,
QFrame#rpInfoField QSpinBox,
QFrame#rpInfoField QComboBox {
    padding: 0;
    min-height: 16px;
    max-height: 20px;
    background-color: transparent;
    border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 0;
    font-size: 14px;
    font-weight: 400;
    color: #c8d6e5;
}
QFrame#rpInfoField QLineEdit:focus,
QFrame#rpInfoField QSpinBox:focus,
QFrame#rpInfoField QComboBox:focus {
    border-bottom: 1px solid #00b4d8;
    background-color: transparent;
}
QFrame#rpInfoField QPushButton {
    min-height: 16px;
    max-height: 20px;
    padding: 0 4px;
    font-size: 14px;
}
#rpSectionLabel {
    color: #00b4d8;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding-top: 4px;
}
#rpFieldLabel {
    color: #6f8599;
    font-size: 11px;
}
QLabel#rpFieldLabelCaps {
    font-size: 11px;
}
#rpValue {
    color: #ffffff;
    font-size: 18px;
    font-weight: 800;
    background-color: #14141F;
    border: 0px solid #1f2b3a;
    border-radius: 12px;
}
#rpDivider {
    background-color: #1f2b3a;
    max-height: 1px;
    min-height: 1px;
}

/* Status dot/label in info panel */
#rpStatusDot {
    font-size: 9px;
    color: #3a4a5a;
}
#rpStatusDot[mounted="true"] { color: #00d464; }
#rpStatusLabel {
    color: #607489;
    font-size: 11px;
    font-weight: 600;
}
#rpStatusLabel[mounted="true"] { color: #00d464; }

/* Header action buttons (edit, trash, close in right panel) */
QPushButton#rpHeaderBtn {
    background-color: #14141F;
    border: 1px solid #243243;
    border-radius: 10px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#rpHeaderBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
}
QPushButton#rpHeaderBtn[btn_type="danger"] {
    background-color: rgba(239, 68, 68, 0.16);
    border: 1px solid rgba(239, 68, 68, 0.38);
}
QPushButton#rpHeaderBtn[btn_type="danger"]:hover {
    background-color: rgba(239, 68, 68, 0.24);
    border: 1px solid #ef4444;
}
QPushButton#rpHeaderBtn:disabled {
    background-color: #111822;
    border: 1px solid #1a2330;
    color: #2a3a4a;
}
QPushButton#rpHeaderBtn[btn_type="danger"]:disabled,
QPushButton#rpHeaderBtn[btn_type="danger"]:disabled:hover {
    background-color: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.18);
}
QPushButton#rpHeaderSaveBtn {
    background-color: rgba(0, 212, 100, 0.15);
    border: 1px solid rgba(0, 212, 100, 0.35);
    border-radius: 10px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#rpHeaderSaveBtn:hover {
    background-color: rgba(0, 212, 100, 0.24);
    border: 1px solid rgba(0, 212, 100, 0.60);
}
QPushButton#rpHeaderSaveBtn:disabled {
    background: #1a2330;
    border: 1px solid #243243;
}

/* Right panel save/cancel button bar */
#rpBtnBar {
    background-color: #111822;
    border-top: 1px solid #1f2b3a;
}

QPushButton#rpActionBtn {
    background-color: #141d28;
    border: 1px solid #243243;
    border-radius: 12px;
    color: #E4EAF0;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 12px;
    min-height: 32px;
}
QPushButton#rpActionBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
}
QPushButton#rpActionBtn[btn_type="primary"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #00b4d8, stop:1 #0077b6);
    border: none;
    color: #deebf7;
}
QPushButton#rpActionBtn[btn_type="primary"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #22c4e8, stop:1 #0088c8);
}
QPushButton#rpActionBtn[btn_type="danger"] {
    background: rgba(239, 68, 68, 0.10);
    border: 1px solid rgba(239, 68, 68, 0.28);
    color: #ff8d8d;
}
QPushButton#rpActionBtn[btn_type="danger"]:hover {
    background: rgba(239, 68, 68, 0.16);
    border: 1px solid #ef4444;
}
QPushButton#rpActionBtn:disabled {
    background-color: #111822;
    border: 1px solid #1a2330;
    color: #607489;
}

/* [i] info button active state */
QPushButton#cardInfoBtn[active="true"] {
    background: rgba(0, 180, 216, 0.15);
    border: 1px solid rgba(0, 180, 216, 0.5);
    color: #00b4d8;
}

#divider {
    background-color: #1a1a2e;
    max-height: 1px;
    min-height: 1px;
    margin: 10px 4px;
}

/* ---- Global Action Buttons -------------------------------- */
#actionBtn, QPushButton#sshBtn, QPushButton#mountBtn {
    font-weight: 500;
}

/* Standard Secondary Action Button */
#actionBtn {
    background-color: #141d28;
    border: 1px solid #243243;
    border-radius: 12px;
    color: #9ab0c5;
    font-size: 12px;
    padding: 7px 12px;
    text-align: left;
}
#actionBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
    color: #deebf7;
}

/* Primary Brand Button (Add, etc) */
#actionBtn[btn_type="primary"], #primaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #00b4d8, stop:1 #0077b6);
    border: none;
    color: #deebf7;
    font-weight: 700;
    padding: 0 14px;
    border-radius: 10px;
    min-height: 32px;
    max-height: 32px;
}
#actionBtn[btn_type="primary"]:hover, #primaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #22c4e8, stop:1 #0088c8);
}
#actionBtn[btn_type="primary"]:disabled, #primaryBtn:disabled,
#actionBtn[btn_type="primary"]:disabled:hover, #primaryBtn:disabled:hover {
    background: #111822;
    border: 1px solid #1a2330;
    color: #607489;
}

/* Secondary / Cancel Button */
#secondaryBtn {
    background-color: #141d28;
    border: 1px solid #243243;
    border-radius: 10px;
    color: #c1cfdd;
    font-size: 13px;
    padding: 0 14px;
    min-height: 32px;
    max-height: 32px;
}
#secondaryBtn:hover {
    background-color: #192433;
    border: 1px solid #36506c;
    color: #deebf7;
}
QPushButton#aboutLinkBtn {
    background-color: #141d28;
    border: 1px solid #243243;
    border-radius: 8px;
    color: #00b4d8;
    font-size: 12px;
    padding: 0 10px;
    min-height: 34px;
    max-height: 34px;
    text-align: left;
}
QPushButton#aboutLinkBtn:hover {
    background-color: #0d2137;
    border: 1px solid #00b4d8;
    color: #38d4f8;
}
QPushButton#aboutLinkBtn:pressed {
    background-color: #0a1929;
}
QLineEdit[invalid="true"] {
    border: 2px solid #0077b6;
}
QLineEdit[invalid="true"]:focus {
    border: 2px solid #0077b6;
}
QLineEdit:focus, QPushButton:focus {
    border: 2px solid #00b4d8;
}

/* Dialog Button Bar */
#dialogBtnBar {
    background-color: #0d0d12;
    border-top: 1px solid #1a1a2e;
}

/* Danger Button */
#actionBtn[btn_type="danger"], #dangerBtn {
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.2);
    border-radius: 10px;
    color: #ef4444;
    padding: 0 14px;
    min-height: 32px;
    max-height: 32px;
}
#actionBtn[btn_type="danger"]:hover, #dangerBtn:hover {
    background: rgba(239, 68, 68, 0.15);
    border: 1px solid #ef4444;
}

/* Warning Button (Debug) */
#actionBtn[btn_type="warning"] {
    background: rgba(245, 158, 11, 0.08);
    border: 1px solid rgba(245, 158, 11, 0.2);
    color: #f59e0b;
}
#actionBtn[btn_type="warning"]:hover {
    background: rgba(245, 158, 11, 0.15);
    border: 1px solid #f59e0b;
}

/* Integrated Terminal UI */
#terminalArea {
    background-color: #0d0d12;
}
#terminalTabBar {
    background-color: #0d1117;
    border-bottom: 1px solid #1a2330;
}
#terminalTabBtn {
    background-color: #141d28;
    border: 1px solid #1f2b3a;
    border-radius: 6px;
    color: #6a7a8a;
    padding: 3px 12px;
    min-height: 24px;
    max-height: 24px;
    font-size: 11px;
}
#terminalTabBtn:hover {
    background-color: #192433;
    color: #aab4c4;
}
#terminalTabBtn:checked {
    background-color: #192433;
    border-color: #00b4d8;
    color: #deebf7;
}
#terminalEndBar {
    background-color: #0d1117;
    border-top: 1px solid #1a2330;
}

/* SSH Circular/Small Button */
QPushButton#sshBtn {
    background: #141d28;
    border: 1px solid #243243;
    color: #7ddfff;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#sshBtn:hover {
    background: rgba(0, 180, 216, 0.14);
    border: 1px solid #47c3ff;
}

/* Card-internal Info/Edit Buttons */
QPushButton#cardInfoBtn, QPushButton#cardEditBtn {
    background: #141d28;
    border: 1px solid #243243;
    color: #c1cfdd;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#cardInfoBtn:hover, QPushButton#cardEditBtn:hover {
    background: rgba(170, 180, 196, 0.12);
    border: 1px solid #9ab0c5;
    color: #deebf7;
}
QPushButton#cardEditBtn:disabled {
    color: #3a3a4a;
    border: 1px solid #1e1e2e;
    background: #14141f;
}

/* Mount Toggle Circle */
QPushButton#mountBtn {
    background-color: #141d28;
    border: 1px solid #2f4358;
    border-radius: 10px;
    color: #deebf7;
    font-size: 12px;
    font-weight: 700;
    padding: 0px;
    text-align: center;
}
QPushButton#mountBtn:hover {
    background-color: rgba(0, 180, 216, 0.14);
    border: 1px solid #47c3ff;
    color: #7ddfff;
}
QPushButton#mountBtn[mounted="true"] {
    background-color: rgba(0, 212, 100, 0.10);
    border: 1px solid rgba(0, 212, 100, 0.42);
    color: #00d464;
}
QPushButton#mountBtn[mounted="true"]:hover {
    background-color: rgba(239, 68, 68, 0.15);
    border: 1px solid #ef4444;
    color: #ef4444;
}
QPushButton#mountBtn[loading="true"], QPushButton#mountBtn[loading="true"]:disabled {
    background-color: rgba(0, 180, 216, 0.14);
    border: 1px solid rgba(71, 195, 255, 0.38);
    border-radius: 16px;
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 700;
    padding: 0 10px;
}

/* ---- Inputs ----------------------------------------------- */
QLineEdit, QSpinBox, QComboBox {
    background-color: #14141f;
    border: 1px solid #1e1e30;
    border-radius: 8px;
    color: #c8d6e5;
    padding: 3px 8px;
    font-size: 13px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #00b4d8;
    background-color: #16162a;
}
QLineEdit::placeholder {
    color: #3f4e5e;
}

QComboBox::drop-down { border: none; width: 30px; }
QComboBox::down-arrow {
    image: url("__CHEVRON_URL__");
    width: 12px;
    height: 12px;
    margin-right: 10px;
}

/* Dropdown popup */
QComboBox QAbstractItemView {
    background-color: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    color: #c8d6e5;
    selection-background-color: rgba(0, 180, 216, 0.18);
    selection-color: #e4eaf0;
    outline: none;
    padding: 1px;
}
QComboBox QAbstractItemView::item {
    padding: 4px 8px;
    min-height: 24px;
    border-radius: 12px;
}
QComboBox QAbstractItemView::item:selected {
    background-color: rgba(0, 180, 216, 0.18);
}

/* ---- Status Bar ------------------------------------------- */
#statusBar {
    background-color: #0a0f15;
    border-top: 1px solid #1c2633;
    color: #8fa4b8;
    font-family: "Consolas";
    font-size: 12px;
    padding: 10px 14px;
}
#statusDot { color: #00d464; font-size: 9px; margin-right: 4px; }
#statusText {
    color: #8fa4b8;
}
#statusPill {
    color: #607489;
}

#mountErrorDialog {
    background-color: #0d1117;
}

#mountErrorLead {
    color: #edf4fb;
    font-size: 13px;
    font-weight: 600;
}

#mountErrorBlock {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 14px;
}

#mountErrorBody {
    color: #9ab0c5;
    font-size: 12px;
}

#mountErrorDetails {
    background-color: #111822;
    border: 1px solid #1f2b3a;
    border-radius: 12px;
    color: #7ddfff;
    font-family: "Consolas";
    font-size: 11px;
    padding: 12px;
}

/* ---- Progress Bars ---------------------------------------- */
QProgressBar {
    background-color: #1a1a2e;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
    height: 8px;
}
QProgressBar::chunk {
    background-color: #00b4d8;
    border-radius: 4px;
}

/* ---- Tabs ------------------------------------------------- */
QTabWidget::pane {
    border: 1px solid #1e1e30;
    border-radius: 10px;
    background: #0f0f1a;
    margin-top: -1px;
}
QTabBar::tab {
    background: transparent;
    border-bottom: 2px solid transparent;
    color: #556070;
    font-size: 12px;
    padding: 10px 20px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    color: #00b4d8;
    border-bottom: 2px solid #00b4d8;
    font-weight: 600;
}

/* ---- Dialogs ---------------------------------------------- */
QDialog {
    background-color: #0d0d12;
}

#dialogTitle {
    color: #e4eaf0;
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 8px;
}

#sectionLabel {
    color: #00b4d8;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    padding-top: 12px;
}

#fieldLabel {
    color: #556070;
    font-size: 11px;
    font-weight: 600;
    margin-bottom: 2px;
}

/* ---- Tooltips / Messagebox -------------------------------- */
QToolTip {
    background-color: #1a1a2e;
    border: 1px solid #2a2a4a;
    color: #c8d6e5;
    border-radius: 6px;
    padding: 5px 10px;
}

QMessageBox {
    background-color: __SURFACE__;
    color: #c8d6e5;
}
QMessageBox QPushButton {
    min-width: 90px;
    min-height: 32px;
    max-height: 32px;
    padding: 0 14px;
}
"""

# Ergänze get_stylesheet, um den Platzhalter zu füllen
def get_stylesheet_v2(theme: str = "dark") -> str:
    colors = THEME_COLORS.get(theme, THEME_COLORS["dark"])
    sheet = get_stylesheet(theme)
    return sheet.replace("__SURFACE__", colors["surface"])
LIGHT_STYLESHEET = """
/* ============================================================
   NEO SSH-Win Manager – Light Theme
   ============================================================ */

/* ---- Custom Titlebar (light) ------------------------------ */
#customTitlebar {
    background-color: #f0f2f5;
    border-bottom: 1px solid #d4d8df;
}
#customTitlebarTitle {
    color: #1a2332;
    font-family: "Segoe UI", sans-serif;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
#customTitlebarVersion {
    color: #5a6a7a;
    font-family: "Consolas";
    font-size: 10px;
    background: transparent;
    padding: 0 4px;
}
#fwOuter {
    background-color: #f0f2f5;
}

QWidget {
    color: #1a2332;
    font-family: "Inter", "Segoe UI", sans-serif;
    font-size: 13px;
    border: none;
    outline: none;
}

QLabel, QCheckBox, QRadioButton, QGroupBox {
    background: transparent;
}

QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1.5px solid #c8d0dc;
    background-color: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #9aacbe;
}
QCheckBox::indicator:checked {
    width: 16px;
    height: 16px;
    background-color: #0077b6;
    border: 1.5px solid #005a8a;
    image: url("__CHECKMARK_URL__");
}
QCheckBox::indicator:checked:hover {
    width: 16px;
    height: 16px;
    background-color: #0088c8;
    border: 1.5px solid #0066a0;
    image: url("__CHECKMARK_URL__");
}

#MainWindow {
    background-color: #f0f2f5;
}

#sidePanel {
    background-color: #e4e8ef;
    border-right: 1px solid #c8d0dc;
}

#connectionScroll {
    background-color: transparent;
    border: none;
}

#dialogTitle {
    color: #0077b6;
    font-size: 18px;
    font-weight: bold;
    margin-bottom: 5px;
}

#sectionLabel {
    color: #0077b6;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    margin-top: 8px;
}

#fieldLabel {
    color: #4a5a6a;
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 2px;
}

#hintLabel {
    color: #7a8a9a;
    font-size: 11px;
}

#ctrlRowLabel {
    color: #445769;
    font-size: 12px;
    font-weight: 600;
}

/* ---- Settings Cards (per-section) ------------------------ */
#settingsGroupCard {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 14px;
}

#settingsRow {
    background: transparent;
    border-radius: 0px;
}

#settingsRow:hover {
    background: rgba(0, 0, 0, 0.03);
}

#rowSep {
    background-color: rgba(0, 0, 0, 0.07);
    max-height: 1px;
    min-height: 1px;
    margin: 0 14px;
}

#rowLabel {
    color: #1a2332;
    font-size: 13px;
}

QPushButton#settingsActionBtn {
    background-color: #f0f4f8;
    border: 1px solid #c8d3df;
    border-radius: 10px;
    color: #3a5067;
    font-size: 12px;
    font-weight: 600;
    padding: 0 14px;
    text-align: center;
}
QPushButton#settingsActionBtn:hover {
    background-color: #e4ecf4;
    border: 1px solid #9ab0c5;
    color: #182536;
}
QPushButton#settingsActionBtn[btn_type="primary"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0088c8, stop:1 #005fa3);
    border: none;
    color: #fff;
    font-weight: 700;
}
QPushButton#settingsActionBtn[btn_type="primary"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #009add, stop:1 #006fb8);
}

#errorLabel { color: #dc2626; font-size: 12px; }
#mutedLabel { color: #6a7a8a; font-size: 12px; }
#accentLabel { color: #0077b6; font-size: 11px; }
#secondaryTitle { color: #2a3a4a; font-size: 11px; font-weight: bold; }

#divider {
    background-color: rgba(0, 0, 0, 0.10);
    max-height: 1px;
    min-height: 1px;
    margin: 10px 4px;
}

#dialogHeroCard, #dialogSectionCard {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 18px;
}

#dialogLead {
    color: #617386;
    font-size: 13px;
}

#dialogPill {
    background-color: #edf7fc;
    color: #0077b6;
    font-family: "Consolas";
    font-size: 10px;
    font-weight: 700;
    border: 1px solid rgba(0, 119, 182, 0.18);
    border-radius: 12px;
    padding: 4px 10px;
}

QLabel#dialogLink {
    color: #0077b6;
    font-size: 13px;
    font-weight: 600;
}

QPushButton#dialogMaximizeBtn {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 10px;
}
QPushButton#dialogMaximizeBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
}
QPushButton#dialogMaximizeBtn:checked {
    background-color: rgba(0, 119, 182, 0.10);
    border: 1px solid rgba(0, 119, 182, 0.28);
}

#sysinfoHeroCard, #sysinfoSectionCard, #sysinfoStateCard {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 18px;
}

#sysinfoLoadingOverlay {
    background-color: rgba(235, 241, 247, 165);
}
#sysinfoLoadingCard {
    background-color: rgba(255, 255, 255, 248);
    border: 1px solid rgba(0, 119, 182, 0.20);
    border-radius: 18px;
    min-width: 260px;
}
#sysinfoLoadingIcon {
    color: #0077b6;
    font-size: 26px;
}
#sysinfoLoadingTitle {
    color: #182536;
    font-size: 14px;
    font-weight: 800;
}
#sysinfoLoadingDots {
    color: #0077b6;
    font-family: "Consolas";
    font-size: 16px;
    font-weight: 800;
    min-height: 18px;
}

#sysinfoHeroTitle {
    color: #182536;
    font-size: 18px;
    font-weight: 700;
}

#sysinfoHeroMeta {
    color: #617386;
    font-size: 12px;
}

#sysinfoStatePill {
    background-color: #edf7fc;
    color: #0077b6;
    font-family: "Consolas";
    font-size: 10px;
    font-weight: 700;
    border: 1px solid rgba(0, 119, 182, 0.18);
    border-radius: 8px;
    padding: 4px 10px;
}
#sysinfoStatePill[connected="false"] {
    background-color: rgba(220, 38, 38, 0.10);
    color: #c62828;
    border: 1px solid rgba(220, 38, 38, 0.24);
}

#sysinfoStateText {
    color: #617386;
    font-size: 12px;
}

#sysinfoErrorText {
    color: #c62828;
    font-size: 12px;
}

#sysinfoStatLabel {
    color: #6a7a8a;
    font-size: 11px;
    font-weight: 600;
}

#sysinfoStatValue {
    color: #182536;
    font-size: 12px;
    font-weight: 700;
}

QProgressBar#sysinfoProgress {
    background-color: #e7edf4;
    border-radius: 3px;
}
QProgressBar#sysinfoProgress::chunk {
    background-color: #0077b6;
    border-radius: 3px;
}
QProgressBar#sysinfoProgress[level="warn"]::chunk {
    background-color: #d97706;
    border-radius: 3px;
}
QProgressBar#sysinfoProgress[level="error"]::chunk {
    background-color: #dc2626;
    border-radius: 3px;
}

QMenu {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 8px;
    color: #1a2332;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: #edf5fb;
    color: #0077b6;
}
QMenu::item:disabled {
    color: #aab4c4;
}
QMenu::separator {
    height: 1px;
    background: #d5dde7;
    margin: 4px 2px;
}

QMenu#trayMenu {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    color: #182536;
    padding: 6px;
}
QMenu#trayMenu::item {
    padding: 8px 18px;
    border-radius: 8px;
}
QMenu#trayMenu::item:selected {
    background-color: #edf5fb;
    color: #0077b6;
}
QMenu#trayMenu::separator {
    height: 1px;
    background: #d5dde7;
    margin: 6px 2px;
}

#debugSurface {
    background-color: #f0f4f8;
}

#debugToolbar {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 18px;
}

#debugTitle {
    color: #182536;
    font-size: 18px;
    font-weight: 700;
}

#debugMeta {
    color: #617386;
    font-size: 12px;
}

QCheckBox#debugCheck {
    color: #617386;
    font-size: 12px;
    font-weight: 600;
}

QTextEdit#debugLogView {
    background-color: #ffffff;
    color: #182536;
    border: 1px solid #d5dde7;
    border-radius: 18px;
    padding: 14px;
}

#loadingOverlay {
    background-color: rgba(235, 241, 247, 165);
}

#loadingFrame {
    background-color: rgba(255, 255, 255, 248);
    border: 1px solid rgba(0, 119, 182, 0.20);
    border-radius: 18px;
}

#loadingText {
    color: #182536;
    font-size: 18px;
    font-weight: 700;
}

#loadingDots {
    color: #0077b6;
    font-family: "Consolas";
    font-size: 18px;
    font-weight: 700;
}

#loadingHint {
    color: #617386;
    font-size: 12px;
}

#userBox {
    background: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 16px;
}

#userBox QLabel[state="user_row"] {
    color: #1a2332;
    font-size: 13px;
    background: transparent;
    border: none;
}

#userBox[current="true"] {
    border: 1px solid rgba(0, 119, 182, 0.30);
    background: rgba(0, 119, 182, 0.08);
}

#userAvatar {
    background: #f3f6fa;
    border: 1px solid #c8d3df;
    border-radius: 14px;
    color: #203246;
    font-family: "Consolas";
    font-size: 13px;
    font-weight: 700;
}

#userAvatar[admin="true"] {
    background: rgba(0, 180, 216, 0.12);
    border: 1px solid rgba(0, 180, 216, 0.38);
    color: #0f7cb2;
}

#userMetaSub {
    color: #617386;
    font-size: 11px;
    font-family: "Consolas";
}

#userRowName {
    color: #1a2332;
    font-size: 13px;
    font-weight: 600;
}

#userRoleBadge {
    padding: 3px 8px;
    border-radius: 8px;
    background: #f3f6fa;
    border: 1px solid #d5dde7;
    color: #617386;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
}

#userRoleBadge[variant="accent"] {
    background: rgba(0, 180, 216, 0.12);
    border: 1px solid rgba(0, 180, 216, 0.34);
    color: #0f7cb2;
}

QScrollBar:vertical {
    background: transparent;
    width: 4px;
    margin: 2px 0;
    border-radius: 2px;
}
QScrollBar::handle:vertical {
    background: rgba(100, 130, 160, 0.35);
    border-radius: 2px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: rgba(100, 130, 160, 0.65); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

#connectionCard {
    background-color: #ffffff;
    border: 1px solid #d7e0ea;
    border-radius: 16px;
    margin: 0px;
    padding: 0px;
}
#connectionCard:hover {
    background-color: #eff5fb;
    border: 1px solid #a8c3dc;
}
#connectionCard[mounted="true"] {
    background-color: #e8f6fb;
    border: 1px solid rgba(0, 119, 182, 0.46);
}
#connectionCard[selected="true"] {
    border: 1px solid #1590cf;
    background-color: #dff1fb;
}
#connectionCard[expanded="true"] {
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
    margin-bottom: 0px;
    border-bottom: none;
}

#cardInfoWrapper { background: transparent; }
#connName { color: #1a2332; font-size: 14px; font-weight: 600; }
#connDetail { color: #6a7a8a; font-size: 11px; }

#cloudIcon { font-size: 22px; color: #b0bac4; }
#cloudIcon[mounted="true"] { color: #0077b6; }
#cloudIcon[state="large"] { font-size: 48px; padding: 8px; }

#driveBadge {
    background-color: #edf7fc;
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 700;
    border-radius: 9px;
    padding: 2px 4px;
    border: 1px solid #c7dfef;
}

#driveBadge[mounted="true"] {
    background-color: rgba(0, 180, 80, 0.12);
    color: #007a3d;
    border: 1px solid #007a3d;
}

#systemInfoPanel {
    background-color: #eef2f7;
    border: 1px solid #c8d0dc;
    border-top: none;
    border-bottom-left-radius: 12px;
    border-bottom-right-radius: 12px;
    margin: 0 12px 12px 12px;
    padding: 8px;
}

#sysinfoFullPanel {
    background-color: transparent;
    border: none;
    margin: 0;
    padding: 0;
}

#sectionFrame {
    background-color: #ffffff;
    border: 1px solid #d0d8e4;
    border-radius: 8px;
    padding: 6px;
}

#sectionTitle { color: #0077b6; font-size: 10px; font-weight: bold; text-transform: uppercase; }
#infoLabel { color: #6a7a8a; font-size: 10px; }
#valueLabel { color: #1a2332; font-size: 11px; font-weight: 500; }
#bigValue { color: #1a2332; font-size: 15px; font-weight: bold; }

#sidebar {
    background-color: #e4e8ef;
    border-right: 1px solid #c8d0dc;
    min-width: 60px;
    max-width: 60px;
}

#connectionsPanel { background-color: #f0f2f5; }

#connectionsHeader {
    background-color: #edf2f7;
    border-bottom: 1px solid #d5dde7;
    min-height: 52px;
    max-height: 52px;
}

#connectionsKicker {
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
}

#connectionsTitle {
    color: #1a2332;
    font-size: 16px;
    font-weight: 700;
}

#connectionsBadge {
    background-color: #ffffff;
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 600;
    border: 1px solid rgba(0, 119, 182, 0.22);
    border-radius: 8px;
    min-height: 32px;
    max-height: 32px;
    padding: 0 8px;
}

/* ---- Splitter handle (Light) -------------------------------- */
#bodySplitter::handle {
    background-color: #c8d0dc;
    width: 4px;
}
#bodySplitter::handle:hover {
    background-color: #0077b6;
}

#rightPanel {
    background-color: #f3f6fa;
    border-left: 1px solid #d5dde7;
}

#rightPanelHeader {
    background-color: #edf2f7;
    border-bottom: 1px solid #d5dde7;
    min-height: 52px;
    max-height: 52px;
    padding: 0 16px;
}

#rightPanelKicker { color: #0077b6; font-family: "Consolas"; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 1.4px; }
#rightPanelTitle { color: #1a2332; font-size: 16px; font-weight: 700; }
#rightPanelEmpty { color: #8093a7; font-size: 12px; }

#rightPanelPlaceholderTitle {
    color: #182536;
    font-size: 20px;
    font-weight: 700;
    padding: 0;
}

#rightPanelPlaceholderBody {
    color: #617386;
    font-size: 13px;
    padding: 0;
    min-height: 45px;
    max-height: 45px;
}

#rightPanelPlaceholder,
#connectionsTitleWrap,
#rightPanelTitleWrap,
#fullscreenContent {
    background: transparent;
}

#fullscreenPanel {
    background-color: #f0f4f8;
}

#fullscreenForm {
    background-color: transparent;
}

#fullscreenSectionCard {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 18px;
}

QPushButton#sidebarBtn {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    min-width: 42px;
    max-width: 42px;
    min-height: 42px;
    max-height: 42px;
}
QPushButton#sidebarBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
}
QPushButton#sidebarBtn[active="true"] {
    background-color: rgba(0, 119, 182, 0.10);
    border: 1px solid rgba(0, 119, 182, 0.28);
}
QPushButton#sidebarBtn[btn_type="danger"] {
    border: 1px solid #d5dde7;
}
QPushButton#sidebarBtn[btn_type="danger"]:hover {
    background-color: rgba(220, 38, 38, 0.10);
    border: 1px solid rgba(220, 38, 38, 0.3);
}
QPushButton#sidebarBtn[btn_type="warning"] {
    border: 1px solid #d5dde7;
}
QPushButton#sidebarBtn[btn_type="warning"]:hover {
    background-color: rgba(217, 119, 6, 0.10);
    border: 1px solid rgba(217, 119, 6, 0.3);
}

QPushButton#headerAddBtn {
    background-color: #effaf3;
    border: 1px solid rgba(0, 122, 61, 0.26);
    border-radius: 10px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#headerAddBtn:hover {
    background-color: rgba(0, 122, 61, 0.14);
    border: 1px solid #007a3d;
}

/* ---- Mount/Dismount All Buttons (Light) ---------------- */
QPushButton#headerActionBtn {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    min-height: 30px;
    max-height: 30px;
    min-width: 30px;
    max-width: 30px;
}
QPushButton#headerActionBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
}

/* ---- Groups Filter Dropdown (Light) -------------------- */
QComboBox#headerGroupsCombo {
    background-color: #ffffff;
    color: #182536;
    border: 1px solid #0077b6;
    border-radius: 12px;
    padding: 4px 10px;
    font-size: 12px;
    min-height: 22px;
}
QComboBox#headerGroupsCombo:hover {
    border: 1px solid #00b4d8;
}
QComboBox#headerGroupsCombo::drop-down {
    border: none;
    width: 20px;
}
QComboBox#headerGroupsCombo::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #182536;
    width: 0;
    height: 0;
}
QComboBox#headerGroupsCombo QAbstractItemView {
    background-color: #ffffff;
    color: #182536;
    border: 1px solid #d5dde7;
    border-radius: 8px;
    selection-background-color: #edf5fb;
    selection-color: #0077b6;
}

#versionLabel { color: #7d8fa2; font-size: 11px; font-family: "Consolas"; }

/* ---- Right Panel – content elements (Light) --------------- */
#rightPanelScroll {
    background-color: transparent;
    border: none;
}
#rightPanelContent { background-color: transparent; min-width: 100%;}
#rpInfoBody { background-color: transparent; }
QFrame#rpInfoField {
    background-color: #ffffff;
    border: 1px solid #e2e8ef;
    border-radius: 12px;
}
QFrame#rpInfoField QLineEdit,
QFrame#rpInfoField QSpinBox,
QFrame#rpInfoField QComboBox {
    padding: 0;
    min-height: 16px;
    max-height: 20px;
    background-color: transparent;
    border: none;
    border-bottom: 1px solid #c8d0dc;
    border-radius: 0;
    font-size: 14px;
    font-weight: 400;
    color: #1a2332;
}
QFrame#rpInfoField QLineEdit:focus,
QFrame#rpInfoField QSpinBox:focus,
QFrame#rpInfoField QComboBox:focus {
    border-bottom: 1px solid #0077b6;
    background-color: transparent;
}
QFrame#rpInfoField QPushButton {
    min-height: 16px;
    max-height: 20px;
    padding: 0 4px;
    font-size: 14px;
}
#rpSectionLabel {
    color: #0077b6;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding-top: 4px;
}
#rpFieldLabel { color: #000000; font-size: 11px; padding: 6px 0 1px 0; }
#rpValue {
    color: #1a2332;
    font-size: 12px;
    font-weight: 500;
    background-color: transparent;
    border: none;
    padding: 0;
}
QFrame#rpInfoField QLabel#rpFieldLabelCaps {
    color: #6a7685;
}
QLabel#rpFieldLabelCaps {
    font-size: 11px;
}
#rpDivider {
    background-color: #d5dde7;
    max-height: 1px;
    min-height: 1px;
}
#rpStatusDot { font-size: 9px; color: #9aacbe; }
#rpStatusDot[mounted="true"] { color: #007a3d; }
#rpStatusLabel { color: #8093a7; font-size: 11px; font-weight: 600; }
#rpStatusLabel[mounted="true"] { color: #007a3d; }
QPushButton#rpHeaderBtn {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 10px;
    min-width: 32px; max-width: 32px;
    min-height: 32px; max-height: 32px;
}
QPushButton#rpHeaderBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
}
QPushButton#rpHeaderBtn[btn_type="danger"] {
    background-color: rgba(220, 38, 38, 0.16);
    border: 1px solid rgba(220, 38, 38, 0.34);
}
QPushButton#rpHeaderBtn[btn_type="danger"]:hover {
    background-color: rgba(220, 38, 38, 0.22);
    border: 1px solid #dc2626;
}
QPushButton#rpHeaderBtn:disabled {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #b0bcc8;
}
QPushButton#rpHeaderBtn:disabled:hover {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
}
QPushButton#rpHeaderBtn[btn_type="danger"]:disabled,
QPushButton#rpHeaderBtn[btn_type="danger"]:disabled:hover {
    background-color: rgba(220, 38, 38, 0.08);
    border: 1px solid rgba(220, 38, 38, 0.20);
}
QPushButton#rpHeaderSaveBtn {
    background-color: rgba(0, 180, 80, 0.15);
    border: 1px solid rgba(0, 180, 80, 0.35);
    border-radius: 10px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#rpHeaderSaveBtn:hover {
    background-color: rgba(0, 180, 80, 0.24);
    border: 1px solid rgba(0, 180, 80, 0.60);
}
QPushButton#rpHeaderSaveBtn:disabled {
    background: #f4f7fa;
    border: 1px solid #d5dde7;
}
#rpBtnBar {
    background-color: #edf2f7;
    border-top: 1px solid #d5dde7;
}

QPushButton#rpActionBtn {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    color: #4a5a6a;
    font-size: 12px;
    font-weight: 600;
    padding: 7px 12px;
    min-height: 32px;
}
QPushButton#rpActionBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
    color: #1a2332;
}
QPushButton#rpActionBtn[btn_type="primary"] {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #00b4d8, stop:1 #0077b6);
    border: none;
    color: #deebf7;
}
QPushButton#rpActionBtn[btn_type="primary"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #22c4e8, stop:1 #0088c8);
}
QPushButton#rpActionBtn[btn_type="danger"] {
    background: rgba(220, 38, 38, 0.08);
    border: 1px solid rgba(220, 38, 38, 0.24);
    color: #c62828;
}
QPushButton#rpActionBtn[btn_type="danger"]:hover {
    background: rgba(220, 38, 38, 0.14);
    border: 1px solid #dc2626;
}
QPushButton#rpActionBtn:disabled {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #95a6b8;
}
QPushButton#rpActionBtn:disabled:hover {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #95a6b8;
}
QPushButton#cardInfoBtn[active="true"] {
    background: rgba(0, 119, 182, 0.12);
    border: 1px solid rgba(0, 119, 182, 0.5);
    color: #0077b6;
}

#actionBtn {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    color: #4a5a6a;
    font-size: 12px;
    padding: 7px 12px;
    text-align: left;
}
#actionBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
    color: #1a2332;
}
QPushButton#actionBtn:disabled {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #95a6b8;
}
QPushButton#actionBtn:disabled:hover {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #95a6b8;
}

#actionBtn[btn_type="primary"], #primaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #00b4d8, stop:1 #0077b6);
    border: none;
    color: #deebf7;
    font-weight: 700;
    padding: 0 14px;
    border-radius: 10px;
    min-height: 32px;
    max-height: 32px;
}
#actionBtn[btn_type="primary"]:hover, #primaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #22c4e8, stop:1 #0088c8);
}
#actionBtn[btn_type="primary"]:disabled, #primaryBtn:disabled,
#actionBtn[btn_type="primary"]:disabled:hover, #primaryBtn:disabled:hover {
    background: #e4e8ef;
    border: 1px solid #d5dde7;
    color: #9aacbe;
}

#secondaryBtn {
    background-color: #E4EAF0;
    border: 1px solid #d5dde7;
    border-radius: 10px;
    color: #4a5a6a;
    font-size: 13px;
    padding: 0 14px;
    min-height: 32px;
    max-height: 32px;
}
#secondaryBtn:hover {
    background-color: #edf5fb;
    border: 1px solid #aec6dd;
    color: #1a2332;
}
QPushButton#aboutLinkBtn {
    background-color: #f0f5fa;
    border: 1px solid #d5dde7;
    border-radius: 8px;
    color: #0077b6;
    font-size: 12px;
    padding: 0 10px;
    min-height: 34px;
    max-height: 34px;
    text-align: left;
}
QPushButton#aboutLinkBtn:hover {
    background-color: #e0eef8;
    border: 1px solid #0077b6;
    color: #005a8e;
}
QPushButton#aboutLinkBtn:pressed {
    background-color: #d0e6f5;
}
QLineEdit[invalid="true"] {
    border: 1px solid #0077b6;
}
QLineEdit[invalid="true"]:focus {
    border: 1px solid #0077b6;
}
QLineEdit:focus, QPushButton:focus {
    border: 1px solid #00b4d8;
}

#dialogBtnBar {
    background-color: #eef2f7;
    border-top: 1px solid #c8d0dc;
}

#actionBtn[btn_type="danger"], #dangerBtn {
    background: rgba(220, 38, 38, 0.08);
    border: 1px solid rgba(220, 38, 38, 0.3);
    border-radius: 10px;
    color: #dc2626;
    padding: 0 14px;
    min-height: 32px;
    max-height: 32px;
}
#actionBtn[btn_type="danger"]:hover, #dangerBtn:hover {
    background: rgba(220, 38, 38, 0.15);
    border: 1px solid #dc2626;
}

#actionBtn[btn_type="warning"] {
    background: rgba(217, 119, 6, 0.08);
    border: 1px solid rgba(217, 119, 6, 0.3);
    color: #d97706;
}
#actionBtn[btn_type="warning"]:hover {
    background: rgba(217, 119, 6, 0.15);
    border: 1px solid #d97706;
}

/* Integrated Terminal UI (light) */
#terminalArea {
    background-color: #f0f2f5;
}
#terminalTabBar {
    background-color: #e8edf3;
    border-bottom: 1px solid #c8d0dc;
}
#terminalTabBtn {
    background-color: #f4f7fa;
    border: 1px solid #d5dde7;
    border-radius: 6px;
    color: #6a7a8a;
    padding: 3px 12px;
    min-height: 24px;
    max-height: 24px;
    font-size: 11px;
}
#terminalTabBtn:hover {
    background-color: #edf5fb;
    color: #1a2332;
}
#terminalTabBtn:checked {
    background-color: #edf5fb;
    border-color: #0077b6;
    color: #0077b6;
}
#terminalEndBar {
    background-color: #e8edf3;
    border-top: 1px solid #c8d0dc;
}

QPushButton#sshBtn {
    background: #ffffff;
    border: 1px solid #d5dde7;
    color: #0077b6;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#sshBtn:hover {
    background: rgba(0, 119, 182, 0.10);
    border: 1px solid #72add6;
}
QPushButton#sshBtn:disabled,
QPushButton#sshBtn:disabled:hover {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #95a6b8;
}

QPushButton#cardInfoBtn, QPushButton#cardEditBtn {
    background: #E4EAF0;
    border: 1px solid #d5dde7;
    color: #4a5a6a;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#cardInfoBtn:hover, QPushButton#cardEditBtn:hover {
    background: rgba(0, 119, 182, 0.10);
    border: 1px solid #72add6;
    color: #0077b6;
}
QPushButton#cardEditBtn:disabled {
    color: #b0bac4;
    border: 1px solid #d0d8e4;
    background: #f0f2f5;
}

QPushButton#mountBtn {
    background-color: #ffffff;
    border: 1px solid #aec6dd;
    border-radius: 10px;
    color: #4a5a6a;
    font-size: 12px;
    font-weight: 700;
    padding: 0px;
    text-align: center;
}
QPushButton#mountBtn:hover {
    background-color: rgba(0, 119, 182, 0.10);
    border: 1px solid #72add6;
    color: #0077b6;
}
QPushButton#mountBtn:disabled,
QPushButton#mountBtn:disabled:hover {
    background-color: #f4f7fa;
    border: 1px solid #e2e8ef;
    color: #95a6b8;
}
QPushButton#mountBtn[mounted="true"] {
    background-color: rgba(0, 180, 80, 0.10);
    border: 1px solid #007a3d;
    color: #007a3d;
}
QPushButton#mountBtn[mounted="true"]:hover {
    background-color: rgba(220, 38, 38, 0.12);
    border: 1px solid #dc2626;
    color: #dc2626;
}
QPushButton#mountBtn[loading="true"], QPushButton#mountBtn[loading="true"]:disabled {
    background-color: rgba(0, 119, 182, 0.10);
    border: 1px solid rgba(0, 119, 182, 0.24);
    border-radius: 16px;
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    font-weight: 700;
    padding: 0 10px;
}

QLineEdit, QSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #c8d0dc;
    border-radius: 8px;
    color: #1a2332;
    padding: 3px 8px;
    font-size: 13px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #0077b6;
    background-color: #f5faff;
}
QLineEdit::placeholder { color: #9aacbe; }
QComboBox::drop-down { border: none; width: 30px; }
QComboBox::down-arrow {
    image: url("__CHEVRON_URL__");
    width: 12px;
    height: 12px;
    margin-right: 10px;
}

/* Dropdown popup (light) */
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #c8d0dc;
    border-radius: 12px;
    color: #1a2332;
    selection-background-color: rgba(0, 119, 182, 0.12);
    selection-color: #0077b6;
    outline: none;
    padding: 1px;
}
QComboBox QAbstractItemView::item {
    padding: 4px 4px;
    min-height: 24px;
    border-radius: 12px;
}
QComboBox QAbstractItemView::item:selected {
    background-color: rgba(0, 119, 182, 0.12);
}

#statusBar {
    background-color: #edf2f7;
    border-top: 1px solid #d5dde7;
    color: #4a5a6a;
    font-family: "Consolas";
    font-size: 12px;
    padding: 10px 14px;
}
#statusDot { color: #007a3d; font-size: 9px; margin-right: 4px; }
#statusText {
    color: #617386;
}
#statusPill {
    background-color: #ffffff;
    color: #0077b6;
    border: 1px solid rgba(0, 119, 182, 0.22);
    border-radius: 999px;
    padding: 4px 9px;
}

#mountErrorDialog {
    background-color: #f6f9fc;
}

#mountErrorLead {
    color: #182536;
    font-size: 13px;
    font-weight: 600;
}

#mountErrorBlock {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 14px;
}

#mountErrorBody {
    color: #617386;
    font-size: 12px;
}

#mountErrorDetails {
    background-color: #ffffff;
    border: 1px solid #d5dde7;
    border-radius: 12px;
    color: #0077b6;
    font-family: "Consolas";
    font-size: 11px;
    padding: 12px;
}

QProgressBar {
    background-color: #dde2ea;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
    height: 8px;
}
QProgressBar::chunk {
    background-color: #0077b6;
    border-radius: 4px;
}

QTabWidget::pane {
    border: 1px solid #c8d0dc;
    border-radius: 10px;
    background: #f8fafc;
    margin-top: -1px;
}
QTabBar::tab {
    background: transparent;
    border-bottom: 2px solid transparent;
    color: #6a7a8a;
    font-size: 12px;
    padding: 10px 20px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    color: #0077b6;
    border-bottom: 2px solid #0077b6;
    font-weight: 600;
}

QDialog { background-color: #f0f2f5; }

#dialogTitle {
    color: #1a2332;
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 8px;
}

#sectionLabel {
    color: #0077b6;
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    padding-top: 12px;
}

#fieldLabel {
    color: #4a5a6a;
    font-size: 11px;
    font-weight: 600;
    margin-bottom: 2px;
}

QToolTip {
    background-color: #ffffff;
    border: 1px solid #c8d0dc;
    color: #1a2332;
    border-radius: 6px;
    padding: 5px 10px;
}

QMessageBox { background-color: #ffffff; }
QMessageBox QPushButton {
    min-width: 90px;
    min-height: 32px;
    max-height: 32px;
    padding: 0 14px;
}
"""
