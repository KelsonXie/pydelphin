# PyDelphin &mdash; Python libraries for DELPH-IN data

| [master](https://github.com/delph-in/pydelphin/tree/master) branch | [develop](https://github.com/delph-in/pydelphin/tree/develop) branch | [documentation](https://pydelphin.readthedocs.io/) |
| ------ | ------ | ------ |
| [![Build Status](https://travis-ci.org/delph-in/pydelphin.svg?branch=master)](https://travis-ci.org/delph-in/pydelphin) | [![Build Status](https://travis-ci.org/delph-in/pydelphin.svg?branch=develop)](https://travis-ci.org/delph-in/pydelphin) | [![Documentation Status](https://readthedocs.org/projects/pydelphin/badge/?version=latest)](https://pydelphin.readthedocs.io/en/latest/?badge=latest) |

[DELPH-IN](http://delph-in.net) is an international consortium of
researchers committed to producing precise, high-quality language
processing tools and resources, primarily in the
[HPSG](http://hpsg.stanford.edu/) syntactic and
[MRS](http://moin.delph-in.net/RmrsTop) semantic frameworks, and
PyDelphin is a suite of Python libraries for processing data and
interacting with tools in the DELPH-IN ecosystem. PyDelphin's goal is
to lower the barriers to making use of DELPH-IN resources to help
users quickly build applications or perform experiments, and it has
been successfully used for research into machine translation (e.g.,
[Goodman, 2018][]), sentence chunking ([Muszyńska, 2016][]),
neural semantic parsing ([Buys & Blunsom, 2017][]), and more.

[Goodman, 2018]: https://goodmami.org/static/goodman-dissertation.pdf
[Muszyńska, 2016]: http://www.aclweb.org/anthology/P/P16/P16-3014.pdf
[Buys & Blunsom,  2017]: http://www.aclweb.org/anthology/P/P17/P17-1112.pdf

Documentation, including tutorials and an API reference, is available here:
http://pydelphin.readthedocs.io/

New to PyDelphin? Want to see examples? Try the
[walkthrough](https://pydelphin.readthedocs.io/en/latest/tutorials/walkthrough.html).

## Installation and Upgrading

Get the latest release of PyDelphin from [PyPI][]:

```bash
$ pip install pydelphin
```

[PyPI]: https://pypi.python.org/pypi/pyDelphin

PyDelphin is tested to work with [Python 3](http://python.org/download/)
(3.4+) and Python 2.7. Optional requirements include:
  - [NetworkX](http://networkx.github.io/) for MRS isomorphism
    checking
  - [requests](http://requests.readthedocs.io/en/master/) for the
    REST client
  - [Pygments](http://pygments.org/) for TDL and SimpleMRS syntax
    highlighting
  - [Penman](https://github.com/goodmami/penman) for PENMAN
    serialization of DMRS and EDS
  - [tikz-dependency](https://www.ctan.org/pkg/tikz-dependency), while
    not a Python requirement, is needed for compiling LaTeX documents
    using exported DMRSs

The latest development version of PyDelphin can be retrieved via git:

```bash
$ git clone https://github.com/delph-in/pydelphin.git
```

API changes in new versions are documented in the
[CHANGELOG](CHANGELOG.md), but for any unexpected changes please
[file an issue](https://github.com/delph-in/pydelphin/issues). Also note
that the upcoming
[v1.0.0](https://github.com/delph-in/pydelphin/milestone/12) version will
remove Python 2.7 support and numerous deprecated features.

## Sub-packages

The following packages/modules are available:

- `derivation`: [Derivation trees](http://moin.delph-in.net/ItsdbDerivations)
- `itsdb`: [incr tsdb()] profiles
- `tsql`: TSQL testsuite queries
- `mrs`: [Minimal Recursion Semantics](http://moin.delph-in.net/MrsRfc)
- `tdl`: [Type-Description Language](http://moin.delph-in.net/TdlRfc)
- `tfs`: Typed-Feature Structures
- `tokens`: Token lattices
- `repp`: [Regular-Expression PreProcessor](http://moin.delph-in.net/ReppTop)
- `extra.highlight`: [Pygments](http://pygments.org/)-based syntax
  highlighting (currently just for TDL and SimpleMRS)
- `extra.latex`: Formatting for LaTeX (just DMRS)
- `interfaces.ace`: Python wrapper for common tasks using
  [ACE](http://sweaglesw.org/linguistics/ace/)
- `interfaces.rest`: Client for the RESTful web
  [API](http://moin.delph-in.net/ErgApi)

## Other Information

### Contributors

PyDelphin is developed and maintained by several contributors:

- [Michael Wayne Goodman](https://github.com/goodmami/) (primary author)
- [T.J. Trimble](https://github.com/dantiston/) (packaging, derivations, ACE)
- [Guy Emerson](https://github.com/guyemerson/) (MRS)
- [Alex Kuhnle](https://github.com/AlexKuhnle/) (MRS, ACE)
- [Francis Bond](https://github.com/fcbond/) (LaTeX export)
- [Angie McMillan-Major](https://github.com/mcmillanmajora/) (maintainer)

### Related Software

* Parser/Generators (chronological order)
  - LKB: http://moin.delph-in.net/LkbTop
  - PET: http://moin.delph-in.net/PetTop
  - ACE: http://sweaglesw.org/linguistics/ace/
  - agree: http://moin.delph-in.net/AgreeTop
* Grammar profiling, testing, and analysis
  - \[incr tsdb()\]: http://www.delph-in.net/itsdb/
  - gDelta: https://github.com/ned2/gdelta
  - Typediff: https://github.com/ned2/typediff
  - gTest: https://github.com/goodmami/gtest
* Software libraries and repositories
  - LOGON: http://moin.delph-in.net/LogonTop
  - Ruby-DELPH-IN: https://github.com/wpm/Ruby-DELPH-IN
  - pydmrs: https://github.com/delph-in/pydmrs
* Also see (may have overlap with the above):
  - http://moin.delph-in.net/ToolsTop
  - http://moin.delph-in.net/DelphinApplications

### Spelling

Earlier versions of PyDelphin were spelled "pyDelphin" with a
lower-case "p" and this form is used in several publications. The
current recommended spelling has an upper-case "P".
