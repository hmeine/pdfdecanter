import bz2, cPickle

def pickle(filename, slides):
    with bz2.BZ2File(filename, "w") as f:
        cPickle.dump(slides, f, cPickle.HIGHEST_PROTOCOL)
        
def unpickle(filename):
    with bz2.BZ2File(filename) as f:
        return cPickle.Unpickler(f).load()
