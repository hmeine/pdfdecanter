import numpy

class PDFInfos(object):
    __slots__ = ('_pageCount', '_outline', '_links', '_pageBoxes')
    
    def __init__(self):
        self._pageCount = None
        self._outline = None
        self._links = None
        self._pageBoxes = None

    def pageCount(self):
        return self._pageCount

    def outline(self):
        """Return list of (level, title, pageIndex) tuples"""
        return self._outline

    def links(self, pageIndex = None):
        """Return list of (rect, pageIndex) tuples for every (or given) page, where rect is a 2x2 ndarray"""
        if pageIndex is not None:
            return self._links[pageIndex]
        return self._links

    def relativeLinks(self, pageIndex = None):
        """Same as links, but with rects scaled relative to pageBoxes"""
        if pageIndex is None:
            return [self.relativeLinks(i) for i in range(len(self))]
        pageBox = self._pageBoxes[pageIndex]
        pageSize = numpy.diff(pageBox, axis = 0)[0]
        return [((rect - pageBox[0]) / pageSize, pageIndex)
                for rect, pageIndex in self.links(pageIndex)]

    def pageBoxes(self):
        return self._pageBoxes

    def __len__(self):
        return self._pageCount

    def __getslice__(self, b, e):
        if b is None:
            b = 0
        if e is None:
            e = len(self)
        elif e < 0:
            e += len(self)
        result = type(self)()
        result._pageCount = e - b
        result._outline = [(l, t, pi) for l, t, pi in self._outline
                           if b <= pi < e]
        result._links = self._links[b:e]
        result._pageBoxes = self._pageBoxes[b:e]
        return result

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
