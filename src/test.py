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
        server_layout = QtGui.QVBoxLayout()

        server_list = QtGui.QListWidget(self)
        server_layout.addWidget(server_list)

        client_window = QtGui.QTextEdit(self)
        client_command = QtGui.QLineEdit(self)
        client_command.editingFinished.connect(lambda : client.send_command_to_server(str(client_command.text())))

        client_layout.addWidget(client_window)
        client_layout.addWidget(client_command)

        layout.addLayout(client_layout)
        layout.addLayout(server_layout)

        client.message_received.connect(lambda msg : client_window.append(msg))
        client.new_server.connect(lambda uid : server_list.addItem(uid))

if __name__ == '__main__':
    #p = subprocess.Popen(r"C:\Python26\python.exe test_server.py") # TODO
    app = QtGui.QApplication(sys.argv)
    main = MainWindow()
    main.show()
    app.exec_()
    #p.terminate()