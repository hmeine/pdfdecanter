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

def pickle(filename, obj):
    with bz2.BZ2File(filename, "w") as f:
        pkl.dump(obj, f, pkl.HIGHEST_PROTOCOL)
        
def unpickle(filename):
    with bz2.BZ2File(filename) as f:
        return pkl.Unpickler(f).load()
