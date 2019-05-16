# -*- coding: utf-8 -*-

"""
Classes and functions for working with [incr tsdb()] test suites.

The `itsdb` module provides classes and functions for working with
[incr tsdb()] profiles (or, more generally, test suites; see
http://moin.delph-in.net/ItsdbTop). It handles the technical details
of encoding and decoding records in tables, including escaping and
unescaping reserved characters, pairing columns with their relational
descriptions, casting types (such as `:integer`, etc.), and
transparently handling gzipped tables, so that the user has a natural
way of working with the data. Capabilities include:

* Reading and writing test suites:

    >>> from delphin import itsdb
    >>> ts = itsdb.TestSuite('jacy/tsdb/gold/mrs')
    >>> ts.write(path='mrs-copy')

* Selecting data by table name, record index, and column name or
  index:

    >>> items = ts['item']           # get the items table
    >>> rec = items[0]               # get the first record
    >>> rec['i-input']               # input sentence of the first item
    '雨 が 降っ た ．'
    >>> rec[0]                       # values are cast on index retrieval
    11
    >>> rec.get('i-id')              # and on key retrieval
    11
    >>> rec.get('i-id', cast=False)  # unless cast=False
    '11'

* Selecting data as a query (note that types are cast by default):

    >>> next(ts.select('item:i-id@i-input@i-date'))  # query test suite
    [11, '雨 が 降っ た ．', datetime.datetime(2006, 5, 28, 0, 0)]
    >>> next(items.select('i-id@i-input@i-date'))    # query table
    [11, '雨 が 降っ た ．', datetime.datetime(2006, 5, 28, 0, 0)]

* In-memory modification of test suite data:

    >>> # desegment each sentence
    >>> for record in ts['item']:
    ...     record['i-input'] = ''.join(record['i-input'].split())
    ...
    >>> ts['item'][0]['i-input']
    '雨が降った．'

* Joining tables

    >>> joined = itsdb.join(ts['parse'], ts['result'])
    >>> next(joined.select('i-id@mrs'))
    [11, '[ LTOP: h1 INDEX: e2 [ e TENSE: PAST ...']

* Processing data with ACE (results are stored in memory)

    >>> from delphin import ace
    >>> with ace.ACEParser('jacy.dat') as cpu:
    ...     ts.process(cpu)
    ...
    NOTE: parsed 126 / 135 sentences, avg 3167k, time 1.87536s
    >>> ts.write('new-profile')

This module covers all aspects of [incr tsdb()] data, from
:class:`Relations` files and :class:`Field` descriptions to
:class:`Record`, :class:`Table`, and full :class:`TestSuite` classes.
:class:`TestSuite` is the most user-facing interface, and it makes it
easy to load the tables of a test suite into memory, inspect its
contents, modify or create data, and write the data to disk.

By default, the `itsdb` module expects test suites to use the standard
[incr tsdb()] schema. Test suites are always read and written
according to the associated or specified relations file, but other
things, such as default field values and the list of "core" tables,
are defined for the standard schema. It is, however, possible to
define non-standard schemata for particular applications, and most
functions will continue to work. One notable exception is the
:meth:`TestSuite.process` method, for which a new
:class:`~delphin.interface.FieldMapper` class must be defined.
"""

from pathlib import Path
import re
from gzip import open as gzopen
import tempfile
import shutil
import logging
from collections import (
    defaultdict, namedtuple, OrderedDict, Sequence, Mapping
)
from itertools import chain
from contextlib import contextmanager
import weakref

from delphin.exceptions import PyDelphinException
from delphin.util import (safe_int, parse_datetime)
from delphin.interface import FieldMapper
# Default modules need to import the PyDelphin version
from delphin.__about__ import __version__  # noqa: F401


##############################################################################
# Module variables

RELATIONS_FILENAME = 'relations'
FIELD_DELIMITER = '@'
DEFAULT_DATATYPE_VALUES = {
    ':integer': '-1'
}
TSDB_CODED_ATTRIBUTES = {
    'i-wf': 1,
    'i-difficulty': 1,
    'polarity': -1
}
_primary_keys = [
    ["i-id", "item"],
    ["p-id", "phenomenon"],
    ["ip-id", "item-phenomenon"],
    ["s-id", "set"],
    ["run-id", "run"],
    ["parse-id", "parse"],
    ["e-id", "edge"],
    ["f-id", "fold"]
]
TSDB_CORE_FILES = [
    "item",
    "analysis",
    "phenomenon",
    "parameter",
    "set",
    "item-phenomenon",
    "item-set"
]
_default_task_input_selectors = {
    'parse': 'item:i-input',
    'transfer': 'result:mrs',
    'generate': 'result:mrs',
}


#############################################################################
# Exceptions

class ITSDBError(PyDelphinException):
    """Raised when there is an error processing a [incr tsdb()] profile."""


#############################################################################
# Relations files

class Field(
        namedtuple('Field', 'name datatype key partial comment'.split())):
    '''
    A tuple describing a column in an [incr tsdb()] profile.

    Args:
        name (str): the column name
        datatype (str): `":string"`, `":integer"`, `":date"`,
            or `":float"`
        key (bool): `True` if the column is a key in the database
        partial (bool): `True` if the column is a partial key
        comment (str): a description of the column
    '''
    def __new__(cls, name, datatype, key=False, partial=False, comment=None):
        if partial and not key:
            raise ITSDBError('a partial key must also be a key')
        return super(Field, cls).__new__(
            cls, name, datatype, key, partial, comment
        )

    def __str__(self):
        parts = [self.name, self.datatype]
        if self.key:
            parts += [':key']
        if self.partial:
            parts += [':partial']
        s = '  ' + ' '.join(parts)
        if self.comment:
            s = '{}# {}'.format(s.ljust(40), self.comment)
        return s

    def default_value(self):
        """Get the default value of the field."""
        if self.name in TSDB_CODED_ATTRIBUTES:
            return TSDB_CODED_ATTRIBUTES[self.name]
        elif self.datatype == ':integer':
            return -1
        else:
            return ''


class Relation(tuple):
    """
    A [incr tsdb()] table schema.

    Args:
        name: the table name
        fields: a list of Field objects
    """

    def __new__(cls, name, fields):
        tr = super(Relation, cls).__new__(cls, fields)
        tr.name = name
        tr._index = dict(
            (f.name, i) for i, f in enumerate(fields)
        )
        tr._keys = None
        tr.key_indices = tuple(i for i, f in enumerate(fields) if f.key)
        return tr

    def __contains__(self, name):
        return name in self._index

    def index(self, fieldname):
        """Return the Field index given by *fieldname*."""
        return self._index[fieldname]

    def keys(self):
        """Return the tuple of field names of key fields."""
        keys = self._keys
        if keys is None:
            keys = tuple(self[i].name for i in self.key_indices)
        return keys


class _RelationJoin(Relation):
    def __new__(cls, rel1, rel2, on=None):
        if set(rel1.name.split('+')).intersection(rel2.name.split('+')):
            raise ITSDBError('Cannot join tables with the same name; '
                             'try renaming the table.')

        name = '{}+{}'.format(rel1.name, rel2.name)
        # the fields of the joined table, merging shared columns in *on*
        if isinstance(on, str):
            on = _split_cols(on)
        elif on is None:
            on = []

        fields = _prefixed_relation_fields(rel1, on, False)
        fields.extend(_prefixed_relation_fields(rel2, on, True))
        r = super(_RelationJoin, cls).__new__(cls, name, fields)

        # reset _keys to be a unique tuple of column-only forms
        keys = list(rel1.keys())
        seen = set(keys)
        for key in rel2.keys():
            if key not in seen:
                keys.append(key)
                seen.add(key)
        r._keys = tuple(keys)

        return r

    def __contains__(self, name):
        try:
            self.index(name)
        except KeyError:
            return False
        except ITSDBError:
            pass  # ambiguous field name
        return True

    def index(self, fieldname):
        if ':' not in fieldname:
            qfieldnames = []
            for table in self.name.split('+'):
                qfieldname = table + ':' + fieldname
                if qfieldname in self._index:
                    qfieldnames.append(qfieldname)
            if len(qfieldnames) > 1:
                raise ITSDBError(
                    "ambiguous field name; include the table name "
                    "(e.g., 'item:i-id' instead of 'i-id')")
            elif len(qfieldnames) == 1:
                fieldname = qfieldnames[0]
            else:
                pass  # lookup should return KeyError
        elif fieldname not in self._index:
            # join keys don't get prefixed
            uqfieldname = fieldname.rpartition(':')[2]
            if uqfieldname in self._keys:
                fieldname = uqfieldname
        return self._index[fieldname]


def _prefixed_relation_fields(fields, on, drop):
    prefixed_fields = []
    already_joined = isinstance(fields, _RelationJoin)
    for f in fields:
        table, _, fieldname = f[0].rpartition(':')
        if already_joined:
            prefix = table + ':' if table else ''
        else:
            prefix = fields.name + ':'
        if fieldname in on and not drop:
            prefixed_fields.append(Field(fieldname, *f[1:]))
        elif fieldname not in on:
            prefixed_fields.append(Field(prefix + fieldname, *f[1:]))
    return prefixed_fields


class Relations(object):
    """
    A [incr tsdb()] database schema.

    Note:
      Use :meth:`from_file` or :meth:`from_string` for instantiating
      a Relations object.

    Args:
        tables: a list of (table, :class:`Relation`) tuples
    """

    __slots__ = ('tables', '_data', '_field_map')

    def __init__(self, tables):
        tables = [(t[0], Relation(*t)) for t in tables]
        self.tables = tuple(t[0] for t in tables)
        self._data = dict(tables)
        self._field_map = _make_field_map(t[1] for t in tables)

    @classmethod
    def from_file(cls, source):
        """Instantiate Relations from a relations file."""
        if hasattr(source, 'read'):
            relations = cls.from_string(source.read())
        else:
            relations_text = Path(source).expanduser().read_text()
            relations = cls.from_string(relations_text)
        return relations

    @classmethod
    def from_string(cls, s):
        """Instantiate Relations from a relations string."""
        tables = []
        seen = set()
        current_table = None
        lines = list(reversed(s.splitlines()))  # to pop() in right order
        while lines:
            line = lines.pop().strip()
            table_m = re.match(r'^(?P<table>\w.+):$', line)
            field_m = re.match(r'\s*(?P<name>\S+)'
                               r'(\s+(?P<attrs>[^#]+))?'
                               r'(\s*#\s*(?P<comment>.*)$)?',
                               line)
            if table_m is not None:
                table_name = table_m.group('table')
                if table_name in seen:
                    raise ITSDBError(
                        'Table {} already defined.'.format(table_name)
                    )
                current_table = (table_name, [])
                tables.append(current_table)
                seen.add(table_name)
            elif field_m is not None and current_table is not None:
                name = field_m.group('name')
                attrs = field_m.group('attrs').split()
                datatype = attrs.pop(0)
                key = ':key' in attrs
                partial = ':partial' in attrs
                comment = field_m.group('comment')
                current_table[1].append(
                    Field(name, datatype, key, partial, comment)
                )
            elif line != '':
                raise ITSDBError('Invalid line: ' + line)
        return cls(tables)

    def __contains__(self, key):
        return key in self._data

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self.tables)

    def __len__(self):
        return len(self.tables)

    def __str__(self):
        return '\n\n'.join(
            '{tablename}:\n{fields}'.format(
                tablename=tablename,
                fields='\n'.join(str(f) for f in self[tablename])
            )
            for tablename in self
        )

    def items(self):
        """Return a list of (table, :class:`Relation`) for each table."""
        return [(table, self[table]) for table in self]

    def find(self, fieldname):
        """
        Return the list of tables that define the field *fieldname*.
        """
        tablename, _, column = fieldname.rpartition(':')
        if tablename and tablename in self._field_map[column]:
            return tablename
        else:
            return self._field_map[fieldname]

    def path(self, source, target):
        """
        Find the path of id fields connecting two tables.

        This is just a basic breadth-first-search. The relations file
        should be small enough to not be a problem.

        Returns:
            list: (table, fieldname) pairs describing the path from
                the source to target tables
        Raises:
            :class:`delphin.exceptions.ITSDBError`: when no path is
                found
        Example:
            >>> relations.path('item', 'result')
            [('parse', 'i-id'), ('result', 'parse-id')]
            >>> relations.path('parse', 'item')
            [('item', 'i-id')]
            >>> relations.path('item', 'item')
            []
        """
        visited = set(source.split('+'))  # split on + for joins
        targets = set(target.split('+')) - visited
        # ensure sources and targets exists
        for tablename in visited.union(targets):
            self[tablename]
        # base case; nothing to do
        if len(targets) == 0:
            return []
        paths = [[(tablename, None)] for tablename in visited]
        while True:
            newpaths = []
            for path in paths:
                laststep, pivot = path[-1]
                if laststep in targets:
                    return path[1:]
                else:
                    for key in self[laststep].keys():
                        for step in set(self.find(key)) - visited:
                            visited.add(step)
                            newpaths.append(path + [(step, key)])
            if newpaths:
                paths = newpaths
            else:
                break

        raise ITSDBError('no relation path found from {} to {}'
                         .format(source, target))


def _make_field_map(rels):
    g = {}
    for rel in rels:
        for field in rel:
            g.setdefault(field.name, []).append(rel.name)
    return g


##############################################################################
# Test items and test suites

class Record(list):
    """
    A row in a [incr tsdb()] table.

    Args:
        fields: the Relation schema for the table of this record
        iterable: an iterable containing the data for the record
    Attributes:
        fields (:class:`Relation`): table schema
    """

    __slots__ = ('fields', '_tableref', '_rowid')

    def __init__(self, fields, iterable):
        iterable = list(iterable)

        if len(fields) != len(iterable):
            raise ITSDBError(
                'Incorrect number of column values for {} table: {} != {}\n{}'
                .format(fields.name, len(iterable), len(fields), iterable)
            )

        iterable = [_cast_to_str(val, field)
                    for val, field in zip(iterable, fields)]

        self.fields = fields
        self._tableref = None
        self._rowid = None
        super(Record, self).__init__(iterable)

    @classmethod
    def _make(cls, fields, iterable, table, rowid):
        """
        Create a Record bound to a :class:`Table`.

        This is a helper method for creating Records from rows of a
        Table that is attached to a file. It is not meant to be called
        directly. It specifies the row number and a weak reference to
        the Table object so that when the Record is modified it is
        kept in the Table's in-memory list (see Record.__setitem__()),
        otherwise the changes would not be retained the next time the
        record is requested from the Table. The use of a weak
        reference to the Table is to avoid a circular reference and
        thus allow it to be properly garbage collected.
        """
        record = cls(fields, iterable)
        record._tableref = weakref.ref(table)
        record._rowid = rowid
        return record

    @classmethod
    def from_dict(cls, fields, mapping):
        """
        Create a Record from a dictionary of field mappings.

        The *fields* object is used to determine the column indices
        of fields in the mapping.

        Args:
            fields: the Relation schema for the table of this record
            mapping: a dictionary or other mapping from field names to
                column values
        Returns:
            a :class:`Record` object
        """
        iterable = [None] * len(fields)
        for key, value in mapping.items():
            try:
                index = fields.index(key)
            except KeyError:
                raise ITSDBError('Invalid field name(s): ' + key)
            iterable[index] = value
        return cls(fields, iterable)

    def __repr__(self):
        return "<{} '{}' {}>".format(
            self.__class__.__name__,
            self.fields.name,
            ' '.join('{}={}'.format(k, self[k]) for k in self.fields.keys())
        )

    def __str__(self):
        return make_row(self, self.fields)

    def __eq__(self, other):
        return all(a == b for a, b in zip(self, other))

    def __ne__(self, other):
        return any(a != b for a, b in zip(self, other))

    def __iter__(self):
        for raw, field in zip(list.__iter__(self), self.fields):
            yield _cast_to_datatype(raw, field)

    def __getitem__(self, index):
        if not isinstance(index, int):
            index = self.fields.index(index)
        raw = list.__getitem__(self, index)
        field = self.fields[index]
        return _cast_to_datatype(raw, field)

    def __setitem__(self, index, value):
        if not isinstance(index, int):
            index = self.fields.index(index)
        # record values are strings
        value = _cast_to_str(value, self.fields[index])
        # should the value be validated against the datatype?
        list.__setitem__(self, index, value)
        # when a record is modified it should stay in memory
        if self._tableref is not None:
            assert self._rowid is not None
            table = self._tableref()
            if table is not None:
                table[self._rowid] = self

    def get(self, key, default=None, cast=True):
        """
        Return the field data given by field name *key*.

        Args:
            key: the field name of the data to return
            default: the value to return if *key* is not in the row
        """
        tablename, _, key = key.rpartition(':')
        if tablename and tablename not in self.fields.name.split('+'):
            raise ITSDBError('column requested from wrong table: {}'
                             .format(tablename))
        try:
            index = self.fields.index(key)
            value = list.__getitem__(self, index)
        except (KeyError, IndexError):
            value = default
        else:
            if cast:
                field = self.fields[index]
                value = _cast_to_datatype(value, field)
        return value


class Table(object):
    """
    A [incr tsdb()] table.

    Instances of this class contain a collection of rows with the data
    stored in the database. Generally a Table will be created by a
    instantiated individually by the :meth:`Table.from_file` class
    :class:`TestSuite` object for a database, but a Table can also be
    method, and the relations file in the same directory is used to
    get the schema. Tables can also be constructed entirely in-memory
    and separate from a test suite via the standard `Table()`
    constructor.

    Tables have two modes: **attached** and **detached**. Attached
    tables are backed by a file on disk (whether as part of a test
    suite or not) and only store modified records in memory---all
    unmodified records are retrieved from disk. Therefore, iterating
    over a table is more efficient than random-access. Attached files
    use significantly less memory than detached tables but also
    require more processing time. Detached tables are entirely stored
    in memory and are not backed by a file. They are useful for the
    programmatic construction of test suites (including for unit
    tests) and other operations where high-speed random-access is
    required.  See the :meth:`attach` and :meth:`detach` methods for
    more information. The :meth:`is_attached` method is useful for
    determining the mode of a table.

    Args:
        fields: the Relation schema for this table
        records: the collection of Record objects containing the table data
    Attributes:
        name (str): table name
        fields (:class:`Relation`): table schema
        path: if attached, the path to the file containing the table
            data; if detached it is `None`
        encoding (str): the character encoding of the attached table
            file; if detached it is `None`
    """

    __slots__ = ('fields', 'path', 'encoding', '_records',
                 '_last_synced_index', '__weakref__')

    def __init__(self, fields, records=None):
        self.fields = fields
        self.path = None
        self.encoding = None
        self._records = []
        self._last_synced_index = -1

        if records is None:
            records = []
        self.extend(records)

    @classmethod
    def from_file(cls, path, fields=None, encoding='utf-8'):
        """
        Instantiate a Table from a database file.

        This method instantiates a table attached to the file at
        *path*.  The file will be opened and traversed to determine
        the number of records, but the contents will not be stored in
        memory unless they are modified.

        Args:
            path: the path to the table file
            fields: the Relation schema for the table (loaded from the
                relations file in the same directory if not given)
            encoding: the character encoding of the file at *path*
        """
        path = Path(path).expanduser()
        path = _table_path(path)  # do early in case file not found
        if fields is None:
            fields = _get_relation_from_table_path(path)

        table = cls(fields)
        table.attach(path, encoding=encoding)

        return table

    def write(self, records=None, path=None, fields=None, append=False,
              gzip=None):
        """
        Write the table to disk.

        The basic usage has no arguments and writes the table's data
        to the attached file. The parameters accommodate a variety of
        use cases, such as using *fields* to refresh a table to a new
        schema or *records* and *append* to incrementally build a
        table.

        Args:
            records: an iterable of :class:`Record` objects to write;
                if `None` the table's existing data is used
            path: the destination file path; if `None` use the
                path of the file attached to the table
            fields (:class:`Relation`): table schema to use for
                writing, otherwise use the current one
            append: if `True`, append rather than overwrite
            gzip: compress with gzip if non-empty
        Examples:
            >>> table.write()
            >>> table.write(results, path='new/path/result')
        """
        if path is None:
            if not self.is_attached():
                raise ITSDBError('no path given for detached table')
            else:
                path = self.path
        else:
            path = Path(path).expanduser()
        path = path.with_suffix('')
        if fields is None:
            fields = self.fields
        if records is None:
            records = iter(self)
        _write_table(
            path.parent,
            path.name,
            records,
            fields,
            append=append,
            gzip=gzip,
            encoding=self.encoding)

        if self.is_attached():
            original_path = self.path.with_suffix('')
            if path == original_path:
                self.path = _table_path(path)
                self._sync_with_file()

    def commit(self):
        """
        Commit changes to disk if attached.

        This method helps normalize the interface for detached and
        attached tables and makes writing attached tables a bit more
        efficient. For detached tables nothing is done, as there is no
        notion of changes, but neither is an error raised (unlike with
        :meth:`write`). For attached tables, if all changes are new
        records, the changes are appended to the existing file, and
        otherwise the whole file is rewritten.
        """
        if not self.is_attached():
            return
        changes = self.list_changes()
        if changes:
            indices, records = zip(*changes)
            if min(indices) > self._last_synced_index:
                self.write(records, append=True)
            else:
                self.write(append=False)

    def attach(self, path, encoding='utf-8'):
        """
        Attach the Table to the file at *path*.

        Attaching a table to a file means that only changed records
        are stored in memory, which greatly reduces the memory
        footprint of large profiles at some cost of
        performance. Tables created from :meth:`Table.from_file()` or
        from an attached :class:`TestSuite` are automatically
        attached. Attaching a file does not immediately flush the
        contents to disk; after attaching the table must be separately
        written to commit the in-memory data.

        A non-empty table will fail to attach to a non-empty file to
        avoid data loss when merging the contents. In this case, you
        may delete or clear the file, clear the table, or attach to
        another file.

        Args:
            path: the path to the table file
            encoding: the character encoding of the files in the test suite
        """
        if self.is_attached():
            raise ITSDBError('already attached at {!s}'.format(self.path))

        path = Path(path).expanduser()
        try:
            path = _table_path(path)
        except ITSDBError:
            # neither path nor path.gz exist; create new empty file
            # (note: if the file were non-empty this would be destructive)
            path = path.with_suffix('')
            path.write_text('')
        else:
            # path or path.gz exists; check if merging would be a problem
            if path.stat().st_size > 0 and len(self._records) > 0:
                raise ITSDBError(
                    'cannot attach non-empty table to non-empty file')

        self.path = path
        self.encoding = encoding

        # if _records is not empty then we're attaching to an empty file
        if len(self._records) == 0:
            self._sync_with_file()

    def detach(self):
        """
        Detach the table from a file.

        Detaching a table reads all data from the file and places it
        in memory. This is useful when constructing or significantly
        manipulating table data, or when more speed is needed. Tables
        created by the default constructor are detached.

        When detaching, only unmodified records are loaded from the
        file; any uncommited changes in the Table are left as-is.

        .. warning::

           Very large tables may consume all available RAM when
           detached.  Expect the in-memory table to take up about
           twice the space of an uncompressed table on disk, although
           this may vary by system.
        """
        if not self.is_attached():
            raise ITSDBError('already detached')
        records = self._records
        for i, line in self._enum_lines():
            if records[i] is None:
                # check number of columns?
                records[i] = tuple(decode_row(line))
        self.path = None
        self.encoding = None

    @property
    def name(self):
        return self.fields.name

    def is_attached(self):
        """Return `True` if the table is attached to a file."""
        return self.path is not None

    def list_changes(self):
        """
        Return a list of modified records.

        This is only applicable for attached tables.

        Returns:
            A list of `(row_index, record)` tuples of modified records
        Raises:
            :class:`delphin.exceptions.ITSDBError`: when called on a
                detached table
        """
        if not self.is_attached():
            raise ITSDBError('changes are not tracked for detached tables.')
        return [(i, self[i]) for i, row in enumerate(self._records)
                if row is not None]

    def _sync_with_file(self):
        """Clear in-memory structures so table is synced with the file."""
        self._records = []
        i = -1
        for i, line in self._enum_lines():
            self._records.append(None)
        self._last_synced_index = i

    def _enum_lines(self):
        """Enumerate lines from the attached file."""
        with _open_table(self.path, self.encoding) as lines:
            yield from enumerate(lines)

    def _enum_attached_rows(self, indices):
        """Enumerate on-disk and in-memory records."""
        records = self._records
        i = 0
        # first rows covered by the file
        for i, line in self._enum_lines():
            if i in indices:
                row = records[i]
                if row is None:
                    row = decode_row(line)
                yield (i, row)
        # then any uncommitted rows
        for j in range(i, len(records)):
            if j in indices:
                if records[j] is not None:
                    yield (j, records[j])

    def __iter__(self):
        yield from self._iterslice(slice(None))

    def __getitem__(self, index):
        if isinstance(index, slice):
            return list(self._iterslice(index))
        else:
            return self._getitem(index)

    def _iterslice(self, slice):
        """Yield records from a slice index."""
        indices = range(*slice.indices(len(self._records)))
        if self.is_attached():
            rows = self._enum_attached_rows(indices)
            if slice.step is not None and slice.step < 0:
                rows = reversed(list(rows))
        else:
            rows = zip(indices, self._records[slice])

        fields = self.fields
        for i, row in rows:
            yield Record._make(fields, row, self, i)

    def _getitem(self, index):
        """Get a single non-slice index."""
        row = self._records[index]
        if row is not None:
            pass
        elif self.is_attached():
            # need to handle negative indices manually
            if index < 0:
                index = len(self._records) + index
            row = next((decode_row(line)
                        for i, line in self._enum_lines()
                        if i == index),
                       None)
            if row is None:
                raise ITSDBError('could not retrieve row in attached table')
        else:
            raise ITSDBError('invalid row in detached table: {}'.format(index))

        return Record._make(self.fields, row, self, index)

    def __setitem__(self, index, value):
        # first normalize the arguments for slices and regular indices
        if isinstance(index, slice):
            values = list(value)
        else:
            self._records[index]  # check for IndexError
            values = [value]
            index = slice(index, index + 1)
        # now prepare the records for being in a table
        fields = self.fields
        for i, record in enumerate(values):
            values[i] = _cast_record_to_str_tuple(record, fields)
        self._records[index] = values

    def __len__(self):
        return len(self._records)

    def append(self, record):
        """
        Add *record* to the end of the table.

        Args:
            record: a :class:`Record` or other iterable containing
                column values
        """
        self.extend([record])

    def extend(self, records):
        """
        Add each record in *records* to the end of the table.

        Args:
            record: an iterable of :class:`Record` or other iterables
                containing column values
        """
        fields = self.fields
        for record in records:
            record = _cast_record_to_str_tuple(record, fields)
            self._records.append(record)

    def select(self, cols, mode='list'):
        """
        Select columns from each row in the table.

        See :func:`select_rows` for a description of how to use the
        *mode* parameter.

        Args:
            cols: an iterable of Field (column) names
            mode: how to return the data
        """
        if isinstance(cols, str):
            cols = _split_cols(cols)
        if not cols:
            cols = [f.name for f in self.fields]
        return select_rows(cols, self, mode=mode)


def _get_relation_from_table_path(path):
    rpath = path.parent.joinpath(RELATIONS_FILENAME)
    if not rpath.is_file():
        raise ITSDBError(
            'No relation is specified and a relations file could '
            'not be found.'
        )
    rels = Relations.from_file(rpath)
    name = path.with_suffix('').name
    if name not in rels:
        raise ITSDBError(
            'Table \'{}\' not found in the relations.'.format(name)
        )
    # successfully inferred the relations for the table
    return rels[name]


def _cast_record_to_str_tuple(record, fields):
    if len(record) != len(fields):
        raise ITSDBError('wrong number of fields')
    return tuple(_cast_to_str(value, field)
                 for value, field in zip(record, fields))


class TestSuite(object):
    """
    A [incr tsdb()] test suite database.

    Args:
        path: the path to the test suite's directory
        relations (:class:`Relations`, str): the database schema; either
            a :class:`Relations` object or a path to a relations file;
            if not given, the relations file under *path* will be used
        encoding: the character encoding of the files in the test suite
    Attributes:
        encoding (:py:class:`str`): character encoding used when reading and
            writing tables
        relations (:class:`Relations`): database schema
    """

    __slots__ = ('_path', 'relations', '_data', 'encoding')

    def __init__(self, path=None, relations=None, encoding='utf-8'):
        if path is not None:
            path = Path(path).expanduser()
        self._path = path
        self.encoding = encoding

        if isinstance(relations, Relations):
            self.relations = relations
        elif relations is None and path is not None:
            relations = self._path.joinpath(RELATIONS_FILENAME)
            self.relations = Relations.from_file(relations)
        else:
            relations = Path(relations).expanduser()
            if not relations.is_file():
                raise ITSDBError(
                    'Either the relations parameter must be provided or '
                    '*path* must point to a directory with a relations file.'
                )
            self.relations = Relations.from_file(relations)

        self._data = dict((t, None) for t in self.relations)

        if self._path is not None:
            self.reload()

    def __getitem__(self, tablename):
        # if the table is None it is invalidated; reload it
        if self._data[tablename] is None:
            if self._path is not None:
                self._reload_table(tablename)
            else:
                self._data[tablename] = Table(
                    self.relations[tablename]
                )
        return self._data[tablename]

    def reload(self):
        """Discard temporary changes and reload the database from disk."""
        if self._path is None:
            raise ITSDBError('cannot reload an in-memory test suite')
        for tablename in self.relations:
            self._reload_table(tablename)

    def _reload_table(self, tablename):
        # assumes self.path is not None
        fields = self.relations[tablename]
        path = self._path.joinpath(tablename)
        try:
            path = _table_path(path)
        except ITSDBError:
            # path doesn't exist
            path.with_suffix('').write_text('')  # create empty file
        table = Table.from_file(path,
                                fields=fields,
                                encoding=self.encoding)
        self._data[tablename] = table

    def select(self, arg, cols=None, mode='list'):
        """
        Select columns from each row in the table.

        The first parameter, *arg*, may either be a table name or a
        data specifier. If the former, the *cols* parameter selects
        the columns from the table. If the latter, *cols* is left
        unspecified and both the table and columns are taken from the
        data specifier; e.g., `select('item:i-id@i-input')` is
        equivalent to `select('item', ('i-id', 'i-input'))`.

        See select_rows() for a description of how to use the *mode*
        parameter.

        Args:
            arg: a table name, if *cols* is specified, otherwise a data
                specifier
            cols: an iterable of Field (column) names
            mode: how to return the data
        """
        if cols is None:
            table, cols = get_data_specifier(arg)
        else:
            table = arg
        if cols is None:
            cols = [f.name for f in self.relations[table]]
        return select_rows(cols, self[table], mode=mode)

    def write(self, tables=None, path=None, relations=None,
              append=False, gzip=None):
        """
        Write the test suite to disk.

        Args:
            tables: a name or iterable of names of tables to write,
                or a Mapping of table names to table data; if `None`,
                all tables will be written
            path: the destination directory; if `None` use the path
                assigned to the TestSuite
            relations: a :class:`Relations` object or path to a
                relations file to be used when writing the tables
            append: if `True`, append to rather than overwrite tables
            gzip: compress non-empty tables with gzip
        Examples:
            >>> ts.write(path='new/path')
            >>> ts.write('item')
            >>> ts.write(['item', 'parse', 'result'])
            >>> ts.write({'item': item_rows})
        """
        if path is None:
            path = self._path
        else:
            path = Path(path).expanduser()
        if tables is None:
            tables = self._data
        elif isinstance(tables, str):
            tables = {tables: self[tables]}
        elif isinstance(tables, Mapping):
            pass
        elif isinstance(tables, (Sequence, set)):
            tables = dict((table, self[table]) for table in tables)
        if relations is None:
            relations = self.relations
        elif isinstance(relations, str):
            relations = Relations.from_file(relations)

        # prepare destination
        # raise error if path != self._path?
        path.mkdir(parents=True, exist_ok=True)
        path.joinpath(RELATIONS_FILENAME).write_text(str(relations) + '\n')

        for tablename, fields in relations.items():
            if tablename in tables:
                data = tables[tablename]
                # reload table from disk if it is invalidated
                if data is None:
                    data = self[tablename]
                elif not isinstance(data, Table):
                    data = Table(fields, data)
                _write_table(
                    path,
                    tablename,
                    data,
                    fields,
                    append=append,
                    gzip=gzip,
                    encoding=self.encoding
                )

    def exists(self, table=None):
        """
        Return `True` if the test suite or a table exists on disk.

        If *table* is `None`, this method returns `True` if the
        :attr:`TestSuite.path` is specified and points to an existing
        directory containing a valid relations file. If *table* is
        given, the function returns `True` if, in addition to the
        above conditions, the table exists as a file (even if
        empty). Otherwise it returns False.
        """
        if self._path is None or not self._path.is_dir():
            return False
        if not self._path.joinpath(RELATIONS_FILENAME).is_file():
            return False
        if table is not None:
            try:
                _table_path(self._path.joinpath(table))
            except ITSDBError:
                return False
        return True

    def size(self, table=None):
        """
        Return the size, in bytes, of the test suite or *table*.

        If *table* is `None`, return the size of the whole test suite
        (i.e., the sum of the table sizes). Otherwise, return the size
        of *table*.

        Notes:
            * If the file is gzipped, it returns the compressed size.
            * Only tables on disk are included.
        """
        size = 0
        if table is None:
            for table in self.relations:
                size += self.size(table)
        else:
            try:
                path = _table_path(self._path.joinpath(table))
                size += path.stat().st_size
            except ITSDBError:
                pass
        return size

    def process(self, cpu, selector=None, source=None, fieldmapper=None,
                gzip=None, buffer_size=1000):
        """
        Process each item in a [incr tsdb()] test suite

        If the test suite is attached to files on disk, the output
        records will be flushed to disk when the number of new records
        in a table is *buffer_size*. If the test suite is not attached
        to files or *buffer_size* is set to `None`, records are kept
        in memory and not flushed to disk.

        Args:
            cpu (:class:`~delphin.interface.Processor`):
                processor interface (e.g.,
                :class:`~delphin.ace.ACEParser`)
            selector (str): data specifier to select a single table and
                column as processor input (e.g., `"item:i-input"`)
            source (:class:`TestSuite`, :class:`Table`): test suite or
                table from which inputs are taken; if `None`, use `self`
            fieldmapper (:class:`~delphin.FieldMapper`):
                object for mapping response fields to [incr tsdb()]
                fields; if `None`, use a default mapper for the
                standard schema
            gzip: compress non-empty tables with gzip
            buffer_size (int): number of output records to hold in
                memory before flushing to disk; ignored if the test suite
                is all in-memory; if `None`, do not flush to disk
        Examples:
            >>> ts.process(ace_parser)
            >>> ts.process(ace_generator, 'result:mrs', source=ts2)
        """
        if selector is None:
            selector = _default_task_input_selectors.get(cpu.task)
        if source is None:
            source = self
        if fieldmapper is None:
            fieldmapper = FieldMapper()
        if self._path is None:
            buffer_size = None

        tables = set(fieldmapper.affected_tables).intersection(self.relations)
        _prepare_target(self, tables, buffer_size)
        source, cols = _prepare_source(selector, source)
        key_cols = cols[:-1]

        for item in select_rows(cols, source, mode='list'):
            datum = item.pop()
            keys = dict(zip(key_cols, item))
            response = cpu.process_item(datum, keys=keys)
            logging.info(
                'Processed item {:>16}  {:>8} results'
                .format(encode_row(item), len(response['results']))
            )
            for tablename, data in fieldmapper.map(response):
                _add_record(self[tablename], data, buffer_size)

        for tablename, data in fieldmapper.cleanup():
            _add_record(self[tablename], data, buffer_size)

        # finalize data if writing to disk
        for tablename in tables:
            table = self[tablename]
            if buffer_size is not None:
                table.write(gzip=gzip)


def _prepare_target(ts, tables, buffer_size):
    """Clear tables affected by the processing."""
    for tablename in tables:
        table = ts[tablename]
        table[:] = []
        if buffer_size is not None and table.is_attached():
            table.write(append=False)


def _prepare_source(selector, source):
    """Normalize source rows and selectors."""
    tablename, fields = get_data_specifier(selector)
    if len(fields) != 1:
        raise ITSDBError(
            'Selector must specify exactly one data column: {}'
            .format(selector)
        )
    if isinstance(source, TestSuite):
        if not tablename:
            tablename = source.relations.find(fields[0])[0]
        source = source[tablename]
    cols = list(source.fields.keys()) + fields
    return source, cols


def _add_record(table, data, buffer_size):
    """
    Prepare and append a Record into its Table; flush to disk if necessary.
    """
    fields = table.fields
    # remove any keys that aren't relation fields
    for invalid_key in set(data).difference([f.name for f in fields]):
        del data[invalid_key]
    table.append(Record.from_dict(fields, data))
    # write if requested and possible
    if buffer_size is not None and table.is_attached():
        # for now there isn't a public method to get the number of new
        # records, so use private members
        if (len(table) - 1) - table._last_synced_index > buffer_size:
            table.commit()


##############################################################################
# Non-class (i.e. static) functions

data_specifier_re = re.compile(r'(?P<table>[^:]+)?(:(?P<cols>.+))?$')


def get_data_specifier(string):
    """
    Return a tuple (table, col) for some [incr tsdb()] data specifier.
    For example::

        item              -> ('item', None)
        item:i-input      -> ('item', ['i-input'])
        item:i-input@i-wf -> ('item', ['i-input', 'i-wf'])
        :i-input          -> (None, ['i-input'])
        (otherwise)       -> (None, None)
    """
    match = data_specifier_re.match(string)
    if match is None:
        return (None, None)
    table = match.group('table')
    if table is not None:
        table = table.strip()
    cols = _split_cols(match.group('cols'))
    return (table, cols)


def _split_cols(colstring):
    if not colstring:
        return None
    colstring = colstring.lstrip(':')
    return [col.strip() for col in colstring.split('@')]


def decode_row(line, fields=None):
    """
    Decode a raw line from a profile into a list of column values.

    Decoding involves splitting the line by the field delimiter
    (`"@"` by default) and unescaping special characters. If *fields*
    is given, cast the values into the datatype given by their
    respective Field object.

    Args:
        line: a raw line from a [incr tsdb()] profile.
        fields: a list or Relation object of Fields for the row
    Returns:
        A list of column values.
    """
    cols = line.rstrip('\n').split(FIELD_DELIMITER)
    cols = list(map(unescape, cols))
    if fields is not None:
        if len(cols) != len(fields):
            raise ITSDBError(
                'Wrong number of fields: {} != {}'
                .format(len(cols), len(fields))
            )
        for i in range(len(cols)):
            col = cols[i]
            if col:
                field = fields[i]
                col = _cast_to_datatype(col, field)
            cols[i] = col
    return cols


def _cast_to_datatype(col, field):
    if col is None:
        col = field.default_value()
    else:
        dt = field.datatype
        if dt == ':integer':
            col = int(col)
        elif dt == ':float':
            col = float(col)
        elif dt == ':date':
            dt = parse_datetime(col)
            col = dt if dt is not None else col
        # other casts? :position?
    return col


def _cast_to_str(col, field):
    if col is None:
        if field.key:
            raise ITSDBError('missing key: {}'.format(field.name))
        col = field.default_value()
    return str(col)


def encode_row(fields):
    """
    Encode a list of column values into a [incr tsdb()] profile line.

    Encoding involves escaping special characters for each value, then
    joining the values into a single string with the field delimiter
    (`"@"` by default). It does not fill in default values (see
    make_row()).

    Args:
        fields: a list of column values
    Returns:
        A [incr tsdb()]-encoded string
    """
    str_fields = [str(f) for f in fields]
    escaped_fields = map(escape, str_fields)
    return FIELD_DELIMITER.join(escaped_fields)


def escape(string):
    r"""
    Replace any special characters with their [incr tsdb()] escape
    sequences. The characters and their escape sequences are::

        @         -> \s
        (newline) -> \n
        \         -> \\

    Also see :func:`unescape`

    Args:
        string: the string to escape
    Returns:
        The escaped string
    """
    # str.replace()... is about 3-4x faster than re.sub() here
    return (string
            .replace('\\', '\\\\')  # must be done first
            .replace('\n', '\\n')
            .replace(FIELD_DELIMITER, '\\s'))


def unescape(string):
    """
    Replace [incr tsdb()] escape sequences with the regular equivalents.
    Also see :func:`escape`.

    Args:
        string (str): the escaped string
    Returns:
        The string with escape sequences replaced
    """
    # str.replace()... is about 3-4x faster than re.sub() here
    return (string
            .replace('\\\\', '\\')  # must be done first
            .replace('\\n', '\n')
            .replace('\\s', FIELD_DELIMITER))


def _table_path(tbl_path):
    """
    Determine if the table path should end in .gz or not and return it.

    A .gz path is preferred only if it exists and is newer than any
    regular text file path.

    Raises:
        :class:`delphin.exceptions.ITSDBError`: when neither the .gz
            nor text file exist.
    """
    tx_path = tbl_path.with_suffix('')
    gz_path = tbl_path.with_suffix('.gz')

    if tx_path.is_file():
        if (gz_path.is_file()
                and gz_path.stat().st_mtime > tx_path.stat().st_mtime):
            tbl_path = gz_path
        else:
            tbl_path = tx_path
    elif gz_path.is_file():
        tbl_path = gz_path
    else:
        raise ITSDBError(
            'Table does not exist at {!s}(.gz)'
            .format(tbl_path)
        )

    return tbl_path


@contextmanager
def _open_table(tbl_path, encoding):
    """
    Transparently open the compressed or text table file.

    Can be used as a context manager in a 'with' statement.
    """
    path = _table_path(tbl_path)
    # open and gzip.open don't accept pathlib.Path objects until Python 3.6
    if path.suffix.lower() == '.gz':
        with gzopen(str(path), mode='rt', encoding=encoding) as f:
            yield f
    else:
        with path.open(encoding=encoding) as f:
            yield f


def _write_table(testsuite_dir, table_name, rows, fields,
                 append=False, gzip=False, encoding='utf-8'):
    # don't gzip if empty
    rows = iter(rows)
    try:
        first_row = next(rows)
    except StopIteration:
        gzip = False
    else:
        rows = chain([first_row], rows)
    if encoding is None:
        encoding = 'utf-8'

    if gzip and append:
        logging.warning('Appending to a gzip file may result in '
                        'inefficient compression.')

    if not testsuite_dir.is_dir():
        raise ITSDBError('Profile directory does not exist: {}'
                         .format(testsuite_dir))

    with tempfile.NamedTemporaryFile(
            mode='w+b', suffix='.tmp',
            prefix=table_name, dir=str(testsuite_dir)) as f_tmp:

        for row in rows:
            f_tmp.write((make_row(row, fields) + '\n').encode(encoding))
        f_tmp.seek(0)

        tx_path = testsuite_dir.joinpath(table_name)
        gz_path = tx_path.with_suffix('.gz')
        mode = 'ab' if append else 'wb'

        if gzip:
            # clean up non-gzip files, if any
            if tx_path.is_file():
                tx_path.unlink()
            with gzopen(str(gz_path), mode) as f_out:
                shutil.copyfileobj(f_tmp, f_out)
        else:
            # clean up gzip files, if any
            if gz_path.is_file():
                gz_path.unlink()
            with tx_path.open(mode=mode) as f_out:
                shutil.copyfileobj(f_tmp, f_out)


def make_row(row, fields):
    """
    Encode a mapping of column name to values into a [incr tsdb()]
    profile line. The *fields* parameter determines what columns are
    used, and default values are provided if a column is missing from
    the mapping.

    Args:
        row: a mapping of column names to values
        fields: an iterable of :class:`Field` objects
    Returns:
        A [incr tsdb()]-encoded string
    """
    if not hasattr(row, 'get'):
        row = {f.name: col for f, col in zip(fields, row)}

    row_fields = []
    for f in fields:
        val = row.get(f.name, None)
        if val is None:
            val = str(f.default_value())
        row_fields.append(val)
    return encode_row(row_fields)


def select_rows(cols, rows, mode='list', cast=True):
    """
    Yield data selected from rows.

    It is sometimes useful to select a subset of data from a profile.
    This function selects the data in *cols* from *rows* and yields it
    in a form specified by *mode*. Possible values of *mode* are:

    ==================  =================  ==========================
    mode                description        example `['i-id', 'i-wf']`
    ==================  =================  ==========================
    `'list'` (default)  a list of values   `[10, 1]`
    `'dict'`            col to value map   `{'i-id': 10,'i-wf': 1}`
    `'row'`             [incr tsdb()] row  `'10@1'`
    ==================  =================  ==========================

    Args:
        cols: an iterable of column names to select data for
        rows: the rows to select column data from
        mode: the form yielded data should take
        cast: if `True`, cast column values to their datatype
            (requires *rows* to be :class:`Record` objects)

    Yields:
        Selected data in the form specified by *mode*.
    """
    mode = mode.lower()
    if mode == 'list':

        def modecast(cols, data):
            return data

    elif mode == 'dict':

        def modecast(cols, data):
            return dict(zip(cols, data))

    elif mode == 'row':

        def modecast(cols, data):
            return encode_row(data)

    else:
        raise ITSDBError('Invalid mode for select operation: {}\n'
                         '  Valid options include: list, dict, row'
                         .format(mode))
    for row in rows:
        try:
            data = [row.get(c, cast=cast) for c in cols]
        except TypeError:
            data = [row.get(c) for c in cols]
        yield modecast(cols, data)


def match_rows(rows1, rows2, key, sort_keys=True):
    """
    Yield triples of `(value, left_rows, right_rows)` where
    `left_rows` and `right_rows` are lists of rows that share the same
    column value for *key*. This means that both *rows1* and *rows2*
    must have a column with the same name *key*.

    .. warning::

       Both *rows1* and *rows2* will exist in memory for this
       operation, so it is not recommended for very large tables on
       low-memory systems.

    Args:
        rows1: a :class:`Table` or list of :class:`Record` objects
        rows2: a :class:`Table` or list of :class:`Record` objects
        key (str): the column name on which to match
        sort_keys (bool): if `True`, yield matching rows sorted by the
            matched key instead of the original order
    """
    matched = OrderedDict()
    for i, rows in enumerate([rows1, rows2]):
        for row in rows:
            val = row[key]
            try:
                data = matched[val]
            except KeyError:
                matched[val] = ([], [])
                data = matched[val]
            data[i].append(row)
    vals = matched.keys()
    if sort_keys:
        vals = sorted(vals, key=safe_int)
    for val in vals:
        left, right = matched[val]
        yield (val, left, right)


def join(table1, table2, on=None, how='inner', name=None):
    """
    Join two tables and return the resulting Table object.

    Fields in the resulting table have their names prefixed with their
    corresponding table name. For example, when joining `item` and
    `parse` tables, the `i-input` field of the `item` table will be
    named `item:i-input` in the resulting Table. Pivot fields (those
    in *on*) are only stored once without the prefix.

    Both inner and left joins are possible by setting the *how*
    parameter to `inner` and `left`, respectively.

    .. warning::

       Both *table2* and the resulting joined table will exist in
       memory for this operation, so it is not recommended for very
       large tables on low-memory systems.

    Args:
        table1 (:class:`Table`): the left table to join
        table2 (:class:`Table`): the right table to join
        on (str): the shared key to use for joining; if `None`, find
            shared keys using the schemata of the tables
        how (str): the method used for joining (`"inner"` or `"left"`)
        name (str): the name assigned to the resulting table
    """
    if how not in ('inner', 'left'):
        ITSDBError('Only \'inner\' and \'left\' join methods are allowed.')

    # validate and normalize the pivot
    on = _join_pivot(on, table1, table2)
    # the fields of the joined table
    fields = _RelationJoin(table1.fields, table2.fields, on=on)

    # get key mappings to the right side (useful for inner and left joins)
    def get_key(rec):
        return tuple(rec.get(k) for k in on)

    key_indices = set(table2.fields.index(k) for k in on)
    right = defaultdict(list)
    for rec in table2:
        right[get_key(rec)].append([c for i, c in enumerate(rec)
                                    if i not in key_indices])

    # build joined table
    rfill = [f.default_value() for f in table2.fields if f.name not in on]
    joined = []
    for lrec in table1:
        k = get_key(lrec)
        if how == 'left' or k in right:
            joined.extend(lrec + rrec for rrec in right.get(k, [rfill]))

    return Table(fields, joined)


def _join_pivot(on, table1, table2):
    if isinstance(on, str):
        on = _split_cols(on)
    if not on:
        on = set(table1.fields.keys()).intersection(table2.fields.keys())
        if not on:
            raise ITSDBError(
                'No shared key to join on in the \'{}\' and \'{}\' tables.'
                .format(table1.name, table2.name)
            )
    return sorted(on)
