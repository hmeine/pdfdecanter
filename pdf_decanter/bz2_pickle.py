#  Copyright 2012-2014 Hans Meine <hans_meine@gmx.net>
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import bz2, cPickle as pkl

def pickle(filename, *objs):
    '''Pickle (and compress) one or more objects into the given file.'''
    with bz2.BZ2File(filename, "w") as f:
        for obj in objs:
            pkl.dump(obj, f, pkl.HIGHEST_PROTOCOL)
        
def unpickle(filename):
    '''Uncompress and unpickle exactly one (the first) object from the given file.'''
    return iter_unpickle(filename).next()
        
def iter_unpickle(filename):
    '''Uncompress and unpickle objects from the given file (generator function).'''
    with bz2.BZ2File(filename) as f:
        up = pkl.Unpickler(f)
        while True:
            try:
                yield up.load()
            except EOFError:
                break
