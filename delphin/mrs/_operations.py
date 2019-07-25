
"""
Operations on MRS structures
"""

from typing import Iterable

from delphin import variable
from delphin import predicate
from delphin import sembase
from delphin import scope
from delphin import mrs
from delphin import util


def is_connected(m: mrs.MRS) -> bool:
    """
    Return `True` if *m* is a fully-connected MRS.

    A connected MRS is one where, when viewed as a graph, all EPs are
    connected to each other via regular (non-scopal) arguments, scopal
    arguments (including qeqs), or label equalities.
    """
    ids = {ep.id for ep in m.rels}
    g = {id: set() for id in ids}
    # first establish links from labels and intrinsic variables to EPs
    for ep in m.rels:
        id, lbl, iv = ep.id, ep.label, ep.iv
        g[id].update((lbl, iv))
        g.setdefault(lbl, set()).add(id)
        if iv:
            g.setdefault(iv, set()).add(id)
    # arguments may link EPs with IVs or labels (or qeq) as targets
    hcmap = {hc.hi: hc.lo for hc in m.hcons}
    for id, roleargs in m.arguments().items():
        for role, value in roleargs:
            value = hcmap.get(value, value)  # resolve qeq if any
            if value in g:
                g[id].add(value)
                g[value].add(id)
    return ids.issubset(util._bfs(g))


def has_intrinsic_variable_property(m: mrs.MRS) -> bool:
    """
    Return `True` if *m* satisfies the intrinsic variable property.

    An MRS has the intrinsic variable property when:

    * Every non-quantifier EP has an argument for the intrinsic role
      (i.e., specifies an `ARG0`)

    * Every intrinsic variable is unique to a non-quantifier EP

    Note that for quantifier EPs, `ARG0` is overloaded to mean "bound
    variable". Each quantifier should have an `ARG0` that is the
    intrinsic variable of exactly one non-quantifier EP, but this
    function does not check for that.
    """
    seen = set()
    for ep in m.rels:
        if not ep.is_quantifier():
            iv = ep.iv
            if iv is None:
                return False  # EP does not have an intrinsic variable
            elif iv in seen:  # intrinsic variable is not unique
                return False
            seen.add(iv)
    return True


def is_well_formed(m: mrs.MRS) -> bool:
    """
    Return `True` if MRS *m* is well-formed.

    A well-formed MRS meets the following criteria:

    - is connected
    - has the intrinsic variable property
    - plausibly scopes

    The final criterion is a heuristic for determining if the MRS
    scopes by checking if handle constraints and scopal arguments have
    any immediate violations (e.g., a scopal argument selecting the
    label of its EP).
    """
    return (is_connected(m)
            and has_intrinsic_variable_property(m)
            and _plausibly_scopes(m))


def _plausibly_scopes(m: mrs.MRS) -> bool:
    scopes = m.scopes()
    hcmap = {hc.hi: hc.lo for hc in m.hcons}
    if m.top not in hcmap:
        return False
    seen = set()
    for id, roleargs in m.arguments(types='h').items():
        for _, handle in roleargs:
            if handle == m[id].label:
                return False
            elif handle in hcmap:
                if (handle in seen
                        or hcmap[handle] in seen
                        or hcmap[handle] not in scopes):
                    return False
                seen.add(hcmap[handle])
            elif handle in scopes and handle in seen:
                return False
            seen.add(handle)
    for hi, lo in hcmap.items():
        if hi not in seen and lo not in scopes:
            return False
    return True


def is_isomorphic(m1: mrs.MRS,
                  m2: mrs.MRS,
                  properties: bool = True) -> bool:
    """
    Return `True` if *m1* and *m2* are isomorphic MRSs.

    Isomorphicity compares the predicates of a semantic structure, the
    morphosemantic properties of their predications (if
    `properties=True`), constant arguments, and the argument structure
    between predications. Non-semantic properties like identifiers and
    surface alignments are ignored.

    Args:
        m1: the left MRS to compare
        m2: the right MRS to compare
        properties: if `True`, ensure variable properties are
            equal for mapped predications
    """
    # loading NetworkX is slow; only do this when is_isomorphic is called
    import networkx as nx

    m1dg = _make_mrs_digraph(m1, nx.DiGraph(), properties)
    m2dg = _make_mrs_digraph(m2, nx.DiGraph(), properties)

    def nem(m1d, m2d):  # node-edge-match
        return m1d.get('sig') == m2d.get('sig')

    return nx.is_isomorphic(m1dg, m2dg, node_match=nem, edge_match=nem)


def _make_mrs_digraph(x, dg, properties):
    for ep in x.rels:
        # optimization: retrieve early to avoid successive lookup
        lbl = ep.label
        iv = ep.iv
        props = x.properties(iv)
        args = ep.args
        carg = ep.carg
        # scope labels (may be targets of arguments or hcons)
        dg.add_edge(lbl, iv, sig='eq-scope')
        # predicate-argument structure
        s = predicate.normalize(ep.predicate)
        if carg is not None:
            s += '({})'.format(carg)
        if ep.is_quantifier():
            iv += '(bound)'  # make sure node id is unique
        elif properties and props:
            proplist = []
            for prop in sorted(props, key=sembase.property_priority):
                val = props[prop]
                proplist.append('{}={}'.format(prop.upper(), val.lower()))
            s += '{' + '|'.join(proplist) + '}'
        dg.add_node(iv, sig=s)
        dg.add_edges_from((iv, args[role], {'sig': role})
                          for role in args if role != mrs.CONSTANT_ROLE)
    # hcons
    dg.add_edges_from((hc.hi, hc.lo, {'sig': hc.relation})
                      for hc in x.hcons)
    # icons
    dg.add_edges_from((ic.left, ic.right, {'sig': ic.relation})
                      for ic in x.icons)
    return dg


def compare_bags(testbag: Iterable[mrs.MRS],
                 goldbag: Iterable[mrs.MRS],
                 properties: bool = True,
                 count_only: bool = True):
    """
    Compare two bags of MRS objects, returning a triple of
    (unique-in-test, shared, unique-in-gold).

    Args:
        testbag: An iterable of MRS objects to test
        goldbag: An iterable of MRS objects to compare against
        properties: if `True`, ensure variable properties are
            equal for mapped predications
        count_only: If `True`, the returned triple will only have the
            counts of each; if `False`, a list of MRS objects will be
            returned for each (using the ones from *testbag* for the
            shared set)
    Returns:
        A triple of (unique-in-test, shared, unique-in-gold), where
        each of the three items is an integer count if the
        *count_only* parameter is `True`, or a list of MRS objects
        otherwise.
    """
    gold_remaining = list(goldbag)
    test_unique = []
    shared = []
    for test in testbag:
        gold_match = None
        for gold in gold_remaining:
            if is_isomorphic(test, gold, properties=properties):
                gold_match = gold
                break
        if gold_match is not None:
            gold_remaining.remove(gold_match)
            shared.append(test)
        else:
            test_unique.append(test)
    if count_only:
        return (len(test_unique), len(shared), len(gold_remaining))
    else:
        return (test_unique, shared, gold_remaining)


def from_dmrs(d):
    """
    Create an MRS by converting from DMRS *d*.

    Args:
        d: the input DMRS
    Returns:
        MRS
    Raises:
        MRSError when conversion fails.
    """
    qeq = mrs.HCons.qeq
    vfac = variable.VariableFactory(starting_vid=0)

    # do d.scopes() once to avoid potential errors if label generation
    # is ever non-deterministic
    top, scopes = d.scopes()
    ns_args = d.arguments(types='xeipu')
    sc_args = d.scopal_arguments(scopes=scopes)

    id_to_lbl, id_to_iv = _dmrs_build_maps(d, scopes, vfac)
    # for index see https://github.com/delph-in/pydelphin/issues/214
    index = None if not d.index else id_to_iv[d.index]

    hcons = [qeq(top, id_to_lbl[d.top])]
    icons = None  # see https://github.com/delph-in/pydelphin/issues/220

    rels = []
    for node in d.nodes:
        id = node.id
        label = id_to_lbl[id]
        args = {mrs.INTRINSIC_ROLE: id_to_iv[id]}

        for role, tgt in ns_args[id]:
            args[role] = id_to_iv[tgt]

        for role, relation, tgt_label in sc_args[id]:
            if relation == scope.LHEQ:
                args[role] = tgt_label
            elif relation == scope.QEQ:
                hole = vfac.new(variable.HANDLE)
                args[role] = hole
                hcons.append(qeq(hole, tgt_label))
            else:
                raise mrs.MRSError('DMRS-to-MRS: invalid scope constraint')

        if node.carg is not None:
            args[mrs.CONSTANT_ROLE] = node.carg

        if d.is_quantifier(id) and mrs.BODY_ROLE not in args:
            args[mrs.BODY_ROLE] = vfac.new(variable.HANDLE)

        rels.append(
            mrs.EP(node.predicate,
                   label,
                   args=args,
                   lnk=node.lnk,
                   surface=node.surface,
                   base=node.base))

    return mrs.MRS(
        top=top,
        index=index,
        rels=rels,
        hcons=hcons,
        icons=icons,
        variables=vfac.store,
        lnk=d.lnk,
        surface=d.surface,
        identifier=d.identifier)


def _dmrs_build_maps(d, scopes, vfac):
    id_to_lbl = {}
    for label, nodes in scopes.items():
        vfac.index[variable.id(label)] = label  # prevent vid reuse
        id_to_lbl.update((node.id, label) for node in nodes)

    id_to_iv = {}
    for node, q in d.quantification_pairs():
        if node is not None:
            iv = vfac.new(node.type, node.properties)
            id_to_iv[node.id] = iv
            if q is not None:
                id_to_iv[q.id] = iv
        else:
            pass  # ignore unpaired quantifiers (ill-formed)

    return id_to_lbl, id_to_iv
