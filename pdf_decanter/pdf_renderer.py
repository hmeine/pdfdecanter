try:
    import poppler_renderer
except ImportError, e:
    print 'QtPoppler not found, falling back to pdftoppm...'
    from pdftoppm_renderer import renderAllPages
else:
    from poppler_renderer import renderAllPages

