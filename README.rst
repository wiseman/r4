| Copyright 2009 `John Wiseman`_
| Covered by the MIT License, see `LICENSE.txt`_.

==
r4
==

``r4`` is a wrapper around the Perforce command-line tool, ``p4``,
that adds extra functionality.  You can use ``r4`` in the same way you
use ``p4``, except there are some new commands available.


------------
New commands
------------

grep
----

 r4 grep [ -i ] [ -l ] [ -v ] pattern file[revRange]...

Searches the named files for lines containing a match to the given
pattern.  By default, grep prints the matching lines.

The pattern can be a Perl-style regular expression.

If a file is specified without a revision, then all revisions of the
file are searched.

Example::

 $ r4 grep ALL Makefile
 
 //depot/project/Makefile#1: ALL     :=      tools
 //depot/project/Makefile#2: ALL     :=      tools scripts
 //depot/project/Makefile#3: ALL     :=      tools scripts tests
 //depot/project/Makefile#5: ALL     :=      tools scripts tests
      
You can use revision specifiers and revision ranges to control which
revisions of a file will be searched.

Examples::

 r4 grep pattern file#head
 r4 grep pattern file#4
 r4 grep pattern file#12,20
 r4 grep pattern file@release_4

Note that p4 wildcards can be used, giving the ability to do recursive greps.

Examples::

 r4 grep pattern ./...
 r4 grep pattern ./.../file

The ``-i``/``--ignore-case`` flag causes the matching to be done while
ignoring case distinctions.

The ``-l``/``--files-with-matches`` flag suppresses normal output and
instead just prints the names of each file from which output would
normally have been printed.  File names are printed with revision
specifiers or revision ranges indicating which revisions of the file
contain matches.

Example::

  $ r4 grep -l ALL Makefile
  //depot/project/Makefile#1,9
  //depot/project/Makefile#11

The ``-v``/``--invert-match`` flag inverts the sense of matching, to
select non-matching lines.


status
------


--------
Examples
--------

----
Bugs
----
 

