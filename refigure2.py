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
__version__ = "0.1"

import gtk
# Monkey patch gtk to keep matplotlib from setting the window icon.
# This can't be an intelligent thing to do....
gtk.window_set_default_icon_from_file = lambda x: None

import matplotlib.pyplot as _p
from matplotlib.figure import Figure
import reinteract.custom_result as custom_result
from threading import Lock

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
if _backend == 'GTKCairo': _gui_elements[1] = 'NavigationToolbar2GTK'
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
    
    lock = Lock()
    current_fig = None
    
    def __init__(self, **figkw):
        Figure.__init__(self, **figkw)
        c = FigureCanvas(self)
        # Set this here to allow 'f = figure()'  syntax
        self.__class__.current_fig = self
    
    def __enter__(self):
        self.__class__.lock.acquire()
        # Be sure current_fig is correct.  When multiple worksheets are 
        # executed at the same time, this does get changed between
        # __init__ and here!
        self.__class__.current_fig = self
        self.prev_rc = setOnceDict()
        return self
    
    def __exit__(self, type, value, traceback):
        self.__class__.current_fig = None
        _p.rcParams.update(self.prev_rc)
        self.__class__.lock.release()

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
#        box.print_widget = new.instancemethod(print_fig(self), box, gtk.VBox)
        return box

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
                'psd', 'quiver', 'scatter', 'specgram', 'spy', 'stem', 'xcorr')

def _make_func(name):
    pfunc = getattr(_p,name)
    def func(*args, **kw):
        if gcf() is None:
            with figure() as f:
                pfunc(*args, **kw)
            return f
        else:
            return pfunc(*args, **kw)
    func.__doc__ = pfunc.__doc__
    return func

for cmd in _solo_funcs:
    exec("%s = _make_func('%s')"%(cmd,cmd))

# Bugs
# - Nested with blocks will hang the calculation of a worksheet.  The probably
#   won't ever work anyway, but it'd be nice to fail more gracefully than this.
