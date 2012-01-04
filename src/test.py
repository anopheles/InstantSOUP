#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import logging
from PyQt4 import QtGui
from instantsoupdata import Client
import subprocess


# Initialize logger & set logging level
log = logging.getLogger("instantsoup")
log.setLevel(logging.DEBUG)
log.addHandler(logging.StreamHandler())

class MainWindow(QtGui.QMainWindow):

    def __init__(self):
        QtGui.QMainWindow.__init__(self)
        central_widget = QtGui.QWidget(self)
        self.setCentralWidget(central_widget)

        client = Client(parent=self)

        layout = QtGui.QHBoxLayout()
        central_widget.setLayout(layout)

        client_layout = QtGui.QVBoxLayout()

        client_window = QtGui.QTextEdit(self)
        client_command = QtGui.QLineEdit(self)
        client_command.editingFinished.connect(lambda : client.send_command_to_server(str(client_command.text())))

        client_layout.addWidget(client_window)
        client_layout.addWidget(client_command)

        layout.addLayout(client_layout)

        client.message_received.connect(lambda msg : client_window.append(msg))

if __name__ == '__main__':
    p = subprocess.Popen(r"C:\Python27\python.exe test_server.py") # TODO
    app = QtGui.QApplication(sys.argv)
    main = MainWindow()
    main.show()
    app.exec_()
    p.terminate()