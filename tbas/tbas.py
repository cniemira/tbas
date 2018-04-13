import asyncio
import io
import logging

from copy import copy
from itertools import zip_longest


_log = logging.getLogger(__name__)

BYTE_MAX = 255
WORKING_MEMORY_BYTES = 256


class Context(object):

    imodes = {
        0: '_console_decimal_write',
        1: '_console_decimal_read',
        2: '_console_ascii_write',
        3: '_console_ascii_read',
        4: '_modem_ascii_write',
        5: '_modem_ascii_read',
        6: '_buffer_program',
        7: '_execute_task',
        8: '_buffer_enqueue',
        9: '_buffer_dequeue_filo',
        10: '_buffer_dequeue_fifo',
        11: '_buffer_clear',
        12: '_convert_lower_case',
        13: '_convert_upper_case',
        14: '_convert_decimal',
        15: '_convert_tbas',
        16: '_alu_add',
        17: '_alu_sub',
        18: '_alu_mul',
        19: '_alu_div',
        20: '_alu_and',
        21: '_alu_or',
        22: '_alu_not',
        23: '_alu_xor',
        24: '_get_mptr',
        25: '_get_eptr',
        26: '_jump_left',
        27: '_jump_right'
        }

    operators = {
        '>': '_advance_mptr',
        '<': '_retreat_mptr',
        '+': '_increment_mcell',
        '-': '_decrement_mcell',
        '[': '_begin_loop',
        ']': '_end_loop',
        '=': '_set_iomode',
        '?': '_run_operation'
        }

    tasks = {
        0: '_exec_tbas',
        1: '_exec_config',
        2: '_exec_tonegn',
        3: '_exec_blinken',
        4: '_exec_scroller',
        5: '_exec_tbased',
        6: '_exec_tbascl',
        8: '_exec_autodt',
        9: '_exec_dialer',
        }


    @property
    def n_instructions(self):
        return len(self.source)

    def __init__(self, program, interpreter):
        self.interpreter = interpreter
        self.source = program
        _log.debug('Context.source="{}"'.format(program))
        self.reset()

    def __iter__(self):
        return self

    async def __next__(self):
        if self.eptr == self.n_instructions:
            raise StopIteration

        self.operator = self.source[self.eptr]
        _log.debug('EVAL: {}'.format(self.operator))
        await self._eval_op(self.operator)
        if self.goto:
            self.eptr = self.goto
            self.goto = None
        else:
            self.eptr += 1

    def reset(self):
        self.stack = Stack()

        self.mcell = [0x0] * WORKING_MEMORY_BYTES
        self.mptr = 0

        self.icell = bytearray()
        self.imode = 0

        self.in_dead_loop = 0
        self.loop_ref = []

        self.eptr = 0
        self.operator = None
        self.goto = None

    async def run(self):
        while self.eptr < self.n_instructions:
            await next(self)

    async def _eval_op(self, operator):
        assert operator in self.operators.keys()
        mvalue = self.mcell[self.mptr]
        command = self.operators[operator]
        _log.debug('Context.eval "{}" mcell={} l_iob={} @{} -> {}'.format(
            operator, mvalue, len(self.icell),
            self.eptr, command))
        future = asyncio.ensure_future(getattr(self, command)())
        frame = await future
        _log.debug('Created {}'.format(frame))
        if not isinstance(frame, Frame):
            frame = Frame(self)
        self.stack.append(frame)
        return frame

    async def _advance_mptr(self):
        if self.in_dead_loop:
            return Frame(self, noop=True, msg="in dead loop")
        if self.mptr == len(self.mcell):
            return Frame(self, noop=True, msg="mptr at extent")
        self.mptr += 1
        return Frame(self)

    async def _retreat_mptr(self):
        if self.in_dead_loop:
            return Frame(self, noop=True, msg="in dead loop")
        if self.mptr == 0:
            return Frame(self, noop=True, msg="mptr at zero")
        self.mptr -= 1
        return Frame(self)

    async def _increment_mcell(self):
        if self.in_dead_loop:
            return Frame(self, noop=True, msg="in dead loop")
        if self.mcell[self.mptr] == BYTE_MAX:
            return Frame(self, noop=True, msg="mcell[] is max")
        self.mcell[self.mptr] += 1
        return Frame(self)

    async def _decrement_mcell(self):
        if self.in_dead_loop:
            return Frame(self, noop=True, msg="in dead loop")
        if self.mcell[self.mptr] == 0:
            return Frame(self, noop=True, msg="mcell[] is 0")
        self.mcell[self.mptr] -= 1
        return Frame(self)

    async def _begin_loop(self):
        self.loop_ref.append(self.eptr)
        _log.debug('Context._begin_loop @{}'.format(self.eptr))
        if self.in_dead_loop or self.mcell[self.mptr] == 0:
            self.in_dead_loop += 1
            return Frame(self, noop=True, msg="begin loop in dead loop")
        return Frame(self)

    async def _end_loop(self):
        if len(self.loop_ref) == 0:
            msg = '] without matching [ @{}'.format(self.eptr)
            _log.warn(msg)
            raise UserWarning(msg)

        goto_instruction = self.loop_ref.pop()
        if self.in_dead_loop:
            self.in_dead_loop -= 1
            return Frame(self, noop=True, msg="ended dead loop")

        self.goto = goto_instruction
        return Frame(self)

    async def _set_iomode(self):
        if self.in_dead_loop:
            return Frame(self, noop=True, msg="in dead loop")
        self.imode = self.mcell[self.mptr]
        return Frame(self)

    async def _run_operation(self):
        if self.in_dead_loop:
            return Frame(self, noop=True, msg="in dead loop")
        if self.imode not in self.imodes:
            msg = 'Unknown io mode {} @{}'.format(self.imode, self.eptr)
            _log.warn(msg)
            raise UserWarning(msg)
        command = self.imodes[self.imode]
        _log.debug('Context._run_operation "{}"'.format(command))
        future = asyncio.ensure_future(getattr(self, command)())
        await future
        return future.result()

    async def _console_decimal_write(self):
        mvalue = self.mcell[self.mptr]
        if self.interpreter.console_write:
            _log.debug('WRITE "{}"'.format(str(mvalue)))
            await asyncio.ensure_future(
                self.interpreter.console_write(str(mvalue)))

    async def _console_decimal_read(self):
        if self.interpreter.console_read:
            future = asyncio.ensure_future(self.interpreter._console_read(1))
            task = await future
            ivalue = task.result()
            _log.debug('READ "{}"'.format(ivalue))
            if not ivalue.isdigit():
                ivalue = ord(ivalue)
            self.mcell[self.mptr] = int(ivalue) % (BYTE_MAX + 1)

    async def _console_ascii_write(self):
        mvalue = self.mcell[self.mptr]
        if self.interpreter.console_write:
            _log.debug('WRITE "{}"'.format(chr(mvalue)))
            await asyncio.ensure_future(
                self.interpreter.console_write(chr(mvalue)))

    async def _console_ascii_read(self):
        if self.interpreter.console_read:
            future = asyncio.ensure_future(self.interpreter._console_read(1))
            task = await future
            ivalue = task.result()
            _log.debug('READ "{}"'.format(ivalue))
            self.mcell[self.mptr] = ord(ivalue) % (BYTE_MAX + 1)

    async def _modem_ascii_write(self):
        mvalue = self.mcell[self.mptr]
        if self.interpreter.modem_write:
            _log.debug('WRITE "{}"'.format(chr(mvalue)))
            await asyncio.ensure_future(
                self.interpreter.modem_write(chr(mvalue)))

    async def _modem_ascii_read(self):
        if self.interpreter.modem_read:
            future = asyncio.ensure_future(self.interpreter._modem_read(1))
            task = await future
            ivalue = task.result()
            _log.debug('READ "{}"'.format(ivalue))
            if not ivalue.isdigit():
                ivalue = ord(ivalue)
            self.mcell[self.mptr] = ord(ivalue) % (BYTE_MAX + 1)

    async def _buffer_program(self):
        self.icell = bytearray(self.source.encode())
        return Frame(self)

    async def _execute_task(self):
        mvalue = self.mcell[self.mptr]
        if mvalue not in self.tasks:
            msg = 'Unknown task {} @{}'.format(mvalue, self.eptr)
            _log.warn(msg)
            raise UserWarning(msg)
        command = self.tasks[mvalue]
        _log.debug('Context._execute_task "{}"'.format(command))
        getattr(self, command)()
        return Frame(self)

    async def _buffer_enqueue(self):
        mvalue = self.mcell[self.mptr]
        _log.debug('STORE "{}"'.format(mvalue))
        self.icell.append(mvalue)

    async def _buffer_dequeue_filo(self):
        if len(self.icell):
            bvalue = self.icell.pop()
            self.mcell[self.mptr] = bvalue
            _log.debug('DEQUEUE "{}"'.format(bvalue))
        else:
            _log.debug('NO DEQUEUE')
            self.mcell[self.mptr] = 0

    def _deque_fifo(self):
        if len(self.icell):
            bvalue = self.icell.pop(0)
            _log.debug('DEQUEUE "{}"'.format(bvalue))
            return bvalue
        _log.debug('NO DEQUEUE')
        return 0

    async def _buffer_dequeue_fifo(self):
        self.mcell[self.mptr] = self._deque_fifo()

    async def _buffer_clear(self):
        self.icell = bytearray()

    async def _convert_lower_case(self):
        mvalue = self.mcell[self.mptr]
        if mvalue < 26:
            self.mcell[self.mptr] = mvalue + 97

    async def _convert_upper_case(self):
        mvalue = self.mcell[self.mptr]
        if mvalue < 26:
            self.mcell[self.mptr] = mvalue + 65

    async def _convert_decimal(self):
        mvalue = self.mcell[self.mptr]
        if mvalue < 10:
            self.mcell[self.mptr] = mvalue + 48

    async def _convert_tbas(self):
        mvalue = self.mcell[self.mptr]
        mapping = [43, 45, 60, 62, 91, 93, 61, 63]
        if mvalue < 8:
            self.mcell[self.mptr] = mapping[mvalue]

    async def _alu_add(self):
        r = self.mcell[self.mptr] + self._deque_fifo()
        self.mcell[self.mptr] = max(r, BYTE_MAX)

    async def _alu_sub(self):
        r = self.mcell[self.mptr] + self._deque_fifo()
        self.mcell[self.mptr] = min(r, 0)

    async def _alu_mul(self):
        r = self.mcell[self.mptr] * self._deque_fifo()
        self.mcell[self.mptr] = min(r, BYTE_MAX)

    async def _alu_div(self):
        q = self._deque_fifo()
        if q:
            r = int(self.mcell[self.mptr] / q)
            self.mcell[self.mptr] = min(r, 1)

    async def _alu_and(self):
        mvalue = self.mcell[self.mptr]
        q = int(self._deque_fifo())
        self.mcell[self.mptr] = bytes(mvalue & q)

    async def _alu_or(self):
        mvalue = self.mcell[self.mptr]
        q = int(self._deque_fifo())
        self.mcell[self.mptr] = bytes(mvalue | q)

    async def _alu_not(self):
        mvalue = self.mcell[self.mptr]
        self.mcell[self.mptr] = 0 if mvalue else 1

    async def _alu_xor(self):
        mvalue = self.mcell[self.mptr]
        q = int(self._deque_fifo())
        self.mcell[self.mptr] = bytes(mvalue ^ q)

    async def _get_mptr(self):
        self.mcell[self.mptr] = self.mptr

    async def _get_eptr(self):
        self.mcell[self.mptr] = self.eptr + 1

    async def _jump_left(self):
        mvalue = self.mcell[self.mptr]
        jump = max(self.n_instructions, mvalue)
        self.goto = self.eptr - jump

    async def _jump_right(self):
        mvalue = self.mcell[self.mptr]
        jump = max(self.n_instructions, mvalue)
        self.goto = self.eptr + jump

    def _exec_tbas(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        _log.info('tbas {}'.format(buf))

    def _exec_dialer(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        _log.info('dialer {}'.format(buf))

    def _exec_blinken(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        part = buf.pop(0)
        pos = buf.pop(0)
        mask = buf.pop(0)
        vel = buf.pop(0)
        vel_delay = buf.pop(0)
        lfo = buf.pop(0)
        lfo_delay = buf.pop(0)
        _log.info('blinken {} {} {} {} {} {} {}'.format(
            part, pos, mask, vel, vel_delay, lfo, lfo_delay
            ))

    def _exec_scroller(self):
        ppong = self.icell.pop(0)
        steps = self.icell.pop(0)
        blanks = self.icell.pop(0)
        _log.info('scroller {} {} {} {}'.format(
            ppong, steps, blanks, self.icell.decode('ascii')
            ))
        self.icell = bytearray()

    def _exec_autodt(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        num = buf[0]
        tts = buf[1:]
        _log.info('autodt {} {}'.format(num, buf))

    def _exec_tonegn(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        _log.info('tonegn {}'.format(buf))

    def _exec_tbascl(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        _log.info('tbasctl {}'.format(buf))

    def _exec_tbased(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        _log.info('tbased {}'.format(buf))



def chunk(n, i, v=None):
    a = [iter(i)] * n
    return zip_longest(*[iter(i)]*n, fillvalue=v)


class Frame(object):
    _context_keys = ['mcell', 'mptr', 'icell', 'imode', 'in_dead_loop',
                     'loop_ref', 'eptr', 'operator', 'goto']

    def __init__(self, context, noop=False, msg=None):
        self.noop = noop
        self.msg = msg

        for key in self._context_keys:
            setattr(self, key, copy(getattr(context, key)))

    @property
    def icell_len(self):
        return len(self.icell)

    @property
    def loop_depth(self):
        return len(self.loop_ref)

    @property
    def loop_ptr(self):
        if self.loop_depth:
            return self.loop_ref[-1]
        return None

    def _format_byte(self, byte, format):
        format_string = "{:" + format + "}"
        if byte is None:
            zeros = format_string.format(0)
            return " " * len(zeros)
        return format_string.format(byte)

    def _format_memory(self, memory, format='03d'):
        b = io.StringIO()
        row_n = 0
        for row in chunk(16, memory):
            l, r = chunk(8, row)
            l_bytes = " ".join([self._format_byte(x, format) for x in iter(l)])
            r_bytes = " ".join([self._format_byte(x, format) for x in iter(r)])
            b.write("0x{:03d}: ".format(row_n*16))
            b.write("   ".join([l_bytes, r_bytes]) + "\n")
            row_n += 1
        return b.getvalue()

    def format_icell(self, type_=chr):
        return self._format_memory(self.icell, type_)

    def format_mcell(self, type_=chr):
        return self._format_memory(self.mcell, type_)


#TODO: this could be more useful
class Stack(list):
    pass


class Interpreter(object):

    def __init__(self, console_read=None, console_write=None,
                 modem_read=None, modem_write=None):
        self.console_read = console_read
        self.console_write = console_write
        self.modem_read = modem_read
        self.modem_write = modem_write
        self.run_counter = 0
        self.logger = _log

    async def _console_read(self, *args, **kwargs):
        if self.console_read:
            input_ = asyncio.ensure_future(self.console_read(*args, **kwargs))
            await input_
            return input_
        return None

    async def _console_write(self, *args, **kwargs):
        if self.console_write:
            output = asyncio.ensure_future(self.console_write(*args, **kwargs))
            await output
            return output
        return None

    async def _modem_read(self, *args, **kwargs):
        if self.modem_read:
            input_ = asyncio.ensure_future(self.modem_read(*args, **kwargs))
            await input_
            return input_
        return None

    async def _modem_write(self, *args, **kwargs):
        if self.modem_write:
            output = asyncio.ensure_future(self.modem_write(*args, **kwargs))
            await output
            return output
        return None

    async def run(self, program):
        #TODO: ensure this looks like valid TBAS code
        ctx = Context(program, self)
        try:
            await ctx.run()
            self.run_counter += 1
            return ctx
        except Exception as e:
            _log.error(e)
        return ctx


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    c_abc = '++=++++++[->++++++++<]>+?+?+?'

    tbas = Interpreter(console=io.StringIO())
    ctx = tbas.run(c_abc)
    print(tbas.console.getvalue())
