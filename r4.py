#!/usr/bin/env python

# Copyright John Wiseman 2009.

"""
r4 - a wrapper around p4 adding new, custom functionality.

Prerequisites:

* P4 python bindings.  I used the version at
ftp://ftp.perforce.com/perforce/r10.1/bin.tools/p4python.tgz

(The python bindings have their own installation instructions, but
basically you need to first install the Perforce C++ API.)

"""
from __future__ import with_statement

__version__ = '$Id: //depot/users/wiseman/r4/r4.py#27 $ $Change: 17757 $'

import P4
import os
import fnmatch
import sys
import pprint
import itertools

# I usually prefer optparse, but this is a special case where we don't
# care about all the extra stuff optparse does for us since we're not
# exactly parsing arguments to an executable program, but to a command
# in an executable.
import getopt


# --------------------
# Maps command names to our custom implementations.
# --------------------

g_command_table = {}

def def_r4_command(name, commandobj):
    g_command_table[name] = commandobj

def get_r4_command(name):
    return g_command_table.get(name, None)

def all_r4_commands():
    return sorted(g_command_table.keys())


# --------------------
# Build maps that lets us translate between paths in depot syntax,
# client syntax and local syntax, like //depot/users/wiseman ->
# /home/wiseman/work/wiseman and vice versa.
# --------------------

g_cached_depot_to_local_map = None

g_translation_map = None


def add_translation_map(fromm, to, map):
    global g_translation_map
    g_translation_map[fromm, to] = map
    g_translation_map[to, fromm] = map.reverse()

def get_translation_map(fromm, to):
    global g_translation_map
    if not g_translation_map:
        ensure_translation_map()
    return g_translation_map[fromm, to]


# I got the inspiration for this from the "P4::Map class" section of
# <http://www.perforce.com/perforce/conferences/us/2009/Presentations/Knop-AdventuresinScriptingLand-paper.pdf>.
# Just note that he's trying to map from //depot/... to the local
# syntax of the file *on the depot server*, whereas I'm mapping
# between depot syntax, client syntax and local syntax on the *client
# machine*.

def ensure_translation_map(p4=None):
    """If we haven't done so already, builds the following maps for
    translating between different syntaxes:

    depot  <-->  client
    client <-->  local
    depot  <-->  local
    """
    global g_translation_map
    if not g_translation_map:
        g_translation_map = {}

        if not p4:
            p4 = get_p4_connection()

        client_info = p4.run_client('-o')[0]
        client_name = client_info['Client']
        client_root = client_info['Root']
        client_views = client_info['View']
        depot_to_client_map = P4.Map()
        
        depot_to_client_map.insert(client_views)
        add_translation_map('depot', 'client', depot_to_client_map)

        client_to_local_map = P4.Map()
        client_to_local_map.insert('//%s/...' % (client_name,), os.path.join(client_root, '...'))
        add_translation_map('client', 'local', client_to_local_map)

        add_translation_map('depot', 'local', P4.Map.join(depot_to_client_map, client_to_local_map))


def translate_local_to_depot(path):
    return get_translation_map('local', 'client').translate(path)

def translate_depot_to_local(path):
    return get_translation_map('depot', 'local').translate(path)


# --------------------
# .r4ignore and processing ignores.
# --------------------

IGNORE_FILE = '.r4ignore'

g_home_ignore_patterns = None

def ignore_patterns_for(path):
    # Cache the contents of ~/.r4ignore.
    global g_home_ignore_patterns
    if g_home_ignore_patterns is None:
        g_home_ignore_patterns = try_load_ignore_patterns(os.path.join(os.path.expanduser('~'), IGNORE_FILE))
        
    patterns = g_home_ignore_patterns
    patterns += try_load_ignore_patterns(os.path.join(path, IGNORE_FILE))
    return patterns

def try_load_ignore_patterns(path):
    patterns = []
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                patterns = f.readlines()
                # Strip the trailing newline from each line.
                patterns = [p[:-1] for p in patterns]
                patterns = [p for p in patterns if len(p) > 0 and p[0] != '#']
        except IOError:
            # Ignore errors.
            pass
    return patterns
        

def is_ignored(ignore_patterns, filename):
    "Checks whether a filename matches any ignore pattern."
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(filename, pattern):
            return True
    return False


# --------------------
# Process commands
# --------------------

def handle_command(command, args, p4=None):
    # If we have a custom implementation, use it, otherwise fall back
    # to regular p4.
    handler = get_r4_command(command)
    if handler:
        return handler.run_command(command, args, p4=p4)
    else:
        run_standard_p4_command(command, args)

def run_standard_p4_command(command, args):
    """Runs a standard p4 command.  Uses exec, so this will be the
    last function you ever call.  Used to transfer control to stock p4
    for non-custom commands.
    """
    if command:
        args = [command] + args
    os.execvp('p4', ['p4'] + args)

class MissingOrWrongArguments(Exception):
    pass


# --------------------
# Custom commands
# --------------------

# Base class for all custom commands.
class R4Command:
    def __init__(self):
        pass
    def short_description(self):
        raise NotImplementedError
    def long_description(self):
        raise NotImplementedError
    def usage(self):
        raise NotImplementedError
    def run(self, p4, command, args):
        raise NotImplementedError

    def run_command(self, command, args, p4=None):
        try:
            if not p4:
                p4 = get_p4_connection()
            return self.run(p4, command, args)
        except MissingOrWrongArguments:
            self.print_usage(stream=sys.stderr)
            sys.stderr.write('Missing/wrong number of arguments.\n')
        except getopt.GetoptError, e:
            self.print_usage(stream=sys.stderr)
            sys.stderr.write('%s\n' % (e,))
            

    def print_usage(self, stream=sys.stdout):
        # Replace '%prog' in usage text with the name of the program.
        stream.write('Usage: %s\n' % (self.usage().replace('prog', sys.argv[0])))
            

class R4Status(R4Command):
    def short_description(self):
        return 'Print the status of working copy files and directories'

    def usage(self):
        return 'status [ --no-ignore ] [ path ... ]'
    
    def long_description(self):
        return """
    status -- %s

    r4 %s

    Lists all locally modified files under the specified paths (if no
    paths are supplied the current working directory is used).

    The --no-ignore flag forces files that are ignored because they
    matched a pattern in a .r4ignore file to be printed with an 'I'
    prefix.

    The first column in the output is one character wide, and
    indicates the file's status:

      '?' Item is not under version control
      'A' Added
      'D' Deleted
      'M' Modified
      'O' Opened for editing--may be unchanged, branched or integrated
      'I' Ignored (only with --no-ignore)
""" % (self.short_description(), self.usage())

    def run(self, p4, command, args):
        no_ignores = False

        optlist, args = getopt.getopt(args, '', ['no-ignore'])
        for opt, value in optlist:
            if opt == '--no-ignore':
                no_ignores = True

        # Was a path specified or should we just use the current
        # directory?
        if len(args) == 0:
            dirs = ['.']
        else:
            dirs = args

        for dir in dirs:

            # Build a list of files that are in p4 under the directory
            # we're checking.
            info = p4.run('have', os.path.join(dir, '...'))
            have_paths = set([i['path'] for i in info])

            # Build a list of opened files that have been modified
            # under the directory we're checking.
            diff_info = p4.run_diff('-sa', os.path.join(dir, '...'))
            # run_diff returns a list that contains dictionaries
            # interspersed with strings containing diff output.  The
            # dicts have the filenames, so here we extract the
            # filenames from dicts. The 'clientFile' keys gives us a
            # local pathname.
            modified_files = [i['clientFile'] for i in diff_info if isinstance(i, dict)]

            # Build a list of files that have been marked for addition
            # or deletion, but are not yet committed.
            opened_info = p4.run_opened(os.path.join(dir, '...'))

            # opened's output's 'depotFile' is a depot path.
            added_files = [translate_depot_to_local(i['depotFile']) for i in opened_info if i['action'] == 'add']
            deleted_files = [translate_depot_to_local(i['depotFile']) for i in opened_info if i['action'] == 'delete']
            opened_files = [translate_depot_to_local(i['depotFile']) for i in opened_info]

            for dirpath, dirnames, filenames in os.walk(dir, topdown=True):
                # Get rid of the ignored files.
                ignore_patterns = ignore_patterns_for(dirpath)
                if not no_ignores:
                    filenames = [f for f in filenames if not is_ignored(ignore_patterns, f)]

                for dirname in dirnames[:]:
                    if is_ignored(ignore_patterns, dirname):
                        dirnames.remove(dirname)
                        if no_ignores:
                            print 'I %s' % (os.path.normpath(os.path.join(dirpath, dirname)),)
                dirnames.sort()
                # If there are any files marked for delete in this
                # directory, add them to the list of files to print
                # status info for.
                dirpath = os.path.normpath(dirpath)
                for f in deleted_files:
                    if os.path.dirname(f) == os.path.abspath(dirpath):
                        filenames += [os.path.basename(f)]

                # Print the status info for each file in this
                # directory.
                for f in sorted(filenames):
                    full_path = os.path.abspath(os.path.join(dirpath, f))
                    print_path = os.path.normpath(os.path.join(dirpath, f))
                    if no_ignores and is_ignored(ignore_patterns, f):
                        print 'I %s' % (print_path,)
                    elif full_path in added_files:
                        print 'A %s' % (print_path,)
                    elif full_path in deleted_files:
                        print 'D %s' % (print_path,)
                    elif full_path in modified_files:
                        print 'M %s' % (print_path,)
                    elif full_path in opened_files:
                        print 'O %s' % (print_path,)
                    elif not full_path in have_paths:
                        print '? %s' % (print_path,)


class R4Blame(R4Command):
    def short_description(self):
        return 'Show what revision and author last modified each line of a file--TBD'

    def usage(self):
        return 'blame'

    def long_description(self):
        return """
    blame -- %s

    r4 %s
    
    Annotates each line in the given file with information on the
    revision which last modified the line.
    """ % (self.short_description(), self.usage())

    def run(self, p4, command, args):
        print args
        annotate_info = p4.run_annotate('-i', args[0])
        filelog_info = p4.run('filelog', '-i', args[0])
        pprint.pprint(annotate_info)
        pprint.pprint(filelog_info)


class R4Bisect(R4Command):
    def short_description(self):
        return 'Efficiently finds the change that introduced a bug--TBD'

    def usage(self):
        return 'bisect <subcommand> <options>'

    def long_description(self):
        return """
    bisect -- %s

    r4 %s

    An implementation of git's bisect command for Perforce.
    """ % (self.short_description(), self.usage())
    

class R4Grep(R4Command):
    def short_description(self):
        return 'Search across revisions of files for lines matching a pattern'

    def usage(self):
        return 'grep [ -i ] [ -l ] [ -v ] pattern file[revRange]...'

    def long_description(self):
        return """
    grep -- %s

    r4 %s

    Searches the named files for lines containing a match to the given
    pattern.  By default, grep prints the matching lines.

    The pattern can be a Perl-style regular expression.

    If a file is specified without a revision, then all revisions of
    the file are searched.

    Example:

      $ r4 grep ALL Makefile

      //depot/project/Makefile#1: ALL     :=      tools
      //depot/project/Makefile#2: ALL     :=      tools scripts
      //depot/project/Makefile#3: ALL     :=      tools scripts tests
      //depot/project/Makefile#5: ALL     :=      tools scripts tests
      
    You can use revision specifiers and revision ranges to control
    which revisions of a file will be searched.

    Examples:

      r4 grep pattern file#head
      r4 grep pattern file#4
      r4 grep pattern file#12,20
      r4 grep pattern file@release_4

    Note that p4 wildcards can be used, giving the ability to do
    recursive greps.

    Examples:

      r4 grep pattern ./...
      r4 grep pattern ./.../file

    The -i/--ignore-case flag causes the matching to be done while
    ignoring case distinctions.

    The -l/--files-with-matches flag suppresses normal output and
    instead just prints the names of each file from which output would
    normally have been printed.  File names are printed with revision
    specifiers or revision ranges indicating which revisions of the
    file contain matches.

    Example:

      $ r4 grep -l ALL Makefile
      //depot/project/Makefile#1,9
      //depot/project/Makefile#11

    The -v/--invert-match flag inverts the sense of matching, to
    select non-matching lines.
    
    """ % (self.short_description(), self.usage())
    
    def run(self, p4, command, args):
        import re
        # Process options.
        case_sensitive = True
        just_list_filenames = False
        invert_matches = False
        options, args = getopt.getopt(args, 'ilv', ['ignore-case', 'files-with-matches',
                                                    'invert-match'])
        for option, value in options:
            if option in ['-i', '--ignore-case']:
                case_sensitive = False
            elif option in ['-l', '--files-with-matches']:
                just_list_filenames = True
            elif option in ['-v', '--invert-match']:
                invert_matches = True

        if len(args) < 2:
            raise MissingOrWrongArguments('Missing/wrong number of arguments.')
            
        regex = args[0]
        files = args[1:]

        # Build our regex.
        re_flags = 0
        if not case_sensitive:
            re_flags |= re.IGNORECASE
        regexp = re.compile(regex, re_flags)

        got_match = False
        match_ranges = []
        path = None
        
        # Search through files.
        for file in files:
            annotate_info = p4.run_annotate('-a', file)
            # Each element in annotate_info is a dictionary, and there are two types:
            #
            # 1. Info on the file who's data follows. Contains
            #    'depotFile' members and others.
            #
            # 2. Info on a line in the file.  Contains 'upper',
            #    'lower' and 'data' members.
            for line in annotate_info:
                if 'depotFile' in line:
                    # Finish up the previous file, if there was one.
                    if path:
                        if just_list_filenames and got_match:
                            for lower, upper in coalesce_revision_ranges(match_ranges):
                                print '%s%s' % (path, (canonicalize_revision_range(lower, upper)))
                    # Prepare to handle the new file.
                    got_match = False
                    match_ranges = []
                    path = strip_revision_specifiers(line['depotFile'])
                else:
                    re_matches = regexp.search(line['data'])
                    if invert_matches: re_matches = not re_matches
                    if re_matches:
                        if just_list_filenames:
                            got_match = True
                            match_ranges.append((line['lower'], line['upper']))
                        else:
                            revisions = canonicalize_revision_range(line['lower'], line['upper'])
                            sys.stdout.write('%s%s: %s' % (path, revisions, line['data']))
            # Finish up the previous file, if there was one.
            if path:
                if just_list_filenames and got_match:
                    for lower, upper in coalesce_revision_ranges(match_ranges):
                        print '%s%s' % (path, (canonicalize_revision_range(lower, upper)))


def canonicalize_revision_range(lower, upper):
    """Given a revision range, returns a string containing a canonical
    revision specifier for that range.  Collapses "degenerate" ranges
    to a single revision number.
    """
    if upper == lower:
        return '#%s' % (lower,)
    else:
        return '#%s,%s' % (lower, upper)

def strip_revision_specifiers(path):
    """Given a file specification that may contain a revision
    specifier, returns just the file specification without a revision
    specifier.
    """
    at_pos = path.rfind('@')
    if at_pos != -1:
        return path[0:at_pos]
    else:
        hash_pos = path.rfind('#')
        if hash_pos != -1:
            return path[0:hash_pos]
    return path
    
    

class R4Help(R4Command):
    """Custom hooks for 'p4 help ...' so we can display information on
    our custom commands.
    """
    def run(self, p4, command, args):
        # User did "r4 help commands", so we want to list our custom
        # commands too.
        if len(args) == 1 and args[0] == 'commands':
            help_output = p4.run('help', 'commands')
            for h in help_output:
                print h.replace('p4', 'r4')
            
            print '    Custom commands:\n'
            for command in all_r4_commands():
                try:
                    print '\t%-11s %s' % (command, get_r4_command(command).short_description())
                except NotImplementedError:
                    pass
        # User did "r4 help <custom command>" so we want to display
        # the custom command's help text.  "r4 help help" is a special
        # case where we want to default to p4 behavior.
        elif len(args) == 1 and args[0] in all_r4_commands() and args[0] != 'help':
            help_text = get_r4_command(args[0]).long_description()
            print help_text
        else:
            help_output = p4.run('help', *args)
            for h in help_output:
                print h.replace('p4', 'r4')


def get_p4_connection():
    p4 = P4.P4()
    p4.exception_level = p4.RAISE_ERROR
    p4.connect()
    return p4



def coalesce_revision_ranges(ranges):
    """Returns the smallest set of revision ranges that cover the
    ranges passed in.  E.g., ((1, 10), (11, 13)) -> (1, 13)
    """
    # Fuck it, let's just brute force this.
    # Build a bitmap.
    max_r = None
    for l, r in ranges:
        if not max_r or int(r) > max_r:
            max_r = int(r)
    revisions = [False] * (max_r + 1)
    for l, r in ranges:
        for i in range(int(l), int(r) + 1):
            revisions[i] = True

    # Scan the bitmap.
    new_ranges = []
    start_l = None
    pos = 0
    while pos < len(revisions):
        state = revisions[pos]
        if start_l:
            if state == False:
                new_ranges.append((start_l, pos - 1))
                start_l = None
        if not start_l:
            if state == True:
                start_l = pos
        pos += 1
    if start_l:
        new_ranges.append((start_l, pos - 1))
    return new_ranges


# Hook our custom implementations to the command names.

def_r4_command('status', R4Status())
def_r4_command('help', R4Help())
def_r4_command('grep', R4Grep())
def_r4_command('bisect', R4Bisect())
def_r4_command('blame', R4Blame())


if __name__ == '__main__':
    try:
        p4 = get_p4_connection()

        if len(sys.argv) > 1:
            command = sys.argv[1]
            args = sys.argv[2:]
            sys.exit(handle_command(command, args, p4=p4))
        else:
            run_standard_p4_command(None, [])
    except P4.P4Exception, e:
        sys.stderr.write('%s\n' % (e,))
        sys.exit(1)
        
