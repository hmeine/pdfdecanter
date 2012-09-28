import numpy, os.path

# TODO:
# - let Presentation store copy of outline, with page indices replaced by Frame references

class PDFPageInfos(object):
    def __init__(self, pageBox, links):
        self._pageBox = pageBox
        self._links = links

    def pageBox(self):
        return self._pageBox

    def links(self):
        """Return list of (rect, pageIndex) tuples links on this page, where rect is a 2x2 ndarray"""
        return self._links

    def relativeLinks(self):
        """Same as links, but with rects scaled relative to pageBox"""
        pageBox = self._pageBox
        pageSize = numpy.diff(pageBox, axis = 0)[0]
        return [((rect - pageBox[0]) / pageSize, link)
                for rect, link in self.links()]


class PDFInfos(object):
    __slots__ = ('_metaInfo', '_pageCount', '_outline', '_pageInfos', '_names')
    
    def __init__(self):
        self._metaInfo = None
        self._pageCount = None
        self._outline = None
        self._pageInfos = None
        self._names = None

    def metaInfo(self):
        """Return dict with meta information about PDF document, e.g. keys like Title, Author, Creator, ..."""
        return self._metaInfo

    def pageCount(self):
        return self._pageCount

    def outline(self):
        """Return list of (level, title, pageIndex) tuples"""
        return self._outline

    def names(self):
        """Return dictionary of named (link) destinations"""
        return self._names

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
        result._metaInfo = self._metaInfo # (probably unused, but anyhow)
        result._pageCount = e - b
        result._outline = self._outline and [(l, t, pi) for l, t, pi in self._outline
                                             if b <= pi < e]
        result._pageInfos = self._pageInfos and self._pageInfos[b:e]
        return result

    def __getitem__(self, index):
        return self._pageInfos[index]

    @classmethod
    def create(cls, filename):
        try:
            return cls.createFromPdfminer(filename)
        except:
            pass
        return None

    @staticmethod
    def createFromPdfminer(filename):
        import pdfminer.pdfparser, pdfminer.pdftypes

        fp = open(filename, 'rb')
        parser = pdfminer.pdfparser.PDFParser(fp)
        doc = pdfminer.pdfparser.PDFDocument()
        parser.set_document(doc)
        doc.set_parser(parser)
        doc.initialize()
        assert doc.is_extractable

        result = PDFInfos()
        result._metaInfo = dict((key, str.decode(value, 'utf-16') if value.startswith('\xfe\xff') else value)
                                for key, value in doc.info[0].items()
                                if isinstance(value, basestring))

        pageids = [page.pageid for page in doc.get_pages()]
        result._pageCount = len(pageids)

        def get(obj, attr = None):
            """Resolve PDFObjRefs, otherwise a no-op. May also perform
            dict lookup, i.e. get(obj, 'A') is roughly the same as
            get(obj)['A']."""
            while isinstance(obj, pdfminer.pdftypes.PDFObjRef):
                obj = obj.resolve()
            if attr is not None:
                return get(obj[attr])
            return obj

        def actionToPageIndex(action):
            assert get(action, 'S').name == 'GoTo'
            name = get(action, 'D')
            dest = get(doc.get_dest(name))
            return destToPageIndex(dest)

        def destToPageIndex(dest):
            if isinstance(dest, dict):
                assert dest.keys() == ['D'], repr(dest)
                dest = get(dest, 'D')
            return pageids.index(dest[0].objid)

        try:
            result._outline = [(level, title, actionToPageIndex(a) if a else destToPageIndex(dest))
                               for level, title, dest, a, se in doc.get_outlines()]
        except pdfminer.pdfparser.PDFNoOutlines:
            result._outline = None

        result._pageInfos = []

        # get annotations (links):
        for page in doc.get_pages():
            pageLinks = []

            for anno in get(page.annots) or []:
                action = get(anno, 'A')
                subType = get(action, 'S').name
                rect = numpy.array(get(anno, 'Rect'), float).reshape((2, 2))
                if subType == 'GoTo':
                    assert sorted(action.keys()) == ['D', 'S']
                    pageLinks.append((rect, actionToPageIndex(action)))
                elif subType == 'URI':
                    #assert sorted(action.keys()) == ['S', 'Type', 'URI']
                    link = get(action, 'URI')
                    if link.startswith('file:'):
                        # resolve relative pathname w.r.t. PDF filename:
                        link = 'file:' + os.path.join(os.path.dirname(filename),
                                                      link[5:])
                    pageLinks.append((rect, link))

            pageBox = numpy.array([page.mediabox], float).reshape((2, 2))

            result._pageInfos.append(PDFPageInfos(links = pageLinks, pageBox = pageBox))

        # extract all named destinations:
        def extract_names(dests, result = None):
            if result is None:
                result = {}
            if 'Names' in dests:
                it = iter(get(dests, 'Names'))
                for name, ref in zip(it, it):
                    result[name] = destToPageIndex(ref)
            if 'Kids' in dests:
                for kid in get(dests, 'Kids'):
                    extract_names(get(kid), result)
            return result

        try:
            result._names = extract_names(get(doc.catalog['Names'], 'Dests'))
        except KeyError:
            pass

        return result

    def __getstate__(self):
        return (self._metaInfo, self._pageCount, self._outline, self._pageInfos, self._names)

    def __setstate__(self, state):
        self._metaInfo, self._pageCount, self._outline, self._pageInfos, self._names = state
