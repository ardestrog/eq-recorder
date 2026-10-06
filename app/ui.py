"""AppKit panel for EQ Recorder: a Dock app with a single window.

One process, one NSApplication; the whole UI is plain AppKit. The panel
reads the state of `Engine` directly from the same process.

Visual constants (colors, typography, icons, component variants) live in
app/theme.py, the design system, and are not hardcoded here.

The window is never destroyed, only hidden (orderOut) or shown
(makeKeyAndOrderFront): background transcription keeps running while the
panel is hidden.
"""

import datetime
import os
import queue as _queue
import re
import subprocess
import sys
import time
import traceback
import wave

import objc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import audio_import                                          # noqa: E402
import config as C                                            # noqa: E402
import strings as S                                           # noqa: E402
import theme as T                                             # noqa: E402

from AppKit import (                                          # noqa: E402
    NSAlert, NSAlertFirstButtonReturn, NSAlertStyleWarning,
    NSApp, NSAppearance, NSAppearanceNameDarkAqua, NSApplication,
    NSAttributedString, NSBackingStoreBuffered,
    NSBezierPath, NSButton, NSColor, NSEdgeInsetsMake, NSEvent,
    NSEventMaskKeyDown, NSFont,
    NSFontAttributeName, NSFontWeightBold, NSFontWeightMedium,
    NSFontWeightRegular, NSFontWeightSemibold, NSForegroundColorAttributeName,
    NSImage, NSImageOnly,
    NSImageScaleProportionallyDown, NSImageScaleProportionallyUpOrDown,
    NSImageSymbolConfiguration,
    NSImageView, NSLayoutConstraint, NSLayoutConstraintOrientationHorizontal,
    NSLayoutGuide, NSLayoutPriorityDefaultLow, NSLineBreakByTruncatingMiddle,
    NSMenu, NSMenuItem, NSNoBorder, NSScrollView, NSStackView,
    NSTableColumn, NSTableColumnAutoresizingMask, NSTableRowView, NSTableView,
    NSTableViewLastColumnOnlyAutoresizingStyle,
    NSTableViewSelectionHighlightStyleNone, NSTableViewStylePlain, NSTextField,
    NSTrackingActiveInKeyWindow, NSTrackingInVisibleRect,
    NSTrackingMouseEnteredAndExited,
    NSUserInterfaceLayoutOrientationVertical, NSView, NSViewWidthSizable,
    NSWindow,
    NSWindowStyleMaskClosable, NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskTitled, NSWindowTitleHidden,
)
from Foundation import (                                      # noqa: E402
    NSInsetRect, NSMakePoint, NSMakeRect, NSMakeSize, NSObject, NSPointInRect,
    NSTimer,
)

# Sizes and spacing live only in theme.py (the panel layout section); this
# module holds no layout numbers, just the NSLayoutConstraints in _build_window().

_WEIGHTS = {
    "regular": NSFontWeightRegular, "medium": NSFontWeightMedium,
    "semibold": NSFontWeightSemibold, "bold": NSFontWeightBold,
}

# Table row kind -> (action icon, action name). The color of the row's
# status marker comes from T.CARD_KIND_COLOR (a StatusDot, not an SF Symbol).
_ROW_ACTION = {
    "orphan": ("record_start", "record"),
    "error": ("record_start", "record"),
    "done": ("open_folder", "reveal"),
}


def _ns_color(hex_str: str):
    h = hex_str.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)


def _font(size: float, weight: str = "regular"):
    """Roboto Mono, bundled with the app (build_app.sh sets
    ATSApplicationFontsPath in Info.plist, so macOS registers it for the app
    process). The system-font fallback is needed when the app runs directly
    (`python3 app/recorder.py`, not via the .app bundle): then
    ATSApplicationFontsPath has no effect and NSFont.fontWithName_size_
    returns None.
    """
    name = T.FONT_BY_WEIGHT.get(weight, T.FONT_REGULAR)
    font = NSFont.fontWithName_size_(name, size)
    return font or NSFont.systemFontOfSize_weight_(size, _WEIGHTS[weight])


def _symbol(name: str, size: float = 14, weight: str = "regular"):
    """An SF Symbols icon as a template image, ready for tinting."""
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if img is None:
        return None
    cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(
        size, _WEIGHTS[weight])
    img = img.imageWithSymbolConfiguration_(cfg)
    img.setTemplate_(True)
    return img


def _reveal_in_finder(path: str) -> None:
    """Open Finder with the file selected. Shared by the folder icon on a
    card and the LAST FILE button.
    """
    subprocess.run(["open", "-R", path], check=False)


# ─────────────────────────── small custom views ────────────────────────


def _safe_draw(method):
    """Keep any exception from escaping drawRect_.

    An exception raised inside drawRect_ during a CATransaction flush makes
    NSApplication._crashOnException: kill the process silently, with no
    traceback in the log. The wrapper prints the cause instead.
    """
    def wrapper(self, rect):
        try:
            method(self, rect)
        except Exception:                                        # noqa: BLE001
            traceback.print_exc()
    wrapper.__name__ = method.__name__
    return wrapper


def _safe_event(method):
    """Same protection as _safe_draw, for mouseEntered_, mouseExited_ and
    updateTrackingAreas, which AppKit also calls synchronously outside the
    usual Python stack.
    """
    def wrapper(self, *args):
        try:
            method(self, *args)
        except Exception:                                        # noqa: BLE001
            traceback.print_exc()
    wrapper.__name__ = method.__name__
    return wrapper


class StatusDot(NSView):
    """A colored circle, used filled in the header and as a hollow ring
    status marker on a row card.
    """

    @_safe_draw
    def drawRect_(self, rect):                                    # noqa: N802,ARG002
        color = _ns_color(getattr(self, "_color", T.TEXT_SECONDARY))
        filled = getattr(self, "_filled", True)
        bounds = self.bounds()
        if filled:
            color.setFill()
            NSBezierPath.bezierPathWithOvalInRect_(bounds).fill()
        else:
            oval = NSBezierPath.bezierPathWithOvalInRect_(
                NSInsetRect(bounds, 1, 1))
            oval.setLineWidth_(1.5)
            color.setStroke()
            oval.stroke()

    def setColor_(self, hex_color):                                # noqa: N802
        self._color = hex_color
        self.setNeedsDisplay_(True)

    def setFilled_(self, filled):                                  # noqa: N802
        self._filled = bool(filled)
        self.setNeedsDisplay_(True)


class ProgressBar(NSView):
    """Thin custom progress bar in theme colors (the native one ignores the accent)."""

    @_safe_draw
    def drawRect_(self, rect):                                     # noqa: N802,ARG002
        bounds = self.bounds()
        radius = bounds.size.height / 2.0
        _ns_color(T.SURFACE).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, radius, radius).fill()
        pct = getattr(self, "_progress", 0.0)
        if pct > 0:
            width = max(bounds.size.height, bounds.size.width * (pct / 100.0))
            fill_rect = NSMakeRect(0, 0, width, bounds.size.height)
            _ns_color(T.ACCENT).setFill()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                fill_rect, radius, radius).fill()

    def setProgress_(self, pct):                                   # noqa: N802
        self._progress = max(0.0, min(100.0, pct))
        self.setNeedsDisplay_(True)


def _zero_insets(self):
    """alignmentRectInsets = 0 for the custom buttons and icons.

    An image-only NSButton and an NSImageView with an SF Symbol have
    non-zero alignment insets (symbol padding, bezel shadow), and AutoLayout
    sizes the alignment rect, so an icon-only button would come out taller
    than its constant height. The background is drawn by the view itself, so
    the alignment rect equals the frame.
    """
    return NSEdgeInsetsMake(0, 0, 0, 0)


class FlatImageView(NSImageView):
    """NSImageView without alignment insets (see _zero_insets)."""

    alignmentRectInsets = _zero_insets


class PillButton(NSButton):
    """Button with its own background and corner radius (not a system bezel).

    NSBezelStyleRounded gives a fixed ~6-8px radius that cannot be
    controlled directly. The background is drawn here (drawRect_ +
    NSBezierPath, the same CALayer-free approach as the other custom views),
    while the title and image are left to the system drawing via super(),
    which also gives a correct disabled state (the text dims on its own).
    """

    @_safe_draw
    def drawRect_(self, rect):                                     # noqa: N802
        bounds = self.bounds()
        radius = getattr(self, "_radius", bounds.size.height / 2.0)
        color = getattr(self, "_bg_color", T.SURFACE)
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, radius, radius)
        _ns_color(color).setFill()
        path.fill()
        border_color = getattr(self, "_border_color", None)
        if border_color:
            # Thin outline for the secondary buttons (Output Folder / Last
            # File) so they do not get lost in empty space; same 1pt-inset
            # technique as RowCard.
            border = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSInsetRect(bounds, 0.75, 0.75), max(0, radius - 0.75),
                max(0, radius - 0.75))
            border.setLineWidth_(1.0)
            _ns_color(border_color).setStroke()
            border.stroke()
        objc.super(PillButton, self).drawRect_(rect)

    alignmentRectInsets = _zero_insets

    def setBgColor_(self, hex_color):                              # noqa: N802
        self._bg_color = hex_color
        self.setNeedsDisplay_(True)

    def setBorderColor_(self, hex_color):                          # noqa: N802
        self._border_color = hex_color
        self.setNeedsDisplay_(True)

    def setRadius_(self, radius):                                  # noqa: N802
        self._radius = radius
        self.setNeedsDisplay_(True)


class DropdownButton(PillButton):
    """Custom filter dropdown: a PillButton whose text and chevron are its
    own subviews. Without hitTest_, a click on the text or chevron would be
    caught by the NSTextField/NSImageView instead of the button; this way the
    whole button area delivers the click to it.
    """

    def hitTest_(self, point):                                     # noqa: N802
        return self if NSPointInRect(point, self.frame()) else None


class ThemedRowView(NSTableRowView):
    """Table row view. Background and selection are drawn by RowCard, which
    sits on top of this view and would hide any drawing done here, so this
    class draws nothing.
    """


class TintOverlay(NSView):
    """Solid opaque window background (no vibrancy; see _build_window).

    It is drawn with drawRect_ and NSBezierPath rather than
    CALayer.setBackgroundColor_(color.CGColor()): PyObjC does not bridge
    CGColorRef reliably (it leaves an opaque pointer object and warns with
    ObjCPointerWarning), and the app crashes without a traceback right after
    the layer's first real render. The same drawRect_ approach is used by
    StatusDot and ProgressBar.
    """

    @_safe_draw
    def drawRect_(self, rect):                                     # noqa: N802,ARG002
        _ns_color(T.BG).setFill()
        NSBezierPath.bezierPathWithRect_(self.bounds()).fill()


class RowCard(NSView):
    """Table row background: a rounded card with three explicit looks,
    normal, hover and selected.

    It uses the same drawRect_ approach as TintOverlay, without
    CALayer/CGColor. Hover tracking uses an NSTrackingArea.
    """

    @_safe_draw
    def drawRect_(self, rect):                                     # noqa: N802,ARG002
        selected = getattr(self, "_selected", False)
        hovered = getattr(self, "_hovered", False)
        bounds = self.bounds()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, T.CORNER_RADIUS, T.CORNER_RADIUS)
        if selected:
            bg = T.CARD_BG_SELECTED
        elif hovered:
            bg = T.CARD_BG_HOVER
        else:
            bg = T.CARD_BG
        _ns_color(bg).setFill()
        path.fill()
        if selected:
            border = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSInsetRect(bounds, 1, 1), T.CORNER_RADIUS - 1,
                T.CORNER_RADIUS - 1)
            border.setLineWidth_(1.5)
            _ns_color(T.CARD_BORDER_SELECTED).setStroke()
            border.stroke()

    def setSelected_(self, selected):                              # noqa: N802
        self._selected = bool(selected)
        self.setNeedsDisplay_(True)

    def setHovered_(self, hovered):                                # noqa: N802
        self._hovered = bool(hovered)
        self.setNeedsDisplay_(True)

    @_safe_event
    def updateTrackingAreas(self):                                 # noqa: N802
        objc.super(RowCard, self).updateTrackingAreas()
        for area in list(self.trackingAreas()):
            self.removeTrackingArea_(area)
        area = __import__("AppKit").NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            NSTrackingActiveInKeyWindow | NSTrackingMouseEnteredAndExited
            | NSTrackingInVisibleRect,
            self, None)
        self.addTrackingArea_(area)

    @_safe_event
    def mouseEntered_(self, event):                                # noqa: N802,ARG002
        self.setHovered_(True)

    @_safe_event
    def mouseExited_(self, event):                                 # noqa: N802,ARG002
        self.setHovered_(False)


class RowActionButton(NSButton):
    """Action icon in a table row (transcribe, or reveal in Finder).

    This must be a Python subclass: PyObjC allows arbitrary Python
    attributes (`_row_kind`, `_row_path`) only on instances of its own Python
    subclasses. A bare `NSButton.alloc()...` rejects them with an
    AttributeError, which PyObjC turns into an ObjC exception inside the
    AppKit layout call, outside the usual Python stack, where it kills the
    app without a traceback.
    """

    alignmentRectInsets = _zero_insets


class AppDelegate(NSObject):
    """NSApplication delegate, NSWindow delegate and table data source in one.

    The attributes engine_cls, tools_ok and tools_msg are assigned from
    outside right after alloc().init(): this is an NSObject, and a custom
    __init__ with arguments would need objc.super() handling, so assigning
    the fields on the finished instance is simpler.
    """

    # ── application lifecycle ──────────────────────────────────────────

    def applicationDidFinishLaunching_(self, notification):     # noqa: N802,ARG002
        self.panel_visible = False
        self._activated_at = 0.0
        self._flash_until = 0.0
        self._toast_is_saved_message = False
        self._rows = []
        self._done_total = 0
        self._hotkey_monitor = None
        self._last_selected_row = -1
        self._duration_cache = {}
        self._md_duration_cache = {}
        # Filter/sort mode of the DONE cards; kept in memory only and not
        # persisted across restarts.
        self._sort_filter = "all"

        self.engine = self.engine_cls()
        if not self.tools_ok:
            self.engine.status = S.STATUS_NO_FFMPEG
            C.notify(C.APP_NAME, S.NOTIFY_NO_FFMPEG_TITLE, self.tools_msg)

        self._build_menu()
        self._build_window()
        self._set_dock_icon()
        self._install_hotkeys()

        self._show_panel()
        self.refresh()

        self.timer = (
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.5, self, "onTick:", None, True))
        if os.environ.get("EQ_LAYOUT_DEBUG"):
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.5, self, "dumpLayout:", None, False)

    def dumpLayout_(self, timer):                                  # noqa: N802,ARG002
        """With EQ_LAYOUT_DEBUG=1, print the real frames of the key views to
        the log (window coordinates, y measured from the TOP). It checks the
        layout numerically: the left and right edges of all rows must match.
        """
        content = self.window.contentView()
        height = content.bounds().size.height
        names = ("logo", "engineLabel", "hotkeysButton", "recordButton",
                 "statusDot", "statusLabel", "recIndicatorLabel", "timerLabel",
                 "progressBar", "queueLabel", "processingLabel", "sortButton",
                 "sortLabel", "sortChevron", "removeButton")
        views = [(n, getattr(self, n)) for n in names]
        views += [(f"bottom:{v.title()}", v) for v in content.subviews()
                  if isinstance(v, PillButton) and v.title()
                  and v is not self.recordButton]
        views.append(("scroll", self.table.enclosingScrollView()))
        card = (self.table.viewAtColumn_row_makeIfNecessary_(0, 0, False)
                if self._rows else None)
        if card is not None:
            views += [("card0", card), ("card0.title", card.titleField),
                      ("card0.action", card.actionButton),
                      ("card0.marker", card.statusMarker)]
        for name, view in views:
            r = view.convertRect_toView_(view.bounds(), content)
            base = ""
            try:
                base = f" baseline={height - r.origin.y - r.size.height + view.firstBaselineOffsetFromTop():.1f}"
            except Exception:                                    # noqa: BLE001
                pass
            print(f"[layout] {name:22s} L={r.origin.x:6.1f} R={r.origin.x + r.size.width:6.1f} "
                  f"top={height - r.origin.y - r.size.height:6.1f} "
                  f"w={r.size.width:6.1f} h={r.size.height:5.1f}"
                  f"{' hidden' if view.isHidden() else ''}{base}",
                  file=sys.stderr)

    def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, flag):  # noqa: N802,ARG002
        # Dock icon click, or launching the bundle again (with the native
        # launcher macOS sends a reopen here instead of starting a second
        # process). If the app has just become active (it was behind other
        # windows or hidden), the user wants to SEE the panel, so only show
        # it. Hide it only when it was already in front; an unconditional
        # toggle would hide a window that merely sat under other windows.
        if time.time() - self._activated_at < 1.0:
            self._show_panel()
        else:
            self._toggle_panel()
        return False

    def applicationDidBecomeActive_(self, notification):          # noqa: N802,ARG002
        # A second launch via start.sh (without LaunchServices) activates this
        # process through C.activate_instance(). An active app with no visible
        # window would look dead, so show the panel if it is hidden.
        self._activated_at = time.time()
        window = getattr(self, "window", None)   # may not exist before _build_window()
        if window is not None and not window.isVisible():
            self._show_panel()

    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):  # noqa: N802,ARG002
        return False

    def applicationWillTerminate_(self, notification):           # noqa: N802,ARG002
        try:
            self.engine.shutdown()
        except Exception:                                        # noqa: BLE001
            pass
        try:
            os.remove(C.PID_FILE)
        except OSError:
            pass

    # ── panel window ──────────────────────────────────────────────────

    def windowShouldClose_(self, sender):                        # noqa: N802,ARG002
        # The close button HIDES the panel instead of quitting: background
        # transcription keeps running while the panel is hidden.
        self._hide_panel()
        return False

    def _show_panel(self):
        if NSApp.isHidden():
            NSApp.unhide_(None)
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self.panel_visible = True

    def _hide_panel(self):
        self.window.orderOut_(None)
        self.panel_visible = False

    def _toggle_panel(self):
        # Use the window's real visibility, not just our flag: Cmd+H hides
        # the app without touching panel_visible.
        visible = self.window.isVisible() and not NSApp.isHidden()
        self._hide_panel() if visible else self._show_panel()

    # ── building the UI ───────────────────────────────────────────────

    def _build_menu(self):
        main_menu = NSMenu.alloc().init()
        app_menu_item = NSMenuItem.alloc().init()
        main_menu.addItem_(app_menu_item)
        app_menu = NSMenu.alloc().init()
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            S.QUIT_MENU_ITEM.format(app=C.APP_NAME), "terminate:", "q")
        app_menu.addItem_(quit_item)
        app_menu_item.setSubmenu_(app_menu)
        NSApp.setMainMenu_(main_menu)

    def _set_dock_icon(self):
        try:
            if not os.path.exists(C.ICNS_PATH):
                return
            img = NSImage.alloc().initWithContentsOfFile_(C.ICNS_PATH)
            if img:
                NSApp.setApplicationIconImage_(img)
        except Exception:                                        # noqa: BLE001
            pass

    def _build_window(self):
        """The whole layout is NSLayoutConstraints (AutoLayout), with no manual x/y.

          * One horizontal padding guide `pad` (T.PANEL_PADDING_H on both
            sides); every row is pinned to its leading/trailing anchors.
          * Rows form a vertical chain (T.GAP_*) with heights from theme.py.
          * Text within a row is aligned on firstBaseline.
          * Content-dependent widths (READY: N, file name, status,
            ALL/SHORTEST) come from the intrinsic size; longer text is
            truncated instead of overlapping its neighbor.
        """
        rect = NSMakeRect(0, 0, T.WINDOW_WIDTH, T.WINDOW_HEIGHT)
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskMiniaturizable
                 | NSWindowStyleMaskFullSizeContentView)
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False)
        window.setTitle_(C.APP_NAME)
        window.setTitleVisibility_(NSWindowTitleHidden)
        window.setTitlebarAppearsTransparent_(True)
        window.setMovableByWindowBackground_(True)
        window.setReleasedWhenClosed_(False)   # hide, don't destroy
        # Without this the NATIVE window background (white/system default)
        # shows through for a moment during the deminiaturize genie animation,
        # before TintOverlay has redrawn, which looks like flicker.
        window.setBackgroundColor_(_ns_color(T.BG))
        window.setOpaque_(True)
        window.center()
        window.setDelegate_(self)
        content = window.contentView()
        cons = []                        # all constraints, activated at once

        def add(view, parent=content):
            view.setTranslatesAutoresizingMaskIntoConstraints_(False)
            parent.addSubview_(view)
            return view

        def size(view, w=None, h=None):
            if w is not None:
                cons.append(view.widthAnchor().constraintEqualToConstant_(w))
            if h is not None:
                cons.append(view.heightAnchor().constraintEqualToConstant_(h))

        # Flat background instead of an NSVisualEffectView (vibrancy blur),
        # which crashed the app on launch from the Dock (see _safe_draw). It
        # uses the same drawRect_ approach as the other custom views.
        tint = add(TintOverlay.alloc().initWithFrame_(content.bounds()))
        cons += [tint.leadingAnchor().constraintEqualToAnchor_(content.leadingAnchor()),
                 tint.trailingAnchor().constraintEqualToAnchor_(content.trailingAnchor()),
                 tint.topAnchor().constraintEqualToAnchor_(content.topAnchor()),
                 tint.bottomAnchor().constraintEqualToAnchor_(content.bottomAnchor())]

        # ── single padding container ────────────────────────────────────
        pad = NSLayoutGuide.alloc().init()
        content.addLayoutGuide_(pad)
        cons += [
            pad.leadingAnchor().constraintEqualToAnchor_constant_(
                content.leadingAnchor(), T.PANEL_PADDING_H),
            pad.trailingAnchor().constraintEqualToAnchor_constant_(
                content.trailingAnchor(), -T.PANEL_PADDING_H),
            pad.topAnchor().constraintEqualToAnchor_constant_(
                content.topAnchor(), T.PANEL_PADDING_TOP),
            pad.bottomAnchor().constraintEqualToAnchor_constant_(
                content.bottomAnchor(), -T.PANEL_PADDING_BOTTOM),
        ]

        def row_guide(top_anchor, gap, height):
            """Panel row: the full width of `pad`, fixed height."""
            guide = NSLayoutGuide.alloc().init()
            content.addLayoutGuide_(guide)
            cons.extend([
                guide.leadingAnchor().constraintEqualToAnchor_(pad.leadingAnchor()),
                guide.trailingAnchor().constraintEqualToAnchor_(pad.trailingAnchor()),
                guide.topAnchor().constraintEqualToAnchor_constant_(top_anchor, gap),
            ])
            if height is not None:
                cons.append(guide.heightAnchor().constraintEqualToConstant_(height))
            return guide

        def label(text, size=13, weight="regular", color=T.TEXT_PRIMARY,
                  truncate=None):
            field = add(NSTextField.labelWithString_(text))
            field.setFont_(_font(size, weight))
            field.setTextColor_(_ns_color(color))
            if truncate is not None:
                field.setLineBreakMode_(truncate)
                # Compresses first when the text is longer than the space.
                field.setContentCompressionResistancePriority_forOrientation_(
                    NSLayoutPriorityDefaultLow, NSLayoutConstraintOrientationHorizontal)
            return field

        def icon_view(icon_key, size=14, weight="regular",
                      color=T.TEXT_SECONDARY, parent=content):
            view = add(FlatImageView.alloc().init(), parent)
            img = _symbol(T.ICONS[icon_key], size=size, weight=weight)
            if img:
                view.setImage_(img)
            # The symbol keeps its natural size; the frame only centers it
            # and the symbol is not stretched to fit.
            view.setImageScaling_(NSImageScaleProportionallyDown)
            view.setContentTintColor_(_ns_color(color))
            return view

        def button(title, icon_key, action, accent=None, icon_only=False,
                   icon_color=None, bordered=False, height=T.BUTTON_HEIGHT):
            """Panel button: a PillButton with its own background and corner
            radius (theme.py) instead of the system NSBezelStyleRounded.

            Image and title are not combined: this bezel draws the icon and
            the title on top of each other instead of side by side. Text
            buttons are therefore text only, and the icon is used only in
            icon_only buttons.
            """
            btn = add(PillButton.alloc().init())
            btn.setTitle_("" if icon_only else title)
            if icon_only:
                # _symbol() needs the real SF Symbol name (T.ICONS[...]),
                # not the semantic key; otherwise it returns None.
                img = _symbol(T.ICONS[icon_key], size=16, weight="medium")
                if img:
                    btn.setImage_(img)
                    btn.setImagePosition_(NSImageOnly)
            btn.setFont_(_font(*T.TYPE_BUTTON))
            btn.setBordered_(False)
            btn.setRadius_(height / 2.0)
            btn.setBgColor_(accent or T.SURFACE)
            if bordered:
                btn.setBorderColor_(T.BORDER)
            tint_color = icon_color or (
                T.TEXT_PRIMARY if accent else T.TEXT_SECONDARY)
            btn.setContentTintColor_(_ns_color(tint_color))
            btn.setTarget_(self)
            btn.setAction_(action)
            size(btn, h=height)
            return btn

        # ── 1. header: logo · EQ RECORDER ······ ENGINE: PRO · [gear] ──
        header = row_guide(pad.topAnchor(), 0, T.HEADER_HEIGHT)
        logo = add(FlatImageView.alloc().init())
        if os.path.exists(C.PNG_PATH):
            logo.setImage_(NSImage.alloc().initWithContentsOfFile_(C.PNG_PATH))
        logo.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        size(logo, T.HEADER_LOGO_SIZE, T.HEADER_LOGO_SIZE)
        self.logo = logo
        title = label(S.APP_TITLE, size=14, weight="semibold")
        self.engineLabel = label(S.QUALITY_LABEL, size=T.TYPE_CAPTION[0],
                                 color=T.TEXT_SECONDARY)
        self.hotkeysButton = button("", "hotkeys", "fixHotkeys:",
                                    icon_only=True, height=T.ICON_BUTTON_SIZE)
        size(self.hotkeysButton, w=T.ICON_BUTTON_SIZE)
        self.hotkeysButton.setToolTip_(S.TOOLTIP_HOTKEYS)
        cons += [
            logo.leadingAnchor().constraintEqualToAnchor_(header.leadingAnchor()),
            logo.centerYAnchor().constraintEqualToAnchor_(header.centerYAnchor()),
            title.leadingAnchor().constraintEqualToAnchor_constant_(
                logo.trailingAnchor(), T.SPACE_XS),
            title.centerYAnchor().constraintEqualToAnchor_(header.centerYAnchor()),
            self.engineLabel.firstBaselineAnchor().constraintEqualToAnchor_(
                title.firstBaselineAnchor()),
            self.engineLabel.leadingAnchor().constraintGreaterThanOrEqualToAnchor_constant_(
                title.trailingAnchor(), T.SPACE_XS),
            self.hotkeysButton.trailingAnchor().constraintEqualToAnchor_(
                header.trailingAnchor()),
            self.hotkeysButton.centerYAnchor().constraintEqualToAnchor_(
                header.centerYAnchor()),
        ]
        # The gear is visible only while Accessibility is not granted. When it
        # is hidden, ENGINE: PRO sits flush against the right edge with no gap.
        # refresh() switches between the two constraints.
        self._engineToGear = self.engineLabel.trailingAnchor().constraintEqualToAnchor_constant_(
            self.hotkeysButton.leadingAnchor(), -T.SPACE_XS)
        self._engineToEdge = self.engineLabel.trailingAnchor().constraintEqualToAnchor_(
            header.trailingAnchor())

        # ── 2. record: [START RECORDING] ● READY ··········· 00:00 ─────────
        record = row_guide(header.bottomAnchor(), T.GAP_HEADER_RECORD,
                           T.BUTTON_HEIGHT)
        self.recordButton = button(S.BTN_START_RECORDING, "record_start",
                                   "toggleRecording:", accent=T.ACCENT_BUTTON_BG)
        size(self.recordButton, w=T.RECORD_BUTTON_WIDTH)
        self.timerLabel = label("00:00", size=T.TYPE_DISPLAY[0],
                                weight=T.TYPE_DISPLAY[1])
        self.timerLabel.setAlignment_(2)   # NSTextAlignmentRight
        # "● REC" and the dot + status share ONE slot (left of the timer);
        # refresh() shows exactly one of the two.
        self.recIndicatorLabel = label("", size=12, weight="bold",
                                       color=T.RECORDING)
        self.statusDot = add(StatusDot.alloc().init())
        size(self.statusDot, 10, 10)
        # The status/toast ("SAVED: <file name>") is the longest text in the
        # row: it is truncated in the middle (both "SAVED:" and ".md" stay
        # visible) instead of overlapping the timer. The full text is in the
        # tooltip.
        self.statusLabel = label(S.STATUS_READY, size=11,
                                 color=T.TEXT_SECONDARY,
                                 truncate=NSLineBreakByTruncatingMiddle)
        slot_x = self.recordButton.trailingAnchor()
        cons += [
            self.recordButton.leadingAnchor().constraintEqualToAnchor_(record.leadingAnchor()),
            self.recordButton.centerYAnchor().constraintEqualToAnchor_(record.centerYAnchor()),
            self.timerLabel.trailingAnchor().constraintEqualToAnchor_(record.trailingAnchor()),
            self.timerLabel.centerYAnchor().constraintEqualToAnchor_(record.centerYAnchor()),
            self.recIndicatorLabel.leadingAnchor().constraintEqualToAnchor_constant_(
                slot_x, T.SPACE_S),
            self.recIndicatorLabel.firstBaselineAnchor().constraintEqualToAnchor_(
                self.statusLabel.firstBaselineAnchor()),
            self.statusDot.leadingAnchor().constraintEqualToAnchor_constant_(
                slot_x, T.SPACE_S),
            self.statusDot.centerYAnchor().constraintEqualToAnchor_(
                self.statusLabel.centerYAnchor()),
            self.statusLabel.leadingAnchor().constraintEqualToAnchor_constant_(
                self.statusDot.trailingAnchor(), T.SPACE_XS),
            # Pinned to the button's center, not its baseline: a bezel-less
            # NSButton reports a firstBaseline ~13pt from the top although its
            # title is drawn at the center of the 44pt height. The status text
            # and "● REC" share one baseline with each other.
            self.statusLabel.centerYAnchor().constraintEqualToAnchor_(
                self.recordButton.centerYAnchor()),
            self.statusLabel.trailingAnchor().constraintLessThanOrEqualToAnchor_constant_(
                self.timerLabel.leadingAnchor(), -T.SPACE_S),
        ]

        # ── 3. progress (space is always reserved, so rows do not jump) ──
        progress = row_guide(record.bottomAnchor(), T.GAP_RECORD_PROGRESS,
                             T.PROGRESS_HEIGHT)
        self.progressBar = add(ProgressBar.alloc().init())
        self.progressBar.setHidden_(True)
        cons += [
            self.progressBar.leadingAnchor().constraintEqualToAnchor_(progress.leadingAnchor()),
            self.progressBar.trailingAnchor().constraintEqualToAnchor_(progress.trailingAnchor()),
            self.progressBar.topAnchor().constraintEqualToAnchor_(progress.topAnchor()),
            self.progressBar.bottomAnchor().constraintEqualToAnchor_(progress.bottomAnchor()),
        ]

        # ── 4. section: RECORDINGS  READY: N  PROCESSING: N ·········· [ALL ⌃] ──
        section = row_guide(progress.bottomAnchor(), T.GAP_PROGRESS_SECTION,
                            T.SECTION_ROW_HEIGHT)
        section_label = label(S.SECTION_RECORDINGS, size=T.TYPE_TITLE[0],
                              weight=T.TYPE_TITLE[1], color=T.TEXT_SECONDARY)
        self.queueLabel = label("", size=T.COUNTER_TYPE[0],
                                weight=T.COUNTER_TYPE[1],
                                color=T.COUNTER_READY_COLOR)
        self.processingLabel = label("", size=T.COUNTER_TYPE[0],
                                     weight=T.COUNTER_TYPE[1],
                                     color=T.COUNTER_PROCESSING_COLOR)
        self.processingLabel.setHidden_(True)

        # Filter/sort dropdown for the DONE cards. NSPopUpButton always draws
        # the system bezel, so this is a PillButton whose text and chevron are
        # its own subviews.
        self.sortButton = add(DropdownButton.alloc().init())
        self.sortButton.setTitle_("")
        self.sortButton.setBordered_(False)
        self.sortButton.setRadius_(T.DROPDOWN_HEIGHT / 2.0)
        self.sortButton.setBgColor_(T.SURFACE)
        self.sortButton.setTarget_(self)
        self.sortButton.setAction_("showSortMenu:")
        self.sortLabel = add(NSTextField.labelWithString_(S.FILTER_ALL),
                             self.sortButton)
        self.sortLabel.setFont_(_font(T.TYPE_CAPTION[0]))
        self.sortLabel.setTextColor_(_ns_color(T.TEXT_PRIMARY))
        self.sortChevron = icon_view("sort_chevron", size=10,
                                     parent=self.sortButton)
        size(self.sortChevron, T.DROPDOWN_CHEVRON_SIZE, T.DROPDOWN_CHEVRON_SIZE)
        size(self.sortButton, h=T.DROPDOWN_HEIGHT)
        sb = self.sortButton
        cons += [
            section_label.leadingAnchor().constraintEqualToAnchor_(section.leadingAnchor()),
            section_label.centerYAnchor().constraintEqualToAnchor_(section.centerYAnchor()),
            self.queueLabel.leadingAnchor().constraintEqualToAnchor_constant_(
                section_label.trailingAnchor(), T.SPACE_S),
            self.queueLabel.firstBaselineAnchor().constraintEqualToAnchor_(
                section_label.firstBaselineAnchor()),
            self.processingLabel.leadingAnchor().constraintEqualToAnchor_constant_(
                self.queueLabel.trailingAnchor(), T.COUNTER_GAP),
            self.processingLabel.firstBaselineAnchor().constraintEqualToAnchor_(
                section_label.firstBaselineAnchor()),
            self.processingLabel.trailingAnchor().constraintLessThanOrEqualToAnchor_constant_(
                sb.leadingAnchor(), -T.SPACE_XS),
            # The dropdown's right edge = the right edge of `pad` = the right
            # edge of the cards (the table column fills the whole scroll view
            # width, see below).
            sb.trailingAnchor().constraintEqualToAnchor_(section.trailingAnchor()),
            sb.widthAnchor().constraintGreaterThanOrEqualToConstant_(T.DROPDOWN_MIN_WIDTH),
            # Symmetric padding by construction: both the text and the
            # chevron are centered on the button's height.
            self.sortLabel.leadingAnchor().constraintEqualToAnchor_constant_(
                sb.leadingAnchor(), T.DROPDOWN_PADDING_LEFT),
            self.sortLabel.centerYAnchor().constraintEqualToAnchor_(sb.centerYAnchor()),
            # "ALL" sits on the same baseline as RECORDINGS / READY: N; the pill
            # button is centered around its text (the line above).
            self.sortLabel.firstBaselineAnchor().constraintEqualToAnchor_(
                section_label.firstBaselineAnchor()),
            self.sortChevron.trailingAnchor().constraintEqualToAnchor_constant_(
                sb.trailingAnchor(), -T.DROPDOWN_PADDING_RIGHT),
            self.sortChevron.centerYAnchor().constraintEqualToAnchor_(sb.centerYAnchor()),
            self.sortChevron.leadingAnchor().constraintGreaterThanOrEqualToAnchor_constant_(
                self.sortLabel.trailingAnchor(), T.SPACE_XS),
        ]

        # ── 6. bottom buttons: [🗑] [OUTPUT FOLDER] [LAST FILE] [IMPORT] ───
        # (built before the table, which stretches BETWEEN the section and
        # this row). Priority left to right: Remove (rare, destructive,
        # icon only), then navigation, then Import (the primary action).
        buttons = NSLayoutGuide.alloc().init()
        content.addLayoutGuide_(buttons)
        cons += [
            buttons.leadingAnchor().constraintEqualToAnchor_(pad.leadingAnchor()),
            buttons.trailingAnchor().constraintEqualToAnchor_(pad.trailingAnchor()),
            buttons.bottomAnchor().constraintEqualToAnchor_(pad.bottomAnchor()),
            buttons.heightAnchor().constraintEqualToConstant_(T.BUTTON_HEIGHT),
        ]
        self.removeButton = button("", "remove_queue", "removeSelected:",
                                   icon_only=True, icon_color=T.REMOVE_ICON_MUTED,
                                   height=T.ICON_BUTTON_SIZE)
        size(self.removeButton, w=T.ICON_BUTTON_SIZE)
        self.removeButton.setToolTip_(S.TOOLTIP_REMOVE)
        # Always enabled on purpose: refresh() switches between two explicit
        # colors (REMOVE_ICON_MUTED / STATUS_ERROR), because the system
        # dimming would make the icon look permanently faded. A click with
        # nothing selected does nothing (removeSelected_ returns early).
        out_btn = button(S.BTN_OUTPUT_FOLDER, "open_folder", "openFolder:",
                         bordered=True)
        last_btn = button(S.BTN_LAST_FILE, "reveal_last", "revealLast:",
                          bordered=True)
        imp_btn = button(S.BTN_IMPORT, "import_file", "importFile:",
                         accent=T.ACCENT_BUTTON_BG)
        cons += [
            self.removeButton.leadingAnchor().constraintEqualToAnchor_(buttons.leadingAnchor()),
            self.removeButton.centerYAnchor().constraintEqualToAnchor_(buttons.centerYAnchor()),
            out_btn.leadingAnchor().constraintEqualToAnchor_constant_(
                self.removeButton.trailingAnchor(), T.SPACE_XS),
            last_btn.leadingAnchor().constraintEqualToAnchor_constant_(
                out_btn.trailingAnchor(), T.SPACE_XS),
            imp_btn.leadingAnchor().constraintEqualToAnchor_constant_(
                last_btn.trailingAnchor(), T.SPACE_XS),
            imp_btn.trailingAnchor().constraintEqualToAnchor_(buttons.trailingAnchor()),
            # The three text buttons have equal widths.
            last_btn.widthAnchor().constraintEqualToAnchor_(out_btn.widthAnchor()),
            imp_btn.widthAnchor().constraintEqualToAnchor_(out_btn.widthAnchor()),
        ]
        for b in (out_btn, last_btn, imp_btn):
            cons.append(b.centerYAnchor().constraintEqualToAnchor_(buttons.centerYAnchor()))

        # ── 5. recordings list ──────────────────────────────────────────
        scroll = add(NSScrollView.alloc().init())
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        scroll.setBorderType_(NSNoBorder)
        cons += [
            scroll.leadingAnchor().constraintEqualToAnchor_(pad.leadingAnchor()),
            scroll.trailingAnchor().constraintEqualToAnchor_(pad.trailingAnchor()),
            scroll.topAnchor().constraintEqualToAnchor_constant_(
                section.bottomAnchor(), T.GAP_SECTION_LIST),
            scroll.bottomAnchor().constraintEqualToAnchor_constant_(
                buttons.topAnchor(), -T.GAP_LIST_BUTTONS),
        ]

        table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        # The default NSTableViewStyleAutomatic adds inset margins around the
        # rows. The card is drawn by RowCard, so use Plain: the column then
        # starts exactly at the table's left edge.
        table.setStyle_(NSTableViewStylePlain)
        table.setBackgroundColor_(NSColor.clearColor())
        table.setHeaderView_(None)
        table.setRowHeight_(T.CARD_HEIGHT)
        table.setIntercellSpacing_(NSMakeSize(0, T.CARD_GAP))
        table.setSelectionHighlightStyle_(NSTableViewSelectionHighlightStyleNone)
        # The single column ALWAYS spans the table width (= the width of
        # `pad`): AppKit keeps it that way, so the cards and the dropdown share
        # a right edge.
        table.setColumnAutoresizingStyle_(NSTableViewLastColumnOnlyAutoresizingStyle)
        column = NSTableColumn.alloc().initWithIdentifier_("row")
        column.setResizingMask_(NSTableColumnAutoresizingMask)
        table.addTableColumn_(column)
        table.setDataSource_(self)
        table.setDelegate_(self)
        # Clicking a row only selects it; the action is performed by the icon
        # in the row (rowActionClicked_).
        scroll.setDocumentView_(table)
        self.table = table
        self._tableColumn = column

        NSLayoutConstraint.activateConstraints_(cons)
        # Initial state: gear hidden (ENGINE: PRO against the edge); the
        # first refresh() switches it if Accessibility is not granted.
        self.hotkeysButton.setHidden_(True)
        self._engineToEdge.setActive_(True)
        self.window = window

    # ── file table ───────────────────────────────────────────────────

    @staticmethod
    def _format_duration(total_seconds):
        """Always a whole number, never fractional: under 60 s gives seconds,
        exact minutes give "N MIN", anything else "N MIN M SEC".
        `total_seconds` is rounded to int here; this is the only place where a
        card turns raw seconds into text.
        """
        total_seconds = int(round(total_seconds))
        if total_seconds < 60:
            return S.ROW_SECONDS.format(n=total_seconds)
        minutes, seconds = divmod(total_seconds, 60)
        if seconds == 0:
            return S.ROW_MINUTES.format(n=minutes)
        return S.ROW_MIN_SEC.format(m=minutes, s=seconds)

    def _wav_duration_seconds(self, path):
        """Duration of a WAV in whole seconds, read from the header with the
        stdlib `wave` module and no ffprobe subprocess: the tick refreshes
        every 0.5 s and computes this for every row, so a subprocess would be
        noticeably slow. Memoized by (path, mtime).
        """
        if not path:
            return None
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        cached = self._duration_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            with wave.open(path, "rb") as w:
                seconds = w.getnframes() / float(w.getframerate())
        except Exception:                                        # noqa: BLE001
            self._duration_cache[path] = (mtime, None)
            return None
        total = int(round(seconds))
        self._duration_cache[path] = (mtime, total)
        return total

    _DURATION_RE = re.compile(r"Тривалість:\*\*\s*([\d:]+)")

    def _md_duration_seconds(self, path):
        """Duration of a finished transcript in seconds, taken from the .md
        itself (build_md() writes "**Тривалість:** MM:SS" or "H:MM:SS") rather
        than recomputed from the wav: the wav and md names differ, and
        scanning a large audio file on every tick is needless when the number
        is in the first lines of a small text file.
        """
        if not path:
            return None
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        cached = self._md_duration_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        total = None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for _ in range(8):
                    line = fh.readline()
                    if not line:
                        break
                    m = self._DURATION_RE.search(line)
                    if m:
                        secs = 0
                        for part in m.group(1).split(":"):
                            secs = secs * 60 + int(part)
                        total = secs
                        break
        except OSError:
            pass
        self._md_duration_cache[path] = (mtime, total)
        return total

    # Recording date in the file name; two formats are recognized:
    #   14-30_01-03-26_MID.md (HH-MM_DD-MM-YY…)
    #   meet_2026-01-15_10-00.md                            (legacy format)
    _NAME_DATE_RE = re.compile(r"^\d{2}-\d{2}_(\d{2})-(\d{2})-(\d{2})(?:_|\.md$)")
    _OLD_NAME_DATE_RE = re.compile(r"^meet_(\d{4})-(\d{2})-(\d{2})_")
    _HEADER_DATE_RE = re.compile(r"Дата:\*\*\s*(\d{4})-(\d{2})-(\d{2})")

    def _md_recorded_date(self, path):
        """Recording date (datetime.date), taken from the file name rather than
        the file system: mtime would put a regenerated or copied transcript of
        an old recording under TODAY. If the name has no date, the fallback is
        the "**Дата:**" line in the header written by build_md().
        """
        name = os.path.basename(path)
        try:
            m = self._NAME_DATE_RE.match(name)
            if m:
                day, month, year = (int(g) for g in m.groups())
                return datetime.date(2000 + year, month, day)
            m = self._OLD_NAME_DATE_RE.match(name)
            if m:
                return datetime.date(*(int(g) for g in m.groups()))
            with open(path, "r", encoding="utf-8") as fh:
                for _ in range(8):
                    m = self._HEADER_DATE_RE.search(fh.readline())
                    if m:
                        return datetime.date(*(int(g) for g in m.groups()))
        except (OSError, ValueError):
            pass
        return None

    def _build_rows(self) -> list:
        """Recordings, queue and finished transcripts -> table rows."""
        eng = self.engine
        snap = eng.tq.snapshot()
        rows, queued_wavs = [], set()

        if snap["busy"] and snap["current_wav"]:
            queued_wavs.add(snap["current_wav"])
            rows.append({
                "id": snap["current_id"],
                "name": os.path.basename(snap["current"]),
                "kind": "current",
                "detail": f"{int(snap['progress'])}%",
                "path": snap["current_wav"], "removable": False,
            })
        for item in snap["pending"]:
            queued_wavs.add(item["wav"])
            rows.append({
                "id": item["id"], "name": os.path.basename(item["label"]),
                "kind": "pending", "detail": "",
                "path": item["wav"], "removable": True,
            })
        for wav in C.orphaned_recordings():
            if wav in queued_wavs:
                continue
            error_msg = eng.last_errors.get(wav)
            rows.append({
                "id": None, "name": os.path.basename(wav),
                "kind": "error" if error_msg else "orphan",
                "detail": error_msg or "", "path": wav, "removable": False,
            })
        try:
            mds = sorted(
                (os.path.join(C.OUTPUT_DIR, name)
                 for name in os.listdir(C.OUTPUT_DIR) if name.endswith(".md")),
                key=os.path.getmtime, reverse=True)
        except OSError:
            mds = []
        # READY: N counts all finished transcripts, not the visible cards:
        # the list is cut to the 15 newest, so a count taken from the cards
        # would be stuck at "READY: 15".
        self._done_total = len(mds)
        mds = mds[:15]

        # The filter/sort applies ONLY to finished cards: current, pending,
        # orphan and error rows always need the user's attention and must not
        # be hidden by a "TODAY"/"LONGEST" choice.
        mode = self._sort_filter
        if mode == "today":
            today = datetime.date.today()
            mds = [p for p in mds if self._md_recorded_date(p) == today]
        elif mode == "longest":
            mds = sorted(mds, key=lambda p: self._md_duration_seconds(p) or 0,
                        reverse=True)
        elif mode == "shortest":
            mds = sorted(mds, key=lambda p: self._md_duration_seconds(p) or 0)

        for path in mds:
            rows.append({
                "id": None, "name": os.path.basename(path), "kind": "done",
                "detail": "", "path": path, "removable": False,
            })
        return rows

    def showSortMenu_(self, sender):                              # noqa: N802,ARG002
        """Pop up the filter menu. NSMenu is a native OS component and cannot
        be fully restyled, but the Dark Aqua appearance is much closer to the
        app theme than the default adaptive one (light on a light system).
        """
        menu = NSMenu.alloc().init()
        menu.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
        labels = (S.FILTER_ALL, S.FILTER_TODAY, S.FILTER_LONGEST, S.FILTER_SHORTEST)
        attrs = {NSFontAttributeName: _font(T.TYPE_CAPTION[0], "medium"),
                NSForegroundColorAttributeName: _ns_color(T.TEXT_PRIMARY)}
        for tag, title in enumerate(labels):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, "sortFilterMenuItemChosen:", "")
            item.setTarget_(self)
            item.setTag_(tag)
            item.setAttributedTitle_(
                NSAttributedString.alloc().initWithString_attributes_(title, attrs))
            menu.addItem_(item)
        menu.popUpMenuPositioningItem_atLocation_inView_(
            None, NSMakePoint(0, self.sortButton.bounds().size.height + 4),
            self.sortButton)

    def sortFilterMenuItemChosen_(self, sender):                  # noqa: N802
        modes = ("all", "today", "longest", "shortest")
        labels = (S.FILTER_ALL, S.FILTER_TODAY, S.FILTER_LONGEST, S.FILTER_SHORTEST)
        tag = sender.tag()
        if 0 <= tag < len(modes):
            self._sort_filter = modes[tag]
            self.sortLabel.setStringValue_(labels[tag])
        self._rows_signature = None    # forces reloadData() even if
        self.refresh()                 # the kind/name set did not change

    def numberOfRowsInTableView_(self, table_view):               # noqa: N802,ARG002
        try:
            return len(self._rows)
        except Exception:                                        # noqa: BLE001
            traceback.print_exc()
            return 0

    def tableView_rowViewForRow_(self, table_view, row):          # noqa: N802,ARG002
        try:
            return ThemedRowView.alloc().init()
        except Exception:                                        # noqa: BLE001
            traceback.print_exc()
            return None

    def tableView_viewForTableColumn_row_(self, table_view, column, row):  # noqa: N802
        """Wrapped in try/except on purpose. AppKit calls this delegate method
        during NSTableView layout, in a deferred layout pass on the
        CATransaction flush rather than from our reloadData(); an exception
        here is turned by PyObjC into an ObjC exception that kills the app
        without a traceback. The wrapper logs the exact row instead.
        """
        try:
            return self._view_for_row_unsafe(table_view, column, row)
        except Exception:                                            # noqa: BLE001
            print(f"[tableView_viewForTableColumn_row_] row={row} "
                 f"len(_rows)={len(self._rows)}", file=sys.stderr)
            traceback.print_exc()
            return NSView.alloc().initWithFrame_(
                NSMakeRect(0, 0, column.width(), T.CARD_HEIGHT))

    def _make_card(self, ident):
        """Create a row card. The whole inner layout is constraints relative to
        the card itself, so it is the same at any column width.
        """
        view = RowCard.alloc().initWithFrame_(
            NSMakeRect(0, 0, 100, T.CARD_HEIGHT))
        view.setAutoresizingMask_(NSViewWidthSizable)
        view.setIdentifier_(ident)
        cons = []

        def add(sub):
            sub.setTranslatesAutoresizingMaskIntoConstraints_(False)
            view.addSubview_(sub)
            return sub

        # Marker slot: the ring (StatusDot) and the "done" checkmark (a real
        # SF Symbol) share ONE center.
        slot = NSLayoutGuide.alloc().init()
        view.addLayoutGuide_(slot)
        cons += [
            slot.leadingAnchor().constraintEqualToAnchor_constant_(
                view.leadingAnchor(), T.CARD_PADDING_LEFT),
            slot.widthAnchor().constraintEqualToConstant_(T.CARD_MARKER_SLOT),
            slot.topAnchor().constraintEqualToAnchor_(view.topAnchor()),
            slot.bottomAnchor().constraintEqualToAnchor_(view.bottomAnchor()),
        ]
        marker = add(StatusDot.alloc().init())
        check = add(FlatImageView.alloc().init())
        check.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        check.setHidden_(True)
        for sub, side in ((marker, T.CARD_MARKER_SIZE), (check, T.CARD_CHECK_SIZE)):
            cons += [
                sub.widthAnchor().constraintEqualToConstant_(side),
                sub.heightAnchor().constraintEqualToConstant_(side),
                sub.centerXAnchor().constraintEqualToAnchor_(slot.centerXAnchor()),
                sub.centerYAnchor().constraintEqualToAnchor_(view.centerYAnchor()),
            ]
        view.statusMarker = marker
        view.doneCheckmark = check

        def text(size, weight):
            field = NSTextField.labelWithString_("")
            field.setFont_(_font(size, weight))
            # Long file names are truncated in the middle so that both the
            # date at the start and the extension at the end stay visible.
            # The text never runs under the action icon.
            field.setLineBreakMode_(NSLineBreakByTruncatingMiddle)
            field.setContentCompressionResistancePriority_forOrientation_(
                NSLayoutPriorityDefaultLow, NSLayoutConstraintOrientationHorizontal)
            return field

        title = text(T.TYPE_BODY[0], T.TYPE_BODY[1])
        title.setTextColor_(_ns_color(T.TEXT_PRIMARY))
        subtitle = text(T.TYPE_CAPTION[0], "regular")
        view.titleField = title
        view.subtitleField = subtitle
        stack = add(NSStackView.stackViewWithViews_([title, subtitle]))
        stack.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        stack.setAlignment_(1)          # NSLayoutAttributeLeading
        stack.setSpacing_(T.CARD_TEXT_GAP)

        # Action icon on the right: clicking IT performs the action at once;
        # clicking the rest of the row only selects it.
        action_btn = add(RowActionButton.alloc().init())
        action_btn.setBordered_(False)
        action_btn.setTitle_("")
        action_btn.setImagePosition_(NSImageOnly)
        action_btn.setTarget_(self)
        action_btn.setAction_("rowActionClicked:")
        view.actionButton = action_btn

        cons += [
            action_btn.widthAnchor().constraintEqualToConstant_(T.CARD_ACTION_SIZE),
            action_btn.heightAnchor().constraintEqualToConstant_(T.CARD_ACTION_SIZE),
            action_btn.trailingAnchor().constraintEqualToAnchor_constant_(
                view.trailingAnchor(), -T.CARD_ACTION_INSET),
            action_btn.centerYAnchor().constraintEqualToAnchor_(view.centerYAnchor()),
            stack.leadingAnchor().constraintEqualToAnchor_constant_(
                slot.trailingAnchor(), T.SPACE_XS),
            stack.trailingAnchor().constraintLessThanOrEqualToAnchor_constant_(
                action_btn.leadingAnchor(), -T.SPACE_XS),
            stack.centerYAnchor().constraintEqualToAnchor_(view.centerYAnchor()),
        ]
        NSLayoutConstraint.activateConstraints_(cons)
        return view

    def _view_for_row_unsafe(self, table_view, column, row):          # noqa: ARG002
        ident = "RowCell"
        view = table_view.makeViewWithIdentifier_owner_(ident, self)
        if view is None:
            view = self._make_card(ident)
        record = self._rows[row] if row < len(self._rows) else None
        if record is None:
            return view

        kind = record["kind"]
        color = T.CARD_KIND_COLOR[kind]
        if kind == "done":
            view.statusMarker.setHidden_(True)
            view.doneCheckmark.setHidden_(False)
            img = _symbol(T.ICONS["status_done"], size=12, weight="semibold")
            view.doneCheckmark.setImage_(img)
            view.doneCheckmark.setContentTintColor_(_ns_color(color))
        else:
            view.doneCheckmark.setHidden_(True)
            view.statusMarker.setHidden_(False)
            view.statusMarker.setColor_(color)
            view.statusMarker.setFilled_(kind == "current")
        view.titleField.setStringValue_(record["name"])
        view.titleField.setToolTip_(record["name"])

        # Caption under the name: the recording duration where known.
        if kind == "current":
            caption = S.ROW_TRANSCRIBING.format(detail=record["detail"])
        elif kind == "pending":
            caption = S.ROW_QUEUED
        elif kind == "orphan":
            secs = self._wav_duration_seconds(record.get("path"))
            caption = (f"{S.ROW_NO_TRANSCRIPT} · {self._format_duration(secs)}"
                      if secs is not None else S.ROW_NO_TRANSCRIPT)
        elif kind == "error":
            detail = (record.get("detail") or "")[:48]
            caption = f"{S.ROW_ERROR} · {detail}" if detail else S.ROW_ERROR
        else:  # done
            secs = self._md_duration_seconds(record.get("path"))
            caption = (self._format_duration(secs) if secs is not None
                      else S.ROW_DONE_FALLBACK)
        view.subtitleField.setStringValue_(caption)
        view.subtitleField.setTextColor_(_ns_color(color))

        action = _ROW_ACTION.get(kind)
        if action:
            symbol, action_kind = action
            view.actionButton.setImage_(
                _symbol(T.ICONS[symbol], size=15, weight="semibold"))
            view.actionButton.setContentTintColor_(_ns_color(color))
            view.actionButton.setHidden_(False)
            view.actionButton._row_kind = action_kind
            view.actionButton._row_path = record.get("path")
        else:
            view.actionButton.setHidden_(True)
            view.actionButton._row_kind = None
            view.actionButton._row_path = None

        view.setSelected_(row == self.table.selectedRow())
        return view

    def _selected_row(self):
        index = self.table.selectedRow()
        if index < 0 or index >= len(self._rows):
            return None
        return self._rows[index]

    def tableViewSelectionDidChange_(self, notification):        # noqa: N802,ARG002
        """The selection must be explicitly visible (card outline/background,
        RowCard.setSelected_), not just internal NSTableView state. Only the
        affected rows are updated, without reloadData(), which is unstable
        when called often (see refresh()).
        """
        try:
            new_row = self.table.selectedRow()
            old_row = self._last_selected_row
            for r in (old_row, new_row):
                if r is None or r < 0 or r >= len(self._rows):
                    continue
                view = self.table.viewAtColumn_row_makeIfNecessary_(0, r, False)
                if view is not None:
                    view.setSelected_(r == new_row)
            self._last_selected_row = new_row
            self.refresh()
        except Exception:                                        # noqa: BLE001
            traceback.print_exc()

    def rowActionClicked_(self, sender):                          # noqa: N802
        """Row action icon: transcribe (orphan/error) or reveal in Finder
        (done), immediately and without a prior selection.
        """
        kind = getattr(sender, "_row_kind", None)
        path = getattr(sender, "_row_path", None)
        if not path or not os.path.exists(path):
            return
        if kind == "record":
            from recorder import _stamp_to_dt
            self.engine.tq.add(path, source_label=path,
                               started=_stamp_to_dt(path), duration=None)
            self.refresh()
        elif kind == "reveal":
            _reveal_in_finder(path)

    # ── panel actions ─────────────────────────────────────────────────

    def toggleRecording_(self, sender):                           # noqa: N802,ARG002
        self.engine.toggle()
        self.refresh()

    def importFile_(self, sender):                                # noqa: N802,ARG002
        def on_pick(path):
            if path:
                self.engine.start_import(path)
                self.refresh()
        audio_import.pick_file_native(on_pick=on_pick)

    def _confirm_delete(self, name: str) -> bool:
        alert = NSAlert.alloc().init()
        alert.setMessageText_(S.NOTIFY_REMOVE_CONFIRM_TITLE.format(name=name))
        alert.setInformativeText_(S.NOTIFY_REMOVE_CONFIRM_BODY)
        alert.setAlertStyle_(NSAlertStyleWarning)
        alert.addButtonWithTitle_(S.BTN_DELETE)
        alert.addButtonWithTitle_(S.BTN_CANCEL)
        return alert.runModal() == NSAlertFirstButtonReturn

    def removeSelected_(self, sender):                            # noqa: N802,ARG002
        """REMOVE applied to the selected row.

        A pending row is simply taken out of the queue (not destructive, the
        wav has not been transcribed yet, so no confirmation). An
        orphan/error/done row deletes the file from disk, so it asks for
        confirmation (NSAlert).
        """
        row = self._selected_row()
        if not row:
            return
        if row["kind"] == "pending":
            if row["removable"] and row["id"] is not None:
                self.engine.tq.remove_pending(row["id"])
                self.refresh()
            return
        if row["kind"] in ("orphan", "error", "done"):
            path = row.get("path")
            if not path or not os.path.exists(path):
                return
            if self._confirm_delete(row["name"]):
                try:
                    os.remove(path)
                    self.engine.last_errors.pop(path, None)
                except OSError as exc:
                    C.notify(C.APP_NAME, S.NOTIFY_ERROR_TITLE, str(exc)[:120])
            self.refresh()

    def openFolder_(self, sender):                                # noqa: N802,ARG002
        os.makedirs(C.OUTPUT_DIR, exist_ok=True)
        subprocess.run(["open", C.OUTPUT_DIR], check=False)

    def revealLast_(self, sender):                                # noqa: N802,ARG002
        """Finder with the newest transcript selected, regardless of the
        selection in the list. Engine.last_md (saved in this process) is used
        first, otherwise the newest .md on disk.
        """
        path = self.engine.last_md
        if not path or not os.path.exists(path):
            path = C.latest_transcript()
        if path:
            _reveal_in_finder(path)

    def fixHotkeys_(self, sender):                                # noqa: N802,ARG002
        C.open_accessibility_settings()
        C.notify(C.APP_NAME, S.NOTIFY_HOTKEYS_TITLE,
                 S.NOTIFY_HOTKEYS_BODY.format(app=C.APP_NAME))

    # ── global hotkeys (need the Accessibility permission) ────────────

    def _install_hotkeys(self):
        # Scheme (action -> Mac shortcut). One toggle key for recording: the
        # first press starts, the next press stops.
        #   Toggle recording: ⌘E
        #   Show/hide panel:  ⌘⇧H
        try:
            cmd, shift, ctrl, opt = 1 << 20, 1 << 17, 1 << 18, 1 << 19
            kc_e, kc_h = 14, 4                   # key codes for E and H

            def handler(event):
                """True if the event was handled as a hotkey."""
                try:
                    flags = event.modifierFlags() & (cmd | shift | ctrl | opt)
                    if flags == cmd and event.keyCode() == kc_e:
                        print("[hotkey] ⌘E → toggle recording", file=sys.stderr)
                        self.engine.toggle()
                        self.refresh()
                        return True
                    if flags == cmd | shift and event.keyCode() == kc_h:
                        print("[hotkey] ⌘⇧H → toggle panel", file=sys.stderr)
                        self._toggle_panel()
                        return True
                except Exception:                                # noqa: BLE001
                    traceback.print_exc()
                return False

            # The global monitor covers the case when ANOTHER app is focused
            # (needs Accessibility); the local one covers EQ Recorder itself
            # (a global monitor does not receive the app's own events).
            self._hotkey_monitor = (
                NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    NSEventMaskKeyDown, handler))
            self._hotkey_local_monitor = (
                NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                    NSEventMaskKeyDown,
                    lambda event: None if handler(event) else event))
            print(f"[hotkey] registered: monitor={self._hotkey_monitor is not None} "
                  f"accessibility_trusted={C.hotkeys_enabled()}", file=sys.stderr)
        except Exception:                                        # noqa: BLE001
            traceback.print_exc()
            self._hotkey_monitor = None

    # ── tick loop ─────────────────────────────────────────────────────

    def onTick_(self, timer):                                     # noqa: N802,ARG002
        """Timer callback (every 0.5 s). Wrapped in try/except on purpose: an
        exception inside an ObjC-invoked callback gives no traceback in the
        log, because NSApplication kills the process via _crashOnException:
        silently. Skipping one tick with a visible error in the log is better
        than losing the app without a trace.
        """
        try:
            self._on_tick_unsafe()
        except Exception:                                          # noqa: BLE001
            traceback.print_exc()

    def _on_tick_unsafe(self):
        eng = self.engine

        while True:
            try:
                kind, payload = eng.events.get_nowait()
            except _queue.Empty:
                break
            if kind == "done":
                item, saved = payload
                eng.progress = 0.0
                eng.last_md = saved[0]
                eng.last_name = os.path.basename(saved[0])
                eng.status = S.STATUS_SAVED.format(name=eng.last_name)
                self._flash_until = time.time() + C.DONE_FLASH_SEC
                self._toast_is_saved_message = True
                where = "output + vault" if len(saved) > 1 else "output/"
                C.notify(C.APP_NAME, S.NOTIFY_DONE_TITLE,
                         S.NOTIFY_DONE_BODY.format(name=eng.last_name, where=where))
            elif kind == "empty":
                item, saved = payload
                eng.progress = 0.0
                eng.last_md = saved[0]
                eng.last_name = os.path.basename(saved[0])
                eng.status = S.STATUS_LANGUAGE_NOT_DETECTED
                C.notify(C.APP_NAME, S.NOTIFY_EMPTY_TITLE, S.NOTIFY_EMPTY_BODY)
            elif kind == "queued":
                eng.status = S.STATUS_QUEUED_PAYLOAD.format(payload=payload)
            elif kind == "error":
                eng.progress = 0.0
                eng.status = S.STATUS_ERROR.format(payload=payload[:80])
                # Otherwise the automatic reset of the "SAVED:" toast (its flag
                # set by an earlier "done" in the same queue) would overwrite
                # ERROR with READY after 10 s, and an error must stay visible.
                self._toast_is_saved_message = False
                self._flash_until = 0.0
                C.notify(C.APP_NAME, S.NOTIFY_ERROR_TITLE, payload[:120])
            elif kind == "model_ready" and eng.state == eng.IDLE \
                    and not eng.tq.busy:
                eng.status = S.STATUS_READY
            elif kind == "model_fail":
                eng.status = S.STATUS_MODEL_LOAD_FAILED.format(payload=payload[:60])

        self.refresh()

    def refresh(self):
        eng = self.engine
        recording = eng.state == eng.RECORDING
        snap = eng.tq.snapshot()
        if recording:
            self.recordButton.setTitle_(S.BTN_STOP_RECORDING)
            self.recordButton.setBgColor_(T.RECORDING)
        else:
            self.recordButton.setTitle_(S.BTN_START_RECORDING)
            self.recordButton.setBgColor_(T.ACCENT_BUTTON_BG)

        # "● REC" blinks on the same 0.5 s tick that refreshes everything
        # else: alphaValue is toggled once per tick, with no separate timer.
        # "● REC" and the dot + status text share one slot in the timer row;
        # exactly one of the two is visible at a time.
        if recording:
            self.recIndicatorLabel.setStringValue_(S.REC_INDICATOR)
            self.recIndicatorLabel.setHidden_(False)
            blink_on = int(time.time() * 2) % 2 == 0
            self.recIndicatorLabel.setAlphaValue_(1.0 if blink_on else 0.35)
            self.statusDot.setHidden_(True)
            self.statusLabel.setHidden_(True)
        else:
            self.recIndicatorLabel.setHidden_(True)
            self.statusDot.setHidden_(False)
            self.statusLabel.setHidden_(False)

        self.timerLabel.setStringValue_(C.tc(eng.elapsed))
        flashing = (not recording) and eng.last_name and time.time() < self._flash_until
        if recording:
            self.timerLabel.setTextColor_(_ns_color(T.RECORDING))
            self.statusDot.setColor_(T.RECORDING)
        elif flashing:
            self.timerLabel.setTextColor_(_ns_color(T.ACCENT))
            self.statusDot.setColor_(T.ACCENT)
        else:
            self.timerLabel.setTextColor_(_ns_color(T.TEXT_PRIMARY))
            self.statusDot.setColor_(T.TEXT_SECONDARY)
        self.statusDot.setFilled_(True)

        # "SAVED: filename" is a toast: once the C.DONE_FLASH_SEC window has
        # passed and the engine is idle (not recording, nothing queued), the
        # text returns to STATUS_READY by itself.
        #
        # The reset is limited to self._toast_is_saved_message (set only by the
        # "done" event in _on_tick_unsafe). Checking just "not flashing" would
        # also erase ERROR/MODEL FAILED, which must stay visible until the
        # user has seen the problem.
        if (self._toast_is_saved_message and not recording
                and time.time() >= self._flash_until
                and not snap["busy"] and not snap["pending_count"]):
            eng.status = S.STATUS_READY
            self._toast_is_saved_message = False

        # While the toast is active: accent color and medium weight, the same
        # C.DONE_FLASH_SEC flash that drives the timer/dot color above.
        self.statusLabel.setStringValue_(eng.status[:110])
        self.statusLabel.setToolTip_(eng.status)
        self.statusLabel.setTextColor_(
            _ns_color(T.ACCENT if flashing else T.TEXT_SECONDARY))
        self.statusLabel.setFont_(
            _font(T.TYPE_BODY[0], "medium" if flashing else "regular"))

        new_rows = self._build_rows()

        self.progressBar.setHidden_(not snap["busy"])
        if snap["busy"]:
            self.progressBar.setProgress_(snap["progress"])
        # Not snap["done_count"]: that counts only this process (from zero
        # after each restart). _done_total is all .md files in output/
        # (see _build_rows).
        self.queueLabel.setStringValue_(S.QUEUE_DONE_N.format(n=self._done_total))
        processing_n = int(snap["busy"]) + snap["pending_count"]
        self.processingLabel.setHidden_(processing_n == 0)
        self.processingLabel.setStringValue_(
            S.QUEUE_PROCESSING_N.format(n=processing_n))

        # The hotkeys gear is shown only while Accessibility is not granted;
        # ENGINE: PRO is attached either to it or to the right edge.
        hotkeys_hidden = C.hotkeys_enabled()
        if self.hotkeysButton.isHidden() != hotkeys_hidden:
            self.hotkeysButton.setHidden_(hotkeys_hidden)
            self._engineToGear.setActive_(False)
            self._engineToEdge.setActive_(False)
            (self._engineToEdge if hotkeys_hidden
             else self._engineToGear).setActive_(True)

        signature = [(r["kind"], r["name"], r["detail"]) for r in new_rows]
        if signature != getattr(self, "_rows_signature", None):
            self._rows = new_rows
            self._rows_signature = signature
            # reloadData() rebuilds the view of EVERY visible row, and calling
            # it twice a second even when nothing changed makes the app
            # unstable (a crash in NSApplication._crashOnException: during a
            # CATransaction flush). The table is reloaded only when the rows
            # actually changed.
            self.table.reloadData()

        row = self._selected_row()
        can_remove = bool(row and row["kind"] in ("pending", "orphan", "error", "done"))
        self.removeButton.setContentTintColor_(_ns_color(
            T.STATUS_ERROR if can_remove else T.REMOVE_ICON_MUTED))


def run_app(engine_cls, tools_ok: bool, tools_msg: str) -> None:
    """Start the AppKit run loop. Called from recorder.main()."""
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = C.APP_NAME
        info["CFBundleDisplayName"] = C.APP_NAME
    except Exception:                                            # noqa: BLE001
        pass

    app = NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    delegate.engine_cls = engine_cls
    delegate.tools_ok = tools_ok
    delegate.tools_msg = tools_msg
    app.setDelegate_(delegate)
    app.run()
