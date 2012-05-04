import numpy

class PDFInfos(object):
    __slots__ = ('_pageCount', '_outline', '_links', '_pageBoxes')
    
    def __init__(self):
        self._pageCount = None
        self._outline = None
        self._links = None

    def pageCount(self):
        return self._pageCount

    def outline(self):
        """Return list of (level, title, pageIndex) tuples"""
        return self._outline

    def links(self):
        """Return list of (rect, pageIndex) tuples for every page, where rect is a 2x2 ndarray"""
        return self._links

    @classmethod
    def create(cls, filename):
        try:
            return cls.createFromPdfminer(filename)
        except:
            pass
        return None

    @staticmethod
    def createFromPdfminer(filename):
        import pdfminer.pdfparser

        fp = open(filename, 'rb')
        parser = pdfminer.pdfparser.PDFParser(fp)
        doc = pdfminer.pdfparser.PDFDocument()
        parser.set_document(doc)
        doc.set_parser(parser)
        doc.initialize()
        assert doc.is_extractable

        result = PDFInfos()

        pageids = [page.pageid for page in doc.get_pages()]
        result._pageCount = len(pageids)

        def anchorToPageIndex(name):
            props = doc.get_dest(name).resolve()
            if isinstance(props, dict):
                if props.keys() != ['D']:
                    print props
                props = props['D']
            return pageids.index(props[0].objid)

        result._outline = [(level, title, anchorToPageIndex(a.resolve()['D']))
                           for level, title, dest, a, se in doc.get_outlines()]

        result._links = []

        # get annotations (links):
        for page in doc.get_pages():
            pageLinks = []

            for anno in page.annots:
                props = anno.resolve()
                #print props['Subtype'], props['Rect'], props['A']

                if props['A']['S'].name == 'GoTo':
                    assert sorted(props['A'].keys()) == ['D', 'S']
                    pageLinks.append((numpy.array(props['Rect'], float).reshape((2, 2)),
                                      anchorToPageIndex(props['A']['D'])))
                    #print props['Subtype'], 

            result._links.append(pageLinks)

        result._pageBoxes = numpy.array([page.mediabox for page in doc.get_pages()],
                                        float).reshape((-1, 2, 2))

        return result
