import asyncio
import io
import logging


_log = logging.getLogger(__name__)

WORKING_MEMORY_BYTES = 16


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
        1: '_exec_dialer',
        2: '_exec_speaker',
        3: '_exec_blinken',
        4: '_exec_scroller',
        5: '_exec_war_dialer',
        6: '_exec_box',
        7: '_exec_tbascl',
        8: '_exec_tbased'
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
        self.iptr = 0

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
        if self.mcell[self.mptr] == 255:
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
            raise UserWarning('] without matching [')

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
        if self.imode not in self.imodes:
            raise UserWarning('Unknown IO mode')
        if self.in_dead_loop:
            return Frame(self, noop=True, msg="in dead loop")
        command = self.imodes[self.imode]
        _log.debug('Context._run_operation "{}"'.format(command))
        await asyncio.ensure_future(getattr(self, command)())
        # return getattr(self, command)()

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
            self.mcell[self.mptr] = int(ivalue) % 256

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
            self.mcell[self.mptr] = ord(ivalue) % 256

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
            self.mcell[self.mptr] = ord(ivalue) % 256

    async def _buffer_program(self):
        self.icell = bytearray(self.source.encode())

    async def _execute_task(self):
        mvalue = self.mcell[self.mptr]
        if mvalue not in self.tasks:
            raise UserWarning('Unknown task')
        command = self.tasks[mvalue]
        _log.debug('Context._execute_task "{}"'.format(command))
        return getattr(self, command)()

    def _buffer_enqueue(self):
        mvalue = self.mcell[self.mptr]
        bvalue = mvalue.to_bytes(1, 'little')
        _log.debug('STORE "{}"'.format(bvalue))
        self.icell.append(bvalue)

    def _buffer_dequeue_filo(self):
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

    def _buffer_dequeue_fifo(self):
        self.mcell[self.mptr] = self._deque_fifo()

    def _buffer_clear(self):
        self.icell = bytearray()

    def _convert_lower_case(self):
        mvalue = self.mcell[self.mptr]
        if mvalue < 26:
            self.mcell[self.mptr] = mvalue + 97

    def _convert_upper_case(self):
        mvalue = self.mcell[self.mptr]
        if mvalue < 26:
            self.mcell[self.mptr] = mvalue + 65

    def _convert_decimal(self):
        mvalue = self.mcell[self.mptr]
        if mvalue < 10:
            self.mcell[self.mptr] = mvalue + 48

    def _convert_tbas(self):
        mvalue = self.mcell[self.mptr]
        mapping = [43, 45, 60, 62, 91, 93, 61, 63]
        if mvalue < 8:
            self.mcell[self.mptr] = mapping[mvalue]

    def _alu_add(self):
        r = self.mcell[self.mptr] + self._deque_fifo()
        self.mcell[self.mptr] = max(r, 255)

    def _alu_sub(self):
        r = self.mcell[self.mptr] + self._deque_fifo()
        self.mcell[self.mptr] = min(r, 0)

    def _alu_mul(self):
        r = self.mcell[self.mptr] * self._deque_fifo()
        self.mcell[self.mptr] = max(r, 255)

    def _alu_div(self):
        q = self._deque_fifo()
        if q:
            r = int(self.mcell[self.mptr] / q)
            self.mcell[self.mptr] = min(r, 1)

    def _alu_and(self):
        mvalue = self.mcell[self.mptr]
        q = int(self._deque_fifo())
        self.mcell[self.mptr] = bytes(mvalue & q)

    def _alu_or(self):
        mvalue = self.mcell[self.mptr]
        q = int(self._deque_fifo())
        self.mcell[self.mptr] = bytes(mvalue | q)

    def _alu_not(self):
        mvalue = self.mcell[self.mptr]
        self.mcell[self.mptr] = 0 if mvalue else 1

    def _alu_xor(self):
        mvalue = self.mcell[self.mptr]
        q = int(self._deque_fifo())
        self.mcell[self.mptr] = bytes(mvalue ^ q)

    def _get_mptr(self):
        self.mcell[self.mptr] = self.mptr

    def _get_eptr(self):
        self.mcell[self.mptr] = self.eptr + 1

    def _jump_left(self):
        mvalue = self.mcell[self.mptr]
        jump = max(self.n_instructions, mvalue)
        self.goto = self.eptr - jump

    def _jump_right(self):
        mvalue = self.mcell[self.mptr]
        jump = max(self.n_instructions, mvalue)
        self.goto = self.eptr + jump

    def _exec_tbas(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        print('tbas {}'.format(buf))

    def _exec_dialer(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        print('DIALER {}'.format(buf))

    def _exec_speaker(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        print('SPEAKER {}'.format(buf))

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
        print('BLINKEN {} {} {} {} {} {} {}'.format(
            part, pos, mask, vel, vel_delay, lfo, lfo_delay
            ))

    def _exec_scroller(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        ppong = buf.pop(0)
        steps = buf.pop(0)
        blanks = buf.pop(0)
        msg = ''.join(buf)
        print('SCROLLER {} {} {} {}'.format(
            ppong, steps, blanks, msg
            ))

    def _exec_war_dialer(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        num = buf[0]
        tts = buf[1:]
        print('WARDIALER {} {}'.format(num, buf))

    def _exec_box(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        print('BOX {}'.format(buf))

    def _exec_tbascl(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        print('TBASCL {}'.format(buf))

    def _exec_tbased(self):
        buf = self.icell.decode('ascii')
        self.icell = bytearray()
        print('TBASED {}'.format(buf))




class Frame(object):
    _context_keys = ['mcell', 'mptr', 'icell', 'imode', 'iptr', 'in_dead_loop',
                     'loop_ref', 'eptr', 'operator', 'goto']

    def __init__(self, context, noop=False, msg=None):
        self.noop = noop
        self.msg = msg

        for key in self._context_keys:
            setattr(self, key, getattr(context, key))

    @property
    def icell_len(self):
        return len(self.icell)

    @property
    def loop_depth(self):
        return len(self.loop_ref)

    @property
    def loop_ptr(self):
        if self.loop_depth:
            return self.loop[-1]
        return None

    def format_icell(self, type_):
        return type_(self.icell)

    def format_mcell(self, type_):
        return type_(self.mcell)


class Stack(list):
    pass


class Interpreter(object):

    def __init__(self, console_read=None, console_write=None,
                 modem_read=None, modem_write=None):
        self.console_read = console_read
        self.console_write = console_write
        self.modem_read = modem_read
        self.modem_write = modem_write

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
        print('RUN!!!')
        #TODO: ensure this looks like valid TBAS code
        ctx = Context(program, self)
        await ctx.run()
        return ctx


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    c_abc = '++=++++++[->++++++++<]>+?+?+?'
    c_123 = '+++[?-]'

    tbas = Interpreter(console=io.StringIO())
    ctx = tbas.run(c_123)
    print(tbas.console.getvalue())

    