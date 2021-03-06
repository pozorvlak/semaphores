#!/usr/bin/env python

"""This module is part of Swampy, a suite of programs available from
allendowney.com/swampy.

Copyright 2011 Allen B. Downey
Distributed under the GNU General Public License at gnu.org/licenses/gpl.html.
"""

from collections import ChainMap
from dataclasses import dataclass
import os
import copy
import random
import re
import sys
import string
import time

# the following definitions can be accessed in the simulator

current_thread = None


def noop(*args):
    """A handy function that does nothing."""


def balk():
    """Jumps to the top of the column."""
    current_thread.balk()


class Semaphore:
    """Represents a semaphore in the simulator.

    Maintains a random queue.
    """

    def __init__(self, n=0):
        self.n = n
        self.queue = []

    def __str__(self):
        return str(self.n)

    def wait(self):
        self.n -= 1
        if self.n < 0:
            self.block()
        return self.n

    def block(self):
        thread = current_thread
        thread.enqueue()
        self.queue.append(thread)

    def signal(self, n=1):
        for i in range(n):
            self.n += 1
            if self.queue:
                self.unblock()

    def unblock(self):
        """Chooses a random thread and unblocks it."""
        thread = random.choice(self.queue)
        self.queue.remove(thread)
        thread.dequeue()
        thread.next_loop()


class FifoSemaphore(Semaphore):
    """Semaphore that implements a FIFO queue."""

    def unblock(self):
        """Chooses the first thread and unblocks it."""
        thread = self.queue.pop(0)
        thread.dequeue()
        thread.next_loop()


class Lightswitch:
    """Encapsulates the lightswitch pattern."""

    def __init__(self):
        self.counter = 0
        self.mutex = Semaphore(1)

    def lock(self, semaphore):
        self.mutex.wait()
        self.counter += 1
        if self.counter == 1:
            semaphore.wait()
        self.mutex.signal()

    def unlock(self, semaphore):
        self.mutex.wait()
        self.counter -= 1
        if self.counter == 0:
            semaphore.signal()
        self.mutex.signal()


class Barrier:
    """Barrier class from section 3.7.7 - don't use for earlier exercises!"""
    def __init__(self, n):
        self.n = n
        self.count = 0
        self.mutex = Semaphore(1)
        self.turnstile = Semaphore(0)
        self.turnstile2 = Semaphore(0)

    def phase1(self):
        self.mutex.wait()
        self.count += 1
        if self.count == self.n :
            self.turnstile.signal(self.n)
        self.mutex.signal()
        self.turnstile.wait()

    def phase2(self):
        self.mutex.wait()
        self.count -= 1
        if self.count == 0:
            self.turnstile2.signal(self.n)
        self.mutex.signal()
        self.turnstile2.wait()

    def wait(self):
        self.phase1 ()
        self.phase2 ()


def pid():
    """Gets the ID of the current thread."""
    return current_thread.name


def num_threads():
    """Gets the number of threads."""
    sync = current_thread.column.p
    return len(sync.threads)


# make globals and locals for the simulator

sim_globals = copy.copy(globals())
sim_locals = dict()

# anything defined after this point is not available inside the simulator


# get the version of Python
v = sys.version.split()[0].split(".")
major = int(v[0])

if major == 2:
    all_thread_names = string.uppercase + string.lowercase
else:
    all_thread_names = string.ascii_uppercase + string.ascii_lowercase


START_NEW_LINE = re.compile(r'##\s*thread\s+(.*?)(?:\s*\*\s*(\d+))?\s*$', re.I)

@dataclass
class Options:
    delay: float = 0.2
    max_steps: int = None
    roundrobin: bool = False
    verbose: bool = False
    loop: bool = False
    no_deadlocks: bool = True


class Sync:
    """Represents the thread simulator."""

    def __init__(self, options, filename):
        self.options = options
        self.filename = filename
        self.locals = sim_locals
        self._globals = sim_globals

        self.threads = []
        self.running = False
        self.delay = self.options.delay
        self.max_steps = self.options.max_steps
        self.setup()
        self.run_init()

    @property
    def variables(self):
        # The behaviour of `eval`/`exec` in Python 3 is totally weird:
        # https://bugs.python.org/issue37646
        # Variables passed in `locals` are visible to top-level scopes,
        # but invisible in nested scopes (function/class definitions,
        # comprehensions). To allow, e.g., functions which can update or check
        # global buffers, we use this egregious hack: pass *all* variables in
        # as globals. However, *updates* to variables in `exec` calls are
        # applied to the `locals` mapping, so we must retain `self.locals`.
        #
        # Also, `eval`/`exec` will accept a ChainMap of locals, but not
        # globals. So we must cast this to a dict. Screw you, Python 3.
        return dict(ChainMap(self._globals, self.locals))

    def get_threads(self):
        return self.threads

    def setup(self):
        """Reads in the code."""
        if self.filename:
            self.read_file(self.filename)

    def register(self, thread):
        """Adds a new thread."""
        if self.options.verbose:
            print(f"Registering thread {thread.name}")
        self.threads.append(thread)

    def unregister(self, thread):
        """Removes a thread."""
        if self.options.verbose:
            print(f"Removing thread {thread.name}")
        self.threads.remove(thread)

    def run(self):
        """Runs the simulator."""
        stepper = self.step if self.options.roundrobin else self.random_step
        thread_stepper = self.step_thread_loop if self.options.loop else self.step_thread
        self.run_helper(stepper, thread_stepper)

    def run_helper(self, stepper, thread_stepper):
        """Runs the threads until someone clears self.running."""
        self.running = True
        step_count = 0
        while self.running:
            if not self.threads:
                if self.options.verbose:
                    print("All threads finished, exiting")
                return
            stepper(thread_stepper)
            time.sleep(self.delay)
            step_count += 1
            if self.max_steps is not None and step_count >= self.max_steps:
                if self.options.verbose:
                    print("Reached max_steps, exiting")
                self.running = False

    def step_thread(self, thread):
        thread.step()
        if thread.finished:
            if self.options.verbose:
                print(f"Thread {thread.name} finished")
            self.unregister(thread)

    def step_thread_loop(self, thread):
        thread.step_loop()

    def step(self, thread_stepper):
        """Advances all the threads in order"""
        for thread in self.threads:
            thread_stepper(thread)

    def random_step(self, thread_stepper):
        """Advances one random thread."""
        threads = [thread for thread in self.threads if not thread.queued]
        if not threads:
            print("There are currently no threads that can run.")
            if self.options.no_deadlocks:
                assert False, f"Threads {self.threads} are deadlocked - failing"
            return
        thread = random.choice(threads)
        thread_stepper(thread)

    def stop(self):
        """Stops running."""
        self.running = False

    def read_file(self, filename):
        """Read a file that contains code for the simulator to execute.

        Lines that start with ## do not appear in the display.

        Start a new thread with a line of the form "## Thread NAME [* COUNT]".
        Anything before the first such line is common initialisation code.
        """
        block = []
        name = "init"
        thread_count = 1

        fp = open(filename)
        for line in fp:
            line = line.rstrip()

            m = START_NEW_LINE.match(line)
            if m:
                self.create_threads(block, name, thread_count)
                block = []
                name = m.group(1)
                thread_count = int(m.group(2) or 1)
            else:
                block.append(line)

        self.create_threads(block, name, thread_count)
        fp.close()

    def create_threads(self, block, name, thread_count):
        if self.options.verbose:
            print(f"Creating {thread_count} copies of thread {name}")
        if thread_count > 1:
            for i in range(thread_count):
                self.register(Thread(self, block, f"{name}-{i}", self.options.loop))
        else:
            self.register(Thread(self, block, name, self.options.loop))

    def run_init(self):
        """Runs the initialization code in the top column."""

        if self.options.verbose:
            print("running init")

        thread = self.threads[0]
        thread.run()

        self.unregister(thread)


def subtract(d1, d2):
    """Subtracts two dictionaries.

    Returns a new dictionary containing all the keys from
    d1 that are not in d2.
    """
    d = {}
    for key in d1:
        if key not in d2:
            d[key] = d1[key]
    return d


def diff_dict(d1, d2):
    """Diffs two dictionaries.

    Returns two dictionaries: the first contains all the keys
    from d1 that are not in d2; the second contains all the keys
    that are in both dictionaries, but which have different values.
    """
    d = {}
    c = {}
    for key in d1:
        if key not in d2:
            d[key] = d1[key]
        elif d1[key] is not d2[key]:
            c[key] = d1[key]
    return d, c


def trim_block(block):
    """Removes comments from the beginning and empty lines from the end."""
    if block and block[0].startswith("#"):
        block.pop(0)

    while block and not block[-1].strip():
        block.pop(-1)


class Namespace:
    """Used to store thread-local variables.

    Inside the simulator, self refers to the thread's namespace.
    """


class Thread:
    """Represents simulated threads."""

    def __init__(self, sync, instructions, name, looping):
        self.sync = sync
        self.instructions = instructions
        self.name = name
        self.looping = looping
        self.namespace = Namespace()
        self.flag_map = {}
        self.while_stack = []
        self._iptr = 0
        self.start()

    @property
    def iptr(self):
        return self._iptr

    @iptr.setter
    def iptr(self, value):
        self._iptr = value

    def __repr__(self):
        return f"<{self.name} {self.iptr}>"

    def enqueue(self):
        """Puts this thread into queue."""
        self.queued = True

    def dequeue(self):
        """Removes this thread from queue."""
        self.queued = False

    def jump_to(self, row):
        """Removes this thread from its current row and moves it to row."""
        self.iptr = row

    def balk(self):
        self.iptr = -1  # next_row is called after execution, making the iptr 0

    def start(self):
        """Moves this thread to the top of the column."""
        self.queued = False
        self.iptr = 0

    def next_loop(self):
        """Moves to the next row, looping to the top if necessary."""
        self.next_row()
        if self.finished and self.looping:
            self.start()

    def next_row(self):
        """Moves this thread to the next row in the column."""
        if self.queued:
            return

        self.iptr = self.iptr + 1

    def skip_body(self):
        """Skips an indented block."""
        # get the current line
        # get the next line
        # compute the change in indent
        # find the outdent
        if self.finished:
            return []
        source = self.instructions[self.iptr]
        lines = [source]
        head_indent = self.count_spaces(source)

        while True:
            self.next_row()
            if self.finished:
                return lines
            source = self.instructions[self.iptr]
            if source != "":
                break

        body_indent = self.count_spaces(source)
        indent = body_indent - head_indent

        if indent <= 0:
            raise SyntaxError("Body of compound statement must be indented.")

        while True:
            lines.append(source)
            self.next_row()
            if self.finished:
                break

            source = self.instructions[self.iptr]
            if source == "":
                continue
            line_indent = self.count_spaces(source)
            if line_indent <= head_indent:
                break
        return lines

    def count_spaces(self, source):
        """Returns the number of leading spaces after expanding tabs."""
        s = source.expandtabs(4)
        t = s.lstrip(" ")
        return len(s) - len(t)

    def step(self, event=None):
        """Executes the current line of code, then moves to the next row.

        The current limitation of this simulator is that each row
        has to contain a complete Python statement.  Also, each line
        of code is executed atomically.

        Args:
            event: unused, provided so that this method can be used
                   as a binding callback

        Returns:
            line of code that executed or None
        """
        if self.queued:
            return None

        if self.finished:
            return None

        self.check_end_while()
        source = self.instructions[self.iptr]
        print(self, source)

        before = copy.copy(self.sync.locals)
        before_ns = copy.copy(self.namespace.__dict__)

        flag = self.exec_line(source, self.sync)

        # see if any variables were defined or changed
        after = self.sync.locals
        defined, changed = diff_dict(after, before)
        if self.sync.options.verbose and (defined or changed):
            print(f"{defined} defined, {changed} changed")
        defined, changed = diff_dict(self.namespace.__dict__, before_ns)
        if self.sync.options.verbose and (defined or changed):
            print(f"{self} thread-locals {defined} defined, {changed} changed")

        # either skip to the next line or to the end of a false conditional
        if flag:
            self.next_row()
        else:
            self.skip_body()

        return source

    def exec_line(self, source, sync):
        """Runs a line of source code in the context of the given Sync.

        Args:
            source: source code from a Row
            sync: Sync object

        Returns:
            if the line is an if statement, returns the result of
            evaluating the condition
        """
        global current_thread
        current_thread = self

        sync.locals["self"] = self.namespace

        try:
            s = source.strip()
            code = compile(s, "<user-provided code>", "exec")
            exec(code, sync.variables, sync.locals)
            return True
        except SyntaxError as error:
            # check whether it's a conditional statement
            keyword = s.split()[0]
            if keyword in ["if", "else:", "while"]:
                flag = self.handle_conditional(keyword, source, sync)
                return flag
            elif keyword in ["def", "class"]:
                self.handle_def(sync)
                return False
            else:
                raise error

    def handle_conditional(self, keyword, source, sync):
        """Evaluates the condition part of an if statement.

        Args:
            keyword: if, else or while
            source: source code from a Row
            sync: Sync object

        Returns:
            if the line is an if statement, returns the result of
            evaluating the condition; otherwise raises a SyntaxError
        """
        s = source.strip()
        if not s.endswith(":"):
            raise SyntaxError("Header must end with :")

        if keyword in ["if"]:
            # evaluate the condition
            n = len(keyword)
            condition = s[n:-1].strip()
            flag = eval(condition, sync.variables, sync.locals)

            # store the flag
            indent = self.count_spaces(source)
            self.flag_map[indent] = flag

            return flag

        elif keyword in ["while"]:
            # evaluate the condition
            n = len(keyword)
            condition = s[n:-1].strip()
            flag = eval(condition, sync.variables, sync.locals)

            if flag:
                indent = self.count_spaces(source)
                self.while_stack.append((indent, self.iptr))

            return flag

        else:
            assert keyword == "else:"
            # see whether the condition was true
            indent = self.count_spaces(source)
            try:
                flag = self.flag_map[indent]
                return not flag
            except KeyError:
                raise SyntaxError("else does not match if")

    def handle_def(self, sync):
        head_line = self.iptr
        definition = "\n".join(self.skip_body()) + "\n"
        exec(definition, sync.variables, sync.locals)
        self.iptr = head_line

    def check_end_while(self):
        """Check if we are at the end of a while loop.

        If so, jump to the top.
        """
        if not self.while_stack:
            return

        indent, row = self.while_stack[-1]

        source = self.instructions[self.iptr]
        if self.count_spaces(source) <= indent:
            self.while_stack.pop()
            self.jump_to(row)

    @property
    def finished(self):
        return self.iptr >= len(self.instructions)

    def step_loop(self, event=None):
        self.step()
        if self.finished:
            self.start()

    def run(self):
        while True:
            self.step()
            if self.finished:
                break
