#
# You may need to edit this.
#
SERVER_CONF_PY_FILE = "../server_conf.py"


# Copyright (c) 2007, Alex Drummond <a.d.drummond@gmail.com>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the names of the authors nor the names of contributors may be used to
#   endorse of promote products derived from this software without specific prior
#   written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


import sys
import types
import logging
import getopt
import itertools
import StringIO
import md5
import time as time_module
import types
import os
import os.path
import cgi
import string

PY_SCRIPT_NAME = "server.py"


#
# =========== START OF decoder.py AND scanner.py FROM simple_json PACKAGE ==========
#
# This package is licensed under the MIT license (which is compatible with the BSD
# license used for webspr).
#
# http://pypi.python.org/pypi/simplejson
#
import re

# In the original code: from simplejson.scanner import Scanner, pattern
import sre_parse, sre_compile, sre_constants
from sre_constants import BRANCH, SUBPATTERN
from re import VERBOSE, MULTILINE, DOTALL
import re

__all__ = ['Scanner', 'pattern']

FLAGS = (VERBOSE | MULTILINE | DOTALL)
class Scanner(object):
    def __init__(self, lexicon, flags=FLAGS):
        self.actions = [None]
        # combine phrases into a compound pattern
        s = sre_parse.Pattern()
        s.flags = flags
        p = []
        for idx, token in enumerate(lexicon):
            phrase = token.pattern
            try:
                subpattern = sre_parse.SubPattern(s,
                    [(SUBPATTERN, (idx + 1, sre_parse.parse(phrase, flags)))])
            except sre_constants.error:
                raise
            p.append(subpattern)
            self.actions.append(token)

        p = sre_parse.SubPattern(s, [(BRANCH, (None, p))])
        self.scanner = sre_compile.compile(p)


    def iterscan(self, string, idx=0, context=None):
        """
        Yield match, end_idx for each match
        """
        match = self.scanner.scanner(string, idx).match
        actions = self.actions
        lastend = idx
        end = len(string)
        while True:
            m = match()
            if m is None:
                break
            matchbegin, matchend = m.span()
            if lastend == matchend:
                break
            action = actions[m.lastindex]
            if action is not None:
                rval, next_pos = action(m, context)
                if next_pos is not None and next_pos != matchend:
                    # "fast forward" the scanner
                    matchend = next_pos
                    match = self.scanner.scanner(string, matchend).match
                yield rval, matchend
            lastend = matchend
            
def pattern(pattern, flags=FLAGS):
    def decorator(fn):
        fn.pattern = pattern
        fn.regex = re.compile(pattern, flags)
        return fn
    return decorator

FLAGS = re.VERBOSE | re.MULTILINE | re.DOTALL

def _floatconstants():
    import struct
    import sys
    _BYTES = '7FF80000000000007FF0000000000000'.decode('hex')
    if sys.byteorder != 'big':
        _BYTES = _BYTES[:8][::-1] + _BYTES[8:][::-1]
    nan, inf = struct.unpack('dd', _BYTES)
    return nan, inf, -inf

NaN, PosInf, NegInf = _floatconstants()

def linecol(doc, pos):
    lineno = doc.count('\n', 0, pos) + 1
    if lineno == 1:
        colno = pos
    else:
        colno = pos - doc.rindex('\n', 0, pos)
    return lineno, colno

def errmsg(msg, doc, pos, end=None):
    lineno, colno = linecol(doc, pos)
    if end is None:
        return '%s: line %d column %d (char %d)' % (msg, lineno, colno, pos)
    endlineno, endcolno = linecol(doc, end)
    return '%s: line %d column %d - line %d column %d (char %d - %d)' % (
        msg, lineno, colno, endlineno, endcolno, pos, end)

_CONSTANTS = {
    '-Infinity': NegInf,
    'Infinity': PosInf,
    'NaN': NaN,
    'true': True,
    'false': False,
    'null': None,
}

def JSONConstant(match, context, c=_CONSTANTS):
    return c[match.group(0)], None
pattern('(-?Infinity|NaN|true|false|null)')(JSONConstant)

def JSONNumber(match, context):
    match = JSONNumber.regex.match(match.string, *match.span())
    integer, frac, exp = match.groups()
    if frac or exp:
        res = float(integer + (frac or '') + (exp or ''))
    else:
        res = int(integer)
    return res, None
pattern(r'(-?(?:0|[1-9]\d*))(\.\d+)?([eE][-+]?\d+)?')(JSONNumber)

STRINGCHUNK = re.compile(r'(.*?)(["\\])', FLAGS)
BACKSLASH = {
    '"': u'"', '\\': u'\\', '/': u'/',
    'b': u'\b', 'f': u'\f', 'n': u'\n', 'r': u'\r', 't': u'\t',
}

DEFAULT_ENCODING = "UTF-8"

def scanstring(s, end, encoding=None, _b=BACKSLASH, _m=STRINGCHUNK.match):
    if encoding is None:
        encoding = DEFAULT_ENCODING
    chunks = []
    _append = chunks.append
    begin = end - 1
    while 1:
        chunk = _m(s, end)
        if chunk is None:
            raise ValueError(
                errmsg("Unterminated string starting at", s, begin))
        end = chunk.end()
        content, terminator = chunk.groups()
        if content:
            if not isinstance(content, unicode):
                content = unicode(content, encoding)
            _append(content)
        if terminator == '"':
            break
        try:
            esc = s[end]
        except IndexError:
            raise ValueError(
                errmsg("Unterminated string starting at", s, begin))
        if esc != 'u':
            try:
                m = _b[esc]
            except KeyError:
                raise ValueError(
                    errmsg("Invalid \\escape: %r" % (esc,), s, end))
            end += 1
        else:
            esc = s[end + 1:end + 5]
            try:
                m = unichr(int(esc, 16))
                if len(esc) != 4 or not esc.isalnum():
                    raise ValueError
            except ValueError:
                raise ValueError(errmsg("Invalid \\uXXXX escape", s, end))
            end += 5
        _append(m)
    return u''.join(chunks), end

def JSONString(match, context):
    encoding = getattr(context, 'encoding', None)
    return scanstring(match.string, match.end(), encoding)
pattern(r'"')(JSONString)

WHITESPACE = re.compile(r'\s*', FLAGS)

def JSONObject(match, context, _w=WHITESPACE.match):
    pairs = {}
    s = match.string
    end = _w(s, match.end()).end()
    nextchar = s[end:end + 1]
    # trivial empty object
    if nextchar == '}':
        return pairs, end + 1
    if nextchar != '"':
        raise ValueError(errmsg("Expecting property name", s, end))
    end += 1
    encoding = getattr(context, 'encoding', None)
    iterscan = JSONScanner.iterscan
    while True:
        key, end = scanstring(s, end, encoding)
        end = _w(s, end).end()
        if s[end:end + 1] != ':':
            raise ValueError(errmsg("Expecting : delimiter", s, end))
        end = _w(s, end + 1).end()
        try:
            value, end = iterscan(s, idx=end, context=context).next()
        except StopIteration:
            raise ValueError(errmsg("Expecting object", s, end))
        pairs[key] = value
        end = _w(s, end).end()
        nextchar = s[end:end + 1]
        end += 1
        if nextchar == '}':
            break
        if nextchar != ',':
            raise ValueError(errmsg("Expecting , delimiter", s, end - 1))
        end = _w(s, end).end()
        nextchar = s[end:end + 1]
        end += 1
        if nextchar != '"':
            raise ValueError(errmsg("Expecting property name", s, end - 1))
    object_hook = getattr(context, 'object_hook', None)
    if object_hook is not None:
        pairs = object_hook(pairs)
    return pairs, end
pattern(r'{')(JSONObject)
            
def JSONArray(match, context, _w=WHITESPACE.match):
    values = []
    s = match.string
    end = _w(s, match.end()).end()
    # look-ahead for trivial empty array
    nextchar = s[end:end + 1]
    if nextchar == ']':
        return values, end + 1
    iterscan = JSONScanner.iterscan
    while True:
        try:
            value, end = iterscan(s, idx=end, context=context).next()
        except StopIteration:
            raise ValueError(errmsg("Expecting object", s, end))
        values.append(value)
        end = _w(s, end).end()
        nextchar = s[end:end + 1]
        end += 1
        if nextchar == ']':
            break
        if nextchar != ',':
            raise ValueError(errmsg("Expecting , delimiter", s, end))
        end = _w(s, end).end()
    return values, end
pattern(r'\[')(JSONArray)
 
ANYTHING = [
    JSONObject,
    JSONArray,
    JSONString,
    JSONConstant,
    JSONNumber,
]

JSONScanner = Scanner(ANYTHING)

class JSONDecoder(object):
    """
    Simple JSON <http://json.org> decoder

    Performs the following translations in decoding:
    
    +---------------+-------------------+
    | JSON          | Python            |
    +===============+===================+
    | object        | dict              |
    +---------------+-------------------+
    | array         | list              |
    +---------------+-------------------+
    | string        | unicode           |
    +---------------+-------------------+
    | number (int)  | int, long         |
    +---------------+-------------------+
    | number (real) | float             |
    +---------------+-------------------+
    | true          | True              |
    +---------------+-------------------+
    | false         | False             |
    +---------------+-------------------+
    | null          | None              |
    +---------------+-------------------+

    It also understands ``NaN``, ``Infinity``, and ``-Infinity`` as
    their corresponding ``float`` values, which is outside the JSON spec.
    """

    _scanner = Scanner(ANYTHING)
    __all__ = ['__init__', 'decode', 'raw_decode']

    def __init__(self, encoding=None, object_hook=None):
        """
        ``encoding`` determines the encoding used to interpret any ``str``
        objects decoded by this instance (utf-8 by default).  It has no
        effect when decoding ``unicode`` objects.
        
        Note that currently only encodings that are a superset of ASCII work,
        strings of other encodings should be passed in as ``unicode``.

        ``object_hook``, if specified, will be called with the result
        of every JSON object decoded and its return value will be used in
        place of the given ``dict``.  This can be used to provide custom
        deserializations (e.g. to support JSON-RPC class hinting).
        """
        self.encoding = encoding
        self.object_hook = object_hook

    def decode(self, s, _w=WHITESPACE.match):
        """
        Return the Python representation of ``s`` (a ``str`` or ``unicode``
        instance containing a JSON document)
        """
        obj, end = self.raw_decode(s, idx=_w(s, 0).end())
        end = _w(s, end).end()
        if end != len(s):
            raise ValueError(errmsg("Extra data", s, end, len(s)))
        return obj

    def raw_decode(self, s, **kw):
        """
        Decode a JSON document from ``s`` (a ``str`` or ``unicode`` beginning
        with a JSON document) and return a 2-tuple of the Python
        representation and the index in ``s`` where the document ended.

        This can be used to decode a JSON document from a string that may
        have extraneous data at the end.
        """
        kw.setdefault('context', self)
        try:
            obj, end = self._scanner.iterscan(s, **kw).next()
        except StopIteration:
            raise ValueError("No JSON object could be decoded")
        return obj, end

__all__ = ['JSONDecoder']
#
# ========== END OF decoder.py AND scanner.py ==========
#


c = { }
try:
    execfile(SERVER_CONF_PY_FILE, c)
except Exception, e:
    print "Could not open/load config file: %s" % e
    sys.exit(1)


#
# Random utility.
#
def nice_time(t):
    return time_module.strftime(u"%a, %d-%b-%Y %H:%M:%S", time_module.gmtime(t))

#
# CSS namespaceifier.
#
# This function performs a partial parse of a CSS file (we're only interested
# in the selectors).
def css_parse(css):
    KINDS_CHARS = "#."
    OPS_CHARS = "+>," # We treat comma as an operator just like '>' or '+', since
                      # this works fine for our purposes, despite not being
                      # semantically correct.

    state = "selector"
    prev_char = None
    precomment_return_to_state = None
    current_selectors = []   # Of the form [["tagname", "#/./whatever", "blah"]] (where "blah" includes : whatever unparsed).
                             # Empty string is used to indicate that something (e.g. tag name) is missing.
                             # Note that the empty string counts as a false value in Python conditionals.
    current_selector_tagname = None
    current_selector_kind = None
    current_selector_rest = None
    current_op = None
    current_body = None
    definitions = []
    i = 0
    while i < len(css):
        c = css[i]

        if state is "selector":
            if c.isspace():
                pass
            elif c == "/":
                precomment_state = "selector"
                state = "precomment"
            elif c == "{":
                current_body = StringIO.StringIO()
                state = "body"
            elif c in KINDS_CHARS:
                current_selector_tagname = None
                current_selector_kind = c
                current_selector_rest = StringIO.StringIO()
                state = "selector_rest"
            elif c in OPS_CHARS:
                current_op = StringIO.StringIO()
                current_op.write(c)
                state = "operator"
            elif c.isalnum() or c in "_*": # '*' used to indicate any tag; we'll allow underscores in tag names.
                current_selector_tagname = StringIO.StringIO()
                current_selector_tagname.write(c)
                state = "selector_tagname"
            else:
                assert False
        elif state is "precomment":
            if c == "*":
                state = "comment"
            else:
                state = precomment_return_to_state
        elif state is "comment":
            if c == "*":
                state = "preclose_comment"
        elif state is "preclose_comment":
            if c == "/":
                state = precomment_return_to_state
        elif state is "operator":
            # Special handling of comments since they separate operators (we don't
            # want to go back to this state, but rather to the "selector" state).
            if c == "/":
                state = "operator_comment"
                current_selectors.append(current_op.getvalue())
            elif c in OPS_CHARS:
                current_op.write(c)
            else:
                current_selectors.append(current_op.getvalue())
                i -= 1 # IMPORTANT IMPORTANT IMPORTANT
                state = "selector"
        elif state is "operator_comment":
            if c == "*":
                current_selectors.append(current_op.getvalue())
                precomment_return_to_state = "selector"
                state = "precomment"
            else:
                current_op.write(c) # We'll allow '/' chars in the middle of operators -- this is a permissive parser.
                state = "operator"
        elif state is "selector_tagname":
            if c == "/":
                current_selectors.append([current_selector_tagname.getvalue(), '', ''])
                precomment_return_to_state = "selector"
                state = "precomment"
            elif c.isalnum() or c in ":-":
                current_selector_tagname.write(c)
            elif c == "{":
                selector_kind = None
                current_body = StringIO.StringIO()
                state = "body"
            elif c in OPS_CHARS:
                current_selectors.append([current_selector_tagname.getvalue(), '', ''])
                current_op = StringIO.StringIO()
                current_op.write(c)
                state = "operator"
            elif c.isspace():
                current_selectors.append([current_selector_tagname.getvalue(), '', ''])
                state = "selector"
            else:
                current_selector_kind = (c in KINDS_CHARS and (c,) or (None,))[0]
                current_selector_rest = StringIO.StringIO()
                state = "selector_rest"
        elif state is "selector_rest":
            if c.isalnum() or c in ":-":
                current_selector_rest.write(c)
            else:
                current_selectors.append([
                    (current_selector_tagname and (current_selector_tagname.getvalue(),) or ("",))[0],
                    current_selector_kind or "",
                    (current_selector_rest and (current_selector_rest.getvalue(),) or ("",))[0]
                ])
                if c.isspace():
                    state = "selector"
                elif c == "/":
                    state = "precomment"
                    precomment_return_to_state = "selector"
                elif c in OPS_CHARS:
                    current_op = StringIO.StringIO()
                    current_op.write(c)
                    state = "operator"
                else: #elif c == "{": # Being lax here because we don't want this parser to ever fail.
                    current_body = StringIO.StringIO()
                    state = "body"
        elif state is "body":
            if c == "}":
                definitions.append((current_selectors, current_body.getvalue()))

                current_selectors = []
                current_selector_tagname = None
                current_selector_kind = None
                current_selector_rest = None
                current_op = None
                current_body = None

                state = "selector"
            elif c == "/": # We effectively strip comments out of the body.
                precomment_return_to_state = "body"
                state = "precomment"
            elif c in "\"'":
                current_body.write(c)
                quote_char = c
                state = "body_instring"
            else:
                current_body.write(c)
        elif state is "body_instring":
            current_body.write(c)
            if c == quote_char and prev_char != "\\":
                state = "body"
        else:
            assert False

        i += 1
        prev_char = c

    return definitions

def css_add_namespace(css_definitions, name):
    for d in css_definitions:
        for sel in d[0]:
            if type(sel) is type([]) and sel[2]:
                sel[2] = name + sel[2]

def css_spit_out(css_definitions, ofile):
    for d in css_definitions:
        for sel in d[0]:
            if type(sel) is type(""): # It's an operator (e.g. '>')
                ofile.write(" %s " % sel)
            else:
                ofile.write("%s%s%s " % (sel[0], sel[1], sel[2]))
        ofile.write("{%s}\n" % d[1])

# TEST CODE
#defs = css_parse("foo/**/>#amp/**/gob>++>dd/**/ { ./*.. }*/} foo { ... } amp { 56 }")
#defs = css_parse("a { b} c { d} ")
#print defs
#css_add_namespace(defs, "ns-")
#css_spit_out(defs, sys.stdout)
#sys.exit(0)
            

#
# Logging and configuration variables.
#

logging.basicConfig()
logger = logging.getLogger("server")
logger.addHandler(logging.StreamHandler())
logger.addHandler(logging.FileHandler(filename=os.path.join(c.has_key('WEBSPR_WORKING_DIR') and c['WEBSPR_WORKING_DIR'] or '',
                                          "server.log")))

# Check that all conf variables have been defined
# (except the optional WEBSPR_WORKING_DIR and PORT variables).
for k in ['RESULT_FILE_NAME',
          'RAW_RESULT_FILE_NAME', 'SERVER_STATE_DIR',
          'SERVER_MODE', 'JS_INCLUDES_DIR', 'DATA_INCLUDES_DIR',
          'CSS_INCLUDES_DIR', 'OTHER_INCLUDES_DIR', 'JS_INCLUDES_LIST', 'DATA_INCLUDES_LIST',
          'CSS_INCLUDES_LIST', 'STATIC_FILES_DIR', 'INCLUDE_COMMENTS_IN_RESULTS_FILE',
          'INCLUDE_HEADERS_IN_RESULTS_FILE']:
    if not c.has_key(k):
        logger.error("Configuration variable '%s' was not defined." % k)
        sys.exit(1)
# Define optional variables if they are not already defined.
c['PORT'] = c.has_key('PORT') and c['PORT'] or None
c['WEBSPR_WORKING_DIR'] = c.has_key('WEBSPR_WORKING_DIR') and c['WEBSPR_WORKING_DIR'] or None

# Check for "-m" and "-p" options (sets server mode and port respectively).
# Also check for "-r" option (resest counter on startup).
COUNTER_SHOULD_BE_RESET = False
try:
    opts, _ = getopt.getopt(sys.argv[1:], "m:p:r")
    for k,v in opts:
        if k == "-m":
            c['SERVER_MODE'] = v
        elif k == "-p":
            c['PORT'] = int(v)
        elif k == "-r":
            COUNTER_SHOULD_BE_RESET = True
except getopt.GetoptError:
    logger.error("Bad arguments")
    sys.exit(1)
except ValueError:
    logger.error("Argument to -p must be an integer")
    sys.exit(1)

# Check values of (some) conf variables.
if type(c['PORT']) != types.IntType:
    logger.error("Bad value (or no value) for server port.")
    sys.exit(1)
if type(c['JS_INCLUDES_LIST']) != types.ListType or len(c['JS_INCLUDES_LIST']) < 1 or (c['JS_INCLUDES_LIST'][0] not in ["block", "allow"]):
    logger.error("Bad value for 'JS_INCLUDES_LIST' conf variable.")
    sys.exit(1)
if type(c['CSS_INCLUDES_LIST']) != types.ListType or len(c['CSS_INCLUDES_LIST']) < 1 or (c['CSS_INCLUDES_LIST'][0] not in ["block", "allow"]):
    logger.error("Bad value for 'CSS_INCLUDES_LIST' conf variable.")
    sys.exit(1)
if type(c['DATA_INCLUDES_LIST']) != types.ListType or len(c['DATA_INCLUDES_LIST']) < 1 or (c['DATA_INCLUDES_LIST'][0] not in ["block", "allow"]):
    logger.error("Bad value for 'DATA_INCLUDES_LIST' conf variable.")
    sys.exit(1)


# File locking on UNIX/Linux/OS X
HAVE_FLOCK = False
if (sys.version.split(' ')[0]) >= '2.4': # File locking doesn't seem to work well in Python 2.3.
    try:
        import fcntl # For flock.
        if 'flock' in dir(fcntl) and \
                type(fcntl.flock) == types.BuiltinFunctionType:
            HAVE_FLOCK = True
    except:
        pass

# Configuration.
if c['SERVER_MODE'] not in ["paste", "toy", "cgi"]:
    logger.error("Unrecognized value for SERVER_MODE configuration variable (or '-m' command line option).")
    sys.exit(1)

if c['SERVER_MODE'] in ["toy", "paste"]:
    import BaseHTTPServer
    import SimpleHTTPServer

PWD = None
if c.has_key('WEBSPR_WORKING_DIR'):
    PWD = c['WEBSPR_WORKING_DIR']
if os.environ.get("WEBSPR_WORKING_DIR"):
    PWD = os.environ.get("WEBSPR_WORKING_DIR")
if PWD is None: PWD = ''


#
# Some utility functions/classes.
#

def lock_and_open(filename, mode):
    if os.path.exists(filename):
        f = open(filename, "r") # Open first as read-only.
        if HAVE_FLOCK:
            fcntl.flock(f.fileno(), 2)
        if mode != "r": # If necessary, reopen with the given mode.
            f.close()
            f = open(filename, mode)
        return f
    else:
        f = open(filename, mode)
        return f
def unlock_and_close(f):
    if HAVE_FLOCK:
        fcntl.flock(f.fileno(), 8)
    f.close()

def get_counter():
    try:
        f = lock_and_open(os.path.join(PWD, c['SERVER_STATE_DIR'], 'counter'), "r")
        n = int(f.read().strip())
        unlock_and_close(f)
        return n
    except (IOError, ValueError), e:
        logger.error("Error reading counter from server state: %s" % str(e))
        sys.exit(1)
def set_counter(n):
    try:
        f = lock_and_open(os.path.join(PWD, c['SERVER_STATE_DIR'], 'counter'), "w")
        f.write(str(n))
        unlock_and_close(f)
    except IOError, e:
        logger.error("Error setting counter in server state: %s" % str(e))
        sys.exit(1)

class HighLevelParseError(Exception):
    def __init__(self, *args):
        Exception.__init__(self, *args)

def group_list(l, n):
    """Written in this slightly awkward way so that it works with iterators."""
    assert n > 0

    newl = []
    count = 0
    current_sub = []
    for elem in l:
        if count >= n:
            newl.append(current_sub)
            current_sub = [elem]
            count = 1
        else:
            current_sub.append(elem)
            count += 1
    newl.append(current_sub)
    return newl

def rearrange(parsed_json, thetime, ip):
    if type(parsed_json) != types.ListType or len(parsed_json) != 4:
        raise HighLevelParseError()

    random_counter = parsed_json[0]
    if type(random_counter) != types.BooleanType:
        raise HighLevelParseError()

    counter = None
    try:
        counter = int(parsed_json[1])
    except ValueError:
        raise HighLevelParseError()

    names_array = parsed_json[2]
    def getname(index):
        if index >= len(names_array) or index < 0:
            raise HighLevelParseError()
        return names_array[index]

    #
    # This is a fairly horrible bit of code that does most of the work
    # of inserting comments for columns into the results file. As well as detecting
    # adjacent lines with identical column names, it is also able to detect regular
    # patterns of alternating identical columns. The nice thing about having this
    # monstrosity is that it makes it possible to maintain a very simple concept of
    # results from the point of view of writing a controller (each controller just
    # returns a list of lines, where each line is a list of name/value pairs).
    #
    # Unfortunately, this is almost impossible to understand. If it needs to be
    # changed at all it's probably best to rewrite it. Sorry.
    #
    new_results = []
    column_names = []
    main_index = 0
    next_comment_index = None
    while main_index < len(parsed_json[3]):
        old_main_index = main_index
        for phase in xrange(1, 6): # [1, 2, 3, 4, 5]
            next_comment_index = main_index
            subs = group_list(itertools.islice(parsed_json[3], main_index, None), phase)

            rs = []
            old_names = None
            for sub in subs:
                names = []
                for line in sub:
                    names.append(map(lambda x: getname(x[0]), line))

                if not old_names:
                    old_names = names
                if old_names != names:
                    break
                else:
                    rs.extend(map(lambda l: [int(round(thetime)), md5.md5(ip).hexdigest()] + map(lambda x: x[1], l), sub))
                    main_index += phase
            if len(rs) == 1:
                main_index -= phase
            elif len(rs) > 1:
                column_names.append([next_comment_index, old_names])
                new_results.extend(rs)
                break

            if main_index >= len(parsed_json[3]):
                break # while loop will now also exit, since it perfoms the same test.

        # Fallback to commenting each line.
        if old_main_index == main_index:
            for line, i in itertools.izip(itertools.islice(parsed_json[3], main_index, None), itertools.count(0)):
                new_results.append([int(round(thetime)), md5.md5(ip).hexdigest()] + map(lambda x: x[1], line))
                column_names.append([main_index + i, [map(lambda x: getname(x[0]), line)]])
            break
     
    return random_counter, counter, new_results, column_names

def ensure_period(s):
    if s.endswith(u".") or s.endswith(u"?") or s.endswith(u"!"):
        return s
    else:
        return s + u"."

def intersperse_comments(main, name_specs):
    newr = []
    for line, i in itertools.izip(main, itertools.count(0)):
        for idx, name_spec in name_specs:
            if idx == i:
                if len(name_spec) == 1:
                    newr.append([u"# Columns below this comment are as follows:"])
                    newr.append([u"# 1. Time results were received."])
                    newr.append([u"# 2. MD5 hash of participant's IP address."])
                    for colname,n in itertools.izip(name_spec[0], itertools.count(3)):
                        newr.append([u"# %i. %s" % (n, ensure_period(unicode(colname)))])
                    break
                else:
                    newr.append([u"# The lines below this comment are in groups of %i." % len(name_spec)])
                    newr.append([u"# The formats of the lines in each of these groups are as follows:"])
                    newr.append([u"#"])
                    for names, i in itertools.izip(name_spec, itertools.count(1)):
                        newr.append([u"# Line %i:" % i])
                        newr.append([u"#     Col. 1: Time results were received."])
                        newr.append([u"#     Col. 2: MD5 hash of participant's IP address."])
                        for name, j in itertools.izip(names, itertools.count(3)):
                            newr.append([u"#     Col. %i: %s" % (j, ensure_period(unicode(name)))])
                    break
        newr.append(line)
    return newr

def to_csv(lines):
    s = StringIO.StringIO()
    for l in lines:
        s.write(u','.join(map(unicode, l)))
        s.write(u'\n')
    return s.getvalue()


#
# The server itself.
#

def counter_cookie_header(c, cookiename):
    return (
        "Set-Cookie",
        "%s=%i; path=/" % \
        (cookiename, c)
    )

def create_monster_string(dir, extension, block_allow, manipulator=None):
    filenames = []
    try:
        ds = os.listdir(dir)
        ds.sort()
        for path in ds:
            fullpath = os.path.join(dir, path)
            if os.path.isfile(fullpath) and path.endswith(extension):
                if block_allow[0] == "block" and path not in block_allow[1:]:
                    filenames.append(fullpath)
                elif block_allow[0] == "allow" and path in block_allow[1:]:
                    filenames.append(fullpath)
    except:
        logger.error("Error getting directory listing for Javascript include directory '%s'" % dir)
        sys.exit(1)

    s = StringIO.StringIO()
    f = None
    try:
        try:
            for fn in filenames:
                f = open(fn)
                if not manipulator:
                    s.write(f.read())
                else:
                    content = f.read()
                    newcontent = manipulator(os.path.split(fn)[1], content, s)
                s.write('\n\n')
                f.close()
        except Exception, e:
            logger.error("Error reading Javascript files in '%s'" % dir)
            sys.exit(1)
    finally:
        if f: f.close()

    return s.getvalue()

def css_create_monster_string(dir, extension, block_allow):
    def manipulator (filename, content, ofile):
        if filename.startswith("global_"):
            ofile.write(content)
        else:
            parsed = css_parse(content)
            name = filename.split('.')[0] + '-'
            css_add_namespace(parsed, name)
            css_spit_out(parsed, ofile)
    return create_monster_string(dir, extension, block_allow, manipulator)

# Create a directory for storing results (if it doesn't already exist).
try:
    # Create the directory.
    if os.path.isfile(os.path.join(PWD, c['RESULT_FILES_DIR'])):
        logger.error("'%s' is a file, so could not create results directory" % c['RESULT_FILES_DIR'])
        sys.exit(1)
    elif not os.path.isdir(os.path.join(PWD, c['RESULT_FILES_DIR'])):
        os.mkdir(os.path.join(PWD, c['RESULT_FILES_DIR']))
except os.error, IOError:
    logger.error("Could not create results directory at %s" % os.path.join(PWD, c['RESULT_FILES_DIR']))
    sys.exit(1)

# Create a directory for storing the server state
# (if it doesn't already exist), and initialize the counter.
try:
    # Create the directory.
    if os.path.isfile(os.path.join(PWD, c['SERVER_STATE_DIR'])):
        logger.error("'%s' is a file, so could not create server state directory" % c['SERVER_STATE_DIR'])
        sys.exit(1)
    elif not os.path.isdir(os.path.join(PWD, c['SERVER_STATE_DIR'])):
        os.mkdir(os.path.join(PWD, c['SERVER_STATE_DIR']))

    # Initialize the counter, if there isn't one already.
    if not os.path.isfile(os.path.join(PWD, c['SERVER_STATE_DIR'], 'counter')):
        f = open(os.path.join(PWD, c['SERVER_STATE_DIR'], 'counter'), "w")
        f.write("0")
        f.close()
except os.error, IOError:
    logger.error("Could not create server state directory at %s" % os.path.join(PWD, c['SERVER_STATE_DIR']))
    sys.exit(1)

def control(env, start_response):
    # Save the time the results were received.
    thetime = time_module.time()

    def cc_start_response(status, headers, count=None, cookiename="counter"):
        count = count and count or get_counter()
        start_response(status, headers + [counter_cookie_header(count, cookiename)])

    ip = None
    if env.has_key('HTTP_X_FORWARDED_FOR'):
        ip = env['HTTP_X_FORWARDED_FOR']
    else:
        ip = env['REMOTE_ADDR']

    user_agent = "Unknown user agent"
    if env.has_key('USER_AGENT'):
        user_agent = env['USER_AGENT']
    elif env.has_key('HTTP_USER_AGENT'):
        user_agent = env['HTTP_USER_AGENT']

    base = None
    if env.has_key('REQUEST_URI'):
        base = env['REQUEST_URI']
    else:
        base = env['PATH_INFO']
    # Sometimes the query string likes to stick around.
    base = base.split('?')[0]

    last = filter(lambda x: x != [], base.split('/'))[-1];

    if last == PY_SCRIPT_NAME:
        qs = env.has_key('QUERY_STRING') and env['QUERY_STRING'].lstrip('?') or ''
        qs_hash = cgi.parse_qs(qs)

        # Is it a request for a JS/CSS include file?
        if qs_hash.has_key('include'): 
            if qs_hash['include'][0] == 'js':
                m = create_monster_string(os.path.join(PWD, c['JS_INCLUDES_DIR']), '.js', c['JS_INCLUDES_LIST'])
                start_response('200 OK', [('Content-Type', 'text/javascript; charset=UTF-8'), ('Pragma', 'no-cache')])
                return [m]
            elif qs_hash['include'][0] == 'css':
                m = css_create_monster_string(os.path.join(PWD, c['CSS_INCLUDES_DIR']), '.css', c['CSS_INCLUDES_LIST'])
                start_response('200 OK', [('Content-Type', 'text/css; charset=UTF-8'), ('Pragma', 'no-cache')])
                return [m]
            elif qs_hash['include'][0] == 'data':
                m = create_monster_string(os.path.join(PWD, c['DATA_INCLUDES_DIR']), '.js', c['DATA_INCLUDES_LIST'])
                start_response('200 OK', [('Content-Type', 'text/javascript; charset=UTF-8'), ('Pragma', 'no-cache')])
                return [m]
            elif qs_hash['include'][0] == 'main.js':
                contents = None
                f = None
                try:
                    try:
                        f = open(os.path.join(PWD, c['OTHER_INCLUDES_DIR'], 'main.js'))
                        contents = f.read()
                    except IOError:
                        start_response('500 Internal Server Error', [('Content-Type', 'text/html; charset=UTF-8')])
                        return ["<html><body><h1>500 Internal Server Error</h1></body></html>"]
                finally:
                    if f: f.close()
                # Do we set the 'overview' option?
                retlist = [contents]
                if qs_hash.has_key('overview') and qs_hash['overview'][0].upper() == "YES":
                    # UGLY: We just prepend a variable declaration to the file.
                    retlist = ["var conf_showOverview = true;\n\n"] + retlist
                cc_start_response('200 OK', [('Content-Type', 'text/javascript; charset=utif-8')])
                return retlist

        # (All branches above end with a return from this function.)
        #
        # Is it a request to forward to experiment.html with the counter set to a particular value?
        #
        #     NOTE: This is (as you may have noticed) a rather odd way of doing things. We just do
        #     it this way so that experiment.html can remain as a static file (for no other reason
        #     than keeping things the same as they used to be unless we absolutely have to change
        #     them).
        #
        if qs_hash.has_key('withsquare'):
            ivalue = None
            try:
                ivalue = int(qs_hash['withsquare'][0])
            except ValueError:
                start_response('400 Bad Request', [('Content-Type', 'text/html; charset=UTF-8')])
                return ["<html><body><h1>400 Bad Request</h1></body></html>"]

            cc_start_response('200 OK', [('Content-Type', 'text/html; charset=UTF-8'), ('Refresh', '0; url=experiment.html')],
                              ivalue, "counter_override")
            return []

        # ...if none of the above, it's some results.
        if not (env['REQUEST_METHOD'] == 'POST') and (env.has_key('CONTENT_LENGTH')):
            start_response('400 Bad Request', [('Content-Type', 'text/html; charset=UTF-8')])
            return ["<html><body><h1>400 Bad Request</h1></body></html>"]

        content_length = None
        content_encoding = None
        try:
            content_length = int(env['CONTENT_LENGTH'])
            encoding_re = re.compile(r"((charset)|(encoding))\s*=\s*(?P<encoding>[A-Za-z0-9_-]+)")
            res = encoding_re.search(env['CONTENT_TYPE'])
            if res: content_encoding = res.group('encoding')
        except ValueError:
            start_response('500 Internal Server Error', [('Content-Type', 'text/html; charset=UTF-8')])
            return ["<html><body><h1>500 Internal Server Error</h1></body></html>"]
        except IndexError:
            pass
        if not content_encoding: content_encoding = DEFAULT_ENCODING

        post_data = env['wsgi.input'].read(content_length)
        post_data = post_data.decode(content_encoding, 'ignore')

        # This will be called in the normal course of events, and if
        # there is an error parsing the JSON.
        def backup_raw_post_data(header=None):
            bf = None
            try:
                try:
                    bf = lock_and_open(os.path.join(PWD, c['RESULT_FILES_DIR'], c['RAW_RESULT_FILE_NAME']), "a")
                    if header:
                        bf.write(u"\n")
                        bf.write(header.encode(DEFAULT_ENCODING))
                    bf.write(post_data.encode(DEFAULT_ENCODING))
                except:
                    pass
            finally:
                if bf: unlock_and_close(bf)

        rf = None
        try:
            try:
                dec = JSONDecoder()
                parsed_json = dec.decode(post_data)
                random_counter, counter, main_results, column_names = rearrange(parsed_json, thetime, ip)
                header = None
                if c['INCLUDE_HEADERS_IN_RESULTS_FILE']:
                    header = u'#\n# Results on %s.\n# USER AGENT: %s\n# %s\n#\n' % \
                        (time_module.strftime(u"%A %B %d %Y %H:%M:%S UTC",
                                              time_module.gmtime(thetime)),
                         user_agent,
                         u"Design number was " + ((random_counter and u"random = " or u"non-random = ") + unicode(counter)))
                backup_raw_post_data(header)
                if c['INCLUDE_COMMENTS_IN_RESULTS_FILE']:
                    main_results = intersperse_comments(main_results, column_names)
                csv_results = to_csv(main_results)
                rf = lock_and_open(os.path.join(PWD, c['RESULT_FILES_DIR'], c['RESULT_FILE_NAME']), "a")
                rf.write(header.encode(DEFAULT_ENCODING))
                rf.write(csv_results.encode(DEFAULT_ENCODING))

                # Everything went OK with receiving and recording the results, so
                # update the counter.
                count = get_counter()
                set_counter(count + 1)

                start_response('200 OK', [('Content-Type', 'text/plain; charset=ascii')])
                return ["OK"]
            except ValueError: # JSON parse failed.
                backup_raw_post_data(header="# BAD REQUEST FROM %s\n" % user_agent)
                start_response('400 Bad Request', [('Content-Type', 'text/html; charset=UTF-8')])
                return ["<html><body><1>400 Bad Request</h1></body></html>"]
            except HighLevelParseError:
                backup_raw_post_data(header="# BAD REQUEST FROM %s\n" % user_agent)
                start_response('400 Bad Request', [('Content-Type', 'text/html; charset=UTF-8')])
                return ["<html><body><1>400 Bad Request</h1></body></html>"]
            except IOError:
                start_response('500 Internal Server Error', [('Content-Type', 'text/html; charset=UTF-8')])
                return ["<html><body><h1>500 Internal Server Error</h1></body></html>"]
        finally:
            if rf: unlock_and_close(rf)
    else:
        start_response('404 Not Found', [('Content-Type', 'text/html; charset=UTF-8')])
        return ["<html><body><h1>404 Not Found</h1></body></html>"]

class MyHTTPRequestHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
    STATIC_FILES = [
        'experiment.html',
        'overview.html',
        'json.js',
        'conf.js',
        'shuffle.js',
        'util.js',
        'backcompatcruft.js',
        'jquery.min.js',
        'jquery-ui.min.js'
    ]

    def __init__(self, request, client_address, server):
        self.extensions_map = {
            '' : "application/octet-stream",
            ".html" : "text/html; charset=UTF-8",
            ".css"  : "text/css",
            ".js"   : "text/javascript"
        }

        SimpleHTTPServer.SimpleHTTPRequestHandler.__init__(self, request, client_address, server)

    def do_either(self, method_name):
        last = filter(lambda x: x != [], self.path.split('/'))[-1];
        ps = last.split('?')
        qs = len(ps) > 1 and ps[1] or None
        path = ps[0]
        if method_name == 'GET' and path in MyHTTPRequestHandler.STATIC_FILES:
            return SimpleHTTPServer.SimpleHTTPRequestHandler.do_GET(self);
        else:
            # Bit of a hack. The 'control' function was written for use with the
            # paste module's simple HTTP server, but SimpleHTTPServer has a different
            # interface, so we bridge the gap here.
            response_type = [None]
            headers = [None]
            def start_response(response_type_, headers_):
                response_type[0] = response_type_
                headers[0] = headers_
            env = {
                "REMOTE_ADDR"    : self.client_address[0], # self.client_address is a (host,port) tuple.
                "REQUEST_URI"    : path,
                "REQUEST_METHOD" : method_name,
            }
            if qs:
                env['QUERY_STRING'] = qs
            if method_name == "POST":
                env['wsgi.input'] = self.rfile
            cl = self.headers.getheader("Content-Length")
            if cl:
                env['CONTENT_LENGTH'] = cl
            ct = self.headers.getheader("Content-Type")
            if ct:
                env['CONTENT_TYPE'] = ct
            ua = self.headers.getheader("User-Agent")
            if ua:
                env['USER_AGENT'] = ua

            body = control(env, start_response)
            assert response_type[0]
            rts = response_type[0].split(' ')
            try:
                self.send_response(int(rts[0]), ' '.join(rts[1:]))
                if headers[0]:
                    for h in headers[0]:
                        self.send_header(h[0], h[1])
                self.wfile.write('\n\n')
                for cs in body:
                    self.wfile.write(cs)
            except:
                # If we let exceptions percolate, we end up serving things as static
                # files which shouldn't be.
                sys.error.write("FUCK\n")
                logger.error("Error in responding to GET/POST request for toy Python HTTP server.");

    def do_GET(self):
        self.do_either('GET')

    def do_POST(self):
        self.do_either('POST')

if __name__ == "__main__":
    if COUNTER_SHOULD_BE_RESET:
        set_counter(0)
        print "Counter for latin square designs has been reset.\n"

    if c['SERVER_MODE'] in ["paste", "toy"]:
        server_address = ('', c['PORT'])
        httpd = BaseHTTPServer.HTTPServer(server_address, MyHTTPRequestHandler)
        httpd.path = c['STATIC_FILES_DIR']
        httpd.serve_forever()
    elif c['SERVER_MODE'] == "cgi":
        #wsgiref.handlers.CGIHandler().run(control)
        env = { }
        for k in os.environ:
            env[k] = os.environ[k]
        env['wsgi.input'] = sys.stdin
        def start_response(type, headers):
            sys.stdout.write("Content-Type: %s\n" % type)
            for h in headers:
                sys.stdout.write("%s: %s\n" % h)
            sys.stdout.write("\n")
        for l in control(env, start_response):
            sys.stdout.write(l)
