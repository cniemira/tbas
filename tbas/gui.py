import asyncio
import os
import sys

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import pyqtSignal, Qt, QUrl, QMetaObject, Q_ARG, QVariant
from PyQt5.QtWidgets import QApplication, QMainWindow
from quamash import QEventLoop, QThreadExecutor

from tbas.tbas import Interpreter
from tbas.mainwindow import Ui_MainWindow


import logging
logging.basicConfig(level=logging.DEBUG)


def resource_path(filename):
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        filename
        )


class TBASMainWindow(QMainWindow, Ui_MainWindow):
    connected_signals = ['clicked', 'currentIndexChanged',
        'cursorPositionChanged', 'returnPressed', 'selectionChanged',
        'sliderMoved', 'stateChanged', 'textChanged', 'textEdited',
        'valueChanged']

    status_table_rows = [
        'eptr', 'mptr', 'operator', 'icell_len', 'imode', 'in_dead_loop',
        'loop_depth', 'loop_ptr', 'goto'
    ]

    def __init__(self, app):
        QMainWindow.__init__(self)
        Ui_MainWindow.__init__(self)

        self.app = app
        self.app.setWindowIcon(QtGui.QIcon(resource_path('icon.png')))

        self.setupUi(self)
        self.setWindowTitle('tbas-ide')

        # Setup the busy indicators
        for w in [self.console_blocked, self.modem_blocked]:
            w.setSource(QUrl(resource_path('BusyIndicator.qml')))
            w.setClearColor(Qt.transparent)
            layout = QtWidgets.QVBoxLayout(w)
            layout.setContentsMargins(0, 0, 0, 0)
            QMetaObject.invokeMethod(w.rootObject(), "stop")

        # connect all of the signals 
        for method in self.__dir__():
            if method.count('_') and not method.startswith('_'):
                emitter_name, _, signal_name = method.rpartition('_')
                if signal_name in self.connected_signals:
                    signal = getattr(getattr(self, emitter_name), signal_name)
                    signal.connect(getattr(self, method))

        # start clean
        self.program_input_is_dirty = False

        # setup the mainloop and tie it to asyncio
        self.main_loop = QEventLoop(self)
        asyncio.set_event_loop(self.main_loop)

        # finally setup TBAS
        self.reset_tbas()


    def exec_(self):
        return self.main_loop.run_forever()


    async def _console_read(self, *args, **kwargs):
        self.set_console_blocking()
        self.io_counter += 1
        self._future_console_input = asyncio.Future()
        await self._future_console_input
        self.set_console_blocking(False)
        return self._future_console_input.result()

    async def _console_write(self, value):
        self.append_console_output(1, value)

    def reset_tbas(self):
        self.tbas = Interpreter(
            console_read = self._console_read,
            console_write = self._console_write,
            modem_read = None,
            modem_write = None,
            )
        self.io_counter = 0
        self._future_console_input = None
        self._tbas_future = None
        self.tbas_evaluate_program()


    def tbas_complete_callback(self, task):
        self._tbas_future = None
        self.current_context = task.result()
        self.program_input.setEnabled(True)
        self.io_counter = 0
        self.set_stack_depth()

    def tbas_evaluate_program(self):
        if self._tbas_future:
            print('FIXME')
            return
        self.program_input.setEnabled(False)
        program = self.program_input.toPlainText()
        self._tbas_future = asyncio.ensure_future(self.tbas.run(program.strip()))
        self._tbas_future.add_done_callback(self.tbas_complete_callback)

    def _set_status_item(self, n, value):
            cell = self.status_table.item(n, 1)
            cell.setText(str(value))        

    def set_stack_depth(self):
        stack_depth = len(self.current_context.stack)
        stack_max = max(stack_depth - 1, 0)
        self.frame_slider.setValue(0)
        self.frame_slider.setMaximum(stack_max)
        self._set_status_item(1, stack_max)
        # will trigger a call to view_stack_position
        self.frame_slider.setValue(stack_max)

    def view_stack_position(self, stack_pointer):
        stack = self.current_context.stack
        i = 1

        if not len(stack):
            for item in self.status_table_rows:
                i += 1
                self._set_status_item(i, None)
            self.memory_buffer.setPlainText("")
            self.io_buffer.setPlainText("")
            return

        self._set_status_item(0, stack_pointer)
        frame = stack[stack_pointer]

        for item in self.status_table_rows:
            i += 1
            self._set_status_item(i, getattr(frame, item))

        self.memory_buffer.setText(frame.format_mcell(chr))
        self.io_buffer.setText(frame.format_icell(chr))


    def set_console_blocking(self, truth=True):
        arg = "start" if truth else "stop"
        QMetaObject.invokeMethod(self.console_blocked.rootObject(), arg)

    def set_modem_blocking(self, truth=True):
        arg = "start" if truth else "stop"
        QMetaObject.invokeMethod(self.modem_blocked.rootObject(), arg)


    def append_console_output(self, isoutput, value):
        prefix = "Out" if isoutput else "In "
        self.console_output.append("{}[{}.{}]: {}".format(prefix,
            self.tbas.run_counter, self.io_counter, value))

    def cast_console_input(self):
        input_ = self.console_input.text()
        if len(input_):
            return input_
        return None

    def preview_console_input(self):
        self.console_input_value.setText(self.cast_console_input())

    def process_console_input(self):
        if self._future_console_input:
            input_ = self.cast_console_input()
            if type(input_) is str:
                self.append_console_output(0, input_)
                self._future_console_input.set_result(input_)
                self.console_input.setText("")


    # signal Handlers

    def frame_slider_valueChanged(self, index):
        self.view_stack_position(index)

    def frame_down_button_clicked(self, index):
        p = self.frame_slider.value() - 1
        self.frame_slider.setValue(max(0, p))

    def frame_up_button_clicked(self, index):
        m = self.frame_slider.maximum()
        p = self.frame_slider.value() + 1
        self.frame_slider.setValue(min(m, p))


    def run_step_button_clicked(self, index):
        print(index)
        print(self.outputs_widget.width())
        print(self.width())

    def run_to_breakpoint_button_clicked(self, index):
        print(index)

    def run_to_end_button_clicked(self, index):
        print(index)


    def reset_button_clicked(self, index):
        print(index)

    def reset_run_step_button_clicked(self, index):
        print(index)

    def reset_run_to_breakpoint_button_clicked(self, index):
        print(index)

    def reset_run_to_end_button_clicked(self, index):
        self.program_input_set_clean()
        self.tbas_evaluate_program()

    def log_reset_button_clicked(self, index):
        print(index)

    def memory_select_currentIndexChanged(self, index):
        print(index)

    def buffer_select_currentIndexChanged(self, index):
        print(index)



    def console_enable_stateChanged(self, value):
        pass

    def console_reset_button_clicked(self, index):
        self.console_input.setText("")

    def console_enter_button_clicked(self, index):
        self.process_console_input()

    def console_input_returnPressed(self):
        self.process_console_input()

    def console_input_textEdited(self, value):
        self.preview_console_input()



    def modem_enable_stateChanged(self, value):
        print(value)

    def modem_reset_button_clicked(self, index):
        print(index)

    def modem_enter_button_clicked(self, index):
        print(index)

    def modem_input_returnPressed(self):
        print('return')

    def modem_input_textEdited(self, value):
        print(value)



    def remove_breakpoints_button_clicked(self, index):
        print(index)


    def program_input_set_clean(self):
        self.program_input_is_dirty = False
        self.program_input.setStyleSheet('')

    def program_input_set_dirty(self):
        self.program_input_is_dirty = True
        self.program_input.setStyleSheet('border: 1px solid red')


    def program_input_cursorPositionChanged(self):
        print('cursor')

    def program_input_selectionChanged(self):
        print('selection')

    def program_input_textChanged(self):
        self.program_input_set_dirty()
        print('changed')



def main():
    app = QApplication(['TBAS'])
    tbas = TBASMainWindow(app)
    tbas.show()
    sys.exit(app.exec_())
    


if __name__ == '__main__':
    main()