#!/usr/bin/python

import sys
import random 
import psycopg2
import shutil
import subprocess32
import argparse
import json
import os
import shlex
import lockfile
import signal
import atexit
from os.path import basename, dirname, join, abspath
import threading

import signal

class Command(object):
    def __init__(self, cmd, cwd, envv): #  **popen_kwargs):
        self.cmd = cmd
        self.cwd = cwd
        self.envv = envv
        self.process = None
        self.output = "no output"
#        self.popen_kwargs = popen_kwargs

    def run(self, timeout):
        def target():
#            print "Thread started"
            self.process = subprocess32.Popen(self.cmd.split(), cwd=self.cwd, env=self.envv, \
                                                stdout=subprocess32.PIPE, \
                                                stderr=subprocess32.PIPE, \
                                                preexec_fn=os.setsid, **self.popen_kwargs)
            self.output = self.process.communicate()
#            print 'Thread finished'
        thread = threading.Thread(target=target)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            if debugging:
                print 'Terminating process cmd=[%s] due to timeout' % self.cmd
            self.process.terminate()
            os.killpg(self.process.pid, signal.SIGTERM) 
            self.process.kill()
            print "terminated"
            thread.join(1)
            self.returncode = -9
        else:
            self.returncode = self.process.returncode

project = None
# this is how much code we add to top of any file with main fn in it
NUM_LINES_MAIN_INSTR = 5
debugging = False

def get_conn():
    conn = psycopg2.connect(database=db, user=db_user, password=db_password)
    return conn;


def read_i2s(tablename):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select * from %s;" % tablename)
    i2s = {}
    for row in cur:
        i2s[int(row[0])] = row[1]
    return i2s


def next_bug():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select * from next_bug();")
    bug = cur.fetchone()
    # need to do all three of these in order for the writes to db to actually happen
    cur.close()
    conn.commit()
    conn.close()
    return bug

def next_bug_random():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM bug WHERE inj=false OFFSET floor(random() * (SELECT COUNT(*) FROM bug WHERE inj=false) ) LIMIT 1;")
#    cur.execute("select bug_id from bug,dua where (bug.dua_id=dua.dua_id) and (dua.max_liveness=0) and (dua.max_tcn=0);")
#    bugid = cur.fetchone()[0]
#    cur.execute("select * from bug where bug_id=%d" % bugid);
    bug = cur.fetchone()
#    cur.execute("UPDATE bug SET inj=true WHERE bug_id=%d;" % bugid)
    cur.execute("UPDATE bug SET inj=true WHERE bug_id={};".format(bug[0]))
    # need to do all three of these in order for the writes to db to actually happen
    cur.close()
    conn.commit()
    conn.close()
    return bug



def get_bug(bug_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select * from bug where bug_id=%d;" % bug_id)
    bug = cur.fetchone()
    # need to do all three of these in order for the writes to db to actually happen
    cur.close()
    conn.commit()
    conn.close()
    return (bug[1], bug[2])
    


def remaining_inj():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select * from bug where inj=false;")
    return cur.rowcount


def ptr_to_set(ptr, inputfile_id):
    if ptr == 0: return []
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("select * from unique_taint_set where ptr = " + (str(ptr)) + " and inputfile_id = " + str(inputfile_id) + ";")
    (x, file_offsets, ret_inputfile_id) = cur.fetchone()
    assert (x == ptr and inputfile_id == ret_inputfile_id)
    return file_offsets 


class Dua:

    # initialize dua obtaining all info from db
    def __init__(self, dua_id, sourcefile, inputfile, lval):
        self.dua_id = dua_id
        self.sourcefile = sourcefile
        self.inputfile = inputfile
        self.lval = lval
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("select * from dua where dua_id=%d" % dua_id)
        (x, self.filename_id, self.line, self.lval_id, self.insertionpoint,  \
             self.file_offsets, self.lval_taint, self.inputfile_id, self.max_tcn, \
             self.max_card, self.max_liveness, self.dua_icount, self.dua_scount, self.instr) \
             = cur.fetchone()
        self.instr = int(self.instr)
        # obtain actual taint label sets from db
        n = len(self.lval_taint)
        for i in range(n):
            ptr = self.lval_taint[i]
            self.lval_taint[i] = ptr_to_set(ptr, self.inputfile_id)
        assert(x==dua_id)
        self.filename = self.sourcefile[self.filename_id] 
        self.lval = self.lval[self.lval_id]
        self.inputfile = self.inputfile[self.inputfile_id]

    def as_array(self):
        return [self.dua_id, self.filename, self.line, self.lval, \
            self.insertionpoint, self.file_offsets, self.lval_taint, \
            self.inputfile, self.max_tcn, self.max_card, self.max_liveness, \
            self.dua_icount, self.dua_scount]

    def __str__(self):
        return "(" + (",".join([str(e) for e in self.as_array()])) + ")"


class Atp:

    # initialize atp obtaining all info from db
    def __init__(self, atp_id, sourcefile, inputfile, atptype):
        self.atp_id = atp_id
        self.sourcefile = sourcefile
        self.inputfile = inputfile
        self.atptype = atptype
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("select * from atp where atp_id=%d" % atp_id)
        (x, self.filename_id, self.line, self.typ_id, self.inputfile_id, \
             self.atp_icount, self.atp_scount) \
             = cur.fetchone()
        assert (x==atp_id)
        self.filename = self.sourcefile[self.filename_id]
        self.inputfile = self.inputfile[self.inputfile_id]
        self.typ = self.atptype[self.typ_id]
    
    def as_array(self):
        return [self.atp_id, self.filename, self.line, self.typ, self.inputfile, \
                    self.atp_icount, self.atp_scount]

    def __str__(self):
        return "(" + (",".join([str(e) for e in self.as_array()])) + ")"


# p =  "/a/b/c/d"
# fn = "/a/b/c/d/e/f/g"
# returns "e/f/g"
# so, the end part of fn after the common prefix p (minus leading '/')
# note that if p isnt a prefix of fn then the assert will fail
def filename_suff(p, fn):
    n = fn.find(p)
    assert(n==0)
    l = len(p)
    suff = fn[l:]
    while suff[0] == '/':
        suff = suff[1:]
    return suff

def run_cmd(cmd, cw_dir, envv, timeout, **kwargs):
    p = Command(cmd, cw_dir, envv, **kwargs)
    p.run(timeout)
#    p = subprocess32.Popen(cmd.split(), cwd=cw_dir, env=envv, stdout=subprocess32.PIPE, stderr=subprocess32.PIPE)
    output = p.output  
    exitcode = p.returncode
    if debugging:
        print "run_cmd(" + cmd + ")"
        print "exitcode = " + str(exitcode)
        for line in output:
            print "output = [" + line + "]"
    return (exitcode, output)

def run_cmd_nto(cmd, cw_dir, envv):
    return run_cmd(cmd, cw_dir, envv, 1000000)

def make_safe_copy(fn):
    shutil.copyfile(fn, fn + ".sav")

def revert_to_safe_copy(fn):
    shutil.copyfile(fn + ".sav", fn)


def inject_bug_part_into_src(bug_id, suff, offset):
    global query_build
    global bugs_build
    global lavatool
    global lavadb
    filename_bug_part = bugs_build + "/" + suff
#    make_safe_copy(filename_bug_part)
    cmd = lava_tool + ' -action=inject -bug-list=\"' + str(bug_id) \
        + '\" -lava-db=' + lavadb + ' -p ' + bugs_build \
        + ' -main_instr_correction=' + (str(offset)) \
        + ' ' + filename_bug_part \
        + ' ' + '-project-file=' + project_file
    return run_cmd_nto(cmd, None, None)

def instrument_main(suff):
    global query_build
    global bugs_build
    global lavatool
    global lavadb
    filename_bug_part = bugs_build + "/" + suff
    cmd = lava_tool + ' -action=main -bug-list=\"\"' \
        + ' -lava-db=' + lavadb + ' -p ' + bugs_build \
        + ' ' + filename_bug_part \
        + ' ' + '-project-file=' + project_file
    run_cmd_nto(cmd, None, None)

def add_build_row(bugs, compile_succ):
    conn = get_conn()
    cur = conn.cursor()
    # NB: ignoring binpath for now
    sql = "INSERT into build (bugs,compile) VALUES (ARRAY" + (str(bugs)) + "," + (str(compile_succ)) + ") RETURNING build_id;"
    print sql    
    cur.execute(sql)
    build_id = cur.fetchone()[0]
    # need to do all three of these in order for the writes to db to actually happen
    cur.close()
    conn.commit()
    conn.close()
    return build_id


def get_suffix(fn):
    split = basename(fn).split(".")
    if len(split) == 1:
        return ""
    else:
        return "." + split[-1]

# fuzz_offsets is a list of tainted byte offsets within file filename.
# replace those bytes with random in a new file named new_filename
def mutfile(filename, lval_taint, new_filename):
    # collect set of tainted offsets in file.
    fuzz_offsets = set(sum(lval_taint, []))
    file_bytes = bytearray(open(filename).read())

    # change first 4 bytes to "lava"
    for (i, offset) in zip(range(4), fuzz_offsets):
        print "i=%d offset=%d len(file_bytes)=%d" % (i,offset,len(file_bytes))
        file_bytes[offset] = "lava"[i]
    open(new_filename, "w").write(file_bytes)

# here's how to run the built program
def run_prog(install_dir, input_file, timeout):
    cmd = project['command'].format(install_dir=install_dir,input_file=input_file)
    print cmd
    envv = project['env'] if 'env' in project else {}
    lib_path = project['library_path'].format(install_dir=install_dir)
    envv["LD_LIBRARY_PATH"] = join(install_dir, lib_path)
    return run_cmd(cmd, install_dir, envv, timeout)

import string

def printable(text):
    import string
    # Get the difference of all ASCII characters from the set of printable characters
    nonprintable = set([chr(i) for i in range(256)]).difference(string.printable)
    return ''.join([ '.' if (c in nonprintable)  else c for c in text])


def add_run_row(build_id, fuzz, exitcode, lines, success):
    lines = lines.translate(None, '\'\"')
    lines = printable(lines[0:1024])
    conn = get_conn()
    cur = conn.cursor()
    # NB: ignoring binpath for now
    sql = "INSERT into run (build_id, fuzz, exitcode, output_lines, success) VALUES (" + (str(build_id)) + "," + (str(fuzz)) + "," + (str(exitcode)) + ",\'" + lines + "\'," + (str(success)) + ");"
    print sql    
    cur.execute(sql)
    # need to do all three of these in order for the writes to db to actually happen
    cur.close()
    conn.commit()
    conn.close()



if __name__ == "__main__":    

    next_bug_db = False
    parser = argparse.ArgumentParser(description='Inject and test LAVA bugs.')
    parser.add_argument('project', type=argparse.FileType('r'),
            help = 'JSON project file')
    parser.add_argument('-b', '--bugid', action="store", default=-1,
            help = 'Bug id (otherwise, highest scored will be chosen)')
    parser.add_argument('-r', '--randomize', action='store_true', default = False,
            help = 'Choose the next bug randomly rather than by score')
    args = parser.parse_args()
    project = json.load(args.project)
    project_file = args.project.name

    # Set up our globals now that we have a project

    db_host = project['dbhost']
    db = project['db']
    db_user = "postgres"
    db_password = "postgrespostgres"

    timeout = project['timeout']

    sourcefile = {}
    inputfile = {}
    lval = {}
    atptype = {}

    # This is top-level directory for our LAVA stuff.
    top_dir = join(project['directory'], project['name'])
    lava_dir = dirname(dirname(abspath(sys.argv[0])))
    lava_tool = join(lava_dir, 'src_clang', 'build', 'lavaTool')

    # This should be {{directory}}/{{name}}/bugs
    bugs_top_dir = join(top_dir, 'bugs')
    try:
        os.makedirs(bugs_top_dir)
    except: pass

    # This is where we're going to do our injection. We need to make sure it's
    # not being used by another inject.py.
    bugs_parent = ""
    candidate = 0
    bugs_lock = None
    while bugs_parent == "":
        candidate_path = join(bugs_top_dir, str(candidate))
        lock = lockfile.LockFile(candidate_path)
        try:
            lock.acquire(timeout=-1)
            bugs_parent = join(candidate_path)
            bugs_lock = lock
        except lockfile.AlreadyLocked:
            candidate += 1

    print "Using dir", bugs_parent

    atexit.register(bugs_lock.release)
    for sig in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(sig, lambda s, f: sys.exit(0))

    try:
        os.mkdir(bugs_parent)
    except: pass

    if 'source_root' in project:
        source_root = project['source_root']
    else:
        tar_files = subprocess32.check_output(['tar', 'tf', project['tarfile']], stderr=sys.stderr)
        source_root = tar_files.splitlines()[0].split(os.path.sep)[0]

    queries_build = join(top_dir, source_root)
    bugs_build = join(bugs_parent, source_root)
    bugs_install = join(bugs_build, 'lava-install')
    # Make sure directories and btrace is ready for bug injection.
    def run(args, **kwargs):
        print "run(", args, ")"
        if isinstance(args, basestring):
            args = shlex.split(args)
        subprocess32.check_call(args, cwd=bugs_build,
                stdout=sys.stdout, stderr=sys.stderr, **kwargs)
    def commits():
        return subprocess32.check_output(
                shlex.split("git log --pretty=format:%s"),
                cwd=bugs_build).splitlines()

    if not os.path.exists(bugs_build):
        subprocess32.check_call(['tar', 'xf', project['tarfile'],
            '-C', bugs_parent], stderr=sys.stderr)
    if not os.path.exists(join(bugs_build, '.git')):
        run("git init")
        run("git add -A .")
        run(['git', 'commit', '-m', 'Unmodified source.'])
    if not os.path.exists(join(bugs_build, 'btrace.log')):
        run(shlex.split(project['configure']) + ['--prefix=' + bugs_install])
        run([join(lava_dir, 'btrace', 'sw-btrace')] + shlex.split(project['make']))

    lavadb = join(top_dir, 'lavadb')

    main_files = set(project['main_file'])

    if not os.path.exists(join(bugs_build, 'compile_commands.json')):
        run([join(lava_dir, 'btrace', 'sw-btrace-to-compiledb'),
                '/home/moyix/git/llvm/Debug+Asserts/lib/clang/3.6.1/include'])
        # also insert instr for main() fn in all files that need it
        run("git add compile_commands.json")
        run(['git', 'commit', '-m', 'Add compile_commands.json.'])

    if 'Add autogenerated files.' not in commits():
        run(project['make'])
        run("find .  -name '*.[ch]' -exec git add '{}' \;")
        run(['git', 'commit', '-m', 'Add autogenerated files.'])

    if 'Instrument main().' not in commits():
        print "Instrumenting main fn by running lavatool on %d files\n" % (len(main_files))
        for f in main_files:
            print "injecting lava_set and lava_get code into [%s]" % f
            instrument_main(f)
            run(['git', 'add', f])
        run(['git', 'commit', '-m', 'Instrument main().'])

    if not os.path.exists(bugs_install):
        run(project['install'], shell=True)

    # Now start picking the bug and injecting
    if args.bugid != -1:
        bug_id = int(args.bugid)
        score = 0
        (dua_id, atp_id) = get_bug(bug_id)
    elif args.randomize:
        print "Remaining to inject:", remaining_inj()
        print "Using strategy: random"
        (bug_id, dua_id, atp_id, inj) = next_bug_random()
        next_bug_db = True
    else:
        # no args -- get next bug from postgres
        print "Remaining to inject:", remaining_inj()
        print "Using strategy: score"
        (score, bug_id, dua_id, atp_id) = next_bug()
        next_bug_db = True

    sourcefile = read_i2s("sourcefile")
    inputfile = read_i2s("inputfile")
    lval = read_i2s("lval")
    atptype = read_i2s("atptype")

    print "------------\n"
    print "SELECTED BUG: " + str(bug_id)
    if not args.randomize: print "   score=%d " % score
    print "   (%d,%d)" % (dua_id, atp_id)

    dua = Dua(dua_id, sourcefile, inputfile, lval)
    atp = Atp(atp_id, sourcefile, inputfile, atptype)

    print "DUA:"
    print "   " + str(dua)
    print "ATP:"
    print "   " + str(atp)


    print "max_tcn=%d  max_liveness=%d" % (dua.max_liveness, dua.max_tcn)

    # cleanup
    print "------------\n"
    print "CLEAN UP SRC"
    run_cmd_nto("/usr/bin/git checkout -f master", bugs_build, None)
    run_cmd_nto("/usr/bin/git checkout -f", bugs_build, None)


    print "------------\n"
    print "INJECTING BUGS INTO SOURCE"
    print "inserting code into dua file %s" % dua.filename
    offset = 0
    if dua.filename in main_files:
        offset = NUM_LINES_MAIN_INSTR
    (exitcode, output) = inject_bug_part_into_src(bug_id, dua.filename, offset)
    if (exitcode & 0x4):
        print "... successfully inserted dua siphon"
    else:
        print "... FAIL"
        assert (exitcode & 0x4)
    if dua.filename == atp.filename:
        print "atp is in dua file..."
        if (exitcode & 0x8):
            print "... atp successfully inserted as well"
        else:
            assert (exitcode & 0x8)
    else:
        print "inserting atp dua use into %s" % atp.filename
        offset = 0
        if atp.filename in main_files:
            offset = NUM_LINES_MAIN_INSTR
        (exitcode, output) = inject_bug_part_into_src(bug_id, atp.filename, offset)
        if (exitcode & 0x8):
            print "... success"
        else:
            print "... FAIL"
            assert (exitcode & 0x8)


    # ugh -- with tshark if you *dont* do this, your bug-inj source may not build, sadly
    # it looks like their makefile doesn't understand its own dependencies, in fact
    if ('makeclean' in project) and (project['makeclean']):
        run_cmd_nto("make clean", bugs_build, None)
#        (rv, outp) = run_cmd_nto(project['make'] , bugs_build, None)

        
    # compile
    print "------------\n"
    print "ATTEMPTING BUILD OF INJECTED BUG"
    print "build_dir = " + bugs_build
    (rv, outp) = run_cmd_nto(project['make'], bugs_build, None)
    build = False
    if rv!=0:
        # build failed
        print outp
        print "build failed"    
        sys.exit(1)
    else:
        # build success
        build = True
        print "build succeeded"
        (rv, outp) = run_cmd_nto("make install", bugs_build, None)
        # really how can this fail if build succeeds?
        assert (rv == 0)
        print "make install succeeded"

    # add a row to the build table in the db    
    if next_bug_db:
        build_id = add_build_row([bug_id], build)
        print "build_id = %d" % build_id
    if build:
        try:
            # build succeeded -- testing
            print "------------\n"
            # first, try the original file
            print "TESTING -- ORIG INPUT"
            orig_input = join(top_dir, 'inputs', dua.inputfile)
            print orig_input
            (rv, outp) = run_prog(bugs_install, orig_input, timeout)
            print "retval = %d" % rv
            print "output:"
            lines = outp[0] + " ; " + outp[1]
            print lines
            if next_bug_db:
                add_run_row(build_id, False, rv, lines, True)
            print "SUCCESS"
            # second, fuzz it with the magic value
            print "TESTING -- FUZZED INPUT"
            suff = get_suffix(orig_input)
            pref = orig_input[:-len(suff)] if suff != "" else orig_input
            fuzzed_input = "{}-fuzzed-{}{}".format(pref, bug_id, suff)
            print "fuzzed = [%s]" % fuzzed_input
            mutfile(orig_input, dua.lval_taint, fuzzed_input)
            (rv, outp) = run_prog(bugs_install, fuzzed_input, timeout)
            print "retval = %d" % rv
#            print "output:"
#            lines = outp[0] + " ; " + outp[1]
#            print lines
            if next_bug_db:        
                add_run_row(build_id, True, rv, lines, True)
            print "TESTING COMPLETE"

            run(['git', 'checkout', '-b', str(bug_id)])
            run(['git', 'commit', '-am', str(bug_id)])
            # NB: at the end of testing, the fuzzed input is still in place
            # if you want to try it 
        except:
            print "TESTING FAIL"
            if next_bug_db:
                add_run_row(build_id, False, 1, "", True)
            raise




    # cleanup
#    print "------------\n"
#    print "CLEAN UP SRC"
#    run_cmd("/usr/bin/git checkout -f", bugs_build, None)
#    revert_to_safe_copy(bugs_build + "/" + dua.filename)
#    revert_to_safe_copy(bugs_build + "/" + atp.filename)
