from ..pdftoppm_renderer import readPPM, renderAllPages, renderPDFPage

import os

def test_readPPM():
    filename = os.path.join(os.path.dirname(__file__), 'test_on_white.ppm')
    with open(filename, 'rb') as f:
        buf = readPPM(f)
        assert buf.shape == (44, 83, 3)

def test_renderPDFPage():
    filename = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'testtalks', 'snakes_and_active_contours.pdf')

    page4_buf = renderPDFPage(filename, 4)
    assert page4_buf.shape == (1125, 1500, 3)

    page2_buf = renderPDFPage(filename, 2)
    assert page2_buf.shape == page4_buf.shape

    assert (page4_buf != page2_buf).any()
    
        
#def test_renderAllPages():
    
