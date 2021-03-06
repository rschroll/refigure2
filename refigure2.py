# Copyright 2009--2011 Robert Schroll, rschroll@gmail.com
# http://rschroll.github.com/refigure2/
#
# This file is distributed under the terms of the BSD license, available
# at http://www.opensource.org/licenses/bsd-license.php
#
# Thanks to Owen Taylor for replot:
# http://git.fishsoup.net/cgit/reinteract/tree/lib/replot.py
#
# Thanks to Nicolas Rougier for GTK Python console:
# http://www.loria.fr/~rougier/pycons.html
#
# Thanks to Kai Willadsen for rematplotlib:
# http://ramshacklecode.googlepages.com/#rematplotlib

"""refigure2 is an extension for Reinteract that embeds matplotlib figures in
worksheets.  Syntax:
    
    >>> with figure() as f
    ...     <plotting command>
    ...      :
    ...     <plotting command>
    ...     f

where <plotting command> is any matplotlib command.  The single-command
plotting functions may be used without the with block.
"""
__version__ = "0.4"

import os as _os
import tempfile as _tempfile
import gtk as _gtk
import cairo as _cairo
# Monkey patch gtk to keep matplotlib from setting the window icon.
# This can't be an intelligent thing to do....
_gtk.window_set_default_icon_from_file = lambda x: None

import matplotlib.pyplot as _p
from matplotlib.figure import Figure as _Figure
from matplotlib.backend_bases import FigureCanvasBase as _FigureCanvasBase
from matplotlib.backend_bases import FigureManagerBase as _FigureManager
import reinteract.custom_result as _custom_result
from threading import RLock as _RLock
from reinteract.statement import Statement as _Statement

def _set_rcParams():
    """Add new values to rcParams and read in values from refigurerc file(s)."""
    
    _p.rcParams.validate.update({'refigure.printdpi': _p.matplotlib.rcsetup.validate_float,
                                 'refigure.disableoutput': _p.matplotlib.rcsetup.validate_bool,
                                 'refigure.keyboardcontrol': _p.matplotlib.rcsetup.validate_bool,
                                 'refigure.display': _p.matplotlib.rcsetup.ValidateInStrings('refigure.display', ['inline', 'side']),
                                 'refigure.toolbar': _p.matplotlib.rcsetup.validate_bool,
                                })
    _p.rcParams.update({'figure.figsize': [6.0, 4.5],
                        'figure.subplot.bottom': 0.12,
                        'refigure.printdpi': 300,
                        'refigure.disableoutput': False,
                        'refigure.keyboardcontrol': True,
                        'refigure.display': 'inline',
                        'refigure.toolbar': True,
                       })
    
    paths = ((_os.path.dirname(__file__), 'refigurerc'),
             (_os.path.expanduser('~'), '.matplotlib', 'refigurerc'))
    statement = _Statement.get_current()
    if statement is not None:
        paths += ((statement._Statement__worksheet.notebook.folder, 'refigurerc'),)
    for filename in (_os.path.join(*p) for p in paths):
        if _os.path.exists(filename):
            for line in file(filename, 'r'):
                stripline = line.split('#', 1)[0].strip()
                if not stripline:
                    continue
                key, val = [s.strip() for s in stripline.split(':', 1)]
                try:
                    _p.rcParams[key] = val
                except KeyError:
                    print "Warning: Invalid key %s in %s"%(key, filename)
                    print "         See rcParams.keys() for a list of valid keys."
                except Exception:
                    print "Warning: Bad value for %s: %s\n         in %s"%(key, val, filename)
_set_rcParams()

def _set_backend():
    """Choose the backend and get the GUI elements needed for it."""
    backend = _p.get_backend()
    if not backend.startswith('GTK'):
        if _p.rcParams['backend_fallback']:
            if backend.endswith('Agg'):
                backend = 'GTKAgg'
            elif backend.endswith('Cairo'):
                backend = 'GTKCairo'
            else:
                backend = 'GTK'
        else:
            raise NotImplementedError, """
    You must use a GTK-based backend with refigure.  Adjust
    your matplotlibrc file, or before importing refigure run
        >>> from matplotlib import use
        >>> use( < 'GTK' | 'GTKAgg' | 'GTKCairo' > )
    """
    
    gui_elements = ['FigureCanvas'+backend, 'NavigationToolbar2'+backend]
    if backend == 'GTKCairo':
        gui_elements[1] = 'NavigationToolbar2GTK'
    temp = __import__('matplotlib.backends.backend_' + backend.lower(),
                      globals(), locals(), gui_elements)
    canvas = getattr(temp, gui_elements[0])
    toolbar = getattr(temp, gui_elements[1])
    return backend, canvas, toolbar
_backend, _FigureCanvas, _NavigationToolbar = _set_backend()

if _backend == 'GTKCairo':
    from matplotlib.backends.backend_cairo import RendererCairo as _RendererCairo
else:
    try:
        import poppler as _poppler
    except ImportError:
        _poppler = None

class _ResizeBox(_gtk.VBox):
    
    def __init__(self, figure):
        _gtk.VBox.__init__(self)
        self.figure = figure
        # Rounding errors slowly accumlate in the figure height, shrinking it down
        # over time.  So we make a copy here and use that to keep resetting the
        # canvas to the proper size.
        self.figsize_inches = self.figure.get_size_inches().copy()
    
    def set_sidebar_width(self, width):
        dpi = width / self.figsize_inches[0]
        self.figure.set_dpi(dpi)
        self.figure.canvas.set_size_request(*map(int, self.figsize_inches * dpi))

# SuperFigure inherits from Figure, so it can be used like a matplotlib figure.
# It inherits from CustomResult, so it can embed the figure.  And it has
# __enter__ and __exit__ methods, so it can be used in a with statement.  How's
# that for super?
class SuperFigure(_Figure, _custom_result.CustomResult):
    """Create a new figure.  figure() is designed to be used with a with
    block; the __enter__ method also returns the figure instance.  Thus
        
        with figure() as f
    
    assigns the figure instance to f.
    
    Takes the same optional keywords as matplotlib's figure()."""
    
    lock = _RLock()
    current_fig = None
    
    def __init__(self, locking=True, disable_output=None, display=None, toolbar=None, **figkw):
        if disable_output is not None:
            self._disable_output = disable_output
        else:
            self._disable_output = _p.rcParams['refigure.disableoutput']
        if display is not None:
            self.display = display
        else:
            self.display = _p.rcParams['refigure.display']
        if toolbar is not None:
            self._toolbar = toolbar
        else:
            self._toolbar = _p.rcParams['refigure.toolbar']
        if not self._toolbar and 'facecolor' not in figkw:
            figkw['facecolor'] = 'white'
        
        _Figure.__init__(self, **figkw)
        c = _FigureCanvasBase(self) # For savefig to work
        # Set this here to allow 'f = figure()'  syntax
        if not locking:
            self.__class__.current_fig = self # Another thread can tweak this!
    
    def __enter__(self):
        self.__class__.lock.acquire()
        # Be sure current_fig is correct.  When multiple worksheets are 
        # executed at the same time, this does get changed between
        # __init__ and here!
        self.__class__.current_fig = self
        self.prev_rc = setOnceDict()
        self._disable_reinteract_output()
        return self
    
    def __exit__(self, type, value, traceback):
        self.__class__.current_fig = None
        _p.rcParams.update(self.prev_rc)
        self._restore_reinteract_output()
        self.__class__.lock.release()
    
    def _disable_reinteract_output(self):
        self.statement = _Statement.get_current()
        if self.statement is not None:
            self.old_reinteract_output = self.statement.result_scope['reinteract_output']
            if self._disable_output:
                self.statement.result_scope['reinteract_output'] = lambda *args: None
    
    def _restore_reinteract_output(self):
        if self.statement is not None:
            self.statement.result_scope['reinteract_output'] = self.old_reinteract_output
            
    def _button_press_event(self, widget, event):
        if not self._toolbar and event.button == 3:
            # Release previous mode.
            if self.toolbar._active == 'PAN':
                self.toolbar.release_pan(event)
            elif self.toolbar._active == 'ZOOM':
                self.toolbar.release_zoom(event)
            
            # Pop up context menu.
            menu = _gtk.Menu()
            for toolitem in self.toolbar.toolitems:
                if toolitem[0] != None:
                    if toolitem[3] == 'pan':
                        menu_item = _gtk.CheckMenuItem(toolitem[0])
                        menu_item.set_active(self.toolbar.mode == 'pan/zoom')
                    elif toolitem[3] == 'zoom':
                        menu_item = _gtk.CheckMenuItem(toolitem[0])
                        menu_item.set_active(self.toolbar.mode == 'zoom rect')
                    else:
                        menu_item = _gtk.MenuItem(toolitem[0])
                    menu_item.connect("activate", getattr(self.toolbar, toolitem[3]))
                else:
                    menu_item = _gtk.SeparatorMenuItem()
                menu.append(menu_item)
                menu_item.show()
            menu.popup(None, None, None, event.button, event.time)
            return True
            
        if _p.rcParams['refigure.keyboardcontrol']:
            # On click, grab the focus.  Return True so that event doesn't bubble up to the
            # TextView, which would grab focus right back.
            widget.grab_focus()
            return True
            
        return False

    def create_widget(self):
        c = self.canvas.switch_backends(_FigureCanvas)
        # Axes3D need the mouse events hooked back up after getting a new canvas.
        for ax in self.axes:
            try:
                ax.mouse_init(ax._rotate_btn, ax._zoom_btn)
            except AttributeError:
                pass
        
        if self.display == 'side':
            box = _ResizeBox(self)
        else:
            box = _gtk.VBox()
        box.pack_start(c, True, True)
        c.set_size_request(*map(int, self.get_size_inches()*self.get_dpi()))
        
        # Always create toolbar, even if it is not shown.  We use it to populate the context menu.
        self.toolbar = _NavigationToolbar(c, None) # Last is supposed to be window?
        if self._toolbar:
            # Pack and show toolbar.
            e = _gtk.EventBox() # For setting cursor
            e.add(self.toolbar)
            box.pack_end(e, False, False)
            self.toolbar.connect("realize", lambda widget:
                widget.window.set_cursor(_gtk.gdk.Cursor(_gtk.gdk.LEFT_PTR)))
        
        c.connect("button_press_event", self._button_press_event)
        if _p.rcParams['refigure.keyboardcontrol']:
            # Create a FigureManager for the canvas to handle key_press_events
            _FigureManager(c, 0)
            # Key presses are handled by the canvas already, but need to return True so that
            # event doesn't bubble up to the TextView and cause it to insert a character.
            c.connect("key_press_event", lambda widget, event: True)
        
        box.show_all()
        return box
    
    def print_result(self, context, render):
        cr = context.get_cairo_context()
        cdpi = 72.0
        width, height = self.get_size_inches()
        width *= cdpi
        height *= cdpi

        if render:
            if _backend == "GTKCairo":
                renderer = _RendererCairo(self.dpi)
                renderer.set_width_height(width, height)
                # Want to create surface similar to eventual target,
                # but that doesn't work with a PDFSurface....
                #surf = cr.get_target().create_similar(cairo.CONTENT_COLOR_ALPHA, width, height)
                # So explicitly make a PDFSurface.  We don't need to have
                # it associated with a file, so pass None as first argument.
                # Except that also doesn't work.  So give it a tempfile that
                # will be destroyed as soon as it is closed.
                surf = _cairo.PDFSurface(_tempfile.TemporaryFile(), width, height)
                renderer.set_ctx_from_surface(surf)

                # From backend_bases.FigureCanvasBase.print_figure()
                origDPI = self.dpi
                origfacecolor = self.get_facecolor()
                origedgecolor = self.get_edgecolor()
                self.dpi = cdpi
                self.set_facecolor('w')
                self.set_edgecolor('w')
                try:
                    self.draw(renderer)
                finally:
                    self.dpi = origDPI
                    self.set_facecolor(origfacecolor)
                    self.set_edgecolor(origedgecolor)

                cr.set_source_surface(surf, 0, 0)
                cr.paint()
                surf.finish()

            elif _poppler is not None:
                fd, fn = _tempfile.mkstemp()
                _os.close(fd)
                self.savefig(fn, format='pdf')
                page = _poppler.document_new_from_file('file://' + fn, None).get_page(0)
                _os.unlink(fn)
                
                page.render(cr)

            else:
                fd, fn = _tempfile.mkstemp()
                _os.close(fd)
                dpi = _p.rcParams['refigure.printdpi']
                self.savefig(fn, format='png', dpi=dpi)
                image = _cairo.ImageSurface.create_from_png(fn)
                _os.unlink(fn)

                sf = cdpi/dpi
                cr.scale(sf, sf)
                cr.set_source_surface(image, 0, 0)
                cr.paint()

        return height


# Can't modify class docstring, for some reason....
#SuperFigure.__doc__ += _p.figure.__doc__.split("Optional keyword arguments:", 1)[-1]

# Modify a few functions within pyplot, so they do what I want them to.
_p.gcf = lambda: SuperFigure.current_fig
_p.gcf.__doc__ = "Return a reference to the current figure."

def _do_nothing(*args, **kw): 
    """This function has been disabled by refigure2."""
    pass
# We don't want any code creating other figures, so disable this.
_p.figure = _do_nothing
# draw() calls get_current_fig_manager(), which doesn't work, so disable it
# May need to work around this if there are places where draw() is needed.
_p.draw = _do_nothing

# Introduce rclocal() to adjust rcParams only for the current figure.
class setOnceDict(dict):
    """A Dictionary where only the first setting of a key sticks."""
    def __setitem__(self, k, v):
        if not self.has_key(k):
            dict.__setitem__(self, k, v)

def rclocal(group, **kwargs):
    """Adjust the rcParams object for only this plot.  Takes arguments either in
    the style of rc() (a group string followed by keyword pairs) or of
    rcParams.update() (a dictionary)."""
    if isinstance(group, basestring):
        kw = {}
        for k,v in kwargs.items():
            kw[group + '.' + k] = v
    elif isinstance(group, dict):
        kw = group
    else:
        raise TypeError, "The arguments of rclocal must be either a string followed by keyword pairs or a dictionary."
    try:
        prev_rc = _p.gcf().prev_rc
    except AttributeError:
        raise NotImplementedError, "rclocal() must only be called from within a with block."
    for k in kw.keys():
        prev_rc[k] = _p.rcParams[k]
    _p.rcParams.update(kw)

# Now, import everything from pyplot into the current workspace, to save the
# user an import.  Note that we've already modified a few of the functions;
# the new versions are imported here.
from matplotlib.pyplot import *
# Make figure() work something as expected, by aliasing it to SuperFigure.  But
# makes figure a class - will that cause problems?
figure = SuperFigure

# Make some commands be able to be used by themselves.
_solo_funcs = ('acorr', 'barbs', 'bar', 'barh', 'broken_barh', 'boxplot',
                'cohere', 'contour', 'contourf', 'csd', 'errorbar', 'fill',
                'fill_between', 'hexbin', 'hist', 'hlines', 'imshow', 'loglog',
                'pcolor', 'pcolormesh', 'pie', 'plot', 'plot_date', 'plotfile',
                'polar', 'psd', 'quiver', 'scatter', 'semilogx', 'semilogy',
                'specgram', 'spy', 'stem', 'vlines', 'xcorr')

def _make_func(name):
    try:
        pfunc = getattr(_p,name)
    except AttributeError:
        return None
    
    def func(*args, **kw):
        SuperFigure.lock.acquire()
        try:
            if gcf() is None:
                with figure() as f:
                    pfunc(*args, **kw)
                return f
            else:
                return pfunc(*args, **kw)
        finally:
            SuperFigure.lock.release()
    func.__doc__ = pfunc.__doc__
    return func

for _cmd in _solo_funcs:
    _func = _make_func(_cmd)
    if _func is not None:
        exec("%s = _func"%_cmd)
