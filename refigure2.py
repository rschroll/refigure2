# Copyright 2009--2010 Robert Schroll, rschroll@gmail.com
# http://jfi.uchicago.edu/~rschroll/refigure/
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
__version__ = "0.2"

import os
import tempfile
import gtk
import cairo
# Monkey patch gtk to keep matplotlib from setting the window icon.
# This can't be an intelligent thing to do....
gtk.window_set_default_icon_from_file = lambda x: None

import matplotlib.pyplot as _p
from matplotlib.figure import Figure
import reinteract.custom_result as custom_result
from threading import RLock
from reinteract.statement import Statement
if hasattr(Statement, 'get_current'):
    _get_curr_statement = lambda: Statement.get_current()
else:
    _get_curr_statement = lambda: None

# Set up backend and adjust a few defaults.
_p.rcParams.update({'figure.figsize': [6.0, 4.5],
                   'figure.subplot.bottom': 0.12,
                   })
_backend = _p.get_backend()
if not _backend.startswith('GTK'):
    if _p.rcParams['backend_fallback']:
        if _backend.endswith('Agg'):
            _backend = 'GTKAgg'
        elif _backend.endswith('Cairo'):
            _backend = 'GTKCairo'
        else:
            _backend = 'GTK'
    else:
        raise NotImplementedError, """
You must use a GTK-based backend with refigure.  Adjust
your matplotlibrc file, or before importing refigure run
    >>> from matplotlib import use
    >>> use( < 'GTK' | 'GTKAgg' | 'GTKCairo' > )
"""
    
_gui_elements = ['FigureCanvas'+_backend, 'NavigationToolbar2'+_backend]
if _backend == 'GTKCairo':
    _gui_elements[1] = 'NavigationToolbar2GTK'
    from matplotlib.backends.backend_cairo import RendererCairo
else:
    try:
        import poppler
    except ImportError:
        poppler = None
_temp = __import__('matplotlib.backends.backend_' + _backend.lower(),
                    globals(), locals(), _gui_elements)
FigureCanvas = getattr(_temp, _gui_elements[0])
NavigationToolbar = getattr(_temp, _gui_elements[1])
del(_gui_elements, _temp) #, FigureCanvas, NavigationToolbar)

# SuperFigure inherits from Figure, so it can be used like a matplotlib figure.
# It inherits from CustomResult, so it can embed the figure.  And it has
# __enter__ and __exit__ methods, so it can be used in a with statement.  How's
# that for super?
class SuperFigure(Figure, custom_result.CustomResult):
    """Create a new figure.  figure() is designed to be used with a with
    block; the __enter__ method also returns the figure instance.  Thus
        
        with figure() as f
    
    assigns the figure instance to f.
    
    Takes the same optional keywords as matplotlib's figure()."""
    
    lock = RLock()
    current_fig = None
    
    def __init__(self, locking=True, disable_output=True, **figkw):
        Figure.__init__(self, **figkw)
        c = FigureCanvas(self)
        self._disable_output = disable_output
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
        self._output_figure()
        self.__class__.lock.release()
    
    def _disable_reinteract_output(self):
        self.statement = _get_curr_statement()
        if self.statement is not None:
            self.old_reinteract_output = self.statement.result_scope['reinteract_output']
            if self._disable_output:
                self.statement.result_scope['reinteract_output'] = lambda *args: None
    
    def _restore_reinteract_output(self):
        if self.statement is not None:
            self.statement.result_scope['reinteract_output'] = self.old_reinteract_output
    
    def _output_figure(self):
        if self.statement is not None:
            self.statement.result_scope['reinteract_output'](self)

    def create_widget(self):
        c = self.canvas
        box = gtk.VBox()
        box.pack_start(c, True, True)
        toolbar = NavigationToolbar(c, None) # Last is supposed to be window?
        e = gtk.EventBox() # For setting cursor
        e.add(toolbar)
        box.pack_end(e, False, False)
        c.set_size_request(*map(int, self.get_size_inches()*self.get_dpi()))
        box.show_all()
        toolbar.connect("realize", lambda widget:
            widget.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.LEFT_PTR)))
        return box
    
    def print_result(self, context, render):
        cr = context.get_cairo_context()
        cdpi = context.get_dpi_x()
        width, height = self.get_size_inches()
        width *= cdpi
        height *= cdpi

        if render:
            if _backend == "GTKCairo":
                renderer = RendererCairo(self.dpi)
                renderer.set_width_height(width, height)
                # Want to create surface similar to eventual target,
                # but that doesn't work with a PDFSurface....
                #surf = cr.get_target().create_similar(cairo.CONTENT_COLOR_ALPHA, width, height)
                # So explicitly make a PDFSurface.  We don't need to have
                # it associated with a file, so pass None as first argument.
                # Except that also doesn't work.  So give it a tempfile that
                # will be destroyed as soon as it is closed.
                surf = cairo.PDFSurface(tempfile.TemporaryFile(), width, height)
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

            elif poppler is not None:
                # savefig with PDFs doesn't like pipes.
                fd, fn = tempfile.mkstemp()
                os.close(fd)
                self.savefig(fn, format='pdf')
                page = poppler.document_new_from_file('file://' + fn, None).get_page(0)
                os.unlink(fn)
                
                page.render(cr)

            else:
                r,w = os.pipe()
                rf = os.fdopen(r, 'r')
                wf = os.fdopen(w, 'w')
                self.savefig(wf, format='png') #, dpi=context.get_dpi_x())
                wf.close()
                image = cairo.ImageSurface.create_from_png(rf)
                rf.close()

                sf = cdpi/_p.rcParams['savefig.dpi']
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
                'fill_between', 'hexbin', 'hist', 'imshow', 'loglog', 'pcolor',
                'pcolormesh', 'pie', 'plot', 'plot_date', 'plotfile', 'polar',
                'psd', 'quiver', 'scatter', 'semilogx', 'semilogy', 'specgram',
                'spy', 'stem', 'xcorr')

def _make_func(name):
    try:
        pfunc = getattr(_p,name)
    except AttributeError:
        return None
    
    def func(*args, **kw):
        SuperFigure.lock.acquire()
        try:
            if gcf() is None:
                with figure():
                    pfunc(*args, **kw)
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
