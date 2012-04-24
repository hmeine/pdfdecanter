import bz2, cPickle as pkl

def pickle(filename, slides):
    with bz2.BZ2File(filename, "w") as f:
        pkl.dump(slides, f, pkl.HIGHEST_PROTOCOL)
        
def unpickle(filename):
    with bz2.BZ2File(filename) as f:
        return pkl.Unpickler(f).load()