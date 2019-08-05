# -*- coding: utf-8 -*-

"""
DMRS-JSON serialization and deserialization.

Example:

* *The new chef whose soup accidentally spilled quit and left.*

::

  {
    "top": 10008,
    "index": 10009,
    "nodes": [
      {
        "nodeid": 10000,
        "predicate": "_the_q",
        "lnk": {"from": 0, "to": 3}
      },
      {
        "nodeid": 10001,
        "predicate": "_new_a_1",
        "sortinfo": {"SF": "prop", "TENSE": "untensed", "MOOD": "indicative", "PROG": "bool", "PERF": "-", "cvarsort": "e"},
        "lnk": {"from": 4, "to": 7}
      },
      {
        "nodeid": 10002,
        "predicate": "_chef_n_1",
        "sortinfo": {"PERS": "3", "NUM": "sg", "IND": "+", "cvarsort": "x"},
        "lnk": {"from": 8, "to": 12}
      },
      {
        "nodeid": 10003,
        "predicate": "def_explicit_q",
        "lnk": {"from": 13, "to": 18}
      },
      {
        "nodeid": 10004,
        "predicate": "poss",
        "sortinfo": {"SF": "prop", "TENSE": "untensed", "MOOD": "indicative", "PROG": "-", "PERF": "-", "cvarsort": "e"},
        "lnk": {"from": 13, "to": 18}
      },
      {
        "nodeid": 10005,
        "predicate": "_soup_n_1",
        "sortinfo": {"PERS": "3", "NUM": "sg", "cvarsort": "x"},
        "lnk": {"from": 19, "to": 23}
      },
      {
        "nodeid": 10006,
        "predicate": "_accidental_a_1",
        "sortinfo": {"SF": "prop", "TENSE": "untensed", "MOOD": "indicative", "PROG": "-", "PERF": "-", "cvarsort": "e"},
        "lnk": {"from": 24, "to": 36}
      },
      {
        "nodeid": 10007,
        "predicate": "_spill_v_1",
        "sortinfo": {"SF": "prop", "TENSE": "past", "MOOD": "indicative", "PROG": "-", "PERF": "-", "cvarsort": "e"},
        "lnk": {"from": 37, "to": 44}
      },
      {
        "nodeid": 10008,
        "predicate": "_quit_v_1",
        "sortinfo": {"SF": "prop", "TENSE": "past", "MOOD": "indicative", "PROG": "-", "PERF": "-", "cvarsort": "e"},
        "lnk": {"from": 45, "to": 49}
      },
      {
        "nodeid": 10009,
        "predicate": "_and_c",
        "sortinfo": {"SF": "prop", "TENSE": "past", "MOOD": "indicative", "PROG": "-", "PERF": "-", "cvarsort": "e"},
        "lnk": {"from": 50, "to": 53}
      },
      {
        "nodeid": 10010,
        "predicate": "_leave_v_1",
        "sortinfo": {"SF": "prop", "TENSE": "past", "MOOD": "indicative", "PROG": "-", "PERF": "-", "cvarsort": "e"},
        "lnk": {"from": 54, "to": 59}
      }
    ],
    "links": [
      {"from": 10000, "to": 10002, "rargname": "RSTR", "post": "H"},
      {"from": 10001, "to": 10002, "rargname": "ARG1", "post": "EQ"},
      {"from": 10003, "to": 10005, "rargname": "RSTR", "post": "H"},
      {"from": 10004, "to": 10005, "rargname": "ARG1", "post": "EQ"},
      {"from": 10004, "to": 10002, "rargname": "ARG2", "post": "NEQ"},
      {"from": 10006, "to": 10007, "rargname": "ARG1", "post": "EQ"},
      {"from": 10007, "to": 10005, "rargname": "ARG1", "post": "NEQ"},
      {"from": 10008, "to": 10002, "rargname": "ARG1", "post": "NEQ"},
      {"from": 10009, "to": 10008, "rargname": "ARG1", "post": "EQ"},
      {"from": 10009, "to": 10010, "rargname": "ARG2", "post": "EQ"},
      {"from": 10010, "to": 10002, "rargname": "ARG1", "post": "NEQ"},
      {"from": 10007, "to": 10002, "rargname": "MOD", "post": "EQ"},
      {"from": 10010, "to": 10008, "rargname": "MOD", "post": "EQ"}
    ]
  }
"""

from pathlib import Path
import json

from delphin.lnk import Lnk
from delphin.dmrs import (
    DMRS,
    Node,
    Link,
    CVARSORT,
)


CODEC_INFO = {
    'representation': 'dmrs',
}

HEADER = '['
JOINER = ','
FOOTER = ']'


def load(source):
    """
    Deserialize a DMRS-JSON file (handle or filename) to DMRS objects

    Args:
        source: filename or file object
    Returns:
        a list of DMRS objects
    """
    if hasattr(source, 'read'):
        data = json.load(source)
    else:
        source = Path(source).expanduser()
        with source.open() as fh:
            data = json.load(fh)
    return [from_dict(d) for d in data]


def loads(s):
    """
    Deserialize a DMRS-JSON string to DMRS objects

    Args:
        s (str): a DMRS-JSON string
    Returns:
        a list of DMRS objects
    """
    data = json.loads(s)
    return [from_dict(d) for d in data]


def dump(ds, destination, properties=True, lnk=True,
         indent=False, encoding='utf-8'):
    """
    Serialize DMRS objects to a DMRS-JSON file.

    Args:
        destination: filename or file object
        ds: iterator of :class:`~delphin.dmrs.DMRS` objects to
            serialize
        properties: if `True`, encode variable properties
        lnk: if `False`, suppress surface alignments and strings
        indent: if `True`, adaptively indent; if `False` or `None`,
            don't indent; if a non-negative integer N, indent N spaces
            per level
        encoding (str): if *destination* is a filename, write to the
            file with the given encoding; otherwise it is ignored
    """
    if indent is False:
        indent = None
    elif indent is True:
        indent = 2
    data = [to_dict(d, properties=properties, lnk=lnk) for d in ds]
    if hasattr(destination, 'write'):
        json.dump(data, destination, indent=indent)
    else:
        destination = Path(destination).expanduser()
        with destination.open('w', encoding=encoding) as fh:
            json.dump(data, fh)


def dumps(ds, properties=True, lnk=True, indent=False):
    """
    Serialize DMRS objects to a DMRS-JSON string.

    Args:
        ds: iterator of :class:`~delphin.dmrs.DMRS` objects to
            serialize
        properties: if `True`, encode variable properties
        lnk: if `False`, suppress surface alignments and strings
        indent: if `True`, adaptively indent; if `False` or `None`,
            don't indent; if a non-negative integer N, indent N spaces
            per level
    Returns:
        a DMRS-JSON-serialization of the DMRS objects
    """
    if indent is False:
        indent = None
    elif indent is True:
        indent = 2
    data = [to_dict(d, properties=properties, lnk=lnk) for d in ds]
    return json.dumps(data, indent=indent)


def decode(s):
    """
    Deserialize a DMRS object from a DMRS-JSON string.
    """
    return from_dict(json.loads(s))


def encode(d, properties=True, lnk=True, indent=False):
    """
    Serialize a DMRS object to a DMRS-JSON string.

    Args:
        d: a DMRS object
        properties (bool): if `False`, suppress variable properties
        lnk: if `False`, suppress surface alignments and strings
        indent (bool, int): if `True` or an integer value, add
            newlines and indentation
    Returns:
        a DMRS-JSON-serialization of the DMRS object
    """
    if indent is False:
        indent = None
    elif indent is True:
        indent = 2
    return json.dumps(to_dict(d, properties=properties, lnk=lnk),
                      indent=indent)


def to_dict(d, properties=True, lnk=True):
    """
    Encode DMRS *d* as a dictionary suitable for JSON serialization.
    """
    # attempt to convert if necessary
    # if not isinstance(d, DMRS):
    #     d = DMRS.from_xmrs(d)

    nodes = []
    for node in d.nodes:
        n = dict(nodeid=node.id,
                 predicate=node.predicate)
        if properties and node.sortinfo:
            n['sortinfo'] = node.sortinfo
        if node.carg is not None:
            n['carg'] = node.carg
        if lnk:
            if node.lnk:
                n['lnk'] = {'from': node.cfrom, 'to': node.cto}
            if node.surface:
                n['surface'] = node.surface
            if node.base:
                n['base'] = node.base
        nodes.append(n)
    links = []
    for link in d.links:
        links.append({
            'from': link.start, 'to': link.end,
            'rargname': link.role, 'post': link.post
        })
    data = dict(nodes=nodes, links=links)
    if d.top is not None:  # could be 0
        data['top'] = d.top
    if d.index:
        data['index'] = d.index
    if lnk:
        if d.lnk:
            data['lnk'] = {'from': d.cfrom, 'to': d.cto}
        if d.surface:
            data['surface'] = d.surface
    if d.identifier is not None:
        data['identifier'] = d.identifier
    return data


def from_dict(d):
    """
    Decode a dictionary, as from :func:`to_dict`, into a DMRS object.
    """
    def _lnk(x):
        return None if x is None else Lnk.charspan(x['from'], x['to'])
    nodes = []
    for node in d.get('nodes', []):
        properties = dict(node.get('sortinfo', {}))  # make a copy
        type = None
        if CVARSORT in properties:
            type = properties.pop(CVARSORT)
        nodes.append(Node(
            node['nodeid'],
            node['predicate'],
            type=type,
            properties=properties,
            carg=node.get('carg'),
            lnk=_lnk(node.get('lnk')),
            surface=node.get('surface'),
            base=node.get('base')))
    links = []
    for link in d.get('links', []):
        links.append(Link(
            link['from'],
            link['to'],
            link.get('rargname'),
            link.get('post')))
    return DMRS(
        top=d.get('top'),
        index=d.get('index'),
        nodes=nodes,
        links=links,
        lnk=_lnk(d.get('lnk')),
        surface=d.get('surface'),
        identifier=d.get('identifier')
    )
