import io
import logging
import pytest

from tbas.tbas import Interpreter


logging.basicConfig(level=logging.DEBUG)
_log = logging.getLogger(__name__)


class TestTBAS(object):
    def setup(self):
        self.tbas = Interpreter(
            console=io.StringIO(),
            modem=io.StringIO()
            )

    def setup_function(self):
        _log.info('TEST SETUP FUNCTION')
        self.tbas.console.seek(0)
        self.tbas.console.truncate(0)
        self.tbas.modem.seek(0)
        self.tbas.modem.truncate(0)

    def test_321(self):
        self.tbas.run('+++[?-]')
        assert self.tbas.console.getvalue() == '321'

    def test_ABC(self):
        self.tbas.run('++=++++++[->++++++++<]>+?+?+?')
        assert self.tbas.console.getvalue() == 'ABC'

    def test_decimal_read_write(self):
        c = self.tbas.console
        for i in range(9):
            c.write(str(i))
            p1 = c.tell()
            c.seek(p1-1)
            self.tbas.run('+=>?<-=>?')
            p2 = c.tell()
            assert p2 > p1 # check that we actually wrote something
            c.seek(p2-1)
            assert c.read(1) == str(i) # check it's correct

    def test_modem_read_write(self):
        m = self.tbas.modem
        for i in range(97, 123):
            c = chr(i)
            m.write(c)
            p1 = m.tell()
            m.seek(p1-1)
            self.tbas.run('+++++=>?<-=>?')
            p2 = m.tell()
            _log.info("p1 = {} ; p2 = {}".format(p1, p2))
            assert p2 > p1 # check that we actually wrote something
            m.seek(p2-1)
            assert m.read(1) == c # check it's correct

    def test_buffer_program(self):
        p = '++++++=?'
        ctx = self.tbas.run(p)
        assert ctx.io_buffer.getvalue() == p.encode()

